use anyhow::Result;
use redis::{aio::ConnectionManager, AsyncCommands, Client};
use serde_json;
use std::sync::Arc;
use tokio::sync::broadcast;
use tracing::warn;

use crate::auction::AuctionBid;

const AUCTION_WINDOW_TTL_SECS: i64 = 10;
const LOOM_CHANNEL: &str = "loom:events";
const CERTIFICATE_TTL_SECS: u64 = 86_400; // 24 hours
const FLOW_WINDOW_SECS: i64 = 3_600;      // 1 hour rolling

#[derive(Clone)]
pub struct RedisState {
    conn: ConnectionManager,
    pub loom_tx: broadcast::Sender<String>,
}

impl RedisState {
    pub async fn connect(url: &str) -> Result<Arc<Self>> {
        let client = Client::open(url)?;
        let conn = ConnectionManager::new(client).await?;
        let (loom_tx, _) = broadcast::channel(1024);

        let state = Arc::new(Self { conn, loom_tx });
        state.spawn_pubsub_relay(url).await;
        Ok(state)
    }

    /// Submit a bid into the auction window's sorted set.
    pub async fn submit_bid(&self, window_id: u64, bid: &AuctionBid) -> Result<()> {
        let key = format!("auction:window:{}", window_id);
        let meta_key = format!("auction:meta:{}", bid.request_id);
        let json = serde_json::to_string(bid)?;

        let mut conn = self.conn.clone();

        // Store bid in sorted set (score = grace_tip, tiebreak by submitted_ms embedded in value)
        let _: () = conn
            .zadd(&key, &bid.request_id, bid.grace_tip as f64)
            .await?;
        let _: () = conn.expire::<_, ()>(&key, AUCTION_WINDOW_TTL_SECS).await?;

        // Store full bid metadata
        let _: () = conn.set_ex(&meta_key, &json, AUCTION_WINDOW_TTL_SECS as u64).await?;

        // Broadcast to Loom — dark pool bids are redacted from public view
        let dark_pool = bid.wallet_hash == "[REDACTED]";
        let event = serde_json::json!({
            "type": "BID_RECEIVED",
            "ts": bid.submitted_ms,
            "request_id": if dark_pool { "[REDACTED]" } else { &bid.request_id },
            "tip_sats": if dark_pool { 0 } else { bid.grace_tip }, // dark pool hides tip amount
            "wallet_hash": &bid.wallet_hash,
            "endpoint": &bid.endpoint,
            "dark_pool": dark_pool,
        });
        self.broadcast_loom_event(&event.to_string()).await;

        Ok(())
    }

    /// Resolve auction window — returns bids sorted by tip desc, submission time asc.
    pub async fn resolve_auction(&self, window_id: u64) -> Result<Vec<AuctionBid>> {
        let key = format!("auction:window:{}", window_id);
        let mut conn = self.conn.clone();

        // Get all members sorted by score descending (highest tip first)
        let members: Vec<(String, f64)> = conn.zrevrange_withscores(&key, 0, -1).await?;

        let mut bids = Vec::new();
        for (request_id, _score) in &members {
            let meta_key = format!("auction:meta:{}", request_id);
            let json: Option<String> = conn.get(&meta_key).await?;
            if let Some(j) = json {
                if let Ok(bid) = serde_json::from_str::<AuctionBid>(&j) {
                    bids.push(bid);
                }
            }
        }

        // Sort: grace_tip desc, then submitted_ms asc for ties
        bids.sort_by(|a, b| {
            b.grace_tip
                .cmp(&a.grace_tip)
                .then(a.submitted_ms.cmp(&b.submitted_ms))
        });

        // Broadcast resolution event
        let results: Vec<serde_json::Value> = bids
            .iter()
            .enumerate()
            .map(|(i, b)| {
                serde_json::json!({
                    "rank": i + 1,
                    "request_id": b.request_id,
                    "tip_sats": b.grace_tip,
                    "wallet_hash": b.wallet_hash,
                })
            })
            .collect();

        let event = serde_json::json!({
            "type": "AUCTION_RESOLVED",
            "ts": crate::auction::epoch_ms(),
            "window_id": window_id,
            "results": results,
        });
        self.broadcast_loom_event(&event.to_string()).await;

        // Record to leaderboard
        for (i, bid) in bids.iter().enumerate() {
            if i == 0 && !bid.wallet_hash.is_empty() {
                let _: Result<(), _> = conn
                    .zincr("agent:leaderboard", &bid.wallet_hash, bid.grace_tip as f64)
                    .await;
            }
        }

        Ok(bids)
    }

    /// Append a Merkle leaf to the audit log.
    pub async fn append_merkle_leaf(&self, date: &str, leaf: &str) -> Result<()> {
        let key = format!("audit:merkle:{}", date);
        let mut conn = self.conn.clone();
        let _: () = conn.rpush(&key, leaf).await?;
        Ok(())
    }

    /// Get auction book snapshot (current window bids).
    pub async fn get_auction_book(
        &self,
        window_id: u64,
    ) -> Result<Vec<(String, f64)>> {
        let key = format!("auction:window:{}", window_id);
        let mut conn = self.conn.clone();
        let members: Vec<(String, f64)> = conn.zrevrange_withscores(&key, 0, 49).await?;
        Ok(members)
    }

