from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from backend.database.client import get_db
from backend.database.schema import ContextRouteLog, EMBEDDING_DIM, PendingConflict
from backend.memory.conflicts import is_semantic_contradiction
from backend.memory.context_router import categories_for_domain, classify_query_domain
from backend.memory.decay import infer_decay_profile
from backend.memory.embedder import embed, get_model, get_status
from backend.memory.graph_layer import sync_memory_node, update_graph_on_memory_create
from backend.memory.write_queue import enqueue_write

logger = logging.getLogger(__name__)

_LEGACY_MEMORY_BASE_COLUMNS = {
    "id",
    "content",
    "level",
    "category",
    "importance_score",
    "confidence_score",
    "privacy",
    "tags",
    "source_llm",
    "source_conversation_id",
    "source_message_id",
    "source_excerpt",
    "version",
    "status",
    "created_at",
    "updated_at",
    "last_referenced_at",
    "reference_count",
    "decay_profile",
    "expires_at",
    "needs_review",
    "review_due_at",
    "event_date",
    "suggestion_reason",
    "review_note",
    "vector",
}

_AUTO_ANALYSIS_TAG = "auto:conversation-analysis"
_USER_ANCHOR_PATTERN = re.compile(
    r"\b(the user|user's|l'utilisateur|utilisateur|lutilisateur)\b",
    flags=re.IGNORECASE,
)
_GENERIC_FACT_PATTERN = re.compile(
    r"\b("
    r"is\s+(an?|the)\s+(?:[a-z0-9][a-z0-9_\-]*\s+){0,4}(open|standard|protocol|framework|library|language|concept|method|tool|model)\b|"
    r"refers to\b|means\b|defined as\b|"
    r"est\s+(un|une|le|la)\s+(?:[a-z0-9à-ÿ][a-z0-9à-ÿ_\-]*\s+){0,4}(protocole|standard|framework|biblioth[eè]que|langage|concept|m[eé]thode|outil|mod[eè]le)\b|"
    r"fait r[eé]f[eé]rence [aà]\b|d[eé]signe\b"
    r")",
    flags=re.IGNORECASE,
)
_DEFINITION_STYLE_PATTERN = re.compile(
    r"\b("
    r"(?:the user|l'utilisateur)\b[^.!?\n]{0,80}\b(?:is|est)\s+(?:an?|the|un|une|le|la)\s+[^.!?\n]{0,80}\b("
    r"language|protocol|framework|library|standard|concept|method|tool|model|stack|"
    r"langage|protocole|framework|biblioth[eè]que|standard|concept|m[eé]thode|outil|mod[eè]le"
    r")\b|"
    r"(?:the user|l'utilisateur)\b[^.!?\n]{0,80}\b(?:means|refers to|defined as|d[eé]signe|fait r[eé]f[eé]rence [aà])\b"
    r")",
    flags=re.IGNORECASE,
)
_DURABLE_MEMORY_PATTERN = re.compile(
    r"\b("
    r"prefers|likes|loves|hates|always|never|uses|works on|working on|building|goal|plans|"
    r"name is|is from|lives in|role|job|team|relationship|project|stack|"
    r"pr[eé]f[eè]re|aime|d[eé]teste|utilise|travaille sur|d[eé]veloppe|objectif|projet|"
    r"nom est|habite|r[oô]le|m[eé]tier|[eé]quipe|relation"
    r")\b",
    flags=re.IGNORECASE,
)
_QUESTION_STYLE_PATTERN = re.compile(
    r"\b("
    r"asks?|asked|wants to know|is asking|question|"
    r"demande|a demand[eé]|veut savoir|question"
    r")\b",
    flags=re.IGNORECASE,
)
_VAGUE_CAPABILITY_PATTERN = re.compile(
    r"^\s*(?:the user|l'utilisateur)\s+(?:can|could|may|might|peut)\b",
    flags=re.IGNORECASE,
)
_WEAK_QUALIFIER_PATTERN = re.compile(
    r"\b("
    r"if needed|if necessary|if required|si besoin|au besoin|"
    r"more elaborate|more complex|more advanced|"
    r"additional requests?"
    r")\b",
    flags=re.IGNORECASE,
)


