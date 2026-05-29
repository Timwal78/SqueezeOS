class PNEError(Exception):
    """Base exception for all PNE client errors."""


class PaymentError(PNEError):
    """Raised when payment fails or wallet has insufficient funds."""


class BudgetExhausted(PNEError):
    """Raised when the agent's max_tip budget would be exceeded."""


class MaxRetriesExceeded(PNEError):
    """Raised when all retry attempts have been exhausted."""


class AuctionRankMissed(PNEError):
    """Raised when target rank was not achieved and budget prevents higher bids."""
    def __init__(self, achieved_rank: int, target_rank: int):
        super().__init__(f"Achieved rank {achieved_rank}, target was {target_rank}")
        self.achieved_rank = achieved_rank
        self.target_rank = target_rank


class L402Error(PNEError):
    """Raised when L402 authentication fails."""
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


class UpstreamError(PNEError):
    """Raised when the upstream service returns an error."""
    def __init__(self, status_code: int, body: str):
        super().__init__(f"Upstream error {status_code}: {body[:200]}")
        self.status_code = status_code
        self.body = body


class MerkleVerificationError(PNEError):
    """Raised when Merkle proof verification fails."""
