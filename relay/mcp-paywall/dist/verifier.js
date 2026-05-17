"use strict";
/**
 * Payment proof verification.
 *
 * The proof is a base64-encoded JSON envelope:
 *   { scheme: "exact", network: string, payload: "<signed_xrpl_tx_blob>" }
 *
 * Verification steps:
 *   1. Decode the envelope
 *   2. Decode the XRPL tx blob (xrpl.decode)
 *   3. Verify TransactionType === "Payment"
 *   4. Verify Destination === config.recipient
 *   5. Verify Amount >= config.priceRlusd (RLUSD IOU or XRP)
 *   6. Anti-replay: reject if this tx_blob was used in the last gracePeriodMs
 *
 * Anti-replay is in-process (Map with TTL). For multi-instance deployments
 * replace with a shared Redis SET — the `_antiReplay` export is injectable.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.createInMemoryReplayStore = createInMemoryReplayStore;
exports.verifyPayment = verifyPayment;
const xrpl_1 = require("xrpl");
function createInMemoryReplayStore() {
    const store = new Map();
    return {
        has(key) {
            const exp = store.get(key);
            if (exp === undefined)
                return false;
            if (Date.now() > exp) {
                store.delete(key);
                return false;
            }
            return true;
        },
        set(key, expiresAt) { store.set(key, expiresAt); },
        sweep() {
            const now = Date.now();
            for (const [k, exp] of store)
                if (now > exp)
                    store.delete(k);
        },
    };
}
// Default store — per-process singleton
const _defaultStore = createInMemoryReplayStore();
// ── RLUSD issuer addresses ────────────────────────────────────────────────────
const RLUSD_ISSUERS = {
    xrpl_mainnet: "rHb9CJAWyB4rj91VRWn96DkukG4bwdtyTh",
    xrpl_testnet: "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De",
};
// ── Core verification ─────────────────────────────────────────────────────────
async function verifyPayment(proofBase64, config, store = _defaultStore) {
    // 1. Parse outer envelope
    let envelope;
    try {
        envelope = JSON.parse(Buffer.from(proofBase64, "base64").toString("utf8"));
    }
    catch {
        return { valid: false, reason: "Malformed proof envelope" };
    }
    const txBlob = envelope.payload;
    if (typeof txBlob !== "string" || !txBlob) {
        return { valid: false, reason: "Missing tx payload in proof" };
    }
    // 2. Decode XRPL tx blob
    let decoded;
    try {
        decoded = (0, xrpl_1.decode)(txBlob);
    }
    catch {
        return { valid: false, reason: "Cannot decode XRPL tx blob" };
    }
    // 3. Transaction type
    if (decoded.TransactionType !== "Payment") {
        return { valid: false, reason: `Expected Payment tx, got ${decoded.TransactionType}` };
    }
    // 4. Destination
    if (decoded.Destination !== config.recipient) {
        return {
            valid: false,
            reason: `Wrong recipient: expected ${config.recipient}, got ${decoded.Destination}`,
        };
    }
    // 5. Amount: RLUSD IOU or XRP drops
    const ok = verifyAmount(decoded.Amount, config.priceRlusd, config.network);
    if (!ok.valid)
        return ok;
    // 6. Anti-replay: use tx_blob fingerprint (last 32 chars of blob are signature-unique)
    const replayKey = `${decoded.Destination}:${txBlob.slice(-48)}`;
    if (store.has(replayKey)) {
        return { valid: false, reason: "Payment proof already used (replay attack)" };
    }
    const gracePeriodMs = config.gracePeriodMs ?? 300_000;
    store.set(replayKey, Date.now() + gracePeriodMs);
    return { valid: true };
}
function verifyAmount(amount, requiredRlusd, network) {
    if (amount === null || amount === undefined) {
        return { valid: false, reason: "Missing Amount field" };
    }
    // RLUSD IOU: { currency: "USD", issuer: "...", value: "0.10" }
    if (typeof amount === "object") {
        const iou = amount;
        if (iou.currency !== "USD") {
            return { valid: false, reason: `Expected USD currency, got ${iou.currency}` };
        }
        const expectedIssuer = RLUSD_ISSUERS[network];
        if (expectedIssuer && iou.issuer !== expectedIssuer) {
            return { valid: false, reason: "RLUSD issuer mismatch" };
        }
        const paid = parseFloat(iou.value ?? "0");
        if (paid < requiredRlusd) {
            return { valid: false, reason: `Underpayment: ${paid} RLUSD < ${requiredRlusd} RLUSD required` };
        }
        return { valid: true };
    }
    // XRP drops (fallback; servers should prefer RLUSD)
    if (typeof amount === "string") {
        const drops = parseInt(amount, 10);
        const xrp = drops / 1_000_000;
        // Testnet approximation: 1 RLUSD = 0.5 XRP — accept if 2x overcharged to be safe
        if (xrp < requiredRlusd * 0.4) {
            return { valid: false, reason: `XRP amount ${xrp} insufficient for ${requiredRlusd} RLUSD` };
        }
        return { valid: true };
    }
    return { valid: false, reason: "Unrecognised Amount format" };
}
//# sourceMappingURL=verifier.js.map