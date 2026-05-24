use axum::{
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde_json::json;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum PneError {
    #[error("Payment required")]
    PaymentRequired {
        invoice: String,
        macaroon: String,
        payment_hash: String,
        amount_sats: u64,
        expires_at: u64,
    },

    #[error("Macaroon HMAC verification failed")]
    MacaroonInvalid,

    #[error("Payment preimage does not match payment hash")]
    PreimageInvalid,

    #[error("Macaroon has expired")]
    TokenExpired,

    #[error("Request IP does not match macaroon IP caveat")]
    IpMismatch,

    #[error("Rate limit exceeded")]
    RateLimited,

    #[error("Upstream service unavailable: {0}")]
    UpstreamUnavailable(String),

    #[error("Auction queue at capacity")]
    AuctionOverloaded,

    #[error("Internal error: {0}")]
    Internal(#[from] anyhow::Error),
}

impl IntoResponse for PneError {
    fn into_response(self) -> Response {
        match self {
            PneError::PaymentRequired {
                ref invoice,
                ref macaroon,
                ref payment_hash,
                amount_sats,
                expires_at,
            } => {
                let www_auth = format!(
                    "L402 invoice=\"{}\", macaroon=\"{}\"",
                    invoice, macaroon
                );
                let body = json!({
                    "error": "payment_required",
                    "code": "L402_CHALLENGE",
                    "invoice": invoice,
                    "macaroon": macaroon,
                    "payment_hash": payment_hash,
                    "amount_sats": amount_sats,
                    "expires_at": expires_at,
                    "message": "Pay invoice to receive authorization preimage. Add X-Grace-Tip to bid for auction priority."
                });
                let mut resp = (StatusCode::PAYMENT_REQUIRED, Json(body)).into_response();
                resp.headers_mut().insert(
                    "WWW-Authenticate",
                    www_auth.parse().unwrap(),
                );
                resp.headers_mut().insert("X-PNE-Version", "1.0.0".parse().unwrap());
                resp
            }
            PneError::MacaroonInvalid => error_response(
                StatusCode::UNAUTHORIZED,
                "MACAROON_INVALID",
                "Macaroon HMAC verification failed",
            ),
            PneError::PreimageInvalid => error_response(
                StatusCode::UNAUTHORIZED,
                "PREIMAGE_INVALID",
                "Payment preimage does not match invoice hash",
            ),
            PneError::TokenExpired => {
                let mut resp = error_response(
                    StatusCode::UNAUTHORIZED,
                    "TOKEN_EXPIRED",
                    "Macaroon has expired — request a new invoice",
                );
                resp.headers_mut().insert(
                    "WWW-Authenticate",
                    "L402 error=\"token_expired\"".parse().unwrap(),
                );
                resp
            }
            PneError::IpMismatch => error_response(
                StatusCode::UNAUTHORIZED,
                "IP_MISMATCH",
                "Request IP does not match macaroon IP caveat",
            ),
            PneError::RateLimited => error_response(
                StatusCode::TOO_MANY_REQUESTS,
                "RATE_LIMITED",
                "Unauthenticated rate limit exceeded (100/min)",
            ),
            PneError::UpstreamUnavailable(ref msg) => error_response(
                StatusCode::SERVICE_UNAVAILABLE,
                "UPSTREAM_UNAVAILABLE",
                msg,
            ),
            PneError::AuctionOverloaded => error_response(
                StatusCode::SERVICE_UNAVAILABLE,
                "AUCTION_OVERLOADED",
                "Auction queue is at capacity — retry shortly",
            ),
            PneError::Internal(ref e) => {
                tracing::error!("Internal error: {:#}", e);
                error_response(
                    StatusCode::INTERNAL_SERVER_ERROR,
                    "INTERNAL_ERROR",
                    "An internal error occurred",
                )
            }
        }
    }
}

fn error_response(status: StatusCode, code: &str, message: &str) -> Response {
    let body = json!({ "error": code, "message": message });
    (status, Json(body)).into_response()
}
