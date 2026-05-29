import { createHmac, createHash, randomBytes } from 'crypto';
import type { PaymentChallenge } from './types';

const BASE_AMOUNT = 0.01;
const RANGE_PCT   = 0.20;
export const CHALLENGE_TTL_MS = 90_000;

export function generateChallenge(
  path: string,
  secret: string,
  recipient: string,
  now = Date.now()
): PaymentChallenge {
  const nonce     = randomBytes(12).toString('hex');
  const createdAt = now;
  const expiresAt = now + CHALLENGE_TTL_MS;

  const id = createHash('sha256')
    .update(`${path}:${nonce}:${expiresAt}`)
    .digest('hex');

  const entropySeed = createHmac('sha256', secret)
    .update(`entropy:${id}:${createdAt}`)
    .digest('hex')
    .slice(0, 32);

  const minAmount = parseFloat((BASE_AMOUNT * (1 - RANGE_PCT)).toFixed(6));
  const maxAmount = parseFloat((BASE_AMOUNT * (1 + RANGE_PCT)).toFixed(6));

  const hmac = createHmac('sha256', secret)
    .update(`${id}:${createdAt}:${minAmount}:${maxAmount}:${expiresAt}:${recipient}`)
    .digest('hex');

  return { id, createdAt, minAmount, maxAmount, currency: 'RLUSD', network: 'XRPL',
           recipient, expiresAt, entropySeed, hmac };
}

export function verifyChallengeMac(c: PaymentChallenge, secret: string): boolean {
  const expected = createHmac('sha256', secret)
    .update(`${c.id}:${c.createdAt}:${c.minAmount}:${c.maxAmount}:${c.expiresAt}:${c.recipient}`)
    .digest('hex');
  return timingSafeEqual(expected, c.hmac);
}

export function encodeChallengeHeader(c: PaymentChallenge): string {
  return Buffer.from(JSON.stringify(c)).toString('base64url');
}

export function decodeChallengeHeader(encoded: string): PaymentChallenge {
  return JSON.parse(Buffer.from(encoded, 'base64url').toString('utf-8')) as PaymentChallenge;
}

function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}