def _looks_generic_non_memory(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return True
    lowered = value.lower()
    has_anchor = bool(_USER_ANCHOR_PATTERN.search(value))
    if not has_anchor:
        return True
    if _QUESTION_STYLE_PATTERN.search(lowered):
        return True
    if _VAGUE_CAPABILITY_PATTERN.search(lowered) and _WEAK_QUALIFIER_PATTERN.search(lowered):
        return True
    if _DEFINITION_STYLE_PATTERN.search(lowered) and not _DURABLE_MEMORY_PATTERN.search(lowered):
        return True
    if _GENERIC_FACT_PATTERN.search(lowered) and not _DURABLE_MEMORY_PATTERN.search(lowered):
        return True
    return False


def _is_auto_memory_source(source_llm: str, tags: list[str]) -> bool:
    source = str(source_llm or "").strip().lower()
    if source.startswith("conversation-analyzer:"):
        return True
    lowered_tags = {str(t or "").strip().lower() for t in (tags or [])}
    return _AUTO_ANALYSIS_TAG in lowered_tags


def _append_memory_event(
    db,
    *,
    event_type: str,
    source: str,
    memory_id: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
    created_at: Optional[datetime] = None,
) -> None:
    try:
        if "memory_events" not in db.table_names():
            return
        tbl = db.open_table("memory_events")
        stamp = created_at if isinstance(created_at, datetime) else datetime.now(timezone.utc)
        payload = {
            "id": str(uuid.uuid4()),
            "memory_id": str(memory_id or "").strip() or None,
            "event_type": str(event_type or "").strip()[:80] or "unknown",
            "source": str(source or "").strip()[:120] or "system",
            "details_json": json.dumps(details or {}, ensure_ascii=False, sort_keys=True)[:5000],
            "created_at": stamp,
        }
        tbl.add([payload])
    except Exception:
        # Event logging is best effort and must not block primary writes.
        return


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_tokens(text: str) -> int:
    if get_status() != "ready":
        return max(1, math.ceil(len(text) / 4))
    try:
        model = get_model()
        return len(model.tokenizer.encode(text))
    except Exception as e:
        logger.warning(f"Tokenizer unavailable; using approximate token count: {e}")
        # Conservative approximation when the model tokenizer is unavailable.
        return max(1, math.ceil(len(text) / 4))


def _is_first_person(text: str) -> bool:
    text_padded = f" {text} "
    return (
        " I " in text_padded
        or text.startswith("I ")
        or text.lower().startswith("i'm ")
        or text.lower().startswith("i am ")
    )


def _to_utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return _to_utc(parsed)
        except Exception:
            pass
    return datetime.now(timezone.utc)


def _normalize_optional_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    dt = _to_utc(value)
    # In imported datasets, 1970 timestamps usually represent missing values.
    if dt.year <= 1971:
        return None
    return dt


def _escape_sql(value: str) -> str:
    return value.replace("'", "''")


def _table_columns(tbl) -> set[str]:
    try:
        schema = getattr(tbl, "schema", None)
        names = getattr(schema, "names", None)
        if names:
            return {str(name) for name in names}
    except Exception:
        pass

    # Fallback for environments where schema introspection is unavailable.
    try:
        sample = tbl.search().limit(1).to_list()
        if sample and isinstance(sample[0], dict):
            return {str(k) for k in sample[0].keys()}
    except Exception:
        pass
    return set()


def _filter_values_for_columns(tbl, values: dict[str, Any]) -> dict[str, Any]:
    cols = _table_columns(tbl)
    if not cols:
        # If schema introspection is unavailable, default to legacy-safe memory columns.
        return {k: v for k, v in values.items() if k in _LEGACY_MEMORY_BASE_COLUMNS}
    return {k: v for k, v in values.items() if k in cols}


async def _log_context_route(query: str, domain: str, scores: dict[str, float]):
    if not query:
        return

    async def _write_op():
        db = get_db()
        tbl = db.open_table("context_route_logs")
        now = datetime.now(timezone.utc)
        tbl.add(
            [
                ContextRouteLog(
                    id=str(uuid.uuid4()),
                    query_preview=query[:240],
                    detected_domain=domain,
                    scores_json=json.dumps(scores),
                    created_at=now,
                )
            ]
        )

    try:
        await enqueue_write(_write_op)
    except Exception as e:
        logger.warning(f"Failed to log context routing event: {e}")


def _coerce_resolution(value: str) -> str:
    mapping = {
        "kept_a": "discarded_candidate",
        "kept_b": "overwritten",
        "merged": "merged",
        "both_valid": "versioned",
        "versioned": "versioned",
        "overwrite": "overwritten",
        "overwritten": "overwritten",
    }
    return mapping.get(value, value)


def _embed_with_fallback(text: str) -> list[float]:
    if get_status() != "ready":
        return [0.0] * EMBEDDING_DIM
    try:
        return embed(text)
    except Exception as e:
        logger.warning(f"Embedding unavailable; using zero-vector fallback: {e}")
        return [0.0] * EMBEDDING_DIM


# ---------------------------------------------------------------------------
# create_memory
# ---------------------------------------------------------------------------

async def create_memory(
    content: str,
    category: str,
    level: str,
    source_llm: str,
    importance_score: float = 0.5,
    confidence_score: float = 0.7,
    privacy: str = "public",
    tags: Optional[list[str]] = None,
    source_conversation_id: Optional[str] = None,
    suggestion_reason: Optional[str] = None,
    session_id: Optional[str] = None,
    bypass_conflict_detection: bool = False,
    bypass_deduplication: bool = False,
    forced_status: Optional[str] = None,
    created_at: Optional[Any] = None,
    event_date: Optional[Any] = None,
    source_message_id: Optional[str] = None,
    source_excerpt: Optional[str] = None,
) -> dict:
    tags = tags or []
    content = content.strip()

    if _is_auto_memory_source(source_llm, tags) and _looks_generic_non_memory(content):
        return {
            "id": None,
            "status": "error",
            "action": "rejected_non_personal",
            "message": "Candidate is generic or not user-specific enough to be a memory.",
        }

    if len(content) < 20:
        return {
            "id": None,
            "status": "error",
            "action": "rejected_length",
            "message": f"Content too short ({len(content)} chars). Minimum is 20.",
        }

    if len(content) > 1000:
        return {
            "id": None,
            "status": "error",
            "action": "rejected_length",
            "message": f"Content too long ({len(content)} chars). Maximum is 1000. Split into multiple memories.",
        }

    token_count = _count_tokens(content)
    if token_count > 128:
        return {
            "id": None,
            "status": "error",
            "action": "rejected_tokens",
            "message": f"Content exceeds 128 tokens ({token_count}). Split into multiple memories.",
        }

    if _is_first_person(content):
        return {
            "id": None,
            "status": "error",
            "action": "rejected_first_person",
            "message": "Write memories in third-person declarative format (e.g. 'Thomas prefers...').",
        }

    initial_status = forced_status or "active"
    if not forced_status and level == "semantic" and confidence_score < 0.85:
        initial_status = "pending_review"

    now = datetime.now(timezone.utc)
    source_created_at = _normalize_optional_datetime(created_at) or now
    source_event_date = _normalize_optional_datetime(event_date)
    decay_values = infer_decay_profile(
        content=content,
        category=category,
        level=level,
        now=source_created_at if created_at is not None else now,
    )
    if source_event_date is not None:
        decay_values["event_date"] = source_event_date
        if decay_values.get("decay_profile") == "event-based":
            decay_values["expires_at"] = source_event_date + timedelta(days=1)

    async def _write_op():
        db = get_db()
        tbl = db.open_table("memories")

        vector = _embed_with_fallback(content)

        content_hash = hashlib.sha256(content.lower().encode()).hexdigest()
        existing_all = tbl.search(vector).where("status = 'active' OR status = 'pending_review'").limit(80).to_list()

        if not bypass_deduplication:
            for match in existing_all:
                existing_hash = hashlib.sha256(match["content"].lower().strip().encode()).hexdigest()
                if existing_hash == content_hash:
                    logger.info(f"Exact duplicate found: {match['id']}")
                    _append_memory_event(
                        db,
                        event_type="dedupe_skipped",
                        source=source_llm,
                        memory_id=str(match.get("id") or ""),
                        details={
                            "category": category,
                            "level": level,
                            "reason": "exact_hash",
                        },
                        created_at=now,
                    )
                    return {"id": match["id"], "status": "active", "action": "skipped"}

            # Semantic deduplication across active + pending suggestions.
            for match in existing_all:
                score = 1 - match["_distance"]
                if score > 0.9:
                    new_importance = max(match["importance_score"], importance_score)
                    tbl.update(
                        where=f"id = '{_escape_sql(match['id'])}'",
                        values=_filter_values_for_columns(
                            tbl,
                            {
                                "importance_score": new_importance,
                                "last_referenced_at": now,
                                "updated_at": now,
                                "suggestion_reason": (
                                    str(suggestion_reason or "").strip()[:420]
                                    or str(match.get("suggestion_reason") or "")
                                ),
                            },
                        ),
                    )
                    _append_memory_event(
                        db,
                        event_type="dedupe_merged",
                        source=source_llm,
                        memory_id=str(match.get("id") or ""),
                        details={
                            "category": category,
                            "level": level,
                            "similarity": round(float(score), 4),
                        },
                        created_at=now,
                    )
                    return {"id": match["id"], "status": match["status"], "action": "merged"}

        # Conflict detection (>0.85 in same category + contradiction).
        if not bypass_conflict_detection:
            best_conflict = None
            for match in existing_all:
                if match.get("category") != category:
                    continue
                score = 1 - match["_distance"]
                if score <= 0.85:
                    continue
                if is_semantic_contradiction(match.get("content", ""), content):
                    if not best_conflict or score > best_conflict["similarity_score"]:
                        best_conflict = {
                            "memory_id_existing": match["id"],
                            "similarity_score": score,
                        }

            if best_conflict:
                pending_tbl = db.open_table("pending_conflicts")
                conflict = PendingConflict(
                    id=str(uuid.uuid4()),
                    memory_id_existing=best_conflict["memory_id_existing"],
                    candidate_content=content,
                    candidate_level=level,
                    candidate_category=category,
                    candidate_source_llm=source_llm,
                    similarity_score=best_conflict["similarity_score"],
                    detected_at=now,
                    resolved_at=None,
                    resolution=None,
                    status="pending",
                    candidate_memory_id=None,
                )
                pending_tbl.add([conflict])
                _append_memory_event(
                    db,
                    event_type="conflict_pending",
                    source=source_llm,
                    memory_id=str(best_conflict.get("memory_id_existing") or ""),
                    details={
                        "candidate_level": level,
                        "candidate_category": category,
                        "similarity_score": float(best_conflict.get("similarity_score") or 0.0),
                        "conflict_id": conflict.id,
                    },
                    created_at=now,
                )
                return {
                    "id": None,
                    "status": "pending_conflict",
                    "action": "conflict_pending",
                    "conflict_id": conflict.id,
                }

        memory_id = str(uuid.uuid4())
        memory_payload = {
            "id": memory_id,
            "content": content,
            "level": level,
            "category": category,
            "importance_score": importance_score,
            "confidence_score": confidence_score,
            "privacy": privacy,
            "tags": tags,
            "source_llm": source_llm,
            "source_conversation_id": source_conversation_id,
            "source_message_id": str(source_message_id or "").strip() or None,
            "source_excerpt": str(source_excerpt or "").strip()[:320] or None,
            "version": 1,
            "status": initial_status,
            "created_at": source_created_at,
            "updated_at": now,
            "last_referenced_at": source_created_at,
            "reference_count": 0,
            "decay_profile": decay_values["decay_profile"],
            "expires_at": decay_values["expires_at"],
            "needs_review": decay_values["needs_review"],
            "review_due_at": decay_values["review_due_at"],
            "event_date": decay_values["event_date"],
            "suggestion_reason": str(suggestion_reason or "").strip()[:420],
            "review_note": "",
            "vector": vector,
        }
        add_payload = _filter_values_for_columns(tbl, memory_payload)
        try:
            tbl.add([add_payload])
        except Exception as e:
            # Extra safety for legacy schemas if column discovery fails in some runtimes.
            if "not found in target schema" in str(e).lower():
                add_payload = {k: v for k, v in memory_payload.items() if k in _LEGACY_MEMORY_BASE_COLUMNS}
                tbl.add([add_payload])
            else:
                raise

        # Knowledge graph sync (best effort): nodes + inferred typed edges.
        try:
            update_graph_on_memory_create(add_payload, existing_all, db=db)
        except Exception as e:
            logger.warning(f"Graph sync on create failed for {memory_id}: {e}")

        _append_memory_event(
            db,
            event_type="write",
            source=source_llm,
            memory_id=memory_id,
            details={
                "status": initial_status,
                "category": category,
                "level": level,
                "source_conversation_id": source_conversation_id or "",
                "source_message_id": str(source_message_id or "").strip(),
                "confidence_score": float(confidence_score),
            },
            created_at=source_created_at,
        )

        return {"id": memory_id, "status": initial_status, "action": "created"}

    result = await enqueue_write(_write_op)

    if session_id and result.get("id") and result.get("action") not in ("skipped", "conflict_pending", "error"):
        try:
            from backend.memory.sessions import update_session_activity

            await update_session_activity(session_id, write_ids=[result["id"]])
        except Exception as e:
            logger.warning(f"Failed to update session activity: {e}")

    return result


# ---------------------------------------------------------------------------
# search_memories
# ---------------------------------------------------------------------------

async def search_memories(
    query: str,
    limit: int = 5,
    context: Optional[str] = None,
    session_id: Optional[str] = None,
) -> list[dict]:
    db = get_db()
    tbl = db.open_table("memories")

    now = datetime.now(timezone.utc)
    try:
        query_vector = embed(query)
        results = tbl.search(query_vector).where("status = 'active'").limit(limit * 3).to_list()
    except Exception as e:
        logger.warning(f"Vector search unavailable; falling back to lexical ranking: {e}")
        pool = tbl.search().where("status = 'active'").limit(max(60, limit * 12)).to_list()
        q_words = [w for w in query.lower().split() if w]
        scored = []
        for row in pool:
            text = str(row.get("content") or "").lower()
            if not text:
                continue
            matches = sum(1 for w in q_words if w in text)
            if matches > 0:
                row_copy = dict(row)
                row_copy["_distance"] = max(0.0, 1.0 - min(1.0, matches / max(1, len(q_words))))
                scored.append((matches, row_copy))
        scored.sort(key=lambda x: x[0], reverse=True)
        results = [s[1] for s in scored[: limit * 3]]

    reranked = []
    for r in results:
        similarity = max(0.0, 1 - r["_distance"])
        importance = r.get("importance_score", 0.5)

        last_ref = _to_utc(r.get("last_referenced_at", now))
        days_since = (now - last_ref).total_seconds() / 86400
        recency = math.exp(-0.05 * days_since)

        final_score = (0.5 * similarity) + (0.3 * importance) + (0.2 * recency)
        if context and r.get("tags"):
            if context.lower() in [t.lower() for t in r["tags"]]:
                final_score *= 1.3
        reranked.append((final_score, r))

    reranked.sort(key=lambda x: x[0], reverse=True)
    top_results = [x[1] for x in reranked[:limit]]

    clean_results = [{k: v for k, v in r.items() if k not in ("vector", "_distance")} for r in top_results]

    if top_results:
        async def _touch_refs():
            tbl_update = get_db().open_table("memories")
            for r in top_results:
                try:
                    tbl_update.update(
                        where=f"id = '{_escape_sql(r['id'])}'",
                        values={
                            "last_referenced_at": now,
                            "reference_count": r.get("reference_count", 0) + 1,
                        },
                    )
                except Exception:
                    pass

        await enqueue_write(_touch_refs)

    if session_id and top_results:
        try:
            from backend.memory.sessions import update_session_activity

            await update_session_activity(session_id, read_ids=[r["id"] for r in top_results])
        except Exception as e:
            logger.warning(f"Failed to update session read activity: {e}")

    return clean_results


# ---------------------------------------------------------------------------
# get_snapshot
# ---------------------------------------------------------------------------

async def get_snapshot(context: Optional[str] = None, query: Optional[str] = None) -> str:
    db = get_db()
    tbl = db.open_table("memories")

    detected_domain = "casual"
    domain_scores: dict[str, float] = {}

    if query:
        detected_domain, domain_scores = classify_query_domain(query)
    elif context == "development":
        detected_domain = "code"
    elif context == "business":
        detected_domain = "business"
    elif context == "personal":
        detected_domain = "personal"
    elif context == "casual":
        detected_domain = "casual"
    else:
        # Backward-compatible default when no routing hint is given.
        detected_domain = "default"

    section_order = (
        categories_for_domain(detected_domain)
        if detected_domain in ("code", "business", "personal", "casual")
        else ["identity", "preferences", "projects", "relationships", "skills"]
    )

    section_config = {
        "identity": ("## Identity", 3),
        "preferences": ("## Preferences & Working Style", 5),
        "projects": ("## Active Projects", 8),
        "relationships": ("## Key Relationships", 5),
        "skills": ("## Skills & Expertise", 5),
        "history": ("## Relevant History", 5),
        "working": ("## Working Memory", 6),
    }

    def fetch_category(cat: str, limit: int) -> list[dict]:
        try:
            where_clause = f"category = '{_escape_sql(cat)}' AND status = 'active'"
            results = tbl.search().where(where_clause).limit(limit + 5).to_list()
            results.sort(key=lambda x: x.get("importance_score", 0.0), reverse=True)
            return results[:limit]
        except Exception:
            return []

    now = datetime.now(timezone.utc)
    snapshot_sections = [f"# Memory Context — {now.isoformat()}"]
    if detected_domain != "default":
        snapshot_sections.append(f"_Detected domain: {detected_domain}_")

    for cat in section_order:
        header, limit = section_config.get(cat, (f"## {cat.title()}", 5))
        rows = fetch_category(cat, limit)
        if rows:
            lines = [f"- {row['content']}" for row in rows]
            snapshot_sections.append(f"{header}\n" + "\n".join(lines))

    try:
        working = tbl.search().where("level = 'working' AND status = 'active'").limit(20).to_list()
        working.sort(key=lambda x: _to_utc(x.get("created_at", now)), reverse=True)
    except Exception:
        working = []

    if working:
        lines = [f"- {r['content']}" for r in working[:10]]
        snapshot_sections.append("## Recent Context\n" + "\n".join(lines))

    if query and detected_domain in ("code", "business", "personal", "casual"):
        await _log_context_route(query, detected_domain, domain_scores)

    return "\n\n".join(snapshot_sections)


# ---------------------------------------------------------------------------
# update_memory
# ---------------------------------------------------------------------------

async def update_memory(memory_id: str, content: str, source_llm: str, session_id: Optional[str] = None) -> dict:
    content = content.strip()
    if len(content) < 20:
        return {"id": memory_id, "status": "error", "action": "rejected_length"}

    async def _write_op():
        db = get_db()
        tbl = db.open_table("memories")

        matches = tbl.search().where(f"id = '{_escape_sql(memory_id)}'").limit(1).to_list()
        if not matches:
            return {"id": memory_id, "status": "error", "action": "not_found"}

        current_mem = matches[0]
        version_tbl = db.open_table("memory_versions")
        from backend.database.schema import MemoryVersion

        version_record = MemoryVersion(
            id=str(uuid.uuid4()),
            memory_id=memory_id,
            content=current_mem["content"],
            version=current_mem["version"],
            changed_by=source_llm,
            created_at=current_mem["updated_at"],
        )
        try:
            version_tbl.add([version_record])
        except Exception as e:
            logger.error(f"Failed to archive version: {e}")

        now = datetime.now(timezone.utc)
        vector = _embed_with_fallback(content)
        new_version = current_mem["version"] + 1
        decay_values = infer_decay_profile(
            content=content,
            category=current_mem["category"],
            level=current_mem["level"],
            now=now,
        )

        update_values = _filter_values_for_columns(
            tbl,
            {
                "content": content,
                "vector": vector,
                "updated_at": now,
                "version": new_version,
                "importance_score": max(current_mem["importance_score"], 0.6),
                "last_referenced_at": now,
                "decay_profile": decay_values["decay_profile"],
                "expires_at": decay_values["expires_at"],
                "needs_review": decay_values["needs_review"],
                "review_due_at": decay_values["review_due_at"],
                "event_date": decay_values["event_date"],
            },
        )
        try:
            tbl.update(
                where=f"id = '{_escape_sql(memory_id)}'",
                values=update_values,
            )
        except Exception as e:
            if "not found in target schema" in str(e).lower():
                fallback_values = {
                    k: v
                    for k, v in {
                        "content": content,
                        "vector": vector,
                        "updated_at": now,
                        "version": new_version,
                        "importance_score": max(current_mem["importance_score"], 0.6),
                        "last_referenced_at": now,
                    }.items()
                    if k in _LEGACY_MEMORY_BASE_COLUMNS
                }
                tbl.update(
                    where=f"id = '{_escape_sql(memory_id)}'",
                    values=fallback_values,
                )
            else:
                raise
        try:
            sync_memory_node(memory_id, content)
        except Exception as e:
            logger.warning(f"Graph node sync on update failed for {memory_id}: {e}")
        _append_memory_event(
            db,
            event_type="update",
            source=source_llm,
            memory_id=memory_id,
            details={
                "version": int(new_version),
                "category": str(current_mem.get("category") or ""),
                "level": str(current_mem.get("level") or ""),
            },
            created_at=now,
        )
        return {"id": memory_id, "status": "active", "action": "updated", "version": new_version}

    result = await enqueue_write(_write_op)

    if session_id and result.get("action") == "updated":
        try:
            from backend.memory.sessions import update_session_activity

            await update_session_activity(session_id, write_ids=[memory_id])
        except Exception as e:
            logger.warning(f"Failed to update session activity: {e}")

    return result


# ---------------------------------------------------------------------------
# delete_memory (soft)
# ---------------------------------------------------------------------------

async def delete_memory(memory_id: str) -> dict:
    async def _write_op():
        db = get_db()
        tbl = db.open_table("memories")
        now = datetime.now(timezone.utc)
        tbl.update(
            where=f"id = '{_escape_sql(memory_id)}'",
            values={"status": "archived", "updated_at": now},
        )
        _append_memory_event(
            db,
            event_type="archive",
            source="manual",
            memory_id=memory_id,
            details={"reason": "delete_memory"},
            created_at=now,
        )

        # Cascade: remove dangling graph edges, pending conflicts
        try:
            from backend.memory.graph_layer import delete_memory_graph_edges
            await delete_memory_graph_edges(memory_id, db=db)
        except Exception as e:
            logger.warning(f"Cascade graph edge cleanup failed for {memory_id}: {e}")

        for table_name, column in [
            ("pending_conflicts", "memory_id"),
        ]:
            try:
                if table_name in db.table_names():
                    db.open_table(table_name).delete(f"{column} = '{_escape_sql(memory_id)}'")
            except Exception as e:
                logger.warning(f"Cascade cleanup of {table_name} failed for {memory_id}: {e}")

        return {"id": memory_id, "status": "archived", "action": "deleted"}

    return await enqueue_write(_write_op)


_VALID_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "pending_review": {"active", "rejected", "archived"},
    "active": {"rejected", "archived", "pending_review"},
    "rejected": {"active", "archived", "pending_review"},
    "archived": set(),  # archived is terminal — cannot be resurrected
}


