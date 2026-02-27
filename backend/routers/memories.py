from datetime import datetime, timezone
import logging
import math
import re
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Annotated

from backend.database.client import get_db
from backend.memory.core import create_memory, get_snapshot, search_memories, set_memory_status, set_memory_status_bulk

router = APIRouter(prefix="/api/v1/memories", tags=["memories"])
logger = logging.getLogger(__name__)


_UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)


_DECAY_RATES: dict[str, float] = {"semantic": 0.001, "episodic": 0.05, "working": 0.3}


def _apply_read_time_decay(rows: list[dict]) -> list[dict]:
    """Apply Ebbinghaus read-time decay to importance_score (read-only, no DB write)."""
    now = datetime.now(timezone.utc)
    result = []
    for row in rows:
        level = str(row.get("level") or "semantic").strip().lower()
        k = _DECAY_RATES.get(level, 0.001)
        updated_raw = row.get("updated_at")
        if updated_raw:
            try:
                updated = _to_dt(updated_raw)
                days = max(0.0, (now - updated).total_seconds() / 86400.0)
                retention = math.exp(-k * days)
                current = float(row.get("importance_score") or 0.5)
                row = dict(row)
                row["importance_score"] = round(max(0.0, min(1.0, current * retention)), 4)
            except Exception:
                pass
        result.append(row)
    return result


def _validate_memory_id(memory_id: str) -> str:
    """Validate that memory_id is a well-formed UUID to prevent SQL injection."""
    if not _UUID_RE.match(str(memory_id or "")):
        raise HTTPException(status_code=400, detail="Invalid memory id format")
    return memory_id


def _to_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            pass
    return datetime.fromtimestamp(0, tz=timezone.utc)


def _sanitize_limit(value: int, default: int = 50, minimum: int = 1, maximum: int = 500) -> int:
    try:
        numeric = int(value)
    except Exception:
        numeric = default
    return max(minimum, min(maximum, numeric))


def _serialize_memory(row: dict) -> dict:
    return {k: v for k, v in row.items() if k not in ("vector", "_distance")}


def _internal_error(message: str, exc: Exception | None = None) -> HTTPException:
    if exc is not None:
        logger.exception(message)
    return HTTPException(status_code=500, detail=message)


class MemoryCreate(BaseModel):
    content: str
    category: str
    level: str
    source_llm: str
    importance_score: float = 0.5
    confidence_score: float = 0.7
    privacy: str = "public"
    tags: List[str] = Field(default_factory=list)
    source_conversation_id: str | None = None
    source_message_id: str | None = None
    source_excerpt: str | None = None


@router.post("/")
async def create_memory_endpoint(mem: MemoryCreate):
    try:
        return await create_memory(
            content=mem.content,
            category=mem.category,
            level=mem.level,
            source_llm=mem.source_llm,
            importance_score=mem.importance_score,
            confidence_score=mem.confidence_score,
            privacy=mem.privacy,
            tags=mem.tags,
            source_conversation_id=mem.source_conversation_id,
            source_message_id=mem.source_message_id,
            source_excerpt=mem.source_excerpt,
        )
    except Exception as e:
        raise _internal_error("Failed to create memory.", e)


@router.get("/")
async def list_memories(
    query: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
):
    safe_limit = _sanitize_limit(limit, default=50, maximum=500)
    safe_offset = max(0, int(offset))
    normalized_status = str(status or "").strip().lower()
    if normalized_status in {"", "all"}:
        normalized_status = ""
    elif normalized_status not in {"active", "pending_review", "rejected", "archived"}:
        raise HTTPException(status_code=400, detail="Invalid status filter")

    if query and not normalized_status:
        # Offset is applied client-side on semantic search results.
        results = await search_memories(query, safe_limit + safe_offset)
        return results[safe_offset : safe_offset + safe_limit]

    db = get_db()
    if "memories" not in db.table_names():
        return []

    tbl = db.open_table("memories")
    if normalized_status:
        # normalized_status is already validated against the allowed enum above.
        where_clause = f"status = '{normalized_status}'"
    else:
        # Default "all" view should show approved memories only.
        # Pending suggestions are handled by Inbox and rejected items stay hidden by default.
        where_clause = "status = 'active'"

    fetch_limit = safe_limit + safe_offset
    if query:
        fetch_limit = min(5000, max(fetch_limit * 8, 600))
    rows = tbl.search().where(where_clause).limit(fetch_limit).to_list()
    rows.sort(
        key=lambda x: (_to_dt(x.get("updated_at")), _to_dt(x.get("created_at"))),
        reverse=True,
    )

    if query:
        q = str(query).strip().lower()
        if q:
            rows = [r for r in rows if q in str(r.get("content") or "").lower()]

    rows = _apply_read_time_decay(rows)
    cleaned = [_serialize_memory(r) for r in rows]
    return cleaned[safe_offset : safe_offset + safe_limit]


