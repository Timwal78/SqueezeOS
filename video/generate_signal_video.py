"""
SML Signal Video Generator
Fetches live sovereign signal → writes script → TTS voiceover → chart animation → MP4.

Output: /tmp/sml_signal_video.mp4
"""

import os
import sys
import json
import time
import textwrap
import tempfile
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────
SQUEEZEOS_BASE   = os.getenv("SQUEEZEOS_BASE_URL", "https://squeezeos-api.onrender.com")
ANTHROPIC_KEY    = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_KEY       = os.getenv("OPENAI_API_KEY", "")
OUTPUT_PATH      = os.getenv("VIDEO_OUTPUT_PATH", "/tmp/sml_signal_video.mp4")
SYMBOL           = os.getenv("VIDEO_SYMBOL", "IWM")
TTS_VOICE        = os.getenv("TTS_VOICE", "onyx")   # onyx | alloy | nova | shimmer
VIDEO_W, VIDEO_H = 1920, 1080
FPS              = 24
DURATION_SECS    = 45   # target video length

# ── Fetch signal ──────────────────────────────────────────────────────────────

def fetch_json(url: str, headers: dict = None, body: bytes = None, method: str = "GET") -> dict:
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def get_signal(symbol: str) -> dict:
    """Free preview — no payment needed for video generation."""
    try:
        data = fetch_json(f"{SQUEEZEOS_BASE}/api/preview/{symbol}")
        return data
    except Exception as e:
        print(f"[SIGNAL] preview failed: {e}")
        return {}


def get_council_demo() -> dict:
    try:
        return fetch_json(f"{SQUEEZEOS_BASE}/api/demo/council")
    except Exception as e:
        print(f"[SIGNAL] demo/council failed: {e}")
        return {}


def get_full_context(symbol: str) -> dict:
    preview  = get_signal(symbol)
    council  = get_council_demo()
    return {"preview": preview, "council": council, "symbol": symbol}


# ── Script generation via Claude ──────────────────────────────────────────────

