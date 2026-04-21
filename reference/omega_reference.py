from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Optional, Any, Tuple
import math

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def n1(x: float) -> float:
    return clamp(x, 0.0, 1.0)

def n100(x: float) -> float:
    return clamp(x, 0.0, 100.0)

def softmax(scores: Dict[str, float]) -> Dict[str, float]:
    if not scores:
        return {}
    m = max(scores.values())
    exps = {k: math.exp(v - m) for k, v in scores.items()}
    s = sum(exps.values()) or 1.0
    return {k: exps[k] / s for k in exps}

BIAS_FACTOR = {
    "bullish": 1.00,
    "unstable_bullish": 0.95,
    "bearish": 1.00,
    "unstable_bearish": 0.95,
    "neutral": 0.55,
    "fractured": 0.45,
}
STABILITY_FACTOR = {
    "stable": 1.00,
    "fragile": 0.82,
    "distorted": 0.70,
    "breaking": 0.58,
}

@dataclass
class FusionEngine:
    def argus_strength(self, argus: Dict[str, Any]) -> float:
        ev = argus["event_risk"]
        expansion_signal = n1(0.45*ev["expansion"] + 0.35*ev["squeeze"] + 0.20*(1-ev["trap"]))
        out = (
            argus["state_score"]
            * argus["confidence"]
            * BIAS_FACTOR.get(argus["bias"], 0.45)
            * STABILITY_FACTOR.get(argus["stability"], 0.58)
            * (0.55 + 0.45*expansion_signal)
        )
        return n100(out)

    def echo_strength(self, echo: Dict[str, Any]) -> float:
        continuation_edge = n1(
            echo["continuation_probability"]
            - 0.5*echo["reversal_probability"]
            - 0.75*echo["failure_probability"]
        )
        out = 100 * echo["similarity_score"] * echo["confidence"] * (0.35 + 0.65*continuation_edge)
        return n100(out)

    def liquidity_strength(self, ghost: Dict[str, Any]) -> float:
        directional_clarity = abs(ghost["sweep_probability_up"] - ghost["sweep_probability_down"])
        out = 100 * ghost["destination_score"] * ghost["confidence"] * directional_clarity
        return n100(out)

    def truth_adjusted_strength(self, reality: Dict[str, Any]) -> float:
        out = 100 * reality["confidence"] * reality["truth_score"] * reality["breakout_validity"] * (1 - reality["deception_score"]) * (1 - 0.50*reality["trap_probability"])
        return n100(out)

    def infer_directions(self, argus: Dict[str, Any], echo: Dict[str, Any], ghost: Dict[str, Any], reality: Dict[str, Any]) -> Dict[str, int]:
        bias = argus["bias"]
        if "bullish" in bias:
            argus_dir = 1
        elif "bearish" in bias:
            argus_dir = -1
        else:
            argus_dir = 0

        if echo["continuation_probability"] >= echo["reversal_probability"] and echo["continuation_probability"] >= echo["failure_probability"]:
            echo_dir = 1
        elif echo["reversal_probability"] > echo["continuation_probability"] and echo["reversal_probability"] >= echo["failure_probability"]:
            echo_dir = -1
        else:
            echo_dir = 0

        diff = ghost["sweep_probability_up"] - ghost["sweep_probability_down"]
        if diff >= 0.10:
            ghost_dir = 1
        elif -diff >= 0.10:
            ghost_dir = -1
        else:
            ghost_dir = 0

        if reality["breakout_validity"] >= 0.60 and reality["deception_score"] <= 0.40:
            truth_dir = 1
        elif reality["deception_score"] >= 0.70 and reality["trap_probability"] >= 0.55:
            truth_dir = -1
        else:
            truth_dir = 0

        return {"argus": argus_dir, "echo": echo_dir, "ghost": ghost_dir, "truth": truth_dir}

    def alignment(self, directions: Dict[str, int], deception_score: float) -> Tuple[float, str, float, float]:
        weights = {"argus": 0.35, "echo": 0.25, "ghost": 0.20, "truth": 0.20}
        bull = sum(weights[k] for k, v in directions.items() if v == 1)
        bear = sum(weights[k] for k, v in directions.items() if v == -1)
        neutral = 1.0 - bull - bear
        raw = 100 * max(bull, bear)
        conflict_gap = abs(bull - bear)
        strength = n100(raw * (0.60 + 0.40*conflict_gap))

        if max(bull, bear) >= 0.75 and neutral <= 0.10:
            state = "full_alignment"
        elif max(bull, bear) >= 0.55 and deception_score >= 0.55:
            state = "directional_alignment_with_execution_conflict"
        elif max(bull, bear) >= 0.55:
            state = "directional_alignment"
        elif conflict_gap < 0.20:
            state = "mixed_conflict"
        else:
            state = "low_signal"
        return strength, state, bull, bear

    def penalties_and_bonuses(self, deception_score: float, trap_probability: float, alignment_strength: float, alignment_state: str, bull: float, bear: float) -> Dict[str, float]:
        deception_penalty = 100 * deception_score * (0.35 + 0.65*trap_probability)
        contradiction_penalty = 100 * (1 - abs(bull - bear)) * 0.25 if bull > 0 and bear > 0 else 0.0
        alignment_bonus = 0.25 * alignment_strength if alignment_state in {"full_alignment", "directional_alignment"} else 0.0
        conditional_bonus = 0.15 * alignment_strength if alignment_state == "directional_alignment_with_execution_conflict" else 0.0
        return {
            "deception_penalty": deception_penalty,
            "contradiction_penalty": contradiction_penalty,
            "alignment_bonus": alignment_bonus,
            "conditional_bonus": conditional_bonus,
        }

    def omega_score(self, argus_strength: float, echo_strength: float, liquidity_strength: float, truth_strength: float, alignment_strength: float, p: Dict[str, float]) -> float:
        raw = (
            0.30 * argus_strength
            + 0.25 * echo_strength
            + 0.20 * liquidity_strength
            + 0.15 * truth_strength
            + 0.10 * alignment_strength
            + p["alignment_bonus"]
            + p["conditional_bonus"]
            - 0.22 * p["deception_penalty"]
            - p["contradiction_penalty"]
        )
        return n100(raw)

    def conviction(self, omega_score: float, alignment_strength: float, deception_score: float, similarity_score: float, echo_confidence: float, state_confidence: float) -> str:
        ci = (
            0.45 * (omega_score / 100.0)
            + 0.25 * (alignment_strength / 100.0)
            + 0.15 * (1 - deception_score)
            + 0.15 * max(similarity_score * echo_confidence, state_confidence)
        )
        if ci < 0.40:
            return "low"
        if ci < 0.62:
            return "moderate"
        if ci < 0.82:
            return "high"
        return "extreme"

    def scenario_probabilities(self, argus: Dict[str, Any], echo: Dict[str, Any], ghost: Dict[str, Any], reality: Dict[str, Any], dominant_direction: int) -> Dict[str, float]:
        ev = argus["event_risk"]
        sweep_up = ghost["sweep_probability_up"]
        sweep_down = ghost["sweep_probability_down"]
        if dominant_direction < 0:
            sweep_up, sweep_down = sweep_down, sweep_up

        logits = {
            "clean_continuation": (
                0.35*ev["expansion"]
                + 0.25*echo["continuation_probability"]
                + 0.20*sweep_up
                + 0.20*reality["truth_score"]
                - 0.30*reality["deception_score"]
            ),
            "sweep_then_continuation": (
                0.25*ev["expansion"]
                + 0.20*echo["continuation_probability"]
                + 0.35*max(sweep_up, sweep_down)
                + 0.20*ghost["post_sweep_reversal_probability"]
                + 0.10*reality["deception_score"]
            ),
            "failed_breakout_trap": (
                0.20*ev["trap"]
                + 0.15*echo["failure_probability"]
                + 0.20*reality["deception_score"]
                + 0.25*(1-reality["breakout_validity"])
                + 0.20*reality["trap_probability"]
            ),
            "reversal_after_failed_expansion": (
                0.20*ev["reversal"]
                + 0.20*echo["reversal_probability"]
                + 0.20*ghost["post_sweep_reversal_probability"]
                + 0.15*reality["deception_score"]
                + 0.10*ev["trap"]
                + 0.15*echo["failure_probability"]
            ),
        }
        return softmax(logits)

    def risk_state(self, deception_score: float, alignment_state: str, dominant_scenario: str, conviction: str) -> str:
        if deception_score >= 0.60:
            return "elevated_deception"
        if alignment_state in {"mixed_conflict", "low_signal"}:
            return "structural_conflict"
        if dominant_scenario == "failed_breakout_trap":
            return "trap_risk"
        if conviction in {"high", "extreme"} and deception_score < 0.45:
            return "high_quality_alignment"
        return "balanced_risk"

    def action_class(self, omega_score: float, alignment_state: str, dominant_scenario: str, conviction: str, deception_score: float) -> str:
        if omega_score < 40:
            return "observe_only"
        if alignment_state == "low_signal":
            return "observe_only"
        if dominant_scenario == "failed_breakout_trap":
            return "do_not_chase"
        if alignment_state == "directional_alignment_with_execution_conflict":
            return "watch_for_sweep"
        if deception_score >= 0.70:
            return "do_not_chase"
        if dominant_scenario == "clean_continuation" and conviction in {"high", "extreme"}:
            return "post_confirmation_candidate"
        if dominant_scenario == "reversal_after_failed_expansion":
            return "reduce_risk"
        if conviction == "extreme" and deception_score < 0.35 and alignment_state == "full_alignment":
            return "high_conviction_setup"
        return "watch_trigger"

    def trigger_map(self, argus: Dict[str, Any], ghost: Dict[str, Any], action_class: str, deception_score: float, breakout_validity: float, dominant_direction: int) -> Dict[str, Any]:
        argus_tm = argus.get("trigger_map", {}) or {}
        confirm_above = argus_tm.get("confirm_above")
        invalidate_below = argus_tm.get("invalidate_below")

        if confirm_above is None and dominant_direction > 0:
            confirm_above = ghost.get("primary_magnet")
        if invalidate_below is None:
            invalidate_below = ghost.get("secondary_magnet")

        sweep_target = ghost.get("primary_magnet") if action_class == "watch_for_sweep" else None
        trap_trigger = None
        if deception_score >= 0.55 and confirm_above is not None:
            trap_trigger = f"breakout_above_{confirm_above}_without_breakout_validity"

        if action_class == "watch_for_sweep":
            confirmation_mode = "accept_breakout_only_after_sweep_and_hold"
        elif action_class == "post_confirmation_candidate":
            confirmation_mode = "accept_breakout_on_confirmed_hold"
        elif action_class == "do_not_chase":
            confirmation_mode = "avoid_first_impulse_participation"
        else:
            confirmation_mode = "wait_for_alignment"

        return {
            "confirm_above": confirm_above,
            "invalidate_below": invalidate_below,
            "sweep_target": sweep_target,
            "trap_trigger": trap_trigger,
            "confirmation_mode": confirmation_mode,
        }

    def time_horizon(self, resolution_window_bars: int) -> str:
        if resolution_window_bars <= 8:
            return "1-2 sessions"
        if resolution_window_bars <= 20:
            return "2-5 sessions"
        if resolution_window_bars <= 40:
            return "1-2 weeks"
        return "multi-week"

    def narrative(self, argus: Dict[str, Any], echo: Dict[str, Any], ghost: Dict[str, Any], reality: Dict[str, Any], action_class: str, dominant_scenario: str, horizon: str) -> str:
        bias = argus["bias"].replace("_", " ")
        stability = argus["stability"]
        if dominant_scenario == "sweep_then_continuation":
            core = "Historical analogs favor expansion, while liquidity mapping suggests an initial sweep before durable resolution."
        elif dominant_scenario == "failed_breakout_trap":
            core = "The setup carries a high probability of apparent continuation failing into a trap sequence."
        elif dominant_scenario == "clean_continuation":
            core = "Subsystem alignment supports cleaner continuation than a typical distorted breakout."
        else:
            core = "The balance of evidence favors reversal after expansion quality degrades."

        if action_class == "watch_for_sweep":
            posture = "Breakout chase quality is poor until sweep-and-hold confirmation appears."
        elif action_class == "do_not_chase":
            posture = "Immediate impulse participation is low quality and should be avoided."
        elif action_class == "post_confirmation_candidate":
            posture = "The best posture is confirmation-based participation rather than anticipatory entry."
        else:
            posture = "Patience is favored until subsystem alignment improves."

        return (
            f"{bias.capitalize()} pressure is present, but the structure remains {stability}. "
            f"{core} Deception is {reality['deception_score']:.2f}, with a projected horizon of {horizon}. "
            f"{posture}"
        )

    def fuse(self, ticker: str, timeframes: Any, argus: Dict[str, Any], echo: Dict[str, Any], ghost: Dict[str, Any], reality: Dict[str, Any]) -> Dict[str, Any]:
        a = self.argus_strength(argus)
        e = self.echo_strength(echo)
        l = self.liquidity_strength(ghost)
        t = self.truth_adjusted_strength(reality)

        directions = self.infer_directions(argus, echo, ghost, reality)
        alignment_strength, alignment_state, bull, bear = self.alignment(directions, reality["deception_score"])
        p = self.penalties_and_bonuses(reality["deception_score"], reality["trap_probability"], alignment_strength, alignment_state, bull, bear)
        omega = self.omega_score(a, e, l, t, alignment_strength, p)
        conviction = self.conviction(omega, alignment_strength, reality["deception_score"], echo["similarity_score"], echo["confidence"], argus["confidence"])

        dominant_direction = 1 if bull >= bear else -1 if bear > bull else 0
        scenario_probs = self.scenario_probabilities(argus, echo, ghost, reality, dominant_direction)
        ranked = sorted(scenario_probs.items(), key=lambda kv: kv[1], reverse=True)
        dominant_scenario = ranked[0][0]
        alternate_scenario = ranked[1][0]

        risk_state = self.risk_state(reality["deception_score"], alignment_state, dominant_scenario, conviction)
        action = self.action_class(omega, alignment_state, dominant_scenario, conviction, reality["deception_score"])
        triggers = self.trigger_map(argus, ghost, action, reality["deception_score"], reality["breakout_validity"], dominant_direction)
        horizon = self.time_horizon(echo["resolution_window_bars"])
        briefing = self.narrative(argus, echo, ghost, reality, action, dominant_scenario, horizon)

        return {
            "ticker": ticker,
            "timeframes": timeframes,
            "omega_score": round(omega, 2),
            "conviction": conviction,
            "alignment_state": alignment_state,
            "dominant_scenario": dominant_scenario,
            "alternate_scenario": alternate_scenario,
            "risk_state": risk_state,
            "action_class": action,
            "time_horizon": horizon,
            "composite_briefing": briefing,
            "trigger_map": triggers,
            "scores": {
                "argus_strength": round(a, 2),
                "echo_strength": round(e, 2),
                "liquidity_strength": round(l, 2),
                "truth_adjusted_strength": round(t, 2),
                "alignment_strength": round(alignment_strength, 2),
            },
            "scenario_probabilities": {k: round(v, 3) for k, v in scenario_probs.items()},
            "subsystems": {
                "argus": argus,
                "echo_forge": echo,
                "liquidity_ghost": ghost,
                "false_reality": reality,
            }
        }
