"""
X.com Post Creator — SOP-Optimized Post Generator
Transforms rough sentences into algorithm-ready X posts following the 4-step cheat code.
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


def _call_llm(prompt: str) -> str:
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        import anthropic
        client = anthropic.Anthropic(api_key=anthropic_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=_SOP_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()

    from openai import OpenAI
    model = os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.2-3b-instruct:free")
    client = OpenAI(
        api_key=os.environ.get("OPENROUTER_API_KEY", ""),
        base_url="https://openrouter.ai/api/v1",
    )
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SOP_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        timeout=60,
    )
    return resp.choices[0].message.content.strip()


@xpost_bp.route("/generate", methods=["POST"])
def generate():
    data = request.get_json(force=True) or {}
    sentences = (data.get("sentences") or "").strip()
    media     = (data.get("media") or "").strip()
    niche     = (data.get("niche") or "").strip()

    if not sentences:
        return jsonify({"error": "No input provided"}), 400

    parts = []
    if niche:
        parts.append(f"NICHE / TOPIC AREA: {niche}")
    parts.append(f"RAW INPUT:\n{sentences}")
    if media:
        parts.append(f"ATTACHED MEDIA DESCRIPTION: {media}")

    try:
        post = _call_llm("\n\n".join(parts))
        return jsonify({"post": post, "chars": len(post)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
