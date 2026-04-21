"""
Fusion Engine — Central adjudication engine for Argus Omega.

This module implements the complete OMEGA fusion pipeline as specified in
MATH/OMEGA_FORMULAS.md and REFERENCE_IMPL/omega_reference.py.

Every formula, coefficient, and branching condition must maintain exact
mathematical parity with the reference implementation. No simplifications.
No rounding shortcuts. No retail heuristics.
"""
from typing import Dict, Any, List, Optional
from .normalization import n1, n100
from .alignment import infer_directions, calculate_alignment
from .conviction import calculate_conviction
from .scenario_ranker import rank_scenarios
from .action_mapper import determine_action_class
from .trigger_synthesizer import synthesize_triggers
from .narrative_fusion import generate_narrative
from app.config import (
    BIAS_WEIGHTS, STABILITY_WEIGHTS,
    OMEGA_WEIGHT_ARGUS, OMEGA_WEIGHT_ECHO, OMEGA_WEIGHT_GHOST,
    OMEGA_WEIGHT_REALITY_ADJ, OMEGA_WEIGHT_ALIGNMENT,
    DECEPTION_PENALTY_FACTOR, CONTRADICTION_PENALTY_FACTOR,
    ALIGNMENT_BONUS_FACTOR, CONDITIONAL_BONUS_FACTOR,
    ARGUS_EXPANSION_WEIGHT, ARGUS_SQUEEZE_WEIGHT, ARGUS_TRAP_WEIGHT,
    ARGUS_BASE_MODIFIER, ARGUS_EXPANSION_MODIFIER,
    ECHO_REVERSAL_PENALTY, ECHO_FAILURE_PENALTY,
    ECHO_BASE_MODIFIER, ECHO_CONTINUATION_MODIFIER,
    REALITY_TRAP_PENALTY, RISK_DECEPTION_THRESHOLD,
    RISK_QUALITY_ALIGN_THRESHOLD
)