async def set_memory_status(
    memory_id: str,
    status: str,
    source_llm: str = "manual",
    review_note: Optional[str] = None,
) -> dict:
    normalized_status = str(status or "").strip().lower()
    if normalized_status not in {"active", "pending_review", "rejected", "archived"}:
        return {"id": memory_id, "status": "error", "action": "invalid_status"}

    async def _write_op():
        db = get_db()
        if "memories" not in db.table_names():
            return {"id": memory_id, "status": "error", "action": "not_found"}
        tbl = db.open_table("memories")
        rows = tbl.search().where(f"id = '{_escape_sql(memory_id)}'").limit(1).to_list()
        if not rows:
            return {"id": memory_id, "status": "error", "action": "not_found"}

        current = rows[0]
        current_status = str(current.get("status") or "").strip().lower()
        if current_status == normalized_status:
            return {"id": memory_id, "status": current_status, "action": "unchanged"}

        allowed = _VALID_STATUS_TRANSITIONS.get(current_status, set())
        if normalized_status not in allowed:
            return {
                "id": memory_id,
                "status": "error",
                "action": "invalid_transition",
                "message": f"Cannot transition from '{current_status}' to '{normalized_status}'",
            }

        now = datetime.now(timezone.utc)
        values: dict = {
            "status": normalized_status,
            "updated_at": now,
        }
        note_raw = str(review_note or "").strip()
        if note_raw:
            values["review_note"] = note_raw[:420]
        elif normalized_status in {"active", "rejected"}:
            values["review_note"] = f"{normalized_status} by {source_llm}"[:420]

        if normalized_status == "pending_review":
            values["needs_review"] = True
            if not current.get("review_due_at"):
                values["review_due_at"] = now
        else:
            values["needs_review"] = False
            values["review_due_at"] = None

        safe_values = _filter_values_for_columns(tbl, values)
        tbl.update(where=f"id = '{_escape_sql(memory_id)}'", values=safe_values)
        _append_memory_event(
            db,
            event_type="status_change",
            source=source_llm,
            memory_id=memory_id,
            details={
                "from_status": current_status,
                "to_status": normalized_status,
                "review_note": str(values.get("review_note") or ""),
            },
            created_at=now,
        )

        # Status transitions are tracked as lightweight edits in versions.
        try:
            version_tbl = db.open_table("memory_versions")
            from backend.database.schema import MemoryVersion

            version_record = MemoryVersion(
                id=str(uuid.uuid4()),
                memory_id=memory_id,
                content=current["content"],
                version=int(current.get("version") or 1),
                changed_by=source_llm,
                created_at=now,
            )
            version_tbl.add([version_record])
        except Exception as e:
            logger.warning(f"Failed to persist status change version for {memory_id}: {e}")

        return {"id": memory_id, "status": normalized_status, "action": "status_updated"}

    return await enqueue_write(_write_op)


