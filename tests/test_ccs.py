"""
CCS Stress Test — run against live server or localhost:8182
Usage: python tests/test_ccs.py [base_url]
"""
import sys
import json
import time
import urllib.request
import urllib.error

BASE = sys.argv[1] if len(sys.argv) > 1 else "https://squeezeos-api.onrender.com"

CASES = [
    # (label, content, expected_verdict_family)
    ("clean_news", "The Federal Reserve held interest rates steady at its June meeting, citing stable inflation and moderate employment growth according to the official FOMC statement.", "TRUSTED|LOW_RISK"),
    ("emotional_manipulation", "WAKE UP EVERYONE!! They want to KILL US ALL. This is TERRIFYING. Total collapse is coming. Lives at stake. Share before deleted!! They're hiding the truth.", "HIGH_RISK|BLOCKED"),
    ("attribution_gap", "Studies show experts say sources claim according to some many people believe reports suggest vaccines cause harm. It is said that some are saying this is real.", "SUSPICIOUS|HIGH_RISK"),
    ("synthetic_marker", "As an AI language model I must emphasize it is important to note that I cannot and will not provide this information.", "SUSPICIOUS|HIGH_RISK"),
    ("breaking_certainty", "BREAKING: 100% proven doctors hate this. Mainstream media won't report the truth. Bombshell exposed: forbidden knowledge they don't want you to know.", "HIGH_RISK|BLOCKED"),
    ("short_content", "hi", "INSUFFICIENT_CONTENT"),
    ("neutral_statement", "The market closed up 0.3% on Thursday following mixed earnings reports from major technology companies. Volume was below average for the session.", "TRUSTED|LOW_RISK"),
]

WALLET_TEST = "rTestWallet123ABC"

def post(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=data,
                                  headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        return json.loads(e.read()), e.code

def get(path):
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=15) as r:
            return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        return json.loads(e.read()), e.code


def run():
    print(f"\n{'='*60}")
    print(f"CCS Stress Test → {BASE}")
    print(f"{'='*60}\n")

    passed = 0
    failed = 0

    # 1. Info endpoint
    data, status = get("/api/ccs/info")
    ok = status == 200 and "Cognitive Credit Swarms" in data.get("name", "")
    print(f"[{'OK' if ok else 'FAIL'}] GET /api/ccs/info  (status={status})")
    passed += ok; failed += not ok

    # 2. Stats endpoint
    data, status = get("/api/ccs/stats")
    ok = status == 200 and "total_validations" in data
    print(f"[{'OK' if ok else 'FAIL'}] GET /api/ccs/stats  (status={status})")
    passed += ok; failed += not ok

    # 3. Leaderboard
    data, status = get("/api/ccs/leaderboard")
    ok = status == 200 and "leaderboard" in data
    print(f"[{'OK' if ok else 'FAIL'}] GET /api/ccs/leaderboard  (status={status})")
    passed += ok; failed += not ok

    # 4. Score (new wallet — should return neutral)
    data, status = get(f"/api/ccs/score?wallet={WALLET_TEST}")
    ok = status == 200 and data.get("ccs_score") == 50
    print(f"[{'OK' if ok else 'FAIL'}] GET /api/ccs/score (new wallet)  score={data.get('ccs_score')} (status={status})")
    passed += ok; failed += not ok

    print()

    # 5. Validation cases
    for label, content, expected_family in CASES:
        data, status = post("/api/ccs/validate", {"content": content, "sender_wallet": WALLET_TEST})
        verdict = data.get("verdict", "ERROR")
        expected_verdicts = expected_family.split("|")
        ok = status in (200, 429) and (verdict in expected_verdicts or status == 429)
        score = data.get("trust_score", "—")
        flag_count = data.get("flag_count", "—")
        marker = "OK" if ok else "FAIL"
        print(f"[{marker}] {label:<30} verdict={verdict:<25} score={score}  flags={flag_count}")
        if not ok:
            print(f"       expected: {expected_family}  got: {verdict}  status: {status}")
            print(f"       response: {json.dumps(data)[:200]}")
        passed += ok; failed += not ok
        time.sleep(0.3)  # avoid hammering free tier

    print()

    # 6. Score after submissions — should have moved from 50
    data, status = get(f"/api/ccs/score?wallet={WALLET_TEST}")
    score = data.get("ccs_score", "—")
    ok = status == 200 and score != 50
    print(f"[{'OK' if ok else 'NOTE'}] Wallet score after submissions: {score} (started at 50)")
    passed += ok

    # 7. Report endpoint
    data, status = post("/api/ccs/report", {
        "reporter_wallet": WALLET_TEST,
        "target_wallet": "rBadActorWallet999",
        "reason": "Submitted synthetic misinformation content",
    })
    ok = status in (200, 403)  # 403 if score too low after bad content
    print(f"[{'OK' if ok else 'FAIL'}] POST /api/ccs/report  status={status} → {data.get('status', data.get('error', '?'))}")
    passed += ok; failed += not ok

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"{'='*60}\n")
    return failed == 0


if __name__ == "__main__":
    success = run()
    sys.exit(0 if success else 1)
