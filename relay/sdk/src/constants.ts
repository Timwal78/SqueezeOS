export const XRPL_NODES = {
  xrpl_mainnet: "wss://xrplcluster.com",
  xrpl_testnet: "wss://s.altnet.rippletest.net:51233",
} as const;

export const XRPL_RPC_NODES = {
  xrpl_mainnet: "https://xrplcluster.com",
  xrpl_testnet: "https://s.altnet.rippletest.net:51234",
} as const;

// RLUSD issuer addresses
export const RLUSD_ISSUERS = {
  // Mainnet: Ripple's official RLUSD issuer (GENIUS Act compliant)
  xrpl_mainnet: "rHb9CJAWyB4rj91VRWn96DkukG4bwdtyTh",
  // Testnet: Ripple testnet RLUSD issuer
  xrpl_testnet: "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De",
} as const;

// Relay fee address (receives optional 0.5% via pre-signed channel split)
export const RELAY_FEE_ADDRESS = {
  xrpl_mainnet: "",
  xrpl_testnet: "",
} as const;

// Relay fee percentage (transparent, opt-in)
export const RELAY_FEE_BPS = 50; // 0.50%

// Default escrow / channel settings
export const DEFAULT_TIMEOUT_DAYS = 7;
export const DEFAULT_SETTLE_DELAY_SECONDS = DEFAULT_TIMEOUT_DAYS * 24 * 60 * 60;

// Evaluator network constants
export const MIN_EVALUATOR_STAKE_RLUSD = 500;
export const EVALUATOR_FEE_BPS = 20; // 0.20% of job value
export const SLASH_PERCENTAGE = 10; // 10% of stake
export const CORRECT_VOTE_BONUS_PERCENTAGE = 5; // 5% of slashed amount

// Multi-sig defaults (3-of-5 for dispute resolution)
export const DEFAULT_DISPUTE_THRESHOLD = 3;
export const DEFAULT_EVALUATOR_COUNT = 5;

// Reputation tier thresholds
export const REPUTATION_TIERS = {
  unverified: 0,
  bronze: 100,
  silver: 500,
  gold: 2000,
  platinum: 5000,
} as const;

// x402 HTTP status code
export const HTTP_PAYMENT_REQUIRED = 402;

// XRPL drops per XRP
export const DROPS_PER_XRP = 1_000_000n;

// Minimum XRPL account reserve (10 XRP)
export const ACCOUNT_RESERVE_XRP = 10;

// XRPL currency code for RLUSD (hex-encoded "USD" padded to 20 bytes is just "USD")
export const RLUSD_CURRENCY = "USD";