async def set_memory_status_bulk(
    memory_ids: list[str],
    status: str,
    source_llm: str = "manual",
    review_note: Optional[str] = None,
) -> dict:
    normalized_status = str(status or "").strip().lower()
    if normalized_status not in {"active", "pending_review", "rejected", "archived"}:
        return {"status": "error", "action": "invalid_status"}

    ids: list[str] = []
    seen: set[str] = set()
    for raw in memory_ids or []:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        ids.append(value)

    if not ids:
        return {"status": "error", "action": "empty_ids"}
    if len(ids) > 500:
        return {"status": "error", "action": "too_many_ids", "message": "Maximum 500 ids per bulk request."}

    async def _write_op():
        db = get_db()
        if "memories" not in db.table_names():
            return {
                "status": "error",
                "action": "not_found",
                "updated": 0,
                "unchanged": 0,
                "not_found": ids,
                "updated_ids": [],
            }
        tbl = db.open_table("memories")
        version_tbl = db.open_table("memory_versions")
        now = datetime.now(timezone.utc)
        note_raw = str(review_note or "").strip()

        updated = 0
        unchanged = 0
        not_found: list[str] = []
        updated_ids: list[str] = []

        from backend.database.schema import MemoryVersion

        for memory_id in ids:
            escaped = _escape_sql(memory_id)
            rows = tbl.search().where(f"id = '{escaped}'").limit(1).to_list()
            if not rows:
                not_found.append(memory_id)
                continue

            current = rows[0]
            current_status = str(current.get("status") or "").strip().lower()
            if current_status == normalized_status:
                unchanged += 1
                continue

            values: dict[str, Any] = {
                "status": normalized_status,
                "updated_at": now,
            }
            if normalized_status == "pending_review":
                values["needs_review"] = True
                if not current.get("review_due_at"):
                    values["review_due_at"] = now
            else:
                values["needs_review"] = False
                values["review_due_at"] = None

            if note_raw:
                values["review_note"] = note_raw[:420]
            elif normalized_status in {"active", "rejected"}:
                values["review_note"] = f"{normalized_status} by {source_llm}"[:420]

            safe_values = _filter_values_for_columns(tbl, values)
            tbl.update(where=f"id = '{escaped}'", values=safe_values)
            _append_memory_event(
                db,
                event_type="status_change",
                source=source_llm,
                memory_id=memory_id,
                details={
                    "from_status": current_status,
                    "to_status": normalized_status,
                    "bulk": True,
                    "review_note": str(values.get("review_note") or ""),
                },
                created_at=now,
            )
            updated += 1
            updated_ids.append(memory_id)

            try:
                version_record = MemoryVersion(
                    id=str(uuid.uuid4()),
                    memory_id=memory_id,
                    content=current["content"],
                    version=int(current.get("version") or 1),
                    changed_by=source_llm,
                    created_at=now,
                )
                version_tbl.add([version_record])
            except Exception as e:
                logger.warning(f"Failed to persist status change version for {memory_id}: {e}")

        return {
            "status": "ok",
            "action": "bulk_status_updated",
            "target_status": normalized_status,
            "updated": updated,
            "unchanged": unchanged,
            "not_found": not_found,
            "updated_ids": updated_ids,
        }

    return await enqueue_write(_write_op)


