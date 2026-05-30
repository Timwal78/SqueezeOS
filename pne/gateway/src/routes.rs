use axum::{
    body::Bytes,
    extract::{ConnectInfo, Path, Query, State, WebSocketUpgrade},
    http::{HeaderMap, Method, StatusCode},
    response::{IntoResponse, Json, Response},
    Extension,
};
use futures_util::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{collections::HashMap, net::SocketAddr};
use tokio::sync::broadcast;
use tracing::{info, warn};

use crate::{
    AppState,
    auction::{self, AuctionBookSnapshot, AuctionBookEntry, epoch_ms, ms_until_window_close, window_id},
    error::PneError,
    l402::MacaroonClaims,
    merkle,
    middleware::extract_client_ip,
};

// ─── Health & Info ──────────────────────────────────────────────────────────

pub async fn status(State(state): State<AppState>) -> Json<Value> {
    Json(json!({
        "status": "operational",
        "version": "1.0.0",
        "auction_window_ms": state.config.auction_window_ms,
        "base_price_sats": state.config.base_price_sats,
        "platform_fee_pct": state.config.platform_fee_pct,
        "upstream": state.config.upstream_base_url,
        "timestamp": epoch_ms(),
    }))
}

pub async fn pricing(State(state): State<AppState>) -> Json<Value> {
    Json(json!({
        "base_price_sats": state.config.base_price_sats,
        "base_price_rlusd": state.config.base_price_sats as f64 / 100_000.0,
        "grace_tip_min": 0,
        "grace_tip_max": 1_000_000,
        "platform_fee_pct": state.config.platform_fee_pct,
        "auction_window_ms": state.config.auction_window_ms,
    }))
}

// ─── Auction Book ────────────────────────────────────────────────────────────

pub async fn auction_book(State(state): State<AppState>) -> Json<Value> {
    let now = epoch_ms();
    let wid = window_id(now, state.config.auction_window_ms);

    match state.redis.get_auction_book(wid).await {
        Ok(members) => {
            let bids: Vec<Value> = members
                .iter()
                .enumerate()
                .map(|(i, (request_id, tip))| {
                    json!({
                        "rank": i + 1,
                        "tip_sats": *tip as u64,
                        "wallet_hash": request_id,
                        "submitted_ms": now,
                    })
                })
                .collect();

            let total_tips: u64 = members.iter().map(|(_, t)| *t as u64).sum();

            Json(json!({
                "window_id": wid,
                "window_ms": state.config.auction_window_ms,
                "bids": bids,
                "resolves_in_ms": ms_until_window_close(state.config.auction_window_ms),
                "total_bids": bids.len(),
                "total_tips_sats": total_tips,
            }))
        }
        Err(_) => Json(json!(AuctionBookSnapshot::awaiting())),
    }
}

#[derive(Deserialize)]
pub struct HistoryQuery {
    pub limit: Option<usize>,
    pub wallet_hash: Option<String>,
}

pub async fn auction_history(
    State(_state): State<AppState>,
    Query(q): Query<HistoryQuery>,
) -> Json<Value> {
    let limit = q.limit.unwrap_or(100).min(1000);
    Json(json!({
        "auctions": [],
        "limit": limit,
        "message": "awaiting_intent",
    }))
}

// ─── Leaderboard ─────────────────────────────────────────────────────────────

#[derive(Deserialize)]
pub struct LeaderboardQuery {
    pub period: Option<String>,
    pub limit: Option<i64>,
}

pub async fn leaderboard(
    State(state): State<AppState>,
    Query(q): Query<LeaderboardQuery>,
) -> Json<Value> {
    let limit = q.limit.unwrap_or(25).min(100);

    match state.redis.get_leaderboard(limit).await {
        Ok(entries) => {
            let board: Vec<Value> = entries
                .iter()
                .enumerate()
                .map(|(i, (wallet_hash, total_tips))| {
                    json!({
                        "rank": i + 1,
                        "wallet_hash": wallet_hash,
                        "total_tips_sats": *total_tips as u64,
                        "win_rate": null,
                        "efficiency_score": null,
                    })
                })
                .collect();

            Json(json!({
                "period": q.period.unwrap_or_else(|| "all".to_string()),
                "leaderboard": board,
            }))
        }
        Err(_) => Json(json!({
            "period": "all",
            "leaderboard": [],
            "message": "awaiting_intent",
        })),
    }
}

