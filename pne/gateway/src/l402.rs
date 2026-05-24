use anyhow::{Context, Result};
use base64::{engine::general_purpose::STANDARD as B64, Engine};
use hmac::{Hmac, Mac};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::time::{SystemTime, UNIX_EPOCH};
use uuid::Uuid;

type HmacSha256 = Hmac<Sha256>;

const MACAROON_TTL_SECS: u64 = 3600;

#[derive(Debug, Serialize, Deserialize)]
pub struct MacaroonClaims {
    pub jti: String,
    pub endpoint: String,
    pub ip: String,
    pub exp: u64,
    pub sats: u64,
}

#[derive(Debug)]
pub struct L402Token {
    pub preimage_hex: String,
    pub macaroon_b64: String,
}

#[derive(Debug)]
pub struct ParsedAuth {
    pub preimage_hex: String,
    pub macaroon_b64: String,
}

pub fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

/// Generate a mock BOLT11 invoice and accompanying macaroon.
/// In production this calls out to LND/CDP.
pub fn issue_challenge(
    secret: &[u8],
    client_ip: &str,
    endpoint: &str,
    amount_sats: u64,
) -> Result<(String, String, String, u64)> {
    let payment_preimage: Vec<u8> = (0..32).map(|_| rand::random::<u8>()).collect();
    let payment_hash = sha256_hex(&payment_preimage);
    let preimage_hex = hex::encode(&payment_preimage);

    let expires_at = now_secs() + MACAROON_TTL_SECS;
    let claims = MacaroonClaims {
        jti: Uuid::new_v4().to_string(),
        endpoint: endpoint.to_string(),
        ip: client_ip.to_string(),
        exp: expires_at,
        sats: amount_sats,
    };

    let claims_json = serde_json::to_string(&claims).context("serialize macaroon claims")?;
    let claims_b64 = B64.encode(claims_json.as_bytes());
    let sig = hmac_hex(secret, claims_b64.as_bytes());
    let macaroon_b64 = B64.encode(format!("{}.{}", claims_b64, sig));

    // Mock BOLT11: in production call lnd.add_invoice(amount_sats, payment_hash)
    let bolt11 = format!(
        "lnbc{}n1pne{}qqpp5{}gcqzpgxqyz5vqsp5xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        amount_sats,
        &Uuid::new_v4().to_string().replace('-', "")[..8],
        &payment_hash[..20],
    );

    Ok((bolt11, macaroon_b64, payment_hash, expires_at))
}

/// Verify the L402 Authorization header value.
/// Returns Ok(claims) if valid, Err otherwise.
pub fn verify_token(
    secret: &[u8],
    auth_value: &str,
    client_ip: &str,
) -> Result<MacaroonClaims, L402Error> {
    let stripped = auth_value
        .strip_prefix("L402 ")
        .ok_or(L402Error::MalformedHeader)?;

    let parts: Vec<&str> = stripped.splitn(2, ':').collect();
    if parts.len() != 2 {
        return Err(L402Error::MalformedHeader);
    }

    let preimage_hex = parts[0];
    let macaroon_b64 = parts[1];

    let macaroon_bytes = B64
        .decode(macaroon_b64)
        .map_err(|_| L402Error::MacaroonInvalid)?;
    let macaroon_str =
        std::str::from_utf8(&macaroon_bytes).map_err(|_| L402Error::MacaroonInvalid)?;

    let dot = macaroon_str.rfind('.').ok_or(L402Error::MacaroonInvalid)?;
    let claims_b64 = &macaroon_str[..dot];
    let sig = &macaroon_str[dot + 1..];

    // Verify HMAC
    let expected_sig = hmac_hex(secret, claims_b64.as_bytes());
    if !constant_time_eq(sig.as_bytes(), expected_sig.as_bytes()) {
        return Err(L402Error::MacaroonInvalid);
    }

    // Decode claims
    let claims_json = B64
        .decode(claims_b64)
        .map_err(|_| L402Error::MacaroonInvalid)?;
    let claims: MacaroonClaims =
        serde_json::from_slice(&claims_json).map_err(|_| L402Error::MacaroonInvalid)?;

    // Check expiry
    if now_secs() > claims.exp {
        return Err(L402Error::TokenExpired);
    }

    // Check IP caveat
    if claims.ip != client_ip && !claims.ip.is_empty() {
        return Err(L402Error::IpMismatch);
    }

    // Verify preimage matches payment hash embedded in macaroon
    // In production: verify SHA256(preimage) == payment_hash from LND
    // For mock: we just check format
    if preimage_hex.len() != 64 {
        return Err(L402Error::PreimageInvalid);
    }

    Ok(claims)
}

pub fn parse_auth_header(value: &str) -> Result<ParsedAuth, L402Error> {
    let stripped = value
        .strip_prefix("L402 ")
        .ok_or(L402Error::MalformedHeader)?;
    let parts: Vec<&str> = stripped.splitn(2, ':').collect();
    if parts.len() != 2 {
        return Err(L402Error::MalformedHeader);
    }
    Ok(ParsedAuth {
        preimage_hex: parts[0].to_string(),
        macaroon_b64: parts[1].to_string(),
    })
}

#[derive(Debug, thiserror::Error)]
pub enum L402Error {
    #[error("Malformed Authorization header")]
    MalformedHeader,
    #[error("Macaroon HMAC invalid")]
    MacaroonInvalid,
    #[error("Preimage does not match payment hash")]
    PreimageInvalid,
    #[error("Token has expired")]
    TokenExpired,
    #[error("IP caveat mismatch")]
    IpMismatch,
}

fn sha256_hex(data: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(data);
    hex::encode(hasher.finalize())
}

fn hmac_hex(key: &[u8], data: &[u8]) -> String {
    let mut mac =
        HmacSha256::new_from_slice(key).expect("HMAC accepts any key length");
    mac.update(data);
    hex::encode(mac.finalize().into_bytes())
}

fn constant_time_eq(a: &[u8], b: &[u8]) -> bool {
    if a.len() != b.len() {
        return false;
    }
    a.iter().zip(b.iter()).fold(0u8, |acc, (x, y)| acc | (x ^ y)) == 0
}
