"""
X.com Post Creator — SOP-Optimized Post Generator
Transforms rough sentences into algorithm-ready X posts following the 4-step cheat code.

Provider priority (env-based auto-detect), overridable per-request:
  anthropic  → ANTHROPIC_API_KEY   (Claude Haiku — recommended)
  openai     → OPENAI_API_KEY      (GPT-4o-mini)
  openrouter → OPENROUTER_API_KEY  (free/paid OpenRouter models)
  ollama     → OLLAMA_URL          (local Ollama instance)
"""
import os
from flask import Blueprint, request, jsonify

xpost_bp = Blueprint("xpost", __name__)

_SOP_SYSTEM = """\
You are an X.com post optimization engine.
Your ONLY job: transform rough input into a high-performing, algorithm-optimized X post.

Follow these rules exactly — no exceptions:

RULE 1 — FRONT-LOAD (defeats the 4-Head Attention Model):
Heavy-hitting, domain-specific keywords MUST appear in the first 15–30 words.
NEVER open with: "Hey guys", "I wanted to", "Just wanted to share", "Thoughts on",
"Today I learned", "So I've been thinking", or any vague warm-up phrase.
The first line is the hook — it must lead with substance and domain terms.

RULE 2 — CLEAN SYNTAX (defeats 256-dim embedding compression):
Write in short, direct Subject-Verb-Object sentences.
Use bullet points or short numbered lists where content allows.
High density of domain-specific terms. Zero filler. Zero poetic metaphors.
One idea per sentence.

RULE 3 — NO LINKS (bypasses Grox filters):
Zero URLs. Zero outbound destinations in the post body.
All value lives natively in the post. Describe external references in words only.

RULE 4 — NATIVE MEDIA:
If the user describes attached media, write as if it IS already attached.
Reference it naturally: "Chart above shows…", "As you can see in the clip…"
Never say "I will attach" or "see image below".

OUTPUT:
Return ONLY the finished post text — no preamble, no quotes wrapping it, no "Here is your post:".
Start immediately with the first word. Use natural line breaks.
"""


def _detect_provider() -> str:
    """Auto-detect which provider to use based on available env keys."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("OPENROUTER_API_KEY"):
        return "openrouter"
    if os.environ.get("OLLAMA_URL"):
        return "ollama"
    return "openrouter"  # last resort — will fail gracefully with a useful message


def _call_anthropic(prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=_SOP_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


def _call_openai_compat(prompt: str, api_key: str, base_url: str, model: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=base_url)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SOP_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        timeout=60,
    )
    return resp.choices[0].message.content.strip()


def _call_llm(prompt: str, provider: str, ollama_url: str = "", ollama_model: str = "") -> str:
    if provider == "anthropic":
        return _call_anthropic(prompt)

    if provider == "openai":
        return _call_openai_compat(
            prompt,
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            base_url="https://api.openai.com/v1",
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        )

    if provider == "openrouter":
        return _call_openai_compat(
            prompt,
            api_key=os.environ.get("OPENROUTER_API_KEY", ""),
            base_url="https://openrouter.ai/api/v1",
            model=os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.2-3b-instruct:free"),
        )

    if provider == "ollama":
        url = (ollama_url or os.environ.get("OLLAMA_URL", "http://localhost:11434")).rstrip("/")
        model = ollama_model or os.environ.get("OLLAMA_MODEL", "llama3")
        return _call_openai_compat(
            prompt,
            api_key="ollama",
            base_url=f"{url}/v1",
            model=model,
        )

    raise ValueError(f"Unknown provider: {provider}")


@xpost_bp.route("/providers", methods=["GET"])
def list_providers():
    """Return which providers have keys configured so the UI can pre-select."""
    available = []
    if os.environ.get("ANTHROPIC_API_KEY"):
        available.append("anthropic")
    if os.environ.get("OPENAI_API_KEY"):
        available.append("openai")
    if os.environ.get("OPENROUTER_API_KEY"):
        available.append("openrouter")
    # Ollama is always listed — user supplies URL in UI
    available.append("ollama")
    return jsonify({
        "available": available,
        "default": _detect_provider(),
        "ollama_url": os.environ.get("OLLAMA_URL", "http://localhost:11434"),
        "ollama_model": os.environ.get("OLLAMA_MODEL", "llama3"),
    })


@xpost_bp.route("/generate", methods=["POST"])
def generate():
    data = request.get_json(force=True) or {}
    sentences    = (data.get("sentences") or "").strip()
    media        = (data.get("media") or "").strip()
    niche        = (data.get("niche") or "").strip()
    provider     = (data.get("provider") or _detect_provider()).strip()
    ollama_url   = (data.get("ollama_url") or "").strip()
    ollama_model = (data.get("ollama_model") or "").strip()

    if not sentences:
        return jsonify({"error": "No input provided"}), 400

    parts = []
    if niche:
        parts.append(f"NICHE / TOPIC AREA: {niche}")
    parts.append(f"RAW INPUT:\n{sentences}")
    if media:
        parts.append(f"ATTACHED MEDIA DESCRIPTION: {media}")

    try:
        post = _call_llm("\n\n".join(parts), provider, ollama_url, ollama_model)
        return jsonify({"post": post, "chars": len(post), "provider": provider})
    except Exception as e:
        return jsonify({"error": str(e), "provider": provider}), 500
