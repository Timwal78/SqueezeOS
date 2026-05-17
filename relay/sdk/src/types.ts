export type Network = "xrpl_mainnet" | "xrpl_testnet";
export type Token = "RLUSD" | "XRP";
export type JobStatus =
  | "pending"
  | "funded"
  | "active"
  | "disputed"
  | "completed"
  | "cancelled";
export type DisputeOutcome = "release_to_hirer" | "release_to_worker" | "partial";
export type EvaluatorStatus = "active" | "suspended" | "deregistered";
export type ReputationTier = "unverified" | "bronze" | "silver" | "gold" | "platinum";

export interface RelayConfig {
  network: Network;
  xrplNode?: string;
  relayApiUrl?: string;
  evaluatorPool?: string;
}

export interface Milestone {
  description: string;
  amountPercent: number;
  deadline: number;
  acceptanceCriteria: string;
}

export interface CreateJobParams {
  hirer: string;
  worker: string;
  amount: number;
  token: Token;
  milestones: Milestone[];
  evaluatorPool?: string;
  timeoutDays?: number;
}

export interface JobRecord {
  jobId: string;
  channelId: string;
  hirer: string;
  worker: string;
  amount: number;
  token: Token;
  status: JobStatus;
  milestones: Milestone[];
  evaluatorPool: string;
  timeoutDays: number;
  txHash: string;
  createdAt: number;
  completedAt?: number;
}

export interface PaymentChannelInfo {
  channelId: string;
  account: string;
  destination: string;
  amount: string;
  balance: string;
  settleDelay: number;
  publicKey: string;
  expiration?: number;
  destinationTag?: number;
}

export interface MultiSigConfig {
  threshold: number;
  signers: Array<{ account: string; weight: number }>;
}

export interface DisputeRequest {
  initiator: string;
  jobId: string;
  reason: string;
  evidenceHashes: string[];
  requestedOutcome: DisputeOutcome;
}

export interface DisputeVote {
  evaluator: string;
  vote: "hirer" | "worker" | "partial";
  signature: string;
  timestamp: number;
}

export interface DisputeStatus {
  disputeId: string;
  jobId: string;
  status: "pending" | "evaluating" | "resolved";
  selectedEvaluators: Array<{
    address: string;
    specialization: string;
    stake: number;
  }>;
  votes: DisputeVote[];
  outcome?: DisputeOutcome;
  resolutionTxHash?: string;
  createdAt: number;
  resolvedAt?: number;
}

export interface EvaluatorProfile {
  address: string;
  stakeAmount: number;
  stakeEscrowTx: string;
  specializations: string[];
  accuracy: number | null;
  totalVotes: number;
  correctVotes: number;
  slashCount: number;
  status: EvaluatorStatus;
  joinedAt: number;
}

export interface ReputationScore {
  address: string;
  score: number;
  tier: ReputationTier;
  jobsCompleted: number;
  totalVolume: number;
  disputeRate: number;
  evaluatorAccuracy?: number;
  specializations: string[];
  stakeAmount: number;
  stakeDurationDays: number;
  vouchedBy: string[];
  attestationsGiven: number;
  lastUpdated: number;
}

export interface AttestationRequest {
  attester: string;
  attestee: string;
  context: string;
  signature: string;
}

export interface XRPLEscrowParams {
  account: string;
  destination: string;
  amount: string;
  condition?: string;
  cancelAfter?: number;
  finishAfter?: number;
}

export interface RelayError extends Error {
  code: string;
  details?: unknown;
}
