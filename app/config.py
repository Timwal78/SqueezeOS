import os
from dotenv import load_dotenv

load_dotenv()

# ——— INSTITUTIONAL WEIGHTS (Law 2: No Magic Numbers) ————————————————————————

# Omega Score Components (Primary weights for Fusion Engine)
OMEGA_WEIGHT_ARGUS = float(os.getenv("OMEGA_WEIGHT_ARGUS", 0.30))
OMEGA_WEIGHT_ECHO = float(os.getenv("OMEGA_WEIGHT_ECHO", 0.25))
OMEGA_WEIGHT_GHOST = float(os.getenv("OMEGA_WEIGHT_GHOST", 0.20))
OMEGA_WEIGHT_REALITY_ADJ = float(os.getenv("OMEGA_WEIGHT_REALITY_ADJ", 0.15))
OMEGA_WEIGHT_ALIGNMENT = float(os.getenv("OMEGA_WEIGHT_ALIGNMENT", 0.10))

# Alignment Weights (Section 3)
ALIGN_WEIGHT_ARGUS = float(os.getenv("ALIGN_WEIGHT_ARGUS", 0.35))
ALIGN_WEIGHT_ECHO = float(os.getenv("ALIGN_WEIGHT_ECHO", 0.25))
ALIGN_WEIGHT_GHOST = float(os.getenv("ALIGN_WEIGHT_GHOST", 0.20))
ALIGN_WEIGHT_REALITY = float(os.getenv("ALIGN_WEIGHT_REALITY", 0.20))

# Adjudication Factors
DECEPTION_PENALTY_FACTOR = float(os.getenv("DECEPTION_PENALTY_FACTOR", 0.22))
CONTRADICTION_PENALTY_FACTOR = float(os.getenv("CONTRADICTION_PENALTY_FACTOR", 0.25))
ALIGNMENT_BONUS_FACTOR = float(os.getenv("ALIGNMENT_BONUS_FACTOR", 0.25))
CONDITIONAL_BONUS_FACTOR = float(os.getenv("CONDITIONAL_BONUS_FACTOR", 0.15))

# --- Hardening Layer: Subsystem Coefficients ---
# ARGUS Coefficients (Section 1.1)
ARGUS_EXPANSION_WEIGHT = float(os.getenv("ARGUS_EXPANSION_WEIGHT", 0.45))
ARGUS_SQUEEZE_WEIGHT = float(os.getenv("ARGUS_SQUEEZE_WEIGHT", 0.35))
ARGUS_TRAP_WEIGHT = float(os.getenv("ARGUS_TRAP_WEIGHT", 0.20))
ARGUS_BASE_MODIFIER = float(os.getenv("ARGUS_BASE_MODIFIER", 0.55))
ARGUS_EXPANSION_MODIFIER = float(os.getenv("ARGUS_EXPANSION_MODIFIER", 0.45))

# ECHO Coefficients (Section 1.2)
ECHO_REVERSAL_PENALTY = float(os.getenv("ECHO_REVERSAL_PENALTY", 0.50))
ECHO_FAILURE_PENALTY = float(os.getenv("ECHO_FAILURE_PENALTY", 0.75))
ECHO_BASE_MODIFIER = float(os.getenv("ECHO_BASE_MODIFIER", 0.35))
ECHO_CONTINUATION_MODIFIER = float(os.getenv("ECHO_CONTINUATION_MODIFIER", 0.65))

# REALITY Coefficients (Section 1.4)
REALITY_TRAP_PENALTY = float(os.getenv("REALITY_TRAP_PENALTY", 0.50))

# --- Bias & Stability Mapping ---
BIAS_WEIGHTS = {
    "bullish": float(os.getenv("BIAS_WEIGHT_BULLISH", 1.00)),
    "unstable_bullish": float(os.getenv("BIAS_WEIGHT_UNSTABLE_BULLISH", 0.95)),
    "bearish": float(os.getenv("BIAS_WEIGHT_BEARISH", 1.00)),
    "unstable_bearish": float(os.getenv("BIAS_WEIGHT_UNSTABLE_BEARISH", 0.95)),
    "neutral": float(os.getenv("BIAS_WEIGHT_NEUTRAL", 0.55)),
    "fractured": float(os.getenv("BIAS_WEIGHT_FRACTURED", 0.45)),
}

STABILITY_WEIGHTS = {
    "stable": float(os.getenv("STABILITY_WEIGHT_STABLE", 1.00)),
    "fragile": float(os.getenv("STABILITY_WEIGHT_FRAGILE", 0.82)),
    "distorted": float(os.getenv("STABILITY_WEIGHT_DISTORTED", 0.70)),
    "breaking": float(os.getenv("STABILITY_WEIGHT_BREAKING", 0.58)),
}

# --- Risk State Thresholds ---
RISK_DECEPTION_THRESHOLD = float(os.getenv("RISK_DECEPTION_THRESHOLD", 0.60))
RISK_QUALITY_ALIGN_THRESHOLD = float(os.getenv("RISK_QUALITY_ALIGN_THRESHOLD", 0.45))

# --- Conviction Index (CI) weights ---
CI_OMEGA_WEIGHT = float(os.getenv("CI_OMEGA_WEIGHT", 0.45))
CI_ALIGNMENT_WEIGHT = float(os.getenv("CI_ALIGNMENT_WEIGHT", 0.25))
CI_DECEPTION_WEIGHT = float(os.getenv("CI_DECEPTION_WEIGHT", 0.15))
CI_CONFIDENCE_WEIGHT = float(os.getenv("CI_CONFIDENCE_WEIGHT", 0.15))

# --- Conviction Thresholds ---
CI_MODERATE_THRESH = float(os.getenv("CI_MODERATE_THRESH", 0.40))
CI_HIGH_THRESH = float(os.getenv("CI_HIGH_THRESH", 0.62))
CI_EXTREME_THRESH = float(os.getenv("CI_EXTREME_THRESH", 0.82))

# ——— APP CONFIG ——————————————————————————————————————————————————————————————
APP_NAME = "Argus Omega"
DEBUG = os.getenv("DEBUG", "False") == "True"
PORT = int(os.getenv("PORT", 8080))
HOST = os.getenv("HOST", "0.0.0.0")
