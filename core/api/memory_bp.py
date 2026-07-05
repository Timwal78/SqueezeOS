"""
Memory Graph — /api/memory

Persistent, provenance-tracked agent memory. Every stored node keeps the
caller's own provenance (source_type, source_id, confidence) exactly as
submitted -- this module never invents or upgrades a confidence score.

Recall is literal keyword + tag matching against real stored content,
scoped to the requesting agent_id and ranked by recency. There is no
embedding model wired in here, so this deliberately does NOT claim
semantic/vector search -- every response says exactly what kind of match
was performed so callers don't mistake it for something it isn't.

Storage: Redis (REDIS_URL, already shared with aeo_stripe_bp.py /
aeo_treasury_bp.py / cascade_bp.py) is the durable path. If REDIS_URL is
unset or unreachable, falls back to an in-memory dict -- degrades exactly
like _mem_ledger in aeo_treasury_bp.py: still fully functional, just lost
on restart. Per-agent storage is capped (_MAX_MEMORIES_PER_AGENT) so one
agent can't grow an unbounded list; the cap is an operational safeguard,
not a truncation of what gets returned to a caller within that cap.
"""
import os
import time
import json
import hashlib
import logging

import redis
from flask import Blueprint, jsonify, request

from proof402_integration import dual_payment

log = logging.getLogger("SqueezeOS-MemoryGraph")
memory_bp = Blueprint("memory_bp", __name__)

_REDIS_URL = os.environ.get("REDIS_URL", "")
_MAX_MEMORIES_PER_AGENT = 5000
_VALID_TYPES = {"episodic", "semantic", "procedural", "custom"}

# In-memory fallback if Redis is unavailable -- same degrade pattern as
# aeo_treasury_bp.py's _mem_ledger. Keyed by agent_id -> list of memory dicts.
_mem_store: dict = {}


def _get_redis():
    if not _REDIS_URL:
        return None
    try:
        return redis.from_url(_REDIS_URL, decode_responses=True)
    except Exception as e:
        log.error("[MEMORY] Redis connect failed: %s", e)
        return None


def _agent_key(agent_id: str) -> str:
    return f"memory:agent:{agent_id}"


def _memory_key(memory_id: str) -> str:
    return f"memory:node:{memory_id}"


def _store(agent_id: str, record: dict) -> None:
    r = _get_redis()
    if r:
        pipe = r.pipeline()
        pipe.set(_memory_key(record["memory_id"]), json.dumps(record))
        pipe.lpush(_agent_key(agent_id), record["memory_id"])
        pipe.ltrim(_agent_key(agent_id), 0, _MAX_MEMORIES_PER_AGENT - 1)
        pipe.execute()
    else:
        _mem_store.setdefault(agent_id, [])
        _mem_store[agent_id].insert(0, record)
        del _mem_store[agent_id][_MAX_MEMORIES_PER_AGENT:]


def _load_agent_memories(agent_id: str) -> list:
    r = _get_redis()
    if r:
        ids = r.lrange(_agent_key(agent_id), 0, _MAX_MEMORIES_PER_AGENT - 1)
        if not ids:
            return []
        raw = r.mget([_memory_key(mid) for mid in ids])
        return [json.loads(x) for x in raw if x]
    return list(_mem_store.get(agent_id, []))


@memory_bp.route('/store', methods=['POST'])
@dual_payment(
    price_usdc="0.01",
    description=(
        "Memory Graph — persist an agent memory with the caller's own "
        "provenance (source_type, source_id, confidence) kept exactly as "
        "submitted. Durable in Redis when REDIS_URL is configured."
    ),
)
def store():
    body = request.get_json(silent=True) or {}
    content = (body.get('content') or '').strip()
    agent_id = (body.get('agent_id') or '').strip()
    mem_type = body.get('type', 'episodic')
    tags = body.get('tags') or []
    provenance = body.get('provenance') or {}

    if not content:
        return jsonify({'error': 'ERR_MISSING_CONTENT', 'message': 'content is required'}), 400
    if not agent_id:
        return jsonify({'error': 'ERR_MISSING_AGENT_ID', 'message': 'agent_id is required'}), 400
    if mem_type not in _VALID_TYPES:
        return jsonify({'error': 'ERR_INVALID_TYPE', 'message': f'type must be one of {sorted(_VALID_TYPES)}'}), 400
    if 'confidence' not in provenance:
        return jsonify({
            'error': 'ERR_MISSING_PROVENANCE_CONFIDENCE',
            'message': 'provenance.confidence is required — this endpoint will not fabricate a confidence score on your behalf.',
        }), 400
    if not isinstance(tags, list):
        return jsonify({'error': 'ERR_INVALID_TAGS', 'message': 'tags must be a list of strings'}), 400

    now = time.time()
    memory_id = hashlib.sha256(f"{agent_id}:{content}:{now}".encode()).hexdigest()[:24]
    record = {
        'memory_id': memory_id,
        'agent_id': agent_id,
        'type': mem_type,
        'content': content,
        'tags': [str(t) for t in tags],
        'provenance': provenance,
        'created_at': now,
    }
    _store(agent_id, record)

    return jsonify({'stored': True, 'memory_id': memory_id, 'created_at': now})


@memory_bp.route('/recall', methods=['GET'])
@dual_payment(
    price_usdc="0.01",
    description=(
        "Memory Graph — literal keyword/tag search over an agent's own stored "
        "memories, ranked by recency. Not semantic/vector search — no "
        "embedding model is used, and this endpoint says so explicitly."
    ),
)
def recall():
    agent_id = (request.args.get('agent_id') or '').strip()
    if not agent_id:
        return jsonify({'error': 'ERR_MISSING_AGENT_ID', 'message': 'agent_id query param is required'}), 400

    query = (request.args.get('query') or '').strip().lower()
    mem_type = request.args.get('type')
    tags_filter = [t.strip() for t in (request.args.get('tags') or '').split(',') if t.strip()]
    try:
        limit = max(1, min(int(request.args.get('limit', 10)), 100))
    except ValueError:
        limit = 10

    memories = _load_agent_memories(agent_id)

    def matches(m):
        if mem_type and m.get('type') != mem_type:
            return False
        if tags_filter and not set(tags_filter) & set(m.get('tags', [])):
            return False
        if query and query not in m.get('content', '').lower():
            return False
        return True

    results = [m for m in memories if matches(m)]
    results.sort(key=lambda m: m.get('created_at', 0), reverse=True)
    results = results[:limit]

    return jsonify({
        'agent_id': agent_id,
        'match_method': 'keyword-and-tag-literal-match',
        'match_method_note': 'Not semantic/embedding search. Ranked by recency among literal matches only.',
        'result_count': len(results),
        'results': results,
    })


@memory_bp.route('/stats/<agent_id>', methods=['GET'])
def stats(agent_id: str):
    """Free — real count of an agent's stored memories, no payment required."""
    memories = _load_agent_memories(agent_id)
    by_type = {}
    for m in memories:
        by_type[m.get('type', 'unknown')] = by_type.get(m.get('type', 'unknown'), 0) + 1
    return jsonify({
        'agent_id': agent_id,
        'total_memories': len(memories),
        'by_type': by_type,
        'storage_backend': 'redis' if _get_redis() else 'in-memory (resets on restart — REDIS_URL not configured)',
    })