// ─── Merkle Audit ────────────────────────────────────────────────────────────

pub async fn merkle_root() -> Json<Value> {
    Json(json!({
        "root": null,
        "height": 0,
        "leaf_count": 0,
        "published_at": epoch_ms() / 1000,
        "next_publish_at": (epoch_ms() / 1000) + 60,
        "message": "awaiting_intent",
    }))
}

pub async fn merkle_proof(Path(auction_id): Path<String>) -> Json<Value> {
    Json(json!({
        "auction_id": auction_id,
        "leaf": null,
        "path": [],
        "root": null,
        "verified": false,
        "message": "awaiting_intent",
    }))
}

// ─── Proxy Routes (L402-gated) ───────────────────────────────────────────────

#[derive(Deserialize)]
pub struct MarketDataQuery {
    pub symbol: Option<String>,
    pub fields: Option<String>,
}

pub async fn proxy_market_data(
    State(state): State<AppState>,
    ConnectInfo(_addr): ConnectInfo<SocketAddr>,
    headers: HeaderMap,
    Extension(_claims): Extension<MacaroonClaims>,
    Query(q): Query<MarketDataQuery>,
) -> Result<Response, PneError> {
    let symbol = q.symbol.as_deref().unwrap_or("IWM");
    let grace_tip = parse_grace_tip(&headers);
    let wallet_hash = headers
        .get("X-Agent-Wallet")
        .and_then(|v| v.to_str().ok())
        .map(wallet_hash_or_default)
        .unwrap_or_else(|| "anonymous".to_string());

    let client_ip = extract_client_ip(
        &axum::http::Request::builder()
            .header("X-Forwarded-For", addr.ip().to_string())
            .body(axum::body::Body::empty())
            .unwrap(),
        addr,
    );

    // Enter auction
    let auction_result = auction::enter_auction(
        state.redis.clone(),
        "/v1/market-data",
        grace_tip,
        &wallet_hash,
        state.config.auction_window_ms,
    )
    .await
    .map_err(|e| PneError::Internal(e))?;

    // Call upstream
    let upstream_url = format!(
        "{}/api/preview/{}",
        state.config.upstream_base_url, symbol
    );

    let client = reqwest::Client::new();
    let upstream_resp = client
        .get(&upstream_url)
        .timeout(std::time::Duration::from_secs(10))
        .send()
        .await
        .map_err(|e| PneError::UpstreamUnavailable(e.to_string()))?;

    let status = upstream_resp.status();
    let body_bytes = upstream_resp
        .bytes()
        .await
        .map_err(|e| PneError::UpstreamUnavailable(e.to_string()))?;

    let response_hash = merkle::hash_response(&body_bytes);
    let leaf = merkle::compute_leaf(
        &auction_result.request_id,
        &wallet_hash,
        grace_tip,
        &response_hash,
        epoch_ms(),
    );

    let date = chrono_date();
    let _ = state.redis.append_merkle_leaf(&date, &leaf).await;

    let mut response = (
        StatusCode::from_u16(status.as_u16()).unwrap_or(StatusCode::OK),
        body_bytes,
    )
        .into_response();

    let h = response.headers_mut();
    h.insert("X-Auction-Rank", auction_result.rank.to_string().parse().unwrap());
    h.insert("X-Auction-Window", auction_result.window_id.to_string().parse().unwrap());
    h.insert(
        "X-Execution-Latency",
        format!("{}ms", auction_result.execution_latency_ms as u64).parse().unwrap(),
    );
    h.insert("X-Grace-Tip-Paid", grace_tip.to_string().parse().unwrap());
    h.insert("X-Merkle-Leaf", leaf.parse().unwrap());
    h.insert("X-PNE-Version", "1.0.0".parse().unwrap());
    h.insert("X-Data-Source", "SqueezeOS".parse().unwrap());

    Ok(response)
}

