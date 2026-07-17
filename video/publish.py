"""
SML Video Publisher
Uploads the generated MP4 to YouTube and posts to Discord + Farcaster.

Required env vars:
  YOUTUBE_CLIENT_ID
  YOUTUBE_CLIENT_SECRET
  YOUTUBE_REFRESH_TOKEN
  DISCORD_WEBHOOK_VIDEO      (optional — falls back to DISCORD_WEBHOOK_ALL)
  NEYNAR_API_KEY             (optional — Farcaster)
  NEYNAR_BOT_SIGNER_UUID     (optional — Farcaster)
"""

import os
import json
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime

VIDEO_PATH    = os.getenv("VIDEO_OUTPUT_PATH", "/tmp/sml_signal_video.mp4")
SYMBOL        = os.getenv("VIDEO_SYMBOL", "IWM")
DISCORD_URL   = os.getenv("DISCORD_WEBHOOK_VIDEO") or os.getenv("DISCORD_WEBHOOK_ALL", "")
NEYNAR_KEY    = os.getenv("NEYNAR_API_KEY", "")
NEYNAR_SIGNER = os.getenv("NEYNAR_BOT_SIGNER_UUID", "")

YT_CLIENT_ID  = os.getenv("YOUTUBE_CLIENT_ID", "")
YT_CLIENT_SEC = os.getenv("YOUTUBE_CLIENT_SECRET", "")
YT_REFRESH    = os.getenv("YOUTUBE_REFRESH_TOKEN", "")


# ── YouTube ───────────────────────────────────────────────────────────────────

_TAGS_BASE = [
    "SqueezeOS", "ScriptMaster Labs", "SML signals", "AI trading signals",
    "institutional signals", "options flow", "stock market", "US markets",
    "Wall Street", "NYSE", "NASDAQ", "day trading", "options trading",
    "0DTE", "zero DTE", "market intelligence", "pay per signal",
]

_TAGS_BY_SYMBOL = {
    "IWM": [
        "IWM", "Russell 2000", "small cap stocks", "small cap ETF",
        "IWM options", "pre-market trading", "pre-market signals",
        "morning market", "market open", "IWM 0DTE", "small cap trading",
        "iShares Russell 2000",
    ],
    "SPY": [
        "SPY", "S&P 500", "SP500", "large cap stocks", "S&P 500 ETF",
        "SPY options", "midday trading", "midday market update",
        "market midday", "SPY 0DTE", "index trading", "SPDR S&P 500",
    ],
    "QQQ": [
        "QQQ", "Nasdaq 100", "NASDAQ", "tech stocks", "tech ETF",
        "QQQ options", "market close", "closing bell", "end of day trading",
        "QQQ 0DTE", "growth stocks", "Invesco QQQ", "tech market",
    ],
}


def _build_tags(symbol: str) -> list:
    symbol_tags = _TAGS_BY_SYMBOL.get(symbol.upper(), [symbol.upper()])
    tags = symbol_tags + _TAGS_BASE
    # YouTube: total tag chars ≤ 500, individual tag ≤ 100
    result, total = [], 0
    for tag in tags:
        if total + len(tag) + 1 > 500:
            break
        result.append(tag)
        total += len(tag) + 1
    return result


def _yt_access_token() -> str:
    body = urllib.parse.urlencode({
        "client_id":     YT_CLIENT_ID,
        "client_secret": YT_CLIENT_SEC,
        "refresh_token": YT_REFRESH,
        "grant_type":    "refresh_token",
    }).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())["access_token"]