# ---------------------------------------------------------------------------
# process_feedback
# ---------------------------------------------------------------------------

async def process_feedback(used_memory_ids: list[str], session_id: Optional[str] = None) -> dict:
    if session_id:
        try:
            from backend.memory.sessions import end_session, update_session_activity

            await update_session_activity(session_id, feedback_ids=used_memory_ids)
            await end_session(session_id, reason="feedback_called")
        except Exception as e:
            logger.warning(f"Session feedback update failed: {e}")

    async def _write_op():
        db = get_db()
        tbl = db.open_table("memories")
        now = datetime.now(timezone.utc)
        updated_count = 0

        for mem_id in used_memory_ids:
            try:
                matches = tbl.search().where(f"id = '{_escape_sql(mem_id)}'").limit(1).to_list()
                if not matches:
                    continue
                mem = matches[0]
                new_score = min(1.0, mem.get("importance_score", 0.5) + 0.05)
                tbl.update(
                    where=f"id = '{_escape_sql(mem_id)}'",
                    values={
                        "importance_score": new_score,
                        "reference_count": mem.get("reference_count", 0) + 1,
                        "last_referenced_at": now,
                    },
                )
                _append_memory_event(
                    db,
                    event_type="use_feedback",
                    source="feedback",
                    memory_id=mem_id,
                    details={
                        "importance_score": float(new_score),
                        "reference_count": int(mem.get("reference_count", 0) + 1),
                    },
                    created_at=now,
                )
                updated_count += 1
            except Exception as e:
                logger.error(f"Failed to update feedback for {mem_id}: {e}")

        return {
            "status": "success",
            "updated_count": updated_count,
            "message": "Feedback processed",
        }

    return await enqueue_write(_write_op)


