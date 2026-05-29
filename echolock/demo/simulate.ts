// Two agents. Same query. Different economic behavior. Different epistemic depth.
// No tier is ever revealed.

import { generateChallenge } from '../src/challenge';
import { verifySettlement } from '../src/settlement';
import { createWindow, pushSettlement, buildEFV } from '../src/fingerprint';
import { classify, sampleTier, expectedTier } from '../src/classifier';
import { transformResponse } from '../src/entropy';
import type { BehaviorWindow, PaymentProof } from '../src/types';

const SECRET    = 'demo-secret';
const RECIPIENT = 'rDemo000000000000000000000000000';

const RAW_INTELLIGENCE = {
  _meta: { engine: 'SqueezeOS', version: '3.0.0', timestamp: Date.now() },
  symbol: 'IWM',
  signals: {
    bias:                  'BULLISH',
    regime:                'ALPHA_EXPANSION',
    confidence:            0.847361,
    squeeze_score:         0.923104,
    gamma_flip:            1847.25,
    dark_pool_flow:        0.631892,
    options_sweep: {
      strikes:                [185, 186, 187, 188, 189, 190],
      volumes:                [12400, 8900, 15200, 22100, 9800, 6700],
      direction:              'CALL_DOMINATED',
      unusual_activity_score: 0.784320,
    },
  },
  council: {
    directive:  'BUY (IGNITION)',
    votes:      { buy: 5, hold: 1, sell: 0 },
    reasoning:  'Cross-engine consensus on momentum continuation above gamma flip level with sustained dark pool accumulation consistent with institutional positioning ahead of macro catalyst.',
    catalysts:  ['Fed pivot probability 67%', 'VIX term structure inversion', 'Put/call ratio 0.42'],
    risk_level: 'MODERATE',
  },
  market_graph: {
    nodes:              847,
    edges:              2341,
    fractal_depth:      3,
    dominant_cluster:   'MOMENTUM_CONTINUATION',
    cluster_confidence: 0.891234,
    adjacent_tickers:   ['SPY', 'QQQ', 'TNA', 'TQQQ', 'SOXL'],
  },
  execution: {
    entry_zone:             [185.40, 186.20],
    stop_loss:              184.15,
    target_1:               189.50,
    target_2:               193.20,
    position_size_pct:      0.035000,
    expected_holding_hours: 6.5,
  },
};

type PayStrategy = (min: number, max: number, round: number) => number;
type LatStrategy = (round: number) => number;

function bar(value: number, width = 30): string {
  return '█'.repeat(Math.round(value * width)).padEnd(width);
}

async function runAgent(
  name: string,
  payStrategy: PayStrategy,
  latStrategy: LatStrategy,
  rounds: number
): Promise<void> {
  console.log('\n' + '='.repeat(66));
  console.log(`  AGENT: ${name}`);
  console.log('='.repeat(66));

  const sessionToken = `demo-${name.toLowerCase().replace(/\W+/g, '-')}`;
  let window: BehaviorWindow = createWindow();

  for (let round = 1; round <= rounds; round++) {
    const now       = Date.now() + round * 200;
    const challenge = generateChallenge('/api/intelligence', SECRET, RECIPIENT, now);
    const amount    = payStrategy(challenge.minAmount, challenge.maxAmount, round);
    const latencyMs = latStrategy(round);

    const proof: PaymentProof = {
      challengeId:  challenge.id,
      txHash:       `0x${'a'.repeat(60)}${String(round).padStart(4, '0')}`,
      amount,
      sessionToken,
      submittedAt: now + latencyMs,
    };

    const result = verifySettlement(challenge, proof, SECRET, now + latencyMs);

    if (!result.ok) {
      console.log(`  Round ${round}: ✗  ${result.error.code}  (amount=${amount.toFixed(6)})`);
      continue;
    }

    window = pushSettlement(window, result.record);
    const mid = (challenge.minAmount + challenge.maxAmount) / 2;
    console.log(
      `  Round ${round}: ✓  paid=${amount.toFixed(6)}  mid=${mid.toFixed(6)}` +
      `  ratio=${result.record.feeRatio.toFixed(3)}  latency=${latencyMs}ms`
    );
  }

  // Economic fingerprint
  console.log('\n  -- Economic Fingerprint Vector ---------------------------------');
  const efv = buildEFV(window);
  const fields: [string, number][] = [
    ['latency score    ', efv.latencyScore],
    ['fee intelligence ', efv.feeIntelligence],
    ['correction trend ', efv.correctionTrend],
    ['consistency      ', efv.consistency],
    ['entropy tolerance', efv.entropyTolerance],
    ['sample confidence', efv.sampleConfidence],
  ];
  for (const [label, val] of fields) {
    console.log(`  ${label}  ${bar(val)}  ${val.toFixed(3)}`);
  }

  // Tier distribution (internal, never sent to agent)
  const dist = classify(efv);
  console.log('\n  -- Tier Distribution (internal, never disclosed) ---------------');
  dist.weights.forEach((w, i) =>
    console.log(`  T${i}  ${bar(w)}  ${(w * 100).toFixed(1)}%`)
  );
  console.log(`  Expected tier: ${expectedTier(dist).toFixed(2)}`);

  // Response the agent actually receives
  const tier     = sampleTier(dist);
  const lastChal = generateChallenge('/api/intelligence', SECRET, RECIPIENT);
  const response = transformResponse(RAW_INTELLIGENCE, tier, lastChal.entropySeed);

  console.log('\n  -- Response Received (same query) ------------------------------');
  console.log(JSON.stringify(response, null, 2));
}

// ---- Agent 1: Scripted --------------------------------------------------------
// Always pays minimum+epsilon. Responds in ~200ms. Zero adaptation.
const naivePay: PayStrategy = (min) =>
  parseFloat((min + 0.0001).toFixed(6));

const naiveLat: LatStrategy = () =>
  200 + Math.round(Math.random() * 40);

// ---- Agent 2: Strategic -------------------------------------------------------
// Pays near midpoint with natural variance. Thoughtful latency. Improves over time.
const strategicPay: PayStrategy = (min, max, round) => {
  const mid   = (min + max) / 2;
  const drift = 0.0015 * Math.exp(-round / 6);   // converges toward exact midpoint
  const noise = (Math.random() - 0.5) * 0.0005;
  return parseFloat(
    Math.max(min + 0.0001, Math.min(max - 0.0001, mid + drift + noise)).toFixed(6)
  );
};

const strategicLat: LatStrategy = (round) =>
  Math.round(1800 + (Math.random() - 0.5) * 1400 + 300 / round);

// ---- Run ----------------------------------------------------------------------
(async () => {
  console.log('ECHOLOCK-402™  —  Behavioral Economic Access Control');
  console.log('Same endpoint. Same query. Economics is the only differentiator.\n');

  await runAgent('Naive Agent    [scripted]',    naivePay,     naiveLat,     8);
  await runAgent('Strategic Agent [adaptive]',   strategicPay, strategicLat, 8);

  console.log('\n' + '='.repeat(66));
  console.log('  RESULT: Behavior under cost determines depth of truth received.');
  console.log('  No tiers disclosed. No bans. No keys. No accounts. No trust.');
  console.log('='.repeat(66) + '\n');
})();