def generate_script(context: dict) -> str:
    if not ANTHROPIC_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    symbol  = context.get("symbol", "IWM")
    preview = context.get("preview", {})
    council = context.get("council", {})

    bias        = preview.get("bias", "NEUTRAL")
    regime      = preview.get("regime", "NEUTRAL")
    verdict     = council.get("verdict", council.get("directive", "HOLD"))
    confidence  = council.get("confidence", "")
    conf_str    = f"{confidence}% confidence" if confidence else ""

    prompt = f"""You are the narrator for SML — ScriptMaster Labs, an institutional AI trading intelligence platform.

Write a {DURATION_SECS}-second spoken video script (about 120 words) for a market signal update.

Signal data (DO NOT mention any specific numbers, EMA values, price levels, or indicator readings):
- Symbol: {symbol}
- Bias: {bias}
- Regime: {regime}
- Council verdict: {verdict} {conf_str}

Style: confident, institutional, authoritative. Think Bloomberg Terminal meets crypto Twitter.
Dramatic but credible. Short punchy sentences. No fluff.
Start with the ticker symbol and the top-line verdict immediately.
End with a call to action: "SqueezeOS — pay per signal, no subscription."

Return ONLY the spoken script. No stage directions, no headers."""

    body = json.dumps({
        "model": "claude-opus-4-8",
        "max_tokens": 400,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()

    headers = {
        "x-api-key":         ANTHROPIC_KEY,
        "anthropic-version": "2023-06-01",
        "content-type":      "application/json",
    }
    resp = fetch_json("https://api.anthropic.com/v1/messages",
                      headers=headers, body=body, method="POST")
    return resp["content"][0]["text"].strip()


# ── TTS via OpenAI ────────────────────────────────────────────────────────────

def generate_audio(script: str, out_path: str) -> None:
    if not OPENAI_KEY:
        raise RuntimeError("OPENAI_API_KEY not set")

    body = json.dumps({
        "model": "tts-1-hd",
        "input": script,
        "voice": TTS_VOICE,
    }).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/audio/speech",
        data=body,
        headers={
            "Authorization": f"Bearer {OPENAI_KEY}",
            "Content-Type":  "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        Path(out_path).write_bytes(r.read())
    print(f"[TTS] audio → {out_path}")


# ── Chart frame generation via matplotlib ─────────────────────────────────────

def build_chart_frames(context: dict, frames_dir: str, n_frames: int) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import numpy as np

    symbol  = context.get("symbol", "IWM")
    preview = context.get("preview", {})
    council = context.get("council", {})

    bias    = preview.get("bias", "NEUTRAL")
    regime  = preview.get("regime", "NEUTRAL")
    verdict = council.get("verdict", council.get("directive", "HOLD"))

    BULL_COLOR  = "#00ff88"
    BEAR_COLOR  = "#ff3355"
    NEUT_COLOR  = "#888888"
    BG_COLOR    = "#0a0e1a"
    GRID_COLOR  = "#1a2030"
    TEXT_COLOR  = "#e0e8ff"
    ACCENT      = "#7c6af7"

    verdict_color = BULL_COLOR if any(x in verdict.upper() for x in ("BUY", "BULL", "IGNITION")) \
                    else BEAR_COLOR if any(x in verdict.upper() for x in ("SELL", "BEAR", "SHIELD")) \
                    else NEUT_COLOR

    # Simulate candlestick data (visual only — no real prices surfaced)
    np.random.seed(42)
    n_candles = 60
    returns   = np.random.normal(0, 0.008, n_candles)
    if "BULL" in verdict.upper() or "BUY" in verdict.upper():
        returns[-20:] += 0.003
    elif "BEAR" in verdict.upper() or "SELL" in verdict.upper():
        returns[-20:] -= 0.003

    closes = 100 * np.cumprod(1 + returns)
    opens  = np.roll(closes, 1); opens[0] = closes[0]
    highs  = np.maximum(opens, closes) * (1 + np.abs(np.random.normal(0, 0.003, n_candles)))
    lows   = np.minimum(opens, closes) * (1 - np.abs(np.random.normal(0, 0.003, n_candles)))

    os.makedirs(frames_dir, exist_ok=True)

    for i in range(n_frames):
        progress = i / max(n_frames - 1, 1)
        reveal   = max(5, int(n_candles * min(1.0, progress * 1.4)))

        fig, ax = plt.subplots(figsize=(VIDEO_W / 100, VIDEO_H / 100), dpi=100)
        fig.patch.set_facecolor(BG_COLOR)
        ax.set_facecolor(BG_COLOR)

        # Grid
        ax.yaxis.grid(True, color=GRID_COLOR, linewidth=0.5)
        ax.xaxis.grid(True, color=GRID_COLOR, linewidth=0.5)
        ax.set_axisbelow(True)

        # Candles
        for j in range(min(reveal, n_candles)):
            up    = closes[j] >= opens[j]
            color = BULL_COLOR if up else BEAR_COLOR
            ax.plot([j, j], [lows[j], highs[j]], color=color, linewidth=0.8, alpha=0.7)
            ax.add_patch(mpatches.FancyBboxPatch(
                (j - 0.35, min(opens[j], closes[j])),
                0.7, abs(closes[j] - opens[j]) or 0.1,
                boxstyle="square,pad=0", facecolor=color, alpha=0.85,
            ))

        # EMA ribbon (visual only — no values labeled)
        if reveal > 20:
            for period, alpha in [(9, 0.9), (21, 0.7), (50, 0.5)]:
                if reveal > period:
                    ema = _ema(closes[:reveal], period)
                    ax.plot(range(period - 1, reveal), ema,
                            color=ACCENT, linewidth=1.2, alpha=alpha)

        ax.set_xlim(-1, n_candles + 1)
        ax.tick_params(colors=TEXT_COLOR, labelsize=9)
        for spine in ax.spines.values():
            spine.set_edgecolor(GRID_COLOR)

        # Watermark logo
        ax.text(0.01, 0.99, "SML", transform=ax.transAxes,
                fontsize=28, fontweight="bold", color=ACCENT,
                va="top", ha="left", alpha=0.9,
                fontfamily="monospace")
        ax.text(0.01, 0.91, "ScriptMaster Labs", transform=ax.transAxes,
                fontsize=11, color=TEXT_COLOR, va="top", ha="left", alpha=0.6)

        # Signal panel (right side)
        panel_x = 0.72
        ax.text(panel_x, 0.97, symbol, transform=ax.transAxes,
                fontsize=36, fontweight="bold", color=TEXT_COLOR, va="top")

        # Verdict with pulse effect
        pulse = 0.7 + 0.3 * abs(np.sin(progress * np.pi * 6))
        ax.text(panel_x, 0.82, verdict, transform=ax.transAxes,
                fontsize=22, fontweight="bold", color=verdict_color,
                va="top", alpha=pulse)

        ax.text(panel_x, 0.70, f"Bias: {bias}", transform=ax.transAxes,
                fontsize=14, color=TEXT_COLOR, va="top", alpha=0.85)
        ax.text(panel_x, 0.62, f"Regime: {regime}", transform=ax.transAxes,
                fontsize=14, color=TEXT_COLOR, va="top", alpha=0.85)

        # Timestamp
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        ax.text(0.99, 0.01, ts, transform=ax.transAxes,
                fontsize=9, color=TEXT_COLOR, va="bottom", ha="right", alpha=0.4)

        # URL
        ax.text(0.99, 0.05, "squeezeos-api.onrender.com", transform=ax.transAxes,
                fontsize=9, color=ACCENT, va="bottom", ha="right", alpha=0.5)

        plt.tight_layout(pad=0.5)
        fig.savefig(f"{frames_dir}/frame_{i:05d}.png", dpi=100,
                    facecolor=BG_COLOR, bbox_inches="tight")
        plt.close(fig)

    print(f"[CHART] {n_frames} frames → {frames_dir}")


def _ema(data, period):
    k = 2 / (period + 1)
    ema = [data[0]]
    for v in data[1:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema[period - 1:]


# ── ffmpeg assembly ───────────────────────────────────────────────────────────

def assemble_video(frames_dir: str, audio_path: str, output: str) -> None:
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(FPS),
        "-i", f"{frames_dir}/frame_%05d.png",
        "-i", audio_path,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        "-movflags", "+faststart",
        output,
    ]
    print(f"[FFMPEG] assembling → {output}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError("ffmpeg failed")
    print(f"[FFMPEG] done → {output}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"[SML VIDEO] generating for {SYMBOL} at {datetime.utcnow().isoformat()}")

    # 1. Fetch signal
    context = get_full_context(SYMBOL)
    print(f"[SIGNAL] bias={context.get('preview', {}).get('bias')} "
          f"verdict={context.get('council', {}).get('verdict', context.get('council', {}).get('directive'))}")

    # 2. Generate script
    print("[SCRIPT] generating via Claude...")
    script = generate_script(context)
    print(f"[SCRIPT]\n{script}\n")

    with tempfile.TemporaryDirectory() as tmp:
        audio_path  = os.path.join(tmp, "narration.mp3")
        frames_dir  = os.path.join(tmp, "frames")

        # 3. TTS
        print("[TTS] generating voiceover...")
        generate_audio(script, audio_path)

        # 4. Chart frames
        n_frames = DURATION_SECS * FPS
        print(f"[CHART] rendering {n_frames} frames...")
        build_chart_frames(context, frames_dir, n_frames)

        # 5. Assemble
        assemble_video(frames_dir, audio_path, OUTPUT_PATH)

    print(f"[DONE] video saved → {OUTPUT_PATH}")
    return OUTPUT_PATH


if __name__ == "__main__":
    main()
