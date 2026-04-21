from typing import Dict, Any

def generate_narrative(argus_data: Dict[str, Any], reality_data: Dict[str, Any], action_class: str, dominant_scenario: str, horizon: str) -> str:
    """Generates a concise, analytical machine-intelligence briefing."""
    
    bias = argus_data["bias"].replace("_", " ")
    stability = argus_data["stability"]
    
    # Core scenario logic
    if dominant_scenario == "sweep_then_continuation":
        core = "Historical analogs favor expansion, while liquidity mapping suggests an initial sweep before durable resolution."
    elif dominant_scenario == "failed_breakout_trap":
        core = "The setup carries a high probability of apparent continuation failing into a trap sequence."
    elif dominant_scenario == "clean_continuation":
        core = "Subsystem alignment supports cleaner continuation than a typical distorted breakout."
    else:
        core = "The balance of evidence favors reversal after expansion quality degrades."
        
    # Posture logic
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
        f"{core} Deception is {reality_data['deception_score']:.2f}, with a projected horizon of {horizon}. "
        f"{posture}"
    )
