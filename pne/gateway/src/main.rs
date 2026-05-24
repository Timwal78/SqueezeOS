mod auction;
mod config;
mod error;
mod l402;
mod merkle;
mod middleware;
mod redis_state;
mod routes;

use axum::{
    extract::ConnectInfo,
    middleware as axum_middleware,
    routing::{get, post},
    Router,
};
use std::{net::SocketAddr, sync::Arc};
use tower::ServiceBuilder;
use tower_http::{
    cors::{Any, CorsLayer},
    trace::TraceLayer,
};
use tracing::info;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

use config::Config;
use middleware::{auth_middleware, response_headers_middleware, RateLimitState};
use redis_state::RedisState;

#[derive(Clone)]
pub struct AppState {
    pub config: Arc<Config>,
    pub redis: Arc<RedisState>,
    pub rate_limit: Arc<RateLimitState>,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::registry()
        .with(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "pne_gateway=info,tower_http=debug".into()),
        )
        .with(tracing_subscriber::fmt::layer())
        .init();

    let config = Arc::new(Config::from_env()?);
    let redis = RedisState::connect(&config.redis_url).await?;
    let rate_limit = Arc::new(RateLimitState::default());

    let state = AppState {
        config: config.clone(),
        redis: redis.clone(),
        rate_limit: rate_limit.clone(),
    };

    let cors = CorsLayer::new()
        .allow_origin(Any) // Tighten in production via config.cors_origins
        .allow_methods(Any)
        .allow_headers(Any);

    let app = Router::new()
        // Health & discovery (no auth)
        .route("/v1/status", get(routes::status))
        .route("/v1/pricing", get(routes::pricing))
        .route("/v1/auction/book", get(routes::auction_book))
        .route("/v1/auction/history", get(routes::auction_history))
        .route("/v1/leaderboard", get(routes::leaderboard))
        .route("/v1/audit/merkle-root", get(routes::merkle_root))
        .route("/v1/audit/proof/:auction_id", get(routes::merkle_proof))
        // WebSocket Loom feed (no auth)
        .route("/ws/loom", get(routes::ws_loom_handler))
        // Discovery manifests
        .route("/.well-known/mcp.json", get(routes::well_known_mcp))
        .route("/.well-known/ai-plugin.json", get(routes::well_known_plugin))
        .route("/.well-known/agents.json", get(routes::well_known_agents))
        .route("/llms.txt", get(routes::llms_txt))
        // Auction flow intelligence & certificates (no auth — public meta-signals)
        .route("/v1/auction/flow", get(routes::auction_flow))
        .route("/v1/certificates/:auction_id", get(routes::latency_certificate))
        // Premium proxied endpoints (L402 required)
        .route("/v1/market-data", get(routes::proxy_market_data))
        .route("/v1/council", post(routes::proxy_council))
        .route("/v1/options", get(routes::proxy_options))
        .route("/v1/scan", get(routes::proxy_scan))
        // Layers
        .layer(
            ServiceBuilder::new()
                .layer(TraceLayer::new_for_http())
                .layer(cors)
                .layer(axum_middleware::from_fn_with_state(
                    (config.clone(), rate_limit.clone()),
                    auth_middleware,
                ))
                .layer(axum_middleware::from_fn(response_headers_middleware)),
        )
        .with_state(state);

    let addr = SocketAddr::from(([0, 0, 0, 0], config.port));
    info!("PNE Gateway listening on {}", addr);
    info!("Loom WebSocket: ws://{}/ws/loom", addr);
    info!("Upstream: {}", config.upstream_base_url);

    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(
        listener,
        app.into_make_service_with_connect_info::<SocketAddr>(),
    )
    .await?;

    Ok(())
}
