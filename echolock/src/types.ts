export type CognitionTier = 0 | 1 | 2 | 3 | 4;

export interface PaymentChallenge {
  id: string;
  createdAt: number;
  minAmount: number;
  maxAmount: number;
  currency: 'RLUSD';
  network: 'XRPL';
  recipient: string;
  expiresAt: number;
  entropySeed: string;
  hmac: string;
}

export interface PaymentProof {
  challengeId: string;
  txHash: string;
  amount: number;
  sessionToken: string;
  submittedAt: number;
}

export interface SettlementRecord {
  challengeId: string;
  txHash: string;
  amount: number;
  minAmount: number;
  maxAmount: number;
  latencyMs: number;
  feeRatio: number;
  timestamp: number;
}

export interface EFV {
  latencyScore: number;
  retryPatience: number;
  feeIntelligence: number;
  correctionTrend: number;
  consistency: number;
  entropyTolerance: number;
  sampleConfidence: number;
}

export interface TierDistribution {
  weights: [number, number, number, number, number];
}

export interface BehaviorWindow {
  settlements: SettlementRecord[];
  readonly maxSize: number;
  createdAt: number;
  lastUpdated: number;
}
