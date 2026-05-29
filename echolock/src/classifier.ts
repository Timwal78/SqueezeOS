import type { EFV, TierDistribution, CognitionTier } from './types';

// Expected EFV profile per tier.
// Columns: [latencyScore, retryPatience, feeIntelligence, correctionTrend, consistency, entropyTolerance]
const TIER_PROFILES: ReadonlyArray<readonly number[]> = [
  [0.12, 0.30, 0.04, 0.30, 0.92, 0.05],  // T0: scripted  — instant, rigid, minimum-fee, no adaptation
  [0.22, 0.40, 0.28, 0.42, 0.72, 0.22],  // T1: naive     — slightly above min, low fee sense
  [0.42, 0.52, 0.58, 0.58, 0.62, 0.52],  // T2: adaptive  — approaches midpoint, some learning
  [0.64, 0.66, 0.78, 0.74, 0.66, 0.72],  // T3: strategic — near-optimal, consistent, adaptive
  [0.82, 0.82, 0.92, 0.88, 0.72, 0.88],  // T4: institutional — thoughtful, precise, fully adaptive
];

const EFV_KEYS: (keyof EFV)[] = [
  'latencyScore', 'retryPatience', 'feeIntelligence',
  'correctionTrend', 'consistency', 'entropyTolerance',
];

export function classify(efv: EFV): TierDistribution {
  const vec  = EFV_KEYS.map(k => efv[k]);
  const sims = TIER_PROFILES.map(profile => cosineSimilarity(vec, Array.from(profile)));

  // Low temperature → sharper distribution from clear behavioral signals
  const rawWeights = softmax(sims, 0.25);

  // Blend toward uniform when evidence is thin (few settlements)
  const c       = efv.sampleConfidence;
  const blended = rawWeights.map(w => w * c + (1 - c) / 5);
  const sum     = blended.reduce((a, b) => a + b, 0);
  const weights = blended.map(w => w / sum) as [number, number, number, number, number];

  return { weights };
}

export function sampleTier(dist: TierDistribution): CognitionTier {
  let cumulative = 0;
  const r = Math.random();
  for (let i = 0; i < dist.weights.length; i++) {
    cumulative += dist.weights[i];
    if (r < cumulative) return i as CognitionTier;
  }
  return 4;
}

export function expectedTier(dist: TierDistribution): number {
  return dist.weights.reduce((acc, w, i) => acc + w * i, 0);
}

function cosineSimilarity(a: number[], b: number[]): number {
  const dot  = a.reduce((s, ai, i) => s + ai * b[i], 0);
  const magA = Math.sqrt(a.reduce((s, ai) => s + ai * ai, 0));
  const magB = Math.sqrt(b.reduce((s, bi) => s + bi * bi, 0));
  return magA * magB > 0 ? dot / (magA * magB) : 0;
}

function softmax(xs: number[], temperature: number): number[] {
  const scaled = xs.map(x => x / temperature);
  const maxVal = Math.max(...scaled);
  const exps   = scaled.map(x => Math.exp(x - maxVal));
  const total  = exps.reduce((a, b) => a + b, 0);
  return exps.map(e => e / total);
}