    /// Set a signal embargo on a symbol. SqueezeOS checks this header directly,
    /// but we also track it in Redis for the auction book to surface.
    pub async fn set_embargo(&self, symbol: &str, auction_id: &str, secs: u64) -> Result<()> {
        let key = format!("embargo:{}", symbol.to_uppercase());
        let mut conn = self.conn.clone();
        let _: () = conn.set_ex(&key, auction_id, secs).await?;
        Ok(())
    }

    /// Check if a symbol is currently under embargo.
    pub async fn get_embargo(&self, symbol: &str) -> Option<String> {
        let key = format!("embargo:{}", symbol.to_uppercase());
        let mut conn = self.conn.clone();
        conn.get(&key).await.ok()
    }

    /// Record a bid in the flow intelligence index (ticker → bid volume).
    pub async fn record_flow_bid(&self, symbol: &str, tip_sats: u64, dark_pool: bool) -> Result<()> {
        if dark_pool {
            return Ok(()); // Dark pool bids don't contribute to public flow signal
        }
        let tips_key = format!("flow:tips:{}", symbol.to_uppercase());
        let count_key = format!("flow:count:{}", symbol.to_uppercase());
        let mut conn = self.conn.clone();
        let _: i64 = conn.incr(&tips_key, tip_sats as i64).await?;
        let _: i64 = conn.incr(&count_key, 1i64).await?;
        conn.expire::<_, ()>(&tips_key, FLOW_WINDOW_SECS).await.ok();
        conn.expire::<_, ()>(&count_key, FLOW_WINDOW_SECS).await.ok();
        Ok(())
    }

    /// Get flow stats for top symbols by bid volume.
    pub async fn get_flow_stats(&self, symbols: &[&str]) -> Result<Vec<(String, u64, u64)>> {
        let mut conn = self.conn.clone();
        let mut results = Vec::new();
        for &sym in symbols {
            let tips_key = format!("flow:tips:{}", sym.to_uppercase());
            let count_key = format!("flow:count:{}", sym.to_uppercase());
            let tips: i64 = conn.get(&tips_key).await.unwrap_or(0i64);
            let count: i64 = conn.get(&count_key).await.unwrap_or(0i64);
            if tips > 0 || count > 0 {
                results.push((sym.to_uppercase(), tips as u64, count as u64));
            }
        }
        results.sort_by(|a, b| b.1.cmp(&a.1)); // Sort by total tips desc
        Ok(results)
    }

    /// Store a latency certificate (Merkle proof + auction metadata) for 24 hours.
    pub async fn store_certificate(&self, auction_id: &str, cert_json: &str) -> Result<()> {
        let key = format!("cert:{}", auction_id);
        let mut conn = self.conn.clone();
        let _: () = conn.set_ex(&key, cert_json, CERTIFICATE_TTL_SECS).await?;
        Ok(())
    }

    /// Retrieve a stored latency certificate.
    pub async fn get_certificate(&self, auction_id: &str) -> Option<String> {
        let key = format!("cert:{}", auction_id);
        let mut conn = self.conn.clone();
        conn.get(&key).await.ok()
    }

    /// Get agent leaderboard top N.
    pub async fn get_leaderboard(&self, limit: i64) -> Result<Vec<(String, f64)>> {
        let mut conn = self.conn.clone();
        let stop = (limit - 1) as isize;
        let entries: Vec<(String, f64)> = conn
            .zrevrange_withscores("agent:leaderboard", 0isize, stop)
            .await?;
        Ok(entries)
    }

    /// Publish an event to the Redis pub/sub channel (for the Loom).
    async fn broadcast_loom_event(&self, json: &str) {
        if self.loom_tx.send(json.to_string()).is_err() {
            // No subscribers currently connected — safe to ignore
        }
    }

    /// Spawn a background task that relays Redis pub/sub to the broadcast channel.
    async fn spawn_pubsub_relay(&self, redis_url: &str) {
        let url = redis_url.to_string();
        let tx = self.loom_tx.clone();

        tokio::spawn(async move {
            loop {
                match Client::open(url.as_str()) {
                    Ok(client) => {
                        match client.get_async_connection().await {
                            Ok(conn) => {
                                let mut pubsub = conn.into_pubsub();
                                if let Err(e) = pubsub.subscribe(LOOM_CHANNEL).await {
                                    warn!("Redis pubsub subscribe error: {}", e);
                                    tokio::time::sleep(tokio::time::Duration::from_secs(2)).await;
                                    continue;
                                }
                                loop {
                                    use futures_util::StreamExt;
                                    match pubsub.on_message().next().await {
                                        Some(msg) => {
                                            if let Ok(payload) = msg.get_payload::<String>() {
                                                let _ = tx.send(payload);
                                            }
                                        }
                                        None => {
                                            warn!("Redis pubsub stream ended");
                                            break;
                                        }
                                    }
                                }
                            }
                            Err(e) => {
                                warn!("Redis pubsub connection error: {}", e);
                            }
                        }
                    }
                    Err(e) => {
                        warn!("Redis client error: {}", e);
                    }
                }
                tokio::time::sleep(tokio::time::Duration::from_secs(2)).await;
            }
        });
    }
}

