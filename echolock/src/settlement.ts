import { verifyChallengeMac } from './challenge';
import type { PaymentChallenge, PaymentProof, SettlementRecord } from './types';

const BOUNDARY_EPSILON = 1e-5;

export type SettlementErrorCode =
  | 'EXPIRED' | 'BAD_HMAC' | 'AMOUNT_BELOW_MIN' | 'AMOUNT_ABOVE_MAX'
  | 'EXACT_BOUNDARY' | 'CHALLENGE_MISMATCH' | 'DUPLICATE_TX';

export interface SettlementError { code: SettlementErrorCode; detail: string; }

const _usedTxHashes = new Set<string>();

export function verifySettlement(
  challenge: PaymentChallenge,
  proof: PaymentProof,
  secret: string,
  now = Date.now()
): { ok: true; record: SettlementRecord } | { ok: false; error: SettlementError } {

  if (now > challenge.expiresAt)
    return { ok: false, error: { code: 'EXPIRED', detail: 'Challenge window closed' } };

  if (!verifyChallengeMac(challenge, secret))
    return { ok: false, error: { code: 'BAD_HMAC', detail: 'Challenge integrity failed' } };

  if (proof.challengeId !== challenge.id)
    return { ok: false, error: { code: 'CHALLENGE_MISMATCH', detail: 'Proof does not match challenge' } };

  if (_usedTxHashes.has(proof.txHash))
    return { ok: false, error: { code: 'DUPLICATE_TX', detail: 'Transaction already consumed' } };

  const { amount } = proof;
  const { minAmount, maxAmount } = challenge;

  if (amount < minAmount)
    return { ok: false, error: { code: 'AMOUNT_BELOW_MIN', detail: `Minimum: ${minAmount} RLUSD` } };

  if (amount > maxAmount)
    return { ok: false, error: { code: 'AMOUNT_ABOVE_MAX', detail: `Maximum: ${maxAmount} RLUSD` } };

  if (Math.abs(amount - minAmount) < BOUNDARY_EPSILON || Math.abs(amount - maxAmount) < BOUNDARY_EPSILON)
    return { ok: false, error: { code: 'EXACT_BOUNDARY', detail: 'Range boundaries are not valid payment amounts' } };

  _usedTxHashes.add(proof.txHash);

  const midpoint = (minAmount + maxAmount) / 2;
  const record: SettlementRecord = {
    challengeId: challenge.id,
    txHash:      proof.txHash,
    amount,
    minAmount,
    maxAmount,
    latencyMs:   proof.submittedAt - challenge.createdAt,
    feeRatio:    amount / midpoint,
    timestamp:   now,
  };

  return { ok: true, record };
}