# ---------------------------------------------------------------------------
# Pending Conflicts
# ---------------------------------------------------------------------------

async def list_pending_conflicts(limit: int = 100) -> list[dict]:
    db = get_db()
    if "pending_conflicts" not in db.table_names():
        return []

    pending_tbl = db.open_table("pending_conflicts")
    memory_tbl = db.open_table("memories")

    pending = pending_tbl.search().where("status = 'pending'").limit(limit).to_list()
    pending.sort(key=lambda x: _to_utc(x.get("detected_at")), reverse=True)
    enriched = []
    for conflict in pending:
        try:
            existing = (
                memory_tbl.search()
                .where(f"id = '{_escape_sql(conflict['memory_id_existing'])}'")
                .limit(1)
                .to_list()
            )
            if not existing:
                continue
            enriched.append(
                {
                    **conflict,
                    "memory_a": existing[0],
                    "memory_b": {
                        "content": conflict["candidate_content"],
                        "category": conflict["candidate_category"],
                        "level": conflict["candidate_level"],
                        "source_llm": conflict["candidate_source_llm"],
                        "created_at": conflict["detected_at"],
                    },
                }
            )
        except Exception:
            continue
    return enriched


async def count_pending_conflicts(limit: int = 200000) -> int:
    db = get_db()
    if "pending_conflicts" not in db.table_names():
        return 0

    safe_limit = max(1, min(int(limit), 500000))
    pending_tbl = db.open_table("pending_conflicts")
    rows = pending_tbl.search().where("status = 'pending'").limit(safe_limit).to_list()
    return len(rows)