const EMBARGO_SECS: u64 = 30;

pub async fn proxy_council(
    State(state): State<AppState>,
    ConnectInfo(_addr): ConnectInfo<SocketAddr>,
    headers: HeaderMap,
    Extension(_claims): Extension<MacaroonClaims>,
    body: Bytes,
) -> Result<Response, PneError> {
    let grace_tip = parse_grace_tip(&headers);
    let dark_pool = is_dark_pool(&headers);
    let wallet_hash = if dark_pool {
        "[REDACTED]".to_string()
    } else {
        headers
            .get("X-Agent-Wallet")
            .and_then(|v| v.to_str().ok())
            .map(wallet_hash_or_default)
            .unwrap_or_else(|| "anonymous".to_string())
    };

    let symbol = extract_symbol_from_body(&body).unwrap_or_else(|| "IWM".to_string());

    let auction_result = auction::enter_auction(
        state.redis.clone(),
        "/v1/council",
        grace_tip,
        &wallet_hash,
        state.config.auction_window_ms,
    )
    .await
    .map_err(|e| PneError::Internal(e))?;

    let _ = state.redis.record_flow_bid(&symbol, grace_tip, dark_pool).await;

    let is_rank_one = auction_result.rank == 1;

    let upstream_url = format!("{}/api/council", state.config.upstream_base_url);
    let client = reqwest::Client::new();
    let mut req_builder = client
        .post(&upstream_url)
        .header("Content-Type", "application/json")
        .body(body.to_vec())
        .timeout(std::time::Duration::from_secs(15));

    if is_rank_one {
        req_builder = req_builder
            .header("X-PNE-Embargo", EMBARGO_SECS.to_string())
            .header("X-PNE-Rank", "1")
            .header("X-PNE-Auction-Window", auction_result.window_id.to_string());
        let _ = state.redis.set_embargo(&symbol, &auction_result.request_id, EMBARGO_SECS).await;
    }

    let upstream_resp = req_builder
        .send()
        .await
        .map_err(|e| PneError::UpstreamUnavailable(e.to_string()))?;

    let status = upstream_resp.status();
    let body_bytes = upstream_resp
        .bytes()
        .await
        .map_err(|e| PneError::UpstreamUnavailable(e.to_string()))?;

    let response_hash = merkle::hash_response(&body_bytes);
    let ts = epoch_ms();
    let leaf = merkle::compute_leaf(
        &auction_result.request_id,
        &wallet_hash,
        grace_tip,
        &response_hash,
        ts,
    );

    let date = chrono_date();
    let _ = state.redis.append_merkle_leaf(&date, &leaf).await;

    let cert = serde_json::json!({
        "auction_id": &auction_result.request_id,
        "symbol": &symbol,
        "rank": auction_result.rank,
        "grace_tip_sats": grace_tip,
        "dark_pool": dark_pool,
        "wallet_hash": &wallet_hash,
        "window_id": auction_result.window_id,
        "execution_latency_ms": auction_result.execution_latency_ms,
        "merkle_leaf": &leaf,
        "embargo_secs": if is_rank_one { EMBARGO_SECS } else { 0 },
        "certified_at": ts / 1000,
    });
    let _ = state.redis.store_certificate(&auction_result.request_id, &cert.to_string()).await;

    let mut response = (
        StatusCode::from_u16(status.as_u16()).unwrap_or(StatusCode::OK),
        body_bytes,
    )
        .into_response();

    let h = response.headers_mut();
    attach_auction_headers(h, &auction_result, &leaf, grace_tip);
    if is_rank_one {
        h.insert("X-Embargo-Seconds", EMBARGO_SECS.to_string().parse().unwrap());
        if let Ok(hv) = symbol.parse() {
            h.insert("X-Embargo-Symbol", hv);
        }
    }
    if dark_pool {
        h.insert("X-Dark-Pool", "true".parse().unwrap());
    }
    h.insert(
        "X-Certificate-ID",
        auction_result.request_id.parse().unwrap(),
    );

    Ok(response)
}

// ─── Auction Flow Intelligence ────────────────────────────────────────────────

