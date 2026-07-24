#!/usr/bin/env python3
"""
Ops Sentinel — autonomous operational-drift fixer for SqueezeOS.

OPERATOR MANDATE (2026-07-24): full autonomy for OPERATIONAL fixes only —
no human approval gate. Money and credentials (Stripe products/pricing,
AWS/API keys, wallet signing) are explicitly OUT OF SCOPE for this script
and must never be touched here. That boundary is load-bearing, not a
style choice — see CLAUDE.md's repeated "zero custody" decisions.

NO GUESSING OR ASSUMING — this is the other hard rule this script exists
to enforce on itself:
  - Every auto-applied fix must be a mechanical transformation derived
    from a concrete, re-derivable source of truth in this repo (e.g. the
    literal length of core.api.mcp_bp._TOOLS, the literal string of
    core.api.mcp_bp._SERVER_INFO["version"]). No fix here is generated
    freeform, by an LLM, or by inference.
  - If a check can't establish ground truth unambiguously (a broken link
    with no obviously-correct target, a description that needs shortening
    without losing meaning, anything requiring editorial judgment), it is
    FLAGGED, not fixed. Flagged items are reported to the existing
    marketing activity feed for a human to look at — they are never
    silently auto-resolved.
  - If a source file can't be parsed/read, the check for it is skipped
    and logged as skipped — never treated as "0" or "no drift found".

Run: python3 scripts/ops_sentinel.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MCP_BP_PATH = REPO_ROOT / "core" / "api" / "mcp_bp.py"

# Files where a stated tool count is expected to match the real _TOOLS
# length. Kept as an explicit allowlist (not "every file in the repo")
# so a stray coincidental number never gets mangled by this script.
TOOL_COUNT_FILES = [
    REPO_ROOT / ".well-known" / "ai.txt",
    REPO_ROOT / ".well-known" / "mcp.json",
    REPO_ROOT / ".well-known" / "server.json",
    REPO_ROOT / ".well-known" / "catalog.json",
    REPO_ROOT / ".well-known" / "mcp" / "server-card.json",
    REPO_ROOT / "llms.txt",
    REPO_ROOT / "CLAUDE.md",
]

# Only compound phrasings specific enough to be unambiguously a TOTAL tool
# count are auto-fixable. A bare "N tools" is too ambiguous to safely
# mechanical-fix (a doc can legitimately say "5 tools" about a five-tool
# subsystem right next to "62 tools" about the whole server — matching the
# first ops_sentinel draft did exactly that and produced a false positive
# on llms.txt's "AEO/GEO Intelligence Suite (NEW — 5 tools)" line). Bare
# "N tools" mentions are handled by TOOL_COUNT_FLAG_PATTERN below instead.
TOOL_COUNT_PATTERNS = [
    re.compile(r"(?P<num>\d+)(?P<suffix>\+?\s*MCP tools)"),
    re.compile(r"(?P<num>\d+)(?P<suffix>-tool\b)"),
]

# Bare "N tools" (no "MCP"/"-tool" qualifier) — flagged for a human to
# confirm, never auto-fixed, since it's ambiguous whether this refers to
# the total server tool count or some other, legitimately smaller number.
TOOL_COUNT_FLAG_PATTERN = re.compile(r"(?<!MCP )(?<!-)\b(\d+)\s+tools\b")

MARKETING_ACTIVITY_URL = os.environ.get(
    "MARKETING_ACTIVITY_URL", "https://squeezeos-api.onrender.com/api/marketing/activity"
)
MARKETING_ACTIVITY_SECRET = os.environ.get("MARKETING_ACTIVITY_SECRET", "")


def get_real_tool_count() -> int | None:
    """Mechanically counts _TOOLS entries in mcp_bp.py. Returns None (never
    a guessed number) if the file can't be read or parsed."""
    try:
        text = MCP_BP_PATH.read_text()
    except OSError as e:
        print(f"[skip] cannot read {MCP_BP_PATH}: {e}")
        return None

    start = text.find("\n_TOOLS = [")
    if start == -1:
        print(f"[skip] _TOOLS block not found in {MCP_BP_PATH}")
        return None
    end = text.find("\n]", start)
    if end == -1:
        print(f"[skip] end of _TOOLS block not found in {MCP_BP_PATH}")
        return None

    block = text[start:end]
    names = re.findall(r'"name":\s*"([a-zA-Z0-9_]+)"', block)
    if not names:
        print("[skip] _TOOLS block parsed but yielded zero tool names — refusing to trust this")
        return None
    return len(set(names))


def get_real_version() -> str | None:
    try:
        text = MCP_BP_PATH.read_text()
    except OSError as e:
        print(f"[skip] cannot read {MCP_BP_PATH}: {e}")
        return None
    m = re.search(r'_SERVER_INFO\s*=\s*\{[^}]*?"version":\s*"([^"]+)"', text, re.DOTALL)
    if not m:
        print("[skip] _SERVER_INFO version not found")
        return None
    return m.group(1)