async def resolve_pending_conflict(
    conflict_id: str,
    resolution: str,
    merged_content: Optional[str] = None,
    resolver_source: str = "manual",
) -> dict:
    db = get_db()
    if "pending_conflicts" not in db.table_names():
        return {"status": "error", "message": "pending_conflicts table not available"}

    pending_tbl = db.open_table("pending_conflicts")
    rows = pending_tbl.search().where(f"id = '{_escape_sql(conflict_id)}'").limit(1).to_list()
    if not rows:
        return {"status": "error", "message": "Conflict not found"}

    conflict = rows[0]
    normalized = _coerce_resolution(resolution)
    now = datetime.now(timezone.utc)
    candidate_memory_id = None

    if normalized == "merged":
        if not merged_content:
            return {"status": "error", "message": "Merged content is required"}
        await update_memory(conflict["memory_id_existing"], merged_content, resolver_source)
    elif normalized == "overwritten":
        await update_memory(conflict["memory_id_existing"], conflict["candidate_content"], resolver_source)
    elif normalized == "versioned":
        created = await create_memory(
            content=conflict["candidate_content"],
            category=conflict["candidate_category"],
            level=conflict["candidate_level"],
            source_llm=conflict["candidate_source_llm"],
            confidence_score=0.8,
            bypass_conflict_detection=True,
            bypass_deduplication=True,
            tags=["conflict-versioned"],
        )
        candidate_memory_id = created.get("id")
    elif normalized == "discarded_candidate":
        pass
    else:
        return {"status": "error", "message": f"Unknown resolution: {resolution}"}

    async def _write_op():
        pending_tbl.update(
            where=f"id = '{_escape_sql(conflict_id)}'",
            values={
                "status": "resolved",
                "resolution": normalized,
                "resolved_at": now,
                "candidate_memory_id": candidate_memory_id,
            },
        )
        return {"status": "resolved", "resolution": normalized}

    return await enqueue_write(_write_op)