#[derive(Deserialize)]
pub struct FlowQuery {
    pub limit: Option<usize>,
}

pub async fn auction_flow(
    State(state): State<AppState>,
    Query(q): Query<FlowQuery>,
) -> Json<Value> {
    let tracked_symbols = [
        "IWM", "SPY", "QQQ", "NVDA", "TSLA", "MSTR", "GME", "AMC",
        "PLTR", "HOOD", "AAPL", "AMD", "COIN", "SOFI", "RIVN",
    ];
    let limit = q.limit.unwrap_or(15).min(50);

    match state.redis.get_flow_stats(&tracked_symbols).await {
        Ok(mut flow) => {
            flow.truncate(limit);
            let signals: Vec<Value> = flow
                .iter()
                .enumerate()
                .map(|(i, (sym, tips, count))| {
                    json!({
                        "rank": i + 1,
                        "symbol": sym,
                        "total_tips_sats": tips,
                        "bid_count": count,
                        "avg_tip_sats": if *count > 0 { tips / count } else { 0 },
                        "intensity": if *tips > 50_000 { "HIGH" } else if *tips > 5_000 { "MEDIUM" } else { "LOW" },
                        "window": "1h",
                    })
                })
                .collect();

            let embargo_checks: Vec<Value> = futures_util::future::join_all(
                tracked_symbols.iter().map(|&sym| {
                    let redis = state.redis.clone();
                    async move {
                        if let Some(auction_id) = redis.get_embargo(sym).await {
                            Some(json!({"symbol": sym, "auction_id": auction_id}))
                        } else {
                            None
                        }
                    }
                })
            ).await.into_iter().flatten().collect();

            Json(json!({
                "flow_signals": signals,
                "active_embargoes": embargo_checks,
                "window": "1h",
                "note": "Bidding patterns reveal institutional intent — dark pool bids excluded.",
                "ts": epoch_ms() / 1000,
            }))
        }
        Err(_) => Json(json!({
            "flow_signals": [],
            "active_embargoes": [],
            "window": "1h",
            "message": "awaiting_intent",
        })),
    }
}

// ─── Latency Certificate ──────────────────────────────────────────────────────

pub async fn latency_certificate(
    State(state): State<AppState>,
    Path(auction_id): Path<String>,
) -> impl IntoResponse {
    match state.redis.get_certificate(&auction_id).await {
        Some(cert_json) => {
            match serde_json::from_str::<Value>(&cert_json) {
                Ok(cert) => (StatusCode::OK, Json(json!({
                    "certificate": cert,
                    "verified": true,
                    "retrieved_at": epoch_ms() / 1000,
                }))).into_response(),
                Err(_) => (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({
                    "error": "CERTIFICATE_CORRUPT",
                    "auction_id": auction_id,
                }))).into_response(),
            }
        }
        None => (StatusCode::NOT_FOUND, Json(json!({
            "error": "CERTIFICATE_NOT_FOUND",
            "auction_id": auction_id,
            "message": "Certificate not found or expired (24h TTL). Was this a valid rank-1 auction?",
        }))).into_response(),
    }
}

pub async fn proxy_options(
    State(state): State<AppState>,
    ConnectInfo(_addr): ConnectInfo<SocketAddr>,
    headers: HeaderMap,
    Extension(_claims): Extension<MacaroonClaims>,
    Query(q): Query<HashMap<String, String>>,
) -> Result<Response, PneError> {
    proxy_get(state, "/api/options", q, &headers, _addr).await
}

pub async fn proxy_scan(
    State(state): State<AppState>,
    ConnectInfo(_addr): ConnectInfo<SocketAddr>,
    headers: HeaderMap,
    Extension(_claims): Extension<MacaroonClaims>,
    Query(q): Query<HashMap<String, String>>,
) -> Result<Response, PneError> {
    proxy_get(state, "/api/scan", q, &headers, _addr).await
}

