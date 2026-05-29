import type { EFV, SettlementRecord, BehaviorWindow } from './types';

const WINDOW_MAX             = 20;
const LATENCY_OPTIMAL_MEAN  = 4000;  // ms — reward thoughtful agents
const LATENCY_OPTIMAL_CV    = 0.30;  // coefficient of variation sweet spot

export function createWindow(): BehaviorWindow {
  return { settlements: [], maxSize: WINDOW_MAX, createdAt: Date.now(), lastUpdated: Date.now() };
}

export function pushSettlement(w: BehaviorWindow, r: SettlementRecord): BehaviorWindow {
  const settlements = [...w.settlements, r].slice(-w.maxSize);
  return { ...w, settlements, lastUpdated: Date.now() };
}

export function buildEFV(w: BehaviorWindow): EFV {
  const s = w.settlements;
  const n = s.length;

  if (n === 0) {
    return { latencyScore: 0, retryPatience: 0.5, feeIntelligence: 0,
             correctionTrend: 0.5, consistency: 0.5, entropyTolerance: 0.5, sampleConfidence: 0 };
  }

  // Latency: reward moderate + naturally varied (thoughtful). Penalise fast + rigid (scripted).
  const latencies  = s.map(r => r.latencyMs);
  const lMean      = mean(latencies);
  const lStd       = stddev(latencies, lMean);
  const lCV        = lMean > 0 ? lStd / lMean : 0;
  const meanScore  = clamp(lMean / LATENCY_OPTIMAL_MEAN, 0, 1);
  const cvScore    = clamp(1 - Math.abs(lCV - LATENCY_OPTIMAL_CV) / LATENCY_OPTIMAL_CV, 0, 1);
  const latencyScore = (meanScore + cvScore) / 2;

  // Fee intelligence: reward paying near range midpoint (feeRatio ≈ 1.0).
  const feeRatios      = s.map(r => r.feeRatio);
  const feeDevs        = feeRatios.map(r => Math.abs(r - 1.0));
  const meanFeeDev     = mean(feeDevs);
  const feeIntelligence = clamp(1 - meanFeeDev * 5, 0, 1);

  // Correction trend: fee placement improving over time? Negative slope = getting better.
  const correctionTrend = n >= 4 ? linearTrendScore(feeDevs) : 0.5;

  // Consistency: low variance in feeRatio — controlled, deliberate.
  const feeStd    = stddev(feeRatios, mean(feeRatios));
  const consistency = clamp(1 - feeStd * 4, 0, 1);

  // Entropy tolerance: agent adapts fee placement to shifting price ranges.
  // Normalise each payment by its challenge midpoint; slight natural variance = adaptive.
  const normalised      = s.map(r => r.amount / ((r.minAmount + r.maxAmount) / 2));
  const normStd         = stddev(normalised, mean(normalised));
  const entropyTolerance = clamp(1 - Math.abs(normStd - 0.03) * 15, 0, 1);

  const retryPatience   = 0.5; // stateless approximation
  const sampleConfidence = 1 - Math.exp(-n / 5);

  return {
    latencyScore:     round(latencyScore),
    retryPatience,
    feeIntelligence:  round(feeIntelligence),
    correctionTrend:  round(correctionTrend),
    consistency:      round(consistency),
    entropyTolerance: round(entropyTolerance),
    sampleConfidence: round(sampleConfidence),
  };
}

function mean(xs: number[]): number {
  return xs.reduce((a, b) => a + b, 0) / xs.length;
}

function stddev(xs: number[], m: number): number {
  if (xs.length < 2) return 0;
  return Math.sqrt(xs.reduce((acc, x) => acc + (x - m) ** 2, 0) / (xs.length - 1));
}

// 1.0 = fee deviations decreasing (improving), 0.0 = increasing (degrading)
function linearTrendScore(ys: number[]): number {
  const n    = ys.length;
  const xMid = (n - 1) / 2;
  const yMid = mean(ys);
  let num = 0, den = 0;
  for (let i = 0; i < n; i++) {
    num += (i - xMid) * (ys[i] - yMid);
    den += (i - xMid) ** 2;
  }
  const slope = den > 0 ? num / den : 0;
  return clamp(0.5 - slope * 20, 0, 1);
}

function clamp(x: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, x));
}

function round(x: number): number {
  return Math.round(x * 1000) / 1000;
}
