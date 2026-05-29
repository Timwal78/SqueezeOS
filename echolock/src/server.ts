import http from 'http';
import { generateChallenge, encodeChallengeHeader, decodeChallengeHeader } from './challenge';
import { verifySettlement } from './settlement';
import { createWindow, pushSettlement, buildEFV } from './fingerprint';
import { classify, sampleTier } from './classifier';
import { transformResponse } from './entropy';
import type { BehaviorWindow, PaymentProof } from './types';

const SECRET    = process.env.ECHOLOCK_SECRET    ?? 'dev-secret-change-in-production';
const RECIPIENT = process.env.ECHOLOCK_RECIPIENT ?? 'rHb9CJAWyB4rj91VRWn96DkukG4bwdtyTh';
const PORT      = parseInt(process.env.PORT      ?? '3402', 10);

const SESSION_TTL_MS = 30 * 60_000;
const behaviorStore  = new Map<string, BehaviorWindow>();

// Prune inactive sessions to bound memory
setInterval(() => {
  const cutoff = Date.now() - SESSION_TTL_MS;
  for (const [tok, win] of behaviorStore) {
    if (win.lastUpdated < cutoff) behaviorStore.delete(tok);
  }
}, 60_000).unref();

// Raw intelligence data. Depth of delivery is determined entirely by payment behavior.
const INTELLIGENCE: Record<string, unknown> = {
  _meta: { engine: 'SqueezeOS', version: '3.0.0', timestamp: 0 },
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
    reasoning:  'Cross-engine consensus on momentum continuation above gamma flip level with sustained dark pool accumulation pattern consistent with institutional positioning ahead of macro catalyst.',
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

function readBody(req: http.IncomingMessage): Promise<unknown> {
  return new Promise((resolve, reject) => {
    let raw = '';
    req.on('data', chunk => { raw += chunk; });
    req.on('end', () => {
      try { resolve(raw ? JSON.parse(raw) : {}); }
      catch { reject(new Error('Invalid JSON')); }
    });
    req.on('error', reject);
  });
}

function reply(
  res: http.ServerResponse,
  status: number,
  body: unknown,
  extra: Record<string, string> = {}
): void {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    'Content-Type':   'application/json',
    'Content-Length': Buffer.byteLength(payload),
    'X-Service':      'echolock-402',
    ...extra,
  });
  res.end(payload);
}

const server = http.createServer(async (req, res) => {
  const url = req.url ?? '/';

  if (url === '/health' && req.method === 'GET') {
    return reply(res, 200, { status: 'ok', service: 'echolock-402' });
  }

  if (url.startsWith('/api/intelligence') && req.method === 'GET') {
    const proofHeader     = req.headers['x-payment-proof'] as string | undefined;
    const challengeHeader = req.headers['x-402-challenge']  as string | undefined;

    // Step 1: no payment → issue 402 challenge
    if (!proofHeader || !challengeHeader) {
      const challenge = generateChallenge(url, SECRET, RECIPIENT);
      return reply(
        res, 402,
        {
          error: 'Payment Required',
          challenge,
          instructions: {
            step1: `Pay ${challenge.minAmount}–${challenge.maxAmount} RLUSD to ${RECIPIENT} on XRPL (exact boundary values are invalid)`,
            step2: 'Re-send with headers X-402-Challenge (the challenge JSON base64url) and X-Payment-Proof (URL-encoded proof JSON)',
            proof_format: {
              challengeId:  '<id from challenge>',
              txHash:       '<xrpl-tx-hash>',
              amount:       0.010,
              sessionToken: '<any opaque string you choose>',
              submittedAt:  '<unix-ms>',
            },
          },
        },
        { 'X-402-Challenge': encodeChallengeHeader(challenge) }
      );
    }

    // Step 2: parse and validate proof
    let proof: PaymentProof;
    let challenge;

    try {
      proof = JSON.parse(decodeURIComponent(proofHeader)) as PaymentProof;
    } catch {
      return reply(res, 400, { error: 'Malformed X-Payment-Proof — expected URL-encoded JSON' });
    }

    try {
      challenge = decodeChallengeHeader(challengeHeader);
    } catch {
      return reply(res, 400, { error: 'Malformed X-402-Challenge header' });
    }

    const settlement = verifySettlement(challenge, proof, SECRET);
    if (!settlement.ok) {
      return reply(res, 402, { error: 'Settlement rejected', reason: settlement.error });
    }

    // Step 3: update behavioral window, keyed by agent-chosen session token (not wallet)
    const sessionToken  = proof.sessionToken || 'anonymous';
    const prior         = behaviorStore.get(sessionToken) ?? createWindow();
    const updated       = pushSettlement(prior, settlement.record);
    behaviorStore.set(sessionToken, updated);

    // Step 4: classify behavior, transform response depth accordingly
    const efv      = buildEFV(updated);
    const tierDist = classify(efv);
    const tier     = sampleTier(tierDist);

    const live = { ...INTELLIGENCE, _meta: { engine: 'SqueezeOS', version: '3.0.0', timestamp: Date.now() } };
    const data = transformResponse(live, tier, challenge.entropySeed);

    return reply(res, 200, {
      data,
      _ack: { settled: true, observations: updated.settlements.length },
    });
  }

  return reply(res, 404, { error: 'Not found' });
});

server.listen(PORT, () => {
  console.log(`ECHOLOCK-402 on :${PORT}  recipient=${RECIPIENT}`);
});

export { server };