async fn proxy_get(
    state: AppState,
    path: &str,
    params: HashMap<String, String>,
    headers: &HeaderMap,
    _addr: SocketAddr,
) -> Result<Response, PneError> {
    let grace_tip = parse_grace_tip(headers);
    let wallet_hash = headers
        .get("X-Agent-Wallet")
        .and_then(|v| v.to_str().ok())
        .map(wallet_hash_or_default)
        .unwrap_or_else(|| "anonymous".to_string());

    let auction_result = auction::enter_auction(
        state.redis.clone(),
        path,
        grace_tip,
        &wallet_hash,
        state.config.auction_window_ms,
    )
    .await
    .map_err(|e| PneError::Internal(e))?;

    let query = params
        .iter()
        .map(|(k, v)| format!("{}={}", k, v))
        .collect::<Vec<_>>()
        .join("&");

    let upstream_url = if query.is_empty() {
        format!("{}{}", state.config.upstream_base_url, path)
    } else {
        format!("{}{}?{}", state.config.upstream_base_url, path, query)
    };

    let client = reqwest::Client::new();
    let upstream_resp = client
        .get(&upstream_url)
        .timeout(std::time::Duration::from_secs(10))
        .send()
        .await
        .map_err(|e| PneError::UpstreamUnavailable(e.to_string()))?;

    let status = upstream_resp.status();
    let body_bytes = upstream_resp
        .bytes()
        .await
        .map_err(|e| PneError::UpstreamUnavailable(e.to_string()))?;

    let response_hash = merkle::hash_response(&body_bytes);
    let leaf = merkle::compute_leaf(
        &auction_result.request_id,
        &wallet_hash,
        grace_tip,
        &response_hash,
        epoch_ms(),
    );

    let date = chrono_date();
    let _ = state.redis.append_merkle_leaf(&date, &leaf).await;

    let mut response = (
        StatusCode::from_u16(status.as_u16()).unwrap_or(StatusCode::OK),
        body_bytes,
    )
        .into_response();

    attach_auction_headers(response.headers_mut(), &auction_result, &leaf, grace_tip);
    Ok(response)
}

// ─── WebSocket Loom ──────────────────────────────────────────────────────────

pub async fn ws_loom_handler(
    ws: WebSocketUpgrade,
    State(state): State<AppState>,
) -> Response {
    ws.on_upgrade(move |socket| ws_loom_task(socket, state))
}

async fn ws_loom_task(socket: axum::extract::ws::WebSocket, state: AppState) {
    use axum::extract::ws::Message;

    let mut rx = state.redis.loom_tx.subscribe();
    let (mut sender, mut receiver) = socket.split();

    let connected = json!({
        "type": "CONNECTED",
        "ts": epoch_ms(),
        "message": "Connected to PNE Loom. Welcome to the Intent Auction.",
    });
    if sender.send(Message::Text(connected.to_string())).await.is_err() {
        return;
    }

    loop {
        tokio::select! {
            Ok(event) = rx.recv() => {
                if sender.send(Message::Text(event)).await.is_err() {
                    break;
                }
            }
            Some(msg) = receiver.next() => {
                match msg {
                    Ok(Message::Close(_)) | Err(_) => break,
                    _ => {}
                }
            }
        }
    }
}

// ─── Discovery Manifests ─────────────────────────────────────────────────────

pub async fn well_known_mcp() -> impl IntoResponse {
    (
        StatusCode::OK,
        [("Content-Type", "application/json")],
        include_str!("../../../.well-known/mcp.json"),
    )
}

pub async fn well_known_plugin() -> impl IntoResponse {
    let body = json!({
        "schema_version": "v1",
        "name_for_human": "Neural Exchequer",
        "name_for_model": "neural_exchequer",
        "description_for_human": "Priority market data via Sovereign Intent Auction. Pay RLUSD or sats for access.",
        "description_for_model": "A pay-per-call market data relay with x402 L402 authentication and a Grace Tip auction system. Agents that include X-Grace-Tip headers get priority execution.",
        "auth": { "type": "none" },
        "api": { "type": "openapi", "url": "https://n-exchequer.io/.well-known/openapi.json" },
        "logo_url": "https://n-exchequer.io/logo.png",
        "contact_email": "agents@n-exchequer.io",
    });
    Json(body)
}

