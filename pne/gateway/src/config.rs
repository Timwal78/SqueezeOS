use anyhow::{Context, Result};
use std::env;

#[derive(Debug, Clone)]
pub struct Config {
    pub port: u16,
    pub redis_url: String,
    pub upstream_base_url: String,
    pub macaroon_secret: Vec<u8>,
    pub rate_limit_unauth: u32,
    pub auction_window_ms: u64,
    pub platform_fee_pct: f64,
    pub base_price_sats: u64,
    pub cors_origins: Vec<String>,
}

impl Config {
    pub fn from_env() -> Result<Self> {
        dotenvy::dotenv().ok();

        let macaroon_secret_hex = env::var("MACAROON_SECRET")
            .context("MACAROON_SECRET must be set (32-byte hex string)")?;
        let macaroon_secret = hex::decode(&macaroon_secret_hex)
            .context("MACAROON_SECRET must be valid hex")?;

        if macaroon_secret.len() < 16 {
            anyhow::bail!("MACAROON_SECRET must be at least 16 bytes (32 hex chars)");
        }

        let cors_origins = env::var("CORS_ORIGINS")
            .unwrap_or_else(|_| "http://localhost:5173,https://n-exchequer.io".to_string())
            .split(',')
            .map(|s| s.trim().to_string())
            .collect();

        Ok(Self {
            port: env::var("PORT")
                .unwrap_or_else(|_| "8402".to_string())
                .parse()
                .context("PORT must be a valid number")?,
            redis_url: env::var("REDIS_URL")
                .unwrap_or_else(|_| "redis://127.0.0.1:6379".to_string()),
            upstream_base_url: env::var("UPSTREAM_BASE_URL")
                .unwrap_or_else(|_| "https://lively-fascination-production-41fa.up.railway.app".to_string()),
            macaroon_secret,
            rate_limit_unauth: env::var("RATE_LIMIT_UNAUTH")
                .unwrap_or_else(|_| "100".to_string())
                .parse()
                .context("RATE_LIMIT_UNAUTH must be a number")?,
            auction_window_ms: env::var("AUCTION_WINDOW_MS")
                .unwrap_or_else(|_| "5".to_string())
                .parse()
                .context("AUCTION_WINDOW_MS must be a number")?,
            platform_fee_pct: env::var("PLATFORM_FEE_PCT")
                .unwrap_or_else(|_| "1.0".to_string())
                .parse()
                .context("PLATFORM_FEE_PCT must be a float")?,
            base_price_sats: env::var("BASE_PRICE_SATS")
                .unwrap_or_else(|_| "100".to_string())
                .parse()
                .context("BASE_PRICE_SATS must be a number")?,
            cors_origins,
        })
    }
}
