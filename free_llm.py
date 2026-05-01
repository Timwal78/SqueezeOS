"""
Free LLM via Ollama (local Llama — no API key required).
Ollama must be running: https://ollama.com  →  ollama run llama3.2
Default endpoint: http://localhost:11434
"""
import json
import requests

OLLAMA_BASE = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2"


class FreeLLM:
    def __init__(self, base_url: str = OLLAMA_BASE, model: str = DEFAULT_MODEL):
        self.base_url = base_url.rstrip("/")
        self.model = model

    # ── low-level ──────────────────────────────────────────────────────────

    def _chat(self, prompt: str, system: str = "", timeout: int = 60) -> str:
        """Single-turn chat. Returns the assistant text or raises."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        resp = requests.post(
            f"{self.base_url}/api/chat",
            json={"model": self.model, "messages": messages, "stream": False},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()

    def is_available(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=3)
            return r.status_code == 200
        except Exception:
            return False

    def list_models(self) -> list:
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return [m["name"] for m in r.json().get("models", [])]
        except Exception:
            return []

    # ── domain helpers ─────────────────────────────────────────────────────

    SYSTEM_TRADER = (
        "You are a concise quantitative trading analyst. "
        "Respond in 2-4 sentences max. No disclaimers. Plain English."
    )

    def analyze_signal(self, symbol: str, signal_data: dict) -> str:
        """Narrate a squeeze / options signal in plain English."""
        prompt = (
            f"Ticker: {symbol}\n"
            f"Signal data: {json.dumps(signal_data, indent=2)}\n\n"
            "In 2-4 sentences: what is this signal telling us and what is the key risk?"
        )
        return self._chat(prompt, system=self.SYSTEM_TRADER)

    def commentary(self, prompt: str) -> str:
        """General freeform trade commentary."""
        return self._chat(prompt, system=self.SYSTEM_TRADER)

    def options_thesis(self, symbol: str, chain_summary: dict) -> str:
        """Summarise an options chain into a directional thesis."""
        prompt = (
            f"Options chain summary for {symbol}:\n"
            f"{json.dumps(chain_summary, indent=2)}\n\n"
            "What directional bias does this chain suggest and why?"
        )
        return self._chat(prompt, system=self.SYSTEM_TRADER)

    def score_trade(self, symbol: str, context: dict) -> str:
        """Rate a trade setup out of 10 with one-line rationale."""
        prompt = (
            f"Trade setup for {symbol}:\n"
            f"{json.dumps(context, indent=2)}\n\n"
            "Rate this setup 1-10 and give a one-line rationale."
        )
        return self._chat(prompt, system=self.SYSTEM_TRADER)


# module-level singleton
_llm: FreeLLM | None = None


def get_llm(base_url: str = OLLAMA_BASE, model: str = DEFAULT_MODEL) -> FreeLLM:
    global _llm
    if _llm is None:
        _llm = FreeLLM(base_url=base_url, model=model)
    return _llm
