"""
Free LLM via OpenRouter — uses free-tier Llama 3 models, no billing required.
Docs: https://openrouter.ai/docs
"""
import os
import json
from openai import OpenAI

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
DEFAULT_MODEL   = "meta-llama/llama-3.2-3b-instruct:free"

SYSTEM_TRADER = (
    "You are a concise quantitative trading analyst. "
    "Respond in 2-4 sentences max. No disclaimers. Plain English."
)


class FreeLLM:
    def __init__(self, api_key: str = "", model: str = DEFAULT_MODEL):
        self.model = model
        self.client = OpenAI(
            api_key=api_key or os.environ.get("OPENROUTER_API_KEY", ""),
            base_url=OPENROUTER_BASE,
        )

    # ── low-level ──────────────────────────────────────────────────────────

    def _chat(self, prompt: str, system: str = SYSTEM_TRADER, timeout: int = 60) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ],
            timeout=timeout,
        )
        return resp.choices[0].message.content.strip()

    def is_available(self) -> bool:
        try:
            self._chat("ping", system="Reply with: ok", timeout=10)
            return True
        except Exception:
            return False

    # ── domain helpers ─────────────────────────────────────────────────────

    def analyze_signal(self, symbol: str, signal_data: dict) -> str:
        prompt = (
            f"Ticker: {symbol}\n"
            f"Signal: {json.dumps(signal_data, indent=2)}\n\n"
            "In 2-4 sentences: what is this signal telling us and what is the key risk?"
        )
        return self._chat(prompt)

    def commentary(self, prompt: str) -> str:
        return self._chat(prompt)

    def options_thesis(self, symbol: str, chain_summary: dict) -> str:
        prompt = (
            f"Options chain for {symbol}:\n"
            f"{json.dumps(chain_summary, indent=2)}\n\n"
            "What directional bias does this chain suggest and why?"
        )
        return self._chat(prompt)

    def score_trade(self, symbol: str, context: dict) -> str:
        prompt = (
            f"Trade setup for {symbol}:\n"
            f"{json.dumps(context, indent=2)}\n\n"
            "Rate this setup 1-10 and give a one-line rationale."
        )
        return self._chat(prompt)


# module-level singleton
_llm: FreeLLM | None = None


def get_llm(model: str = DEFAULT_MODEL) -> FreeLLM:
    global _llm
    if _llm is None:
        _llm = FreeLLM(model=model)
    return _llm