@router.get("/snapshot")
async def get_snapshot_endpoint(context: Optional[str] = None, query: Optional[str] = None):
    return {"snapshot": await get_snapshot(context=context, query=query)}


class MemoryUpdate(BaseModel):
    content: str
    source_llm: str


class MemoryStatusUpdate(BaseModel):
    status: str
    source_llm: str = "manual"
    review_note: str | None = None


class MemoryBulkStatusUpdate(BaseModel):
    ids: Annotated[List[str], Field(min_length=1, max_length=500)] = Field(default_factory=list)
    status: str
    source_llm: str = "manual"
    review_note: str | None = None


class MemoryScoresUpdate(BaseModel):
    importance_score: float | None = None
    confidence_score: float | None = None


@router.put("/{memory_id}")
async def update_memory_endpoint(memory_id: str, mem: MemoryUpdate):
    from backend.memory.core import update_memory

    try:
        result = await update_memory(memory_id, mem.content, mem.source_llm)
    except Exception as e:
        raise _internal_error("Failed to update memory.", e)

    if result.get("action") == "not_found":
        raise HTTPException(status_code=404, detail="Memory not found")
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message") or "Unable to update memory")
    return result


@router.patch("/{memory_id}/status")
async def update_memory_status_endpoint(memory_id: str, payload: MemoryStatusUpdate):
    try:
        result = await set_memory_status(memory_id, payload.status, payload.source_llm, payload.review_note)
    except Exception as e:
        raise _internal_error("Failed to update memory status.", e)

    if result.get("action") == "not_found":
        raise HTTPException(status_code=404, detail="Memory not found")
    if result.get("action") == "invalid_transition":
        raise HTTPException(status_code=422, detail=result.get("message") or "Invalid status transition")
    if result.get("action") == "invalid_status" or result.get("status") == "error":
        raise HTTPException(status_code=400, detail="Invalid memory status")
    return result


@router.patch("/status/bulk")
async def update_memory_status_bulk_endpoint(payload: MemoryBulkStatusUpdate):
    try:
        result = await set_memory_status_bulk(
            memory_ids=payload.ids,
            status=payload.status,
            source_llm=payload.source_llm,
            review_note=payload.review_note,
        )
    except Exception as e:
        raise _internal_error("Failed to update memory statuses.", e)

    if result.get("action") in {"invalid_status", "empty_ids", "too_many_ids"} or result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message") or "Invalid bulk status update payload")
    return result


@router.patch("/{memory_id}/scores")
async def update_memory_scores(memory_id: str, payload: MemoryScoresUpdate):
    """Adjust importance_score and/or confidence_score without touching content."""
    db = get_db()
    if "memories" not in db.table_names():
        raise HTTPException(status_code=404, detail="Memory not found")

    tbl = db.open_table("memories")
    safe_id = _validate_memory_id(memory_id)
    rows = tbl.search().where(f"id = '{safe_id}'").limit(1).to_list()
    if not rows or rows[0].get("status") == "archived":
        raise HTTPException(status_code=404, detail="Memory not found")

    try:
        updates: dict = {"updated_at": datetime.now(timezone.utc).isoformat()}
        if payload.importance_score is not None:
            updates["importance_score"] = float(max(0.0, min(1.0, payload.importance_score)))
        if payload.confidence_score is not None:
            updates["confidence_score"] = float(max(0.0, min(1.0, payload.confidence_score)))
        tbl.update(where=f"id = '{safe_id}'", values=updates)
        return {"action": "updated", "id": safe_id, **updates}
    except Exception as e:
        raise _internal_error("Failed to update memory scores.", e)


@router.get("/stats")
async def get_stats():
    db = get_db()
    try:
        if "memories" not in db.table_names():
            return {"total_memories": 0, "active": 0}

        tbl = db.open_table("memories")
        active_memories = tbl.search().where("status != 'archived'").limit(200000).to_list()
        total = len(active_memories)

        return {
            "total_memories": total,
            "active": total,
        }
    except Exception:
        return {"total_memories": 0, "active": 0}


@router.get("/insights")
async def get_insights_dashboard():
    from backend.insights.service import get_insights_dashboard as build_insights_dashboard

    try:
        return build_insights_dashboard()
    except Exception as e:
        raise _internal_error("Failed to load insights dashboard.", e)


