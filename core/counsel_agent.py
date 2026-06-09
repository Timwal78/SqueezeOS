def generate_ai_counsel(result: dict) -> str:
    """
    Translates raw SqueezeOS engine telemetry into a human-readable Trading Desk brief.
    Safe against missing or partial sml_matrix data.
    """
    symbol   = result.get("symbol", "UNKNOWN")
    matrix        = result.get("sml_matrix") or {}
    decision      = matrix.get("decision", "WAIT")
    stacks        = matrix.get("highest_stacked_set", 0)
    matrix_tier   = matrix.get("tier", "NONE")
    god_stacked   = matrix.get("god_stacked", 0)
    execute_gate  = matrix.get("execute_gate", False)
    harmonic_score= matrix.get("harmonic_score", 0)
    signal   = result.get("signal", "NEUTRAL")
    score    = result.get("composite_score", 0)

    # Volume / Engine 3
    e3       = (result.get("engines") or {}).get("e3") or {}
    e3_state = e3.get("signal", "NEUTRAL")
    if e3_state == "DARK_POOL_CEILING_BREACH":
        vol_note = "Engine 3 confirms aggressive Dark Pool accumulation breaking historical resistance ceilings."
    elif e3_state == "DISTRIBUTION":
        vol_note = "Engine 3 detects heavy institutional distribution. Selling pressure is dominant."
    else:
        vol_note = "Engine 3 volume profile is neutral — no anomalous dark pool activity detected."

    # Settlement Clock / Engine 2
    e2          = (result.get("engines") or {}).get("e2") or {}
    in_kill_zone = e2.get("in_kill_zone", False)
    if in_kill_zone:
        clock_note = "CRITICAL: Engine 2 Settlement Clock is in the active Kill Zone — maximum liquidity squeeze potential."
    else:
        clock_note = "Engine 2 is outside the settlement kill zone — standard monitoring mode."

    # Sniper payload
    sniper     = result.get("options_sniper") or {}
    trade_type = sniper.get("type", "CALL")
    strike     = sniper.get("strike")
    exp        = sniper.get("expiration")
    premium    = sniper.get("premium")
    has_error  = bool(sniper.get("error"))

    strike_str  = f"${strike}"  if strike  is not None else "pending"
    exp_str     = str(exp)      if exp     is not None else "pending"
    premium_str = f"${premium}" if premium is not None else "pending"

    # Levels
    levels = matrix.get("levels") or {}
    tp1    = levels.get("tp1")
    inval  = levels.get("invalidation")
    tp1_str   = f"${tp1}"   if tp1   is not None else "—"
    inval_str = f"${inval}" if inval is not None else "—"

    # Matrix availability note
    matrix_note = ""
    if not matrix.get("matrix"):
        err = matrix.get("error", "")
        if "insufficient_bars" in err:
            bars_count = err.split(":")[-1]
            matrix_note = f"\n\nNOTE: SML matrix requires 20+ bars. Currently {bars_count} bars available — matrix will populate on next data cycle."
        elif err:
            matrix_note = f"\n\nNOTE: SML matrix computation encountered an issue ({err}). Engines 1–7 are operating normally."

    # Action directive — GOD_MODE tier is the institutional execution threshold
    if execute_gate and matrix_tier == "GOD_MODE":
        intro = (f"SqueezeOS SML Harmonic Matrix has confirmed GOD_MODE on {symbol} — "
                 f"{god_stacked}/6 SET9 INSTITUTIONAL configurations stacked "
                 f"(Harmonic Score: {harmonic_score} · Composite: {score}).")
        sniper_warn = " [OPTIONS DATA UNAVAILABLE — verify with broker]" if has_error else ""
        action = (
            f"EXECUTE NOW: {strike_str} {trade_type} expiring {exp_str} "
            f"for ~{premium_str} premium.{sniper_warn}"
        )
    elif matrix_tier == "GOD_MODE" and god_stacked > 0:
        intro = (f"SqueezeOS SML Harmonic Matrix: GOD_MODE tier active on {symbol} — "
                 f"{god_stacked}/6 SET9 configurations stacked (need 3+ to execute). "
                 f"Composite: {score}.")
        action = f"BUILDING: {god_stacked} SET9 stack(s) confirmed. Execution gate opens at 3+. Monitor {strike_str} {trade_type} exp {exp_str}."
    elif signal in ("BEASTMODE", "GOD_MODE", "APEX_SINGULARITY"):
        intro = f"SqueezeOS has achieved {signal} on {symbol} (Composite: {score}) — maximum convergence state."
        action = f"HIGH ALERT: All engines locked. Monitor {strike_str} {trade_type} expiring {exp_str} for entry."
    elif matrix_tier == "PRIME":
        intro = f"SqueezeOS SML Harmonic Matrix: PRIME tier alignment on {symbol} (Composite: {score}). SET6 family confirmed — awaiting SET9 institutional confirmation."
        action = f"STANDBY: PRIME tier active. Position for GOD_MODE entry at {strike_str} {trade_type} exp {exp_str}."
    elif signal in ("HIGH_CONVERGENCE", "FRACTAL_LOCK"):
        intro = f"SqueezeOS detects {signal} on {symbol} (Composite: {score}) — approaching execution threshold."
        action = f"STANDBY: {stacks} stacks confirmed. One more convergence event triggers full execution protocol."
    else:
        intro = f"SqueezeOS SML Harmonic Matrix: {matrix_tier} tier on {symbol} (Composite: {score}). Does not meet GOD_MODE execution threshold."
        action = f"DO NOT EXECUTE. Maintain watch. Theoretical setup: {strike_str} {trade_type} exp {exp_str}."

    return (
        f"{intro}\n\n"
        f"{vol_note} {clock_note}\n\n"
        f"{action}\n\n"
        f"Risk: Target {tp1_str} · Hard invalidation {inval_str}."
        f"{matrix_note}"
    )
