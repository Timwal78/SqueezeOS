use sha2::{Digest, Sha256};

/// Compute the Merkle leaf for an auction result.
/// leaf = SHA256(auction_id || winner_wallet_hash || tip_amount_str || timestamp_str)
pub fn compute_leaf(
    request_id: &str,
    wallet_hash: &str,
    tip_sats: u64,
    upstream_response_hash: &str,
    timestamp_ms: u64,
) -> String {
    let input = format!(
        "{}|{}|{}|{}|{}",
        request_id, wallet_hash, tip_sats, upstream_response_hash, timestamp_ms
    );
    let mut hasher = Sha256::new();
    hasher.update(input.as_bytes());
    format!("sha256:{}", hex::encode(hasher.finalize()))
}

/// Build a Merkle root from a list of leaf hashes.
pub fn build_root(leaves: &[String]) -> Option<String> {
    if leaves.is_empty() {
        return None;
    }

    let mut layer: Vec<Vec<u8>> = leaves
        .iter()
        .map(|l| hex::decode(l.strip_prefix("sha256:").unwrap_or(l)).unwrap_or_default())
        .collect();

    while layer.len() > 1 {
        if layer.len() % 2 != 0 {
            layer.push(layer.last().unwrap().clone());
        }
        layer = layer
            .chunks(2)
            .map(|pair| {
                let mut hasher = Sha256::new();
                hasher.update(&pair[0]);
                hasher.update(&pair[1]);
                hasher.finalize().to_vec()
            })
            .collect();
    }

    Some(format!("0x{}", hex::encode(&layer[0])))
}

/// Generate an inclusion proof for a leaf at the given index.
pub fn generate_proof(leaves: &[String], target_index: usize) -> Vec<ProofNode> {
    if leaves.is_empty() || target_index >= leaves.len() {
        return vec![];
    }

    let mut layer: Vec<Vec<u8>> = leaves
        .iter()
        .map(|l| hex::decode(l.strip_prefix("sha256:").unwrap_or(l)).unwrap_or_default())
        .collect();

    let mut proof = Vec::new();
    let mut idx = target_index;

    while layer.len() > 1 {
        if layer.len() % 2 != 0 {
            layer.push(layer.last().unwrap().clone());
        }

        let sibling_idx = if idx % 2 == 0 { idx + 1 } else { idx - 1 };
        let position = if idx % 2 == 0 { "right" } else { "left" };

        proof.push(ProofNode {
            sibling: format!("sha256:{}", hex::encode(&layer[sibling_idx])),
            position: position.to_string(),
        });

        idx /= 2;
        layer = layer
            .chunks(2)
            .map(|pair| {
                let mut hasher = Sha256::new();
                hasher.update(&pair[0]);
                hasher.update(&pair[1]);
                hasher.finalize().to_vec()
            })
            .collect();
    }

    proof
}

/// Verify that a leaf is included in a tree with the given root.
pub fn verify_proof(leaf: &str, proof: &[ProofNode], root: &str) -> bool {
    let mut current = hex::decode(leaf.strip_prefix("sha256:").unwrap_or(leaf))
        .unwrap_or_default();

    for node in proof {
        let sibling = hex::decode(
            node.sibling.strip_prefix("sha256:").unwrap_or(&node.sibling),
        )
        .unwrap_or_default();

        let mut hasher = Sha256::new();
        if node.position == "right" {
            hasher.update(&current);
            hasher.update(&sibling);
        } else {
            hasher.update(&sibling);
            hasher.update(&current);
        }
        current = hasher.finalize().to_vec();
    }

    let computed_root = format!("0x{}", hex::encode(&current));
    computed_root == root
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct ProofNode {
    pub sibling: String,
    pub position: String,
}

pub fn hash_response(body: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(body);
    format!("sha256:{}", hex::encode(hasher.finalize()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn merkle_root_single_leaf() {
        let leaves = vec!["sha256:abc123".to_string()];
        assert!(build_root(&leaves).is_some());
    }

    #[test]
    fn merkle_proof_verify_roundtrip() {
        let leaves: Vec<String> = (0..8)
            .map(|i| {
                let mut h = Sha256::new();
                h.update(format!("leaf_{}", i).as_bytes());
                format!("sha256:{}", hex::encode(h.finalize()))
            })
            .collect();

        let root = build_root(&leaves).unwrap();

        for (i, leaf) in leaves.iter().enumerate() {
            let proof = generate_proof(&leaves, i);
            assert!(
                verify_proof(leaf, &proof, &root),
                "Proof failed for leaf {}",
                i
            );
        }
    }
}
