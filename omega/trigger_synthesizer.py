from typing import Dict, Any, Optional

def synthesize_triggers(argus_triggers: Dict[str, Any], ghost_data: Dict[str, Any], action_class: str, deception_score: float, breakout_validity: float, dominant_direction: int) -> Dict[str, Any]:
    """Synthesizes confirmation, invalidation, and trap triggers into a coherent map."""
    
    confirm_above = argus_triggers.get("confirm_above")
    invalidate_below = argus_triggers.get("invalidate_below")
    
    # Preferred fallback to liquidity magnets if directional intent is clear
    if confirm_above is None and dominant_direction > 0:
        confirm_above = ghost_data.get("primary_magnet")
    if invalidate_below is None:
        invalidate_below = ghost_data.get("secondary_magnet")
        
    sweep_target = ghost_data.get("primary_magnet") if action_class == "watch_for_sweep" else None
    
    trap_trigger = None
    if deception_score >= 0.55 and confirm_above is not None:
        trap_trigger = f"breakout_above_{confirm_above}_without_breakout_validity"
        
    # Confirmation mode mapping
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
        "confirmation_mode": confirmation_mode
    }