def upload_youtube(video_path: str, title: str, description: str) -> str:
    """Resumable upload. Returns YouTube video URL."""
    if not all([YT_CLIENT_ID, YT_CLIENT_SEC, YT_REFRESH]):
        print("[YT] credentials not set — skipping upload")
        return ""

    token = _yt_access_token()
    video_bytes = Path(video_path).read_bytes()

    # Initiate resumable upload
    meta = json.dumps({
        "snippet": {
            "title":       title,
            "description": description,
            "tags":        _build_tags(SYMBOL),
            "categoryId":  "25",  # News & Politics
        },
        "status": {
            "privacyStatus":           "public",
            "selfDeclaredMadeForKids": False,
        },
    }).encode()

    init_req = urllib.request.Request(
        "https://www.googleapis.com/upload/youtube/v3/videos"
        "?uploadType=resumable&part=snippet,status",
        data=meta,
        headers={
            "Authorization":           f"Bearer {token}",
            "Content-Type":            "application/json; charset=UTF-8",
            "X-Upload-Content-Type":   "video/mp4",
            "X-Upload-Content-Length": str(len(video_bytes)),
        },
        method="POST",
    )
    with urllib.request.urlopen(init_req, timeout=20) as r:
        upload_url = r.headers["Location"]

    # Upload video bytes
    upload_req = urllib.request.Request(
        upload_url,
        data=video_bytes,
        headers={
            "Authorization":  f"Bearer {token}",
            "Content-Type":   "video/mp4",
            "Content-Length": str(len(video_bytes)),
        },
        method="PUT",
    )
    with urllib.request.urlopen(upload_req, timeout=300) as r:
        resp = json.loads(r.read())

    video_id  = resp.get("id", "")
    yt_url    = f"https://youtu.be/{video_id}" if video_id else ""
    print(f"[YT] uploaded → {yt_url}")
    return yt_url


# ── Discord ───────────────────────────────────────────────────────────────────

def post_discord(message: str, yt_url: str) -> None:
    if not DISCORD_URL:
        print("[DISCORD] webhook not set — skipping")
        return

    content = message
    if yt_url:
        content += f"\n\n{yt_url}"

    body = json.dumps({"content": content, "username": "SML Signal Bot"}).encode()
    req  = urllib.request.Request(
        DISCORD_URL, data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            pass
        print("[DISCORD] posted")
    except Exception as e:
        print(f"[DISCORD] failed: {e}")


# ── Farcaster (Neynar) ────────────────────────────────────────────────────────

def post_farcaster(text: str, yt_url: str) -> None:
    if not NEYNAR_KEY or not NEYNAR_SIGNER:
        print("[FARCASTER] credentials not set — skipping")
        return

    cast_text = text[:280]  # Farcaster limit
    if yt_url and len(cast_text) + len(yt_url) + 2 <= 280:
        cast_text += f"\n{yt_url}"

    body = json.dumps({
        "signer_uuid": NEYNAR_SIGNER,
        "text":        cast_text,
    }).encode()
    req = urllib.request.Request(
        "https://api.neynar.com/v2/farcaster/cast",
        data=body,
        headers={
            "api_key":      NEYNAR_KEY,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read())
        cast_hash = resp.get("cast", {}).get("hash", "")
        print(f"[FARCASTER] cast → {cast_hash}")
    except Exception as e:
        print(f"[FARCASTER] failed: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main(script_text: str = ""):
    ts    = datetime.utcnow().strftime("%b %d, %Y %H:%M UTC")
    title = f"SML Signal Update — {SYMBOL} — {ts}"

    description = (
        f"Live institutional signal update for {SYMBOL} generated by SqueezeOS.\n\n"
        "Powered by ScriptMaster Labs — pay-per-signal AI market intelligence.\n"
        "No subscription. Agents pay per call in RLUSD or USDC.\n\n"
        "https://squeezeos-api.onrender.com\n"
        "https://scriptmasterlabs.com"
    )

    social_msg = (
        f"🔴 SML LIVE — {SYMBOL} signal update\n"
        f"{ts}\n\n"
        "ScriptMaster Labs AI signal suite fired.\n"
        "Pay-per-signal. No subscription.\n"
        "squeezeos-api.onrender.com"
    )

    # 1. Upload to YouTube
    yt_url = upload_youtube(VIDEO_PATH, title, description)

    # 2. Discord
    post_discord(social_msg, yt_url)

    # 3. Farcaster
    post_farcaster(social_msg, yt_url)

    print(f"[PUBLISH] done. YouTube: {yt_url or 'skipped'}")
    return yt_url


if __name__ == "__main__":
    if not os.path.exists(VIDEO_PATH):
        print(f"[PUBLISH] No video at {VIDEO_PATH} — generation step skipped this run "
              "(likely Claude API unavailable). Nothing to publish, exiting cleanly.")
    else:
        main()
