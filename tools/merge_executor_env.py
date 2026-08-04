"""
Merges desk defaults into tools/executor.env, preserving any secrets
already present (Robinhood credentials, webhook URLs, gate secrets).

This used to be a single `python -c "..."` line embedded directly in
START_EXECUTOR.bat using backslash line-continuation. That works in
Unix shells but NOT in native Windows cmd.exe (cmd uses caret ^ for
line continuation, not backslash) -- cmd was silently truncating the
script after the first line, then trying to execute the rest of the
Python source as literal shell commands (hence errors like "'defaults'
is not recognized as an internal or external command"). Moving this
into a real .py file sidesteps cmd's quoting/continuation rules
entirely.
"""
from pathlib import Path

ENV_FILE = Path("tools/executor.env")
EXAMPLE_FILE = Path("tools/executor.env.example")

DEFAULTS = {
    "POLL_INTERVAL_S": "45",
    "SQUEEZEOS_API_URL": "https://squeezeos-api.onrender.com",
    "MIN_GOD_STACKED": "6",
    "ORACLE_MIN_CONFIDENCE": "60.0",
    "COOLDOWN_S": "900",
    "MAX_ORDER_USD": "150.0",
    "MAX_EQUITY_SHARES": "25",
    # 0 = uncapped -- matches the operator directive already baked into
    # robinhood_executor_sml.py's own defaults ("operator directive
    # 2026-07-29, semi-day-trading"). These used to default to 25/1500.0
    # here, silently re-capping the executor every launch even though the
    # Python script itself was already built to run uncapped. Fixed 2026-08-04.
    "MAX_ORDERS_PER_DAY": "0",
    "MAX_DAILY_NOTIONAL_USD": "0",
    "MAX_DAILY_LOSS_USD": "100.0",
    "MAX_PER_SCAN": "3",
    "PDT_BALANCE_LIMIT": "2100.0",
    "PDT_MAX_TRADES": "3",
    "STOP_LOSS_PCT": "5.0",
    "TAKE_PROFIT_PCT": "15.0",
    "POSITION_MONITOR_ENABLED": "true",
    "MAX_SPREAD_PCT": "2.0",
    "FILL_ALERT_MINUTES": "10.0",
    "ROBINHOOD_PAPER_MODE": "false",
    "KILL_SWITCH": "false",
    "EXEC_BROKER": "robinhood",
    "ROBINHOOD_OPTION_QTY": "1",
    "OPTIONS_DELTA_MIN": "0.30",
    "OPTIONS_DELTA_MAX": "0.40",
    "OPTIONS_DELTA_TARGET": "0.35",
    "OPT_HARD_STOP": "-0.20",
    "OPT_SCALE_1": "0.50",
    "OPT_SCALE_2": "1.50",
    "OPT_BANK_300": "3.00",
    "OPT_BANK_500": "5.00",
    "OPT_GIVEBACK_ARM": "0.50",
    "OPT_GIVEBACK_FRAC": "0.35",
    "OPT_TRAIL": "0.22",
    "OPT_TRAIL_LATE": "0.18",
    "OPT_DELTA_EXIT": "0.60",
    "GAMMA_RAMP_POLL_ENABLED": "false",
    "GAMMA_RAMP_OUTBOX_DIR": "tools/gamma_ramp/rh_outbox",
}

# Keys that, once set by the operator, are never silently overwritten
# by the merge below.
PROTECT = {k for k in DEFAULTS if any(x in k for x in ("USER", "PASS", "SECRET", "TOKEN", "WEBHOOK", "KEY"))}
PROTECT |= {"ROBINHOOD_USERNAME", "ROBINHOOD_PASSWORD", "MACRO_GATE_SECRET",
            "DISCORD_WEBHOOK_BEAST", "DISCORD_WEBHOOK_ALL", "LOG_DIR"}
PROTECT |= {"ROBINHOOD_PAPER_MODE", "KILL_SWITCH", "GAMMA_RAMP_POLL_ENABLED"}


def main() -> None:
    defaults = dict(DEFAULTS)

    if EXAMPLE_FILE.exists():
        for line in EXAMPLE_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            k, v = k.strip(), v.strip()
            if k and k not in PROTECT:
                defaults[k] = v

    kv: dict[str, str] = {}
    order: list[str] = []
    comments: list[str] = []
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
            s = line.strip()
            if not s:
                continue
            if s.startswith("#") or "=" not in s:
                comments.append(line)
                continue
            k, v = s.split("=", 1)
            k = k.strip()
            if not k:
                continue
            kv[k] = v
            order.append(k)

    for k, v in defaults.items():
        if k in PROTECT and k in kv and kv[k].strip():
            continue  # operator already set this protected value -- keep it
        if k not in kv:
            order.append(k)
        kv[k] = v

    # Hard locks -- these are enforced regardless of what was in the file,
    # mirroring the same "LOCKED" convention already used elsewhere.
    kv["POLL_INTERVAL_S"] = "45"
    kv["MIN_GOD_STACKED"] = "6"
    kv["MAX_ORDERS_PER_DAY"] = "0"       # uncapped -- corrects any stale 25 left from before 2026-08-04
    kv["MAX_DAILY_NOTIONAL_USD"] = "0"   # uncapped -- corrects any stale 1500.0 left from before 2026-08-04
    kv["GAMMA_RAMP_POLL_ENABLED"] = "true"
    kv["POSITION_MONITOR_ENABLED"] = "true"
    kv["EXEC_BROKER"] = "robinhood"
    kv["KILL_SWITCH"] = kv.get("KILL_SWITCH") or "false"
    kv["ROBINHOOD_PAPER_MODE"] = kv.get("ROBINHOOD_PAPER_MODE") or "false"

    out: list[str] = []
    seen: set[str] = set()
    for c in comments[:20]:
        out.append(c)
    out.append("# --- desk defaults merged by tools/merge_executor_env.py (secrets preserved) ---")
    for k in order:
        if k in seen or k not in kv:
            continue
        seen.add(k)
        out.append(f"{k}={kv[k]}")
    for k, v in kv.items():
        if k not in seen:
            out.append(f"{k}={v}")

    ENV_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"merged {ENV_FILE} keys {len(kv)} POLL {kv.get('POLL_INTERVAL_S')} MIN_GOD {kv.get('MIN_GOD_STACKED')}")


if __name__ == "__main__":
    main()