@router.get("/graph")
async def get_graph_overview(
    depth: int = 2,
    center_memory_id: Optional[str] = None,
    category: Optional[str] = None,
    edge_type: Optional[str] = None,
    max_nodes: int = 220,
    include_conversations: bool = False,
):
    from backend.memory.graph_layer import memory_graph_overview

    safe_depth = max(1, min(int(depth or 2), 5))
    safe_max_nodes = max(10, min(int(max_nodes or 220), 500))
    try:
        return await memory_graph_overview(
            depth=safe_depth,
            center_memory_id=center_memory_id,
            category=category,
            edge_type=edge_type,
            max_nodes=safe_max_nodes,
            include_conversations=include_conversations,
        )
    except Exception as e:
        raise _internal_error("Failed to load memory graph.", e)


@router.get("/{memory_id}/health")
async def get_memory_health(memory_id: str):
    db = get_db()
    if "memories" not in db.table_names():
        raise HTTPException(status_code=404, detail="Memory not found")

    tbl = db.open_table("memories")
    safe_id = _validate_memory_id(memory_id)
    rows = tbl.search().where(f"id = '{safe_id}'").limit(1).to_list()
    if not rows:
        raise HTTPException(status_code=404, detail="Memory not found")

    m = rows[0]
    if m.get("status") == "archived":
        raise HTTPException(status_code=404, detail="Memory not found")

    importance = float(m.get("importance_score") or 0.5)
    confidence = float(m.get("confidence_score") or 0.5)
    decay_profile = str(m.get("decay_profile") or "stable")
    needs_review = bool(m.get("needs_review"))
    expires_at = m.get("expires_at")
    review_due_at = m.get("review_due_at")

    now = datetime.now(timezone.utc)

    days_until_expiry = None
    if expires_at:
        try:
            exp_dt = _to_dt(expires_at)
            days_until_expiry = max(0, (exp_dt - now).days)
        except Exception:
            pass

    # Grade: A (best) → F (expired/critical)
    if expires_at and days_until_expiry is not None and days_until_expiry == 0:
        grade = "F"
    elif needs_review or (days_until_expiry is not None and days_until_expiry < 7):
        grade = "D"
    elif decay_profile == "decay" or (review_due_at and _to_dt(review_due_at) <= now):
        grade = "C"
    elif importance >= 0.5 and confidence >= 0.5:
        grade = "B" if importance < 0.7 or confidence < 0.7 else "A"
    else:
        grade = "C"

    return {
        "id": safe_id,
        "grade": grade,
        "importance_score": importance,
        "confidence_score": confidence,
        "decay_profile": decay_profile,
        "needs_review": needs_review,
        "expires_at": str(expires_at) if expires_at else None,
        "days_until_expiry": days_until_expiry,
        "review_due_at": str(review_due_at) if review_due_at else None,
        "event_date": str(m.get("event_date")) if m.get("event_date") else None,
        "created_at": str(m.get("created_at")) if m.get("created_at") else None,
        "updated_at": str(m.get("updated_at")) if m.get("updated_at") else None,
    }


@router.get("/{memory_id}/graph")
async def get_memory_graph(memory_id: str, depth: int = 2):
    from backend.memory.graph_layer import memory_graph_search

    try:
        return await memory_graph_search(start_memory_id=memory_id, depth=depth)
    except Exception as e:
        raise _internal_error("Failed to load memory graph.", e)


@router.get("/{memory_id}")
async def get_memory_endpoint(memory_id: str):
    db = get_db()
    if "memories" not in db.table_names():
        raise HTTPException(status_code=404, detail="Memory not found")

    tbl = db.open_table("memories")
    safe_id = _validate_memory_id(memory_id)
    rows = tbl.search().where(f"id = '{safe_id}'").limit(1).to_list()
    if not rows:
        raise HTTPException(status_code=404, detail="Memory not found")

    memory = rows[0]
    if memory.get("status") == "archived":
        raise HTTPException(status_code=404, detail="Memory not found")
    return _serialize_memory(memory)


@router.delete("/{memory_id}")
async def delete_memory_endpoint(memory_id: str):
    from backend.memory.core import delete_memory

    db = get_db()
    if "memories" not in db.table_names():
        raise HTTPException(status_code=404, detail="Memory not found")

    tbl = db.open_table("memories")
    safe_id = _validate_memory_id(memory_id)
    rows = tbl.search().where(f"id = '{safe_id}'").limit(1).to_list()
    if not rows or rows[0].get("status") == "archived":
        raise HTTPException(status_code=404, detail="Memory not found")

    try:
        return await delete_memory(memory_id)
    except Exception as e:
        raise _internal_error("Failed to archive memory.", e)