class FusionEngine:
    """The central adjudication engine for Argus Omega.
    
    Implements the complete institutional fusion pipeline:
    1. Derived strengths (Section 1)
    2. Direction inference (Section 2)
    3. Alignment computation (Section 3)
    4. Penalties and bonuses (Section 4)
    5. Omega score (Section 5)
    6. Conviction bucketing (Section 6)
    7. Scenario ranking (Section 7)
    8. Risk state (Section 8)
    9. Action class (Section 9)
    10. Trigger synthesis (Section 10)
    11. Time horizon (Section 11)
    12. Narrative fusion
    """

    # --- Section 1: Derived Strengths ---

    def argus_strength(self, argus: Dict[str, Any]) -> float:
        """Section 1.1 — ARGUS strength with bias, stability, and expansion modifiers."""
        ev = argus["event_risk"]
        expansion_signal = n1(
            ARGUS_EXPANSION_WEIGHT * ev["expansion"] + 
            ARGUS_SQUEEZE_WEIGHT * ev["squeeze"] + 
            ARGUS_TRAP_WEIGHT * (1 - ev["trap"])
        )
        out = (
            argus["state_score"]
            * argus["confidence"]
            * BIAS_WEIGHTS.get(argus["bias"], 0.45)
            * STABILITY_WEIGHTS.get(argus["stability"], 0.58)
            * (ARGUS_BASE_MODIFIER + ARGUS_EXPANSION_MODIFIER * expansion_signal)
        )
        return n100(out)

    def echo_strength(self, echo: Dict[str, Any]) -> float:
        """Section 1.2 — ECHO strength with similarity, confidence, and continuation edge."""
        continuation_edge = n1(
            echo["continuation_probability"]
            - ECHO_REVERSAL_PENALTY * echo["reversal_probability"]
            - ECHO_FAILURE_PENALTY * echo["failure_probability"]
        )
        out = (
            100
            * echo["similarity_score"]
            * echo["confidence"]
            * (ECHO_BASE_MODIFIER + ECHO_CONTINUATION_MODIFIER * continuation_edge)
        )
        return n100(out)

    def liquidity_strength(self, ghost: Dict[str, Any]) -> float:
        """Section 1.3 — LIQUIDITY strength with directional clarity."""
        directional_clarity = abs(
            ghost["sweep_probability_up"] - ghost["sweep_probability_down"]
        )
        out = (
            100
            * ghost["destination_score"]
            * ghost["confidence"]
            * directional_clarity
        )
        return n100(out)

    def truth_adjusted_strength(self, reality: Dict[str, Any]) -> float:
        """Section 1.4 — Truth-adjusted strength with deception suppression."""
        out = (
            100
            * reality["confidence"]
            * reality["truth_score"]
            * reality["breakout_validity"]
            * (1 - reality["deception_score"])
            * (1 - REALITY_TRAP_PENALTY * reality["trap_probability"])
        )
        return n100(out)

    # --- Section 11: Time Horizon ---

    def time_horizon(self, bars: int) -> str:
        """Section 11 — Map resolution_window_bars to human-readable horizon."""
        if bars <= 8:
            return "1-2 sessions"
        if bars <= 20:
            return "2-5 sessions"
        if bars <= 40:
            return "1-2 weeks"
        return "multi-week"

    # --- Main Fusion Pipeline ---

    def fuse(
        self,
        ticker: str,
        timeframes: List[str],
        argus: Dict[str, Any],
        echo: Dict[str, Any],
        ghost: Dict[str, Any],
        reality: Dict[str, Any],
        sml_squeeze: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute the full OMEGA fusion pipeline.
        
        This method maintains exact mathematical parity with
        REFERENCE_IMPL/omega_reference.py::FusionEngine.fuse()
        
        Args:
            ticker: Symbol being analyzed
            timeframes: List of timeframe strings
            argus: ARGUS subsystem payload
            echo: ECHO FORGE subsystem payload
            ghost: LIQUIDITY GHOST subsystem payload
            reality: FALSE REALITY subsystem payload
            
        Returns:
            Complete OMEGA scan response dictionary
        """
        # 1. Derived strengths
        a_str = self.argus_strength(argus)
        e_str = self.echo_strength(echo)
        l_str = self.liquidity_strength(ghost)
        t_str = self.truth_adjusted_strength(reality)

        # 2. Direction inference + 3. Alignment
        directions = infer_directions(argus["bias"], echo, ghost, reality)
        align = calculate_alignment(directions, reality["deception_score"])

        # 4. Penalties & Bonuses (Section 4)
        deception_penalty = (
            100 * reality["deception_score"]
            * (0.35 + 0.65 * reality["trap_probability"])
        )
        contradiction_penalty = (
            100 * (1 - align["conflict_gap"]) * CONTRADICTION_PENALTY_FACTOR
            if align["bull_weight"] >= 0.15 and align["bear_weight"] >= 0.15
            else 0.0
        )
        alignment_bonus = (
            ALIGNMENT_BONUS_FACTOR * align["strength"]
            if align["state"] in {"full_alignment", "directional_alignment"}
            else 0.0
        )
        conditional_bonus = (
            CONDITIONAL_BONUS_FACTOR * align["strength"]
            if align["state"] == "directional_alignment_with_execution_conflict"
            else 0.0
        )

        # 5. Omega Score (Section 5)
        omega_raw = (
            OMEGA_WEIGHT_ARGUS * a_str
            + OMEGA_WEIGHT_ECHO * e_str
            + OMEGA_WEIGHT_GHOST * l_str
            + OMEGA_WEIGHT_REALITY_ADJ * t_str
            + OMEGA_WEIGHT_ALIGNMENT * align["strength"]
            + alignment_bonus
            + conditional_bonus
            - DECEPTION_PENALTY_FACTOR * deception_penalty
            - contradiction_penalty
        )
        
        # SML 147-Day Cycle Booster (Dynamic structural resonance)
        cycle_booster = 0.0
        if sml_squeeze and sml_squeeze.get("cycle_147_score"):
            cycle_score = sml_squeeze.get("cycle_147_score", 0.0)
            # Cycle booster adds up to 10 points for perfect cycle resonance
            cycle_booster = cycle_score * 10.0
            omega_raw += cycle_booster

        omega = n100(omega_raw)

        # 6. Conviction (Section 6)
        conviction = calculate_conviction(
            omega,
            align["strength"],
            reality["deception_score"],
            echo["similarity_score"],
            echo["confidence"],
            argus["confidence"],
        )

        # 7. Scenario Ranking (Section 7)
        dom_dir = 1 if align["bull_weight"] >= align["bear_weight"] else -1
        scenario_probs = rank_scenarios(
            argus["event_risk"], echo, ghost, reality, dom_dir
        )
        ranked = sorted(scenario_probs.items(), key=lambda x: x[1], reverse=True)
        dominant_scenario = ranked[0][0]
        alternate_scenario = ranked[1][0]

        # 8. Risk State (Section 8)
        if reality["deception_score"] >= RISK_DECEPTION_THRESHOLD:
            risk_state = "elevated_deception"
        elif align["state"] in {"mixed_conflict", "low_signal"}:
            risk_state = "structural_conflict"
        elif dominant_scenario == "failed_breakout_trap":
            risk_state = "trap_risk"
        elif conviction in {"high", "extreme"} and reality["deception_score"] < RISK_QUALITY_ALIGN_THRESHOLD:
            risk_state = "high_quality_alignment"
        else:
            risk_state = "balanced_risk"

        # 9. Action Class (Section 9)
        action = determine_action_class(
            omega, align["state"], dominant_scenario, conviction,
            reality["deception_score"]
        )

        # 11. Time Horizon
        horizon = self.time_horizon(echo["resolution_window_bars"])

        # 10. Trigger Synthesis (Section 10)
        # Reference uses: argus.get("trigger_map", {}) or {}
        # This handles both missing key AND explicit None
        argus_triggers = argus.get("trigger_map") or {}
        triggers = synthesize_triggers(
            argus_triggers, ghost, action,
            reality["deception_score"], reality["breakout_validity"], dom_dir
        )

        # 12. Narrative Fusion
        briefing = generate_narrative(
            argus, reality, action, dominant_scenario, horizon
        )

        return {
            "ticker": ticker,
            "timeframes": timeframes,
            "omega_score": round(omega, 2),
            "conviction": conviction,
            "alignment_state": align["state"],
            "dominant_scenario": dominant_scenario,
            "alternate_scenario": alternate_scenario,
            "risk_state": risk_state,
            "action_class": action,
            "time_horizon": horizon,
            "composite_briefing": briefing,
            "trigger_map": triggers,
            "scores": {
                "argus_strength": round(a_str, 2),
                "echo_strength": round(e_str, 2),
                "liquidity_strength": round(l_str, 2),
                "truth_adjusted_strength": round(t_str, 2),
                "alignment_strength": round(align["strength"], 2),
            },
            "scenario_probabilities": {
                k: round(v, 3) for k, v in scenario_probs.items()
            },
            "subsystems": {
                "argus": argus,
                "echo_forge": echo,
                "liquidity_ghost": ghost,
                "false_reality": reality,
                "sml_squeeze": sml_squeeze,
            },
            "boosters": {
                "sml_cycle_booster": round(cycle_booster, 2),
            }
        }
