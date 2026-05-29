use axum::{
    body::Body,
    extract::{ConnectInfo, Request, State},
    http::{HeaderMap, StatusCode},
    middleware::Next,
    response::Response,
};
use dashmap::DashMap;
use std::{
    net::SocketAddr,
    sync::Arc,
    time::{Duration, Instant},
};

use crate::{config::Config, error::PneError, l402};

/// Rate limit state: tracks request counts per IP with a sliding 60s window.
#[derive(Default)]
pub struct RateLimitState {
    counts: DashMap<String, (u32, Instant)>,
}

impl RateLimitState {
    pub fn check_and_increment(&self, ip: &str, limit: u32) -> bool {
        let now = Instant::now();
        let window = Duration::from_secs(60);

        let mut entry = self.counts.entry(ip.to_string()).or_insert((0, now));
        let (ref mut count, ref mut window_start) = entry.value_mut();

        if now.duration_since(*window_start) > window {
            *count = 1;
            *window_start = now;
            return true;
        }

        if *count >= limit {
            return false;
        }

        *count += 1;
        true
    }
}

/// Returns true if the path is public (no L402 auth required).
fn is_public_path(path: &str) -> bool {
    // Non-/v1/ paths are always public (websocket, well-known, llms.txt)
    if !path.starts_with("/v1/") {
        return true;
    }
    // Public /v1/ routes — health check MUST be here or Render marks service unhealthy
    matches!(
        path,
        "/v1/status"
            | "/v1/pricing"
            | "/v1/auction/book"
            | "/v1/auction/history"
            | "/v1/auction/flow"
            | "/v1/leaderboard"
    ) || path.starts_with("/v1/audit/")
        || path.starts_with("/v1/certificates/")
}

/// Middleware: enforce L402 authentication on premium /v1/* routes.
/// Public routes (health, status, auction book/history/flow, audit, leaderboard)
/// are passed through without auth. Premium routes return HTTP 402.
pub async fn auth_middleware(
    State((config, rate_state)): State<(Arc<Config>, Arc<RateLimitState>)>,
    ConnectInfo(addr): ConnectInfo<SocketAddr>,
    mut request: Request,
    next: Next,
) -> Result<Response, PneError> {
    let path = request.uri().path().to_string();

    if is_public_path(&path) {
        return Ok(next.run(request).await);
    }

    let client_ip = extract_client_ip(&request, addr);

    let auth_header = request
        .headers()
        .get("Authorization")
        .and_then(|v| v.to_str().ok())
        .map(|s| s.to_string());

    match auth_header {
        None => {
            // No auth — check rate limit before issuing challenge
            if !rate_state.check_and_increment(&client_ip, config.rate_limit_unauth) {
                return Err(PneError::RateLimited);
            }

            let (invoice, macaroon, payment_hash, expires_at) = l402::issue_challenge(
                &config.macaroon_secret,
                &client_ip,
                &path,
                config.base_price_sats,
            )
            .map_err(|e| PneError::Internal(e))?;

            request
                .extensions_mut()
                .insert(ChallengeIssued { client_ip: client_ip.clone(), endpoint: path.clone() });

            Err(PneError::PaymentRequired {
                invoice,
                macaroon,
                payment_hash,
                amount_sats: config.base_price_sats,
                expires_at,
            })
        }
        Some(auth_val) => {
            if !auth_val.starts_with("L402 ") {
                return Err(PneError::MacaroonInvalid);
            }

            match l402::verify_token(&config.macaroon_secret, &auth_val, &client_ip) {
                Ok(claims) => {
                    request.extensions_mut().insert(claims);
                    Ok(next.run(request).await)
                }
                Err(l402::L402Error::MacaroonInvalid) => Err(PneError::MacaroonInvalid),
                Err(l402::L402Error::PreimageInvalid) => Err(PneError::PreimageInvalid),
                Err(l402::L402Error::TokenExpired) => Err(PneError::TokenExpired),
                Err(l402::L402Error::IpMismatch) => Err(PneError::IpMismatch),
                Err(l402::L402Error::MalformedHeader) => Err(PneError::MacaroonInvalid),
            }
        }
    }
}

/// Middleware: attach PNE response headers to all responses.
pub async fn response_headers_middleware(request: Request, next: Next) -> Response {
    let mut response = next.run(request).await;
    let headers = response.headers_mut();
    headers.insert("X-PNE-Version", "1.0.0".parse().unwrap());
    headers.insert("X-Content-Type-Options", "nosniff".parse().unwrap());
    headers.insert(
        "Strict-Transport-Security",
        "max-age=31536000; includeSubDomains".parse().unwrap(),
    );
    headers.insert("X-Frame-Options", "DENY".parse().unwrap());
    response
}

/// Extract the real client IP, respecting X-Forwarded-For.
pub fn extract_client_ip(request: &Request, addr: SocketAddr) -> String {
    request
        .headers()
        .get("X-Forwarded-For")
        .and_then(|v| v.to_str().ok())
        .and_then(|s| s.split(',').next())
        .map(|s| s.trim().to_string())
        .unwrap_or_else(|| addr.ip().to_string())
}

/// Extension type for downstream handlers to know a 402 was issued.
#[derive(Clone)]
pub struct ChallengeIssued {
    pub client_ip: String,
    pub endpoint: String,
}
