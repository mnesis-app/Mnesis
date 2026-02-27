from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from backend.database.client import get_db
from backend.memory.embedder import embed, get_status

router = APIRouter(prefix="/api/v1/search", tags=["search"])

_SOURCE_ALIASES: dict[str, set[str]] = {
    "openai": {"openai", "chatgpt", "gpt"},
    "chatgpt": {"openai", "chatgpt", "gpt"},
    "anthropic": {"anthropic", "claude"},
    "claude": {"anthropic", "claude"},
    "gemini": {"gemini"},
    "ollama": {"ollama"},
    "manual": {"manual"},
    "imported": {"imported"},
}


def _to_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception:
            pass
    if isinstance(value, str) and value:
        raw = value.strip()
        try:
            return datetime.fromtimestamp(float(raw), tz=timezone.utc)
        except Exception:
            pass
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            pass
    return datetime.fromtimestamp(0, tz=timezone.utc)


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _escape_sql(value: str) -> str:
    return str(value or "").replace("'", "''")


def _days_since(ts: datetime, now: datetime) -> float:
    return max(0.0, (now - ts).total_seconds() / 86400.0)


def _lexical_score(text: str, words: list[str]) -> float:
    raw = str(text or "").lower()
    if not raw:
        return 0.0
    if not words:
        return 0.0
    matches = sum(1 for w in words if w in raw)
    return min(1.0, matches / max(1, len(words)))


def _within_range(ts: datetime, from_dt: Optional[datetime], to_dt: Optional[datetime]) -> bool:
    if from_dt and ts < from_dt:
        return False
    if to_dt and ts > to_dt:
        return False
    return True


def _expand_source_token(token: str) -> set[str]:
    raw = str(token or "").strip().lower()
    if not raw:
        return set()
    return set(_SOURCE_ALIASES.get(raw, {raw}))


def _parse_sources(value: Optional[str]) -> set[str]:
    if not value:
        return set()
    out: set[str] = set()
    for item in str(value).split(","):
        token = re.sub(r"[^a-z0-9_-]+", "", str(item or "").strip().lower())
        if not token:
            continue
        out.update(_expand_source_token(token))
    return out


def _source_matches(source_llm: str, source_filters: set[str]) -> bool:
    if not source_filters:
        return True
    raw = str(source_llm or "").strip().lower()
    if not raw:
        return False
    tokens = {tok for tok in re.split(r"[^a-z0-9]+", raw) if tok}
    expanded: set[str] = set()
    for token in tokens:
        expanded.update(_expand_source_token(token))
    if tokens.intersection(source_filters):
        return True
    if expanded.intersection(source_filters):
        return True
    return any(token in raw for token in source_filters)


@router.get("/")
async def unified_search(
    q: str = "",
    limit: int = 30,
    include_memories: bool = True,
    include_conversations: bool = True,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sources: Optional[str] = None,
):
    safe_limit = max(1, min(int(limit), 150))
    query = str(q or "").strip()
    query_words = [w for w in query.lower().split() if w]
    from_dt = _parse_dt(date_from)
    to_dt = _parse_dt(date_to)
    source_filters = _parse_sources(sources)
    if from_dt and to_dt and from_dt > to_dt:
        raise HTTPException(status_code=400, detail="date_from must be <= date_to")

    db = get_db()
    now = datetime.now(timezone.utc)
    items: list[dict] = []

    query_vector: list[float] | None = None
    if query and get_status() == "ready":
        try:
            query_vector = embed(query)
        except Exception:
            query_vector = None

    if include_memories and "memories" in db.table_names():
        mem_tbl = db.open_table("memories")
        where_clause = "status = 'active' OR status = 'pending_review'"
        scan_limit = min(8000, max(700, safe_limit * 30))

        lexical_rows = mem_tbl.search().where(where_clause).limit(scan_limit).to_list()
        by_id: dict[str, dict] = {}
        for row in lexical_rows:
            mid = str(row.get("id") or "")
            if mid:
                by_id[mid] = row

        semantic_scores: dict[str, float] = {}
        if query_vector is not None:
            vec_rows = mem_tbl.search(query_vector).where(where_clause).limit(scan_limit).to_list()
            for row in vec_rows:
                mid = str(row.get("id") or "")
                if not mid:
                    continue
                by_id[mid] = row
                semantic_scores[mid] = max(0.0, 1.0 - float(row.get("_distance") or 1.0))

        for row in by_id.values():
            source_llm = str(row.get("source_llm") or "").strip()
            if source_filters and not _source_matches(source_llm, source_filters):
                continue
            ts = _to_dt(row.get("updated_at") or row.get("created_at"))
            if not _within_range(ts, from_dt, to_dt):
                continue
            content = str(row.get("content") or "")
            tags = [str(t) for t in (row.get("tags") or []) if t]
            category = str(row.get("category") or "")
            level = str(row.get("level") or "")
            memory_text = " ".join([content, category, level, " ".join(tags)])
            lex = _lexical_score(memory_text, query_words) if query else 0.15
            if query and lex <= 0 and not query_vector:
                continue
            sem = semantic_scores.get(str(row.get("id") or ""), 0.0)
            recency = math.exp(-0.03 * _days_since(ts, now))
            score = (0.52 * sem) + (0.33 * lex) + (0.15 * recency)
            items.append(
                {
                    "type": "memory",
                    "id": str(row.get("id") or ""),
                    "score": round(score, 4),
                    "title": (content[:140] + ("…" if len(content) > 140 else "")) if content else "Memory",
                    "excerpt": content[:500],
                    "date": ts.isoformat(),
                    "category": category,
                    "level": level,
                    "source_llm": source_llm,
                    "tags": tags,
                }
            )

    if include_conversations and "conversations" in db.table_names():
        conv_tbl = db.open_table("conversations")
        scan_limit = min(6000, max(600, safe_limit * 30))
        rows = conv_tbl.search().where("status != 'deleted'").limit(scan_limit).to_list()
        for row in rows:
            source_llm = str(row.get("source_llm") or "").strip()
            if source_filters and not _source_matches(source_llm, source_filters):
                continue
            ts = _to_dt(row.get("started_at") or row.get("imported_at"))
            if not _within_range(ts, from_dt, to_dt):
                continue
            title = str(row.get("title") or "Untitled conversation")
            summary = str(row.get("summary") or "")
            tags = [str(t) for t in (row.get("tags") or []) if t]
            conversation_text = " ".join([title, summary, source_llm, " ".join(tags)])
            lex = _lexical_score(conversation_text, query_words) if query else 0.12
            if query and lex <= 0:
                continue
            recency = math.exp(-0.022 * _days_since(ts, now))
            score = (0.7 * lex) + (0.3 * recency)
            items.append(
                {
                    "type": "conversation",
                    "id": str(row.get("id") or ""),
                    "score": round(score, 4),
                    "title": title[:180],
                    "excerpt": summary[:500],
                    "date": ts.isoformat(),
                    "source_llm": source_llm,
                    "message_count": int(row.get("message_count") or 0),
                    "tags": tags,
                }
            )

    items.sort(key=lambda item: (float(item.get("score") or 0.0), _to_dt(item.get("date")).timestamp()), reverse=True)
    items = items[:safe_limit]

    return {
        "query": query,
        "filters": {
            "sources": sorted(source_filters),
        },
        "total": len(items),
        "items": items,
    }
