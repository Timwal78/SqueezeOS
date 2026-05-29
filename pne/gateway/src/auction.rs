use anyhow::Result;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio::time::sleep;
use uuid::Uuid;

use crate::redis_state::RedisState;

/// Current epoch in milliseconds
pub fn epoch_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

/// Window ID: which 5ms bucket does this timestamp fall into
pub fn window_id(ts_ms: u64, window_ms: u64) -> u64 {
    ts_ms / window_ms
}

/// Time until the current window closes, in ms
pub fn ms_until_window_close(window_ms: u64) -> u64 {
    let now = epoch_ms();
    let current_window = now / window_ms;
    let window_end = (current_window + 1) * window_ms;
    window_end.saturating_sub(now)
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuctionBid {
    pub request_id: String,
    pub grace_tip: u64,
    pub wallet_hash: String,
    pub endpoint: String,
    pub submitted_ms: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuctionResult {
    pub request_id: String,
    pub rank: u32,
    pub grace_tip: u64,
    pub wallet_hash: String,
    pub window_id: u64,
    pub execution_latency_ms: f64,
}

/// Entry point for auction participation.
/// Returns the auction rank (1 = highest priority = executes first).
/// Blocks until the current auction window resolves.
pub async fn enter_auction(
    redis: Arc<RedisState>,
    endpoint: &str,
    grace_tip: u64,
    wallet_hash: &str,
    window_ms: u64,
) -> Result<AuctionResult> {
    let request_id = Uuid::new_v4().to_string();
    let submitted_ms = epoch_ms();
    let wid = window_id(submitted_ms, window_ms);

    let bid = AuctionBid {
        request_id: request_id.clone(),
        grace_tip,
        wallet_hash: wallet_hash.to_string(),
        endpoint: endpoint.to_string(),
        submitted_ms,
    };

    // Submit bid to Redis sorted set
    redis.submit_bid(wid, &bid).await?;

    // Wait for the window to close
    let wait_ms = ms_until_window_close(window_ms);
    if wait_ms > 0 {
        sleep(Duration::from_millis(wait_ms)).await;
    }

    // Resolve: fetch all bids in window ranked by tip desc, then by submission time
    let ranked = redis.resolve_auction(wid).await?;
    let rank = ranked
        .iter()
        .position(|b| b.request_id == request_id)
        .map(|i| i as u32 + 1)
        .unwrap_or(u32::MAX);

    let execution_latency_ms = (epoch_ms() - submitted_ms) as f64;

    Ok(AuctionResult {
        request_id,
        rank,
        grace_tip,
        wallet_hash: wallet_hash.to_string(),
        window_id: wid,
        execution_latency_ms,
    })
}

/// In-memory priority queue for a single auction window.
/// Key: (grace_tip DESC, submitted_ms ASC) — BTreeMap with inverted tip for desc order.
#[derive(Default)]
pub struct AuctionWindow {
    /// (neg_tip, submitted_ms, request_id) → AuctionBid
    bids: BTreeMap<(i64, u64, String), AuctionBid>,
}

impl AuctionWindow {
    pub fn insert(&mut self, bid: AuctionBid) {
        let key = (-(bid.grace_tip as i64), bid.submitted_ms, bid.request_id.clone());
        self.bids.insert(key, bid);
    }

    /// Returns bids in priority order (rank 1 first)
    pub fn ranked(&self) -> Vec<&AuctionBid> {
        self.bids.values().collect()
    }

    pub fn len(&self) -> usize {
        self.bids.len()
    }

    pub fn is_empty(&self) -> bool {
        self.bids.is_empty()
    }
}

#[derive(Debug, Serialize, Deserialize)]
pub struct AuctionBookSnapshot {
    pub window_id: u64,
    pub window_ms: u64,
    pub bids: Vec<AuctionBookEntry>,
    pub resolves_in_ms: f64,
    pub total_bids: usize,
    pub total_tips_sats: u64,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct AuctionBookEntry {
    pub rank: u32,
    pub tip_sats: u64,
    pub wallet_hash: String,
    pub submitted_ms: u64,
}

impl AuctionBookSnapshot {
    pub fn awaiting() -> Self {
        let now = epoch_ms();
        Self {
            window_id: now / 5,
            window_ms: 5,
            bids: vec![],
            resolves_in_ms: ms_until_window_close(5) as f64,
            total_bids: 0,
            total_tips_sats: 0,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn auction_window_ranks_by_tip_desc() {
        let mut window = AuctionWindow::default();
        window.insert(AuctionBid {
            request_id: "a".to_string(),
            grace_tip: 1000,
            wallet_hash: "w1".to_string(),
            endpoint: "/v1/test".to_string(),
            submitted_ms: 100,
        });
        window.insert(AuctionBid {
            request_id: "b".to_string(),
            grace_tip: 5000,
            wallet_hash: "w2".to_string(),
            endpoint: "/v1/test".to_string(),
            submitted_ms: 101,
        });
        window.insert(AuctionBid {
            request_id: "c".to_string(),
            grace_tip: 3000,
            wallet_hash: "w3".to_string(),
            endpoint: "/v1/test".to_string(),
            submitted_ms: 99,
        });

        let ranked = window.ranked();
        assert_eq!(ranked[0].request_id, "b"); // 5000 tip
        assert_eq!(ranked[1].request_id, "c"); // 3000 tip
        assert_eq!(ranked[2].request_id, "a"); // 1000 tip
    }

    #[test]
    fn auction_window_breaks_tie_by_submission_time() {
        let mut window = AuctionWindow::default();
        window.insert(AuctionBid {
            request_id: "late".to_string(),
            grace_tip: 2000,
            wallet_hash: "w1".to_string(),
            endpoint: "/v1/test".to_string(),
            submitted_ms: 200,
        });
        window.insert(AuctionBid {
            request_id: "early".to_string(),
            grace_tip: 2000,
            wallet_hash: "w2".to_string(),
            endpoint: "/v1/test".to_string(),
            submitted_ms: 100,
        });

        let ranked = window.ranked();
        assert_eq!(ranked[0].request_id, "early"); // same tip, earlier wins
    }
}