def fix_tool_count_mentions(real_count: int, dry_run: bool) -> list[str]:
    fixes = []
    for path in TOOL_COUNT_FILES:
        if not path.exists():
            continue
        try:
            text = path.read_text()
        except OSError as e:
            print(f"[skip] cannot read {path}: {e}")
            continue

        new_text = text
        for pattern in TOOL_COUNT_PATTERNS:
            def _replace(m: re.Match) -> str:
                stated = int(m.group("num"))
                if stated == real_count:
                    return m.group(0)
                fixes.append(
                    f"{path.relative_to(REPO_ROOT)}: {stated} -> {real_count}{m.group('suffix')}"
                )
                return f"{real_count}{m.group('suffix')}"

            new_text = pattern.sub(_replace, new_text)

        if new_text != text and not dry_run:
            path.write_text(new_text)

    return fixes


def fix_mcp_json_embedded_version(real_version: str, dry_run: bool) -> list[str]:
    path = REPO_ROOT / ".well-known" / "mcp.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(f"[skip] cannot parse {path}: {e}")
        return []

    fixes = []
    server = data.get("mcpServers", {}).get("squeezeos", {})
    stated = server.get("version")
    if stated is not None and stated != real_version:
        fixes.append(f"{path.relative_to(REPO_ROOT)}: mcpServers.squeezeos.version {stated} -> {real_version}")
        if not dry_run:
            server["version"] = real_version
            path.write_text(json.dumps(data, indent=2) + "\n")

    return fixes


def flag_ambiguous_tool_count_mentions(real_count: int) -> list[str]:
    """Bare 'N tools' mentions that don't match real_count — reported for a
    human to confirm rather than auto-fixed, since the ambiguity is real
    (see TOOL_COUNT_FLAG_PATTERN's comment)."""
    flags = []
    for path in TOOL_COUNT_FILES:
        if not path.exists():
            continue
        try:
            text = path.read_text()
        except OSError:
            continue
        for m in TOOL_COUNT_FLAG_PATTERN.finditer(text):
            stated = int(m.group(1))
            if stated != real_count:
                line_no = text.count("\n", 0, m.start()) + 1
                flags.append(
                    f"{path.relative_to(REPO_ROOT)}:{line_no} says \"{stated} tools\" "
                    f"(real total is {real_count}) — needs a human to confirm this isn't "
                    f"describing a smaller subsystem on purpose"
                )
    return flags


def flag_broken_internal_links() -> list[str]:
    """Tier 2 — flag only, never auto-fix. A broken link's correct target
    requires editorial judgment (see the mastersheets.html/smlsheets.html
    case), which this script must not guess at."""
    flags = []
    href_pattern = re.compile(r'href="([a-zA-Z0-9_\-./]+\.html)"')
    jsonld_pattern = re.compile(r'"url":\s*"https://[^"]*?/([a-zA-Z0-9_\-]+\.html)"')

    for html_file in REPO_ROOT.glob("**/*.html"):
        if "node_modules" in html_file.parts:
            continue
        try:
            text = html_file.read_text()
        except OSError:
            continue
        for pattern in (href_pattern, jsonld_pattern):
            for m in pattern.finditer(text):
                target = m.group(1)
                if target.startswith("http"):
                    continue
                target_path = (html_file.parent / target).resolve()
                if not target_path.exists():
                    flags.append(f"{html_file.relative_to(REPO_ROOT)} references missing {target}")

    return flags


def report_to_activity_feed(agent: str, action: str, status: str) -> None:
    if not MARKETING_ACTIVITY_SECRET:
        print(f"[activity-feed skipped: no secret configured] {agent}: {action}")
        return
    body = json.dumps({"agent": agent, "action": action, "status": status}).encode()
    req = urllib.request.Request(
        MARKETING_ACTIVITY_URL,
        data=body,
        headers={"Content-Type": "application/json", "X-Marketing-Secret": MARKETING_ACTIVITY_SECRET},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:  # noqa: BLE001 - reporting is best-effort, never fatal
        print(f"[activity-feed post failed] {e}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    real_count = get_real_tool_count()
    real_version = get_real_version()

    fixes: list[str] = []
    if real_count is not None:
        fixes += fix_tool_count_mentions(real_count, args.dry_run)
    else:
        print("[skip] tool-count checks skipped entirely — could not establish real count")

    if real_version is not None:
        fixes += fix_mcp_json_embedded_version(real_version, args.dry_run)
    else:
        print("[skip] version checks skipped entirely — could not establish real version")

    flags = flag_broken_internal_links()
    if real_count is not None:
        flags += flag_ambiguous_tool_count_mentions(real_count)

    if fixes:
        print(f"\n{len(fixes)} fix(es) applied:" if not args.dry_run else f"\n{len(fixes)} fix(es) would be applied:")
        for f in fixes:
            print(f"  - {f}")
        report_to_activity_feed(
            "Ops Sentinel",
            f"Auto-fixed {len(fixes)} operational drift issue(s): " + "; ".join(fixes[:5])
            + (" ..." if len(fixes) > 5 else ""),
            "success",
        )
    else:
        print("\nNo drift found in tool-count/version checks.")

    if flags:
        print(f"\n{len(flags)} item(s) flagged for human review (not auto-fixed):")
        for f in flags:
            print(f"  - {f}")
        report_to_activity_feed(
            "Ops Sentinel",
            f"Flagged {len(flags)} issue(s) needing human judgment: " + "; ".join(flags[:5])
            + (" ..." if len(flags) > 5 else ""),
            "info",
        )

    # Exit 0 always — this script reports, it doesn't fail CI. The
    # workflow decides what to do with a dirty working tree.
    return 0


if __name__ == "__main__":
    sys.exit(main())
