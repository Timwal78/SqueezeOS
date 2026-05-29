import { createHash } from 'crypto';
import type { CognitionTier } from './types';

interface DepthConfig {
  fieldRetention:   number;  // [0,1] fraction of object keys preserved
  numericPrecision: number;  // decimal places (-1 = unlimited)
  textLimit:        number;  // max string chars (-1 = unlimited)
  arrayLimit:       number;  // max array elements (-1 = unlimited)
  metaIncluded:     boolean; // include '_'-prefixed keys
}

const DEPTH_CONFIG: Record<CognitionTier, DepthConfig> = {
  0: { fieldRetention: 0.20, numericPrecision: 0, textLimit:  30, arrayLimit:  2, metaIncluded: false },
  1: { fieldRetention: 0.40, numericPrecision: 1, textLimit:  60, arrayLimit:  4, metaIncluded: false },
  2: { fieldRetention: 0.65, numericPrecision: 2, textLimit: 120, arrayLimit: 12, metaIncluded: false },
  3: { fieldRetention: 0.85, numericPrecision: 4, textLimit: 400, arrayLimit: 40, metaIncluded: true  },
  4: { fieldRetention: 1.00, numericPrecision: 6, textLimit:  -1, arrayLimit: -1, metaIncluded: true  },
};

// Transform raw data to the epistemic depth earned by the agent's behavior.
// No false data — truth is compressed, never fabricated.
export function transformResponse(raw: unknown, tier: CognitionTier, entropySeed: string): unknown {
  return compress(raw, DEPTH_CONFIG[tier], entropySeed, 0);
}

function compress(node: unknown, cfg: DepthConfig, seed: string, depth: number): unknown {
  if (node === null || node === undefined) return node;
  if (typeof node === 'boolean') return node;

  if (typeof node === 'number') {
    return cfg.numericPrecision < 0
      ? node
      : parseFloat(node.toFixed(cfg.numericPrecision));
  }

  if (typeof node === 'string') {
    return cfg.textLimit < 0 || node.length <= cfg.textLimit
      ? node
      : node.slice(0, cfg.textLimit) + '…';
  }

  if (Array.isArray(node)) {
    const limit = cfg.arrayLimit < 0 ? node.length : cfg.arrayLimit;
    return node
      .slice(0, limit)
      .map((el, i) => compress(el, cfg, childSeed(seed, String(i)), depth + 1));
  }

  if (typeof node === 'object') {
    const obj  = node as Record<string, unknown>;
    const keys = Object.keys(obj).filter(k => cfg.metaIncluded || !k.startsWith('_'));

    const keepCount = Math.max(1, Math.round(keys.length * cfg.fieldRetention));

    // Deterministic, seed-dependent selection — opaque to the agent.
    // Same tier + same seed always yields the same field subset.
    const selected = keys
      .map(k => ({ k, rank: hashRank(seed, k) }))
      .sort((a, b) => a.rank - b.rank)
      .slice(0, keepCount)
      .map(x => x.k);

    const out: Record<string, unknown> = {};
    for (const k of selected) {
      out[k] = compress(obj[k], cfg, childSeed(seed, k), depth + 1);
    }
    return out;
  }

  return node;
}

function hashRank(seed: string, key: string): number {
  return parseInt(
    createHash('sha256').update(`${seed}:${key}`).digest('hex').slice(0, 8),
    16
  );
}

function childSeed(parent: string, key: string): string {
  return createHash('sha256').update(`${parent}:${key}`).digest('hex').slice(0, 16);
}
