use anyhow::Result;
use redis::{aio::ConnectionManager, AsyncCommands, Client};
use serde_json;
use std::sync::Arc;
use tokio::sync::broadcast;
use tracing::warn;

use crate::auction::AuctionBid;

const AUCTION_WINDOW_TTL_SECS: usize = 10;
const LOOM_CHANNEL: &str = "loom:events";

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
        let _: () = conn.expire(&key, AUCTION_WINDOW_TTL_SECS).await?;

        // Store full bid metadata
        let _: () = conn.set_ex(&meta_key, &json, AUCTION_WINDOW_TTL_SECS as u64).await?;

        // Broadcast to Loom
        let event = serde_json::json!({
            "type": "BID_RECEIVED",
            "ts": bid.submitted_ms,
            "request_id": bid.request_id,
            "tip_sats": bid.grace_tip,
            "wallet_hash": bid.wallet_hash,
            "endpoint": bid.endpoint,
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

    /// Get agent leaderboard top N.
    pub async fn get_leaderboard(&self, limit: isize) -> Result<Vec<(String, f64)>> {
        let mut conn = self.conn.clone();
        let entries: Vec<(String, f64)> = conn
            .zrevrange_withscores("agent:leaderboard", 0, limit - 1)
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
                                    match pubsub.on_message().next_message().await {
                                        Ok(msg) => {
                                            if let Ok(payload) = msg.get_payload::<String>() {
                                                let _ = tx.send(payload);
                                            }
                                        }
                                        Err(e) => {
                                            warn!("Redis pubsub message error: {}", e);
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

// Extension trait for a simpler pubsub API
trait NextMessage {
    async fn next_message(&mut self) -> Result<redis::Msg, redis::RedisError>;
}

impl NextMessage for redis::aio::PubSub {
    async fn next_message(&mut self) -> Result<redis::Msg, redis::RedisError> {
        use futures_util::StreamExt;
        self.on_message()
            .next()
            .await
            .ok_or_else(|| redis::RedisError::from((redis::ErrorKind::IoError, "stream ended")))
    }
}
