"""
EdgeScanner — AI Setup Analyst
════════════════════════════════
Uses Claude (claude-opus-4-7, adaptive thinking) to evaluate each setup
and produce a structured probability score + plain-English explanation.

The AI layer adds reasoning that pure indicator logic cannot:
  - Pattern quality assessment given market context
  - Sector/macro headwinds or tailwinds
  - Conviction behind the R:R
  - Clear bull and bear case
"""

import os
import json
import logging
from typing import Optional

import anthropic

logger = logging.getLogger("AI_ANALYST")


_SYSTEM_PROMPT = """You are an elite quantitative trader and options strategist specializing in
high-probability equity setups for retail traders. You have deep expertise in technical analysis,
order flow, market microstructure, and risk management.

When analyzing a setup, you think like a professional: you look for confluence, you respect
what the tape is telling you, and you never force a trade.

Your analysis must be:
- HONEST: If the setup is marginal, say so. Never hype.
- SPECIFIC: Reference the exact data points provided.
- ACTIONABLE: Clear entry logic, invalidation, and targets.
- CONCISE: Retail traders need clarity, not essays.

Output JSON only. No markdown fences. No commentary outside the JSON.
"""

_USER_TEMPLATE = """Analyze this setup and return a JSON object with exactly these keys:

Setup data:
{setup_json}

Required JSON output:
{{
  "probability_score": <integer 0-100, your estimated probability this trade works>,
  "conviction": <"HIGH" | "MEDIUM" | "LOW">,
  "bull_case": "<1-2 sentences: why this works>",
  "bear_case": "<1-2 sentences: what kills this>",
  "catalyst": "<what event or condition confirms entry>",
  "key_risk": "<single biggest risk to the position>",
  "ai_commentary": "<2-3 sentence narrative for a retail trader. Be direct.>",
  "grade": <"S" | "A" | "B" | "C" | "F">
}}

Grade rubric:
  S  = 80+ probability, HIGH conviction, textbook pattern
  A  = 70-79 OR MEDIUM conviction with strong data
  B  = 60-69, tradeable with sizing discipline
  C  = 50-59, marginal — monitor only
  F  = <50, skip this setup
"""


class AIAnalyst:
    """
    Calls Claude API to score and explain each setup.
    Results are cached in-memory to avoid redundant API calls within a scan cycle.
    """

    def __init__(self):
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY environment variable not set")
        self.client = anthropic.Anthropic(api_key=api_key)
        self._cache: dict[str, dict] = {}

    def _cache_key(self, setup: dict) -> str:
        return f"{setup.get('symbol')}|{setup.get('pattern')}|{setup.get('timestamp', '')[:13]}"

    def analyze(self, setup: dict) -> Optional[dict]:
        """
        Analyze a single setup with Claude.
        Returns enriched setup dict with AI fields, or None on failure.
        """
        key = self._cache_key(setup)
        if key in self._cache:
            return {**setup, **self._cache[key]}

        # Strip internal fields Claude doesn't need
        clean_setup = {k: v for k, v in setup.items()
                       if k not in {"timestamp"}}

        prompt = _USER_TEMPLATE.format(
            setup_json=json.dumps(clean_setup, indent=2)
        )

        try:
            response = self.client.messages.create(
                model="claude-opus-4-7",
                max_tokens=800,
                thinking={"type": "adaptive"},
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )

            # Extract text content (skip thinking blocks)
            text = ""
            for block in response.content:
                if block.type == "text":
                    text = block.text.strip()
                    break

            if not text:
                logger.warning(f"[AI] Empty response for {setup.get('symbol')}")
                return None

            ai_result = json.loads(text)

            # Validate required keys
            required = {"probability_score", "conviction", "bull_case",
                        "bear_case", "catalyst", "key_risk", "ai_commentary", "grade"}
            if not required.issubset(ai_result.keys()):
                logger.warning(f"[AI] Missing keys for {setup.get('symbol')}: {required - ai_result.keys()}")
                return None

            # Clamp probability score
            ai_result["probability_score"] = int(
                max(0, min(100, int(ai_result.get("probability_score", 50))))
            )

            self._cache[key] = ai_result
            return {**setup, **ai_result}

        except json.JSONDecodeError as e:
            logger.error(f"[AI] JSON parse error for {setup.get('symbol')}: {e} | raw: {text[:200]}")
            return None
        except anthropic.APIError as e:
            logger.error(f"[AI] API error for {setup.get('symbol')}: {e}")
            return None
        except Exception as e:
            logger.error(f"[AI] Unexpected error for {setup.get('symbol')}: {e}")
            return None

    def analyze_batch(self, setups: list[dict], max_per_cycle: int = 20) -> list[dict]:
        """
        Analyze up to max_per_cycle setups (sorted by edge_score desc).
        Lower-ranked setups are returned without AI fields if limit hit.
        """
        analyzed = []
        budget = max_per_cycle

        for setup in setups:
            if budget > 0:
                result = self.analyze(setup)
                if result is not None:
                    analyzed.append(result)
                    budget -= 1
                else:
                    analyzed.append(setup)
            else:
                analyzed.append(setup)

        return analyzed

    def clear_cache(self):
        self._cache.clear()