pub async fn well_known_agents() -> Json<Value> {
    Json(json!({
        "name": "Neural Exchequer",
        "type": "priority_relay",
        "protocol": "x402+L402",
        "endpoints": {
            "market_data": "/v1/market-data",
            "council": "/v1/council",
            "auction_book": "/v1/auction/book",
            "leaderboard": "/v1/leaderboard",
        },
        "payment": {
            "currencies": ["RLUSD", "BTC_LIGHTNING", "ETH_BASE"],
            "min_payment_sats": 100,
            "auction_extension": "X-Grace-Tip",
        },
        "upgrade_hint": "Include X-Grace-Tip header to bid for execution priority",
    }))
}

pub async fn llms_txt() -> impl IntoResponse {
    (
        StatusCode::OK,
        [("Content-Type", "text/plain; charset=utf-8")],
        r#"# Neural Exchequer — Priority Data Relay

## What This Is
A pay-per-call API relay with real-time priority auction (Sovereign Intent Auction).
To access data, agents must pay via x402 (L402 protocol).
Agents that pay a Grace Tip via X-Grace-Tip header get faster execution priority.

## How to Use
1. Make any GET/POST request to /v1/*
2. You will receive HTTP 402 with a BOLT11 invoice in WWW-Authenticate header
3. Pay the invoice, receive the preimage
4. Retry with: Authorization: L402 <preimage>:<macaroon>
5. Optional: Add X-Grace-Tip: <satoshis> to bid for priority rank

## Pricing
- Base access: 100 sats (~$0.001)
- Council verdict: 10,000 sats (~$0.10)
- Grace Tips: optional, 0 to 1,000,000 sats

## Auction Mechanics
All requests in a 5ms window compete by Grace Tip amount.
Highest tip = rank 1 = fastest upstream execution.
Public auction book: GET /v1/auction/book
All auctions auditable via Merkle proof: GET /v1/audit/proof/<auction_id>

## SDK
pip install pne-client

## Endpoints
GET  /v1/market-data?symbol=IWM
POST /v1/council
GET  /v1/options?symbol=IWM
GET  /v1/scan
GET  /v1/auction/book
GET  /v1/leaderboard
GET  /v1/audit/merkle-root
WS   /ws/loom
"#,
    )
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

fn parse_grace_tip(headers: &HeaderMap) -> u64 {
    headers
        .get("X-Grace-Tip")
        .and_then(|v| v.to_str().ok())
        .and_then(|s| s.parse::<u64>().ok())
        .unwrap_or(0)
}

fn is_dark_pool(headers: &HeaderMap) -> bool {
    headers
        .get("X-Dark-Pool")
        .and_then(|v| v.to_str().ok())
        .map(|s| s.eq_ignore_ascii_case("true") || s == "1")
        .unwrap_or(false)
}

fn extract_symbol_from_body(body: &Bytes) -> Option<String> {
    serde_json::from_slice::<Value>(body)
        .ok()?
        .get("symbol")?
        .as_str()
        .map(|s| s.to_uppercase())
}

fn wallet_hash_or_default(wallet: &str) -> String {
    use sha2::{Digest, Sha256};
    let mut h = Sha256::new();
    h.update(wallet.as_bytes());
    format!("sha256:{}", hex::encode(h.finalize()))
}

fn chrono_date() -> String {
    let secs = epoch_ms() / 1000;
    let days = secs / 86400;
    format!("day-{}", days)
}

fn attach_auction_headers(
    h: &mut axum::http::HeaderMap,
    result: &auction::AuctionResult,
    leaf: &str,
    grace_tip: u64,
) {
    h.insert("X-Auction-Rank", result.rank.to_string().parse().unwrap());
    h.insert("X-Auction-Window", result.window_id.to_string().parse().unwrap());
    h.insert(
        "X-Execution-Latency",
        format!("{}ms", result.execution_latency_ms as u64).parse().unwrap(),
    );
    h.insert("X-Grace-Tip-Paid", grace_tip.to_string().parse().unwrap());
    h.insert("X-Merkle-Leaf", leaf.parse().unwrap());
    h.insert("X-PNE-Version", "1.0.0".parse().unwrap());
    h.insert("X-Data-Source", "SqueezeOS".parse().unwrap());
}