async def archive_stale_pending_conflicts(max_age_days: int = 7) -> int:
    db = get_db()
    if "pending_conflicts" not in db.table_names():
        return 0

    tbl = db.open_table("pending_conflicts")
    pending = tbl.search().where("status = 'pending'").limit(10000).to_list()
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    stale = [c for c in pending if _to_utc(c.get("detected_at")) <= cutoff]
    if not stale:
        return 0

    async def _write_op():
        now = datetime.now(timezone.utc)
        count = 0
        for conflict in stale:
            tbl.update(
                where=f"id = '{_escape_sql(conflict['id'])}'",
                values={
                    "status": "archived",
                    "resolution": "auto_archived",
                    "resolved_at": now,
                },
            )
            count += 1
        return count

    return await enqueue_write(_write_op)


async def apply_temporal_decay_and_reviews() -> dict:
    db = get_db()
    tbl = db.open_table("memories")
    now = datetime.now(timezone.utc)
    rows = tbl.search().where("status = 'active'").limit(100000).to_list()
    cols = _table_columns(tbl)
    has_expires = "expires_at" in cols
    has_decay_profile = "decay_profile" in cols
    has_needs_review = "needs_review" in cols
    has_review_due_at = "review_due_at" in cols

    async def _write_op():
        expired = 0
        reviewed = 0
        for mem in rows:
            mem_id = mem.get("id")
            if not mem_id:
                continue
            expires_at = mem.get("expires_at") if has_expires else None
            if expires_at and _to_utc(expires_at) <= now:
                tbl.update(
                    where=f"id = '{_escape_sql(mem_id)}'",
                    values=_filter_values_for_columns(
                        tbl,
                        {"status": "archived", "updated_at": now},
                    ),
                )
                _append_memory_event(
                    db,
                    event_type="decay_archive",
                    source="scheduler",
                    memory_id=str(mem_id),
                    details={"expires_at": str(expires_at)},
                    created_at=now,
                )
                expired += 1
                continue

            if has_decay_profile and has_needs_review and has_review_due_at and mem.get("decay_profile") == "semi-stable":
                review_due_at = mem.get("review_due_at")
                if review_due_at and _to_utc(review_due_at) <= now:
                    tbl.update(
                        where=f"id = '{_escape_sql(mem_id)}'",
                        values=_filter_values_for_columns(
                            tbl,
                            {
                                "needs_review": True,
                                "review_due_at": now + timedelta(days=60),
                                "updated_at": now,
                            },
                        ),
                    )
                    _append_memory_event(
                        db,
                        event_type="review_flagged",
                        source="scheduler",
                        memory_id=str(mem_id),
                        details={"next_review_due_at": str(now + timedelta(days=60))},
                        created_at=now,
                    )
                    reviewed += 1
        return {"expired": expired, "reviewed": reviewed}

    return await enqueue_write(_write_op)
