from datetime import datetime, timezone
import logging
from typing import Any, Optional, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.config import load_config
from backend.database.client import get_db
from backend.memory.write_queue import enqueue_write

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])
logger = logging.getLogger(__name__)


def _escape_sql(value: str) -> str:
    return value.replace("'", "''")


def _to_dt(value) -> datetime:
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


def _internal_error(message: str, exc: Exception | None = None) -> HTTPException:
    if exc is not None:
        logger.exception(message)
    return HTTPException(status_code=500, detail=message)


class ConversationMemoryMiningPayload(BaseModel):
    dry_run: bool = True
    force_reanalyze: bool = False
    include_assistant_messages: bool = False
    max_conversations: int = Field(default=40, ge=1, le=400)
    max_messages_per_conversation: int = Field(default=24, ge=4, le=80)
    max_candidates_per_conversation: int = Field(default=6, ge=1, le=20)
    max_new_memories: int = Field(default=120, ge=1, le=500)
    min_confidence: float = Field(default=0.78, ge=0.5, le=0.99)
    provider: str = "auto"
    model: Optional[str] = None
    api_base_url: Optional[str] = None
    api_key: Optional[str] = None
    concurrency: int = Field(default=2, ge=1, le=4)


class ConversationIngestMessage(BaseModel):
    id: Optional[str] = None
    role: str = "user"
    content: str
    timestamp: Any = None


class ConversationIngestPayload(BaseModel):
    conversation_id: str
    title: str = "Untitled conversation"
    source_llm: str = "imported"
    messages: List[ConversationIngestMessage] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    summary: str = ""
    started_at: Any = None
    ended_at: Any = None
    status: str = "archived"


@router.get("/")
async def list_conversations(
    source_llm: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
):
    try:
        db = get_db()
        if "conversations" not in db.table_names():
            return []

        safe_limit = max(1, min(int(limit), 5000))
        safe_offset = max(0, int(offset))

        tbl = db.open_table("conversations")
        query = tbl.search().where("status != 'deleted'")
        if source_llm:
            query = query.where(f"source_llm = '{_escape_sql(source_llm)}'")

        rows = query.limit(safe_offset + safe_limit).to_list()
        rows.sort(key=lambda x: _to_dt(x.get("started_at")), reverse=True)
        return rows[safe_offset : safe_offset + safe_limit]
    except Exception as e:
        raise _internal_error("Failed to list conversations.", e)


@router.post("/ingest")
async def ingest_conversation(payload: ConversationIngestPayload):
    try:
        from backend.memory.conversation_capture import ingest_conversation_transcript

        messages = [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "timestamp": m.timestamp,
            }
            for m in payload.messages
        ]
        result = await ingest_conversation_transcript(
            conversation_id=payload.conversation_id,
            title=payload.title,
            source_llm=payload.source_llm,
            messages=messages,
            tags=payload.tags,
            summary=payload.summary,
            started_at=payload.started_at,
            ended_at=payload.ended_at,
            status=payload.status,
        )
        if str(result.get("status") or "").lower() == "error":
            raise HTTPException(status_code=400, detail=result.get("message") or result.get("action") or "Ingestion failed")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise _internal_error("Failed to ingest conversation.", e)


@router.delete("/{conversation_id}")
async def delete_conversation(conversation_id: str):
    """Soft delete a conversation."""
    try:
        db = get_db()
        if "conversations" not in db.table_names():
            raise HTTPException(status_code=404, detail="Conversation not found")

        tbl = db.open_table("conversations")
        escaped_id = _escape_sql(conversation_id)
        matches = tbl.search().where(f"id = '{escaped_id}'").limit(1).to_list()
        if not matches:
            raise HTTPException(status_code=404, detail="Conversation not found")

        async def _write_op():
            tbl.update(
                where=f"id = '{escaped_id}'",
                values={"status": "deleted"},
            )

        await enqueue_write(_write_op)
        return {"id": conversation_id, "status": "deleted", "action": "deleted"}

    except HTTPException:
        raise
    except Exception as e:
        raise _internal_error("Failed to delete conversation.", e)


@router.get("/search")
async def search_conversations(
    query: str,
    limit: int = 5,
    source_llm: Optional[str] = None,
):
    # FTS/vector search on conversations is not indexed yet.
    # Current strategy: in-memory filter/rank over recent rows.
    try:
        db = get_db()
        if "conversations" not in db.table_names():
            return []

        safe_limit = max(1, min(int(limit), 100))
        fetch_limit = min(max(safe_limit * 25, 200), 5000)

        tbl = db.open_table("conversations")
        all_convs = tbl.search().where("status != 'deleted'").limit(fetch_limit).to_list()

        if source_llm:
            all_convs = [c for c in all_convs if c.get("source_llm") == source_llm]

        q_lower = query.lower().strip()
        if not q_lower:
            return []

        scored = []
        words = [w for w in q_lower.split() if w]
        for conv in all_convs:
            text = f"{conv.get('title', '')} {conv.get('summary', '')}".lower()
            matches = sum(1 for w in words if w in text)
            if matches > 0:
                scored.append((matches, _to_dt(conv.get("started_at")), conv))

        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [item[2] for item in scored[:safe_limit]]

    except Exception as e:
        raise _internal_error("Failed to search conversations.", e)


@router.post("/mine-memories")
async def mine_conversations_to_memories(payload: ConversationMemoryMiningPayload):
    try:
        from backend.memory.conversation_mining import (
            get_analysis_llm_gate_status,
            run_mining_singleflight,
        )

        cfg = load_config(force_reload=True)
        auto_cfg = cfg.get("conversation_analysis", {}) if isinstance(cfg.get("conversation_analysis"), dict) else {}
        require_llm_configured = bool(auto_cfg.get("require_llm_configured", True))
        model = payload.model if payload.model is not None else (str(auto_cfg.get("model") or "").strip() or None)
        api_base_url = payload.api_base_url if payload.api_base_url is not None else (str(auto_cfg.get("api_base_url") or "").strip() or None)
        api_key = payload.api_key if payload.api_key is not None else (str(auto_cfg.get("api_key") or "").strip() or None)

        gate = await get_analysis_llm_gate_status(
            provider=payload.provider,
            model=model,
            api_base_url=api_base_url,
            api_key=api_key,
            require_llm_configured=require_llm_configured,
        )
        if not bool(gate.get("analysis_allowed", True)):
            raise HTTPException(
                status_code=400,
                detail=str(gate.get("reason") or "Conversation analysis is blocked until LLM is configured."),
            )

        response = await run_mining_singleflight(
            trigger="manual_conversations",
            wait_if_busy=False,
            dry_run=payload.dry_run,
            force_reanalyze=payload.force_reanalyze,
            include_assistant_messages=payload.include_assistant_messages,
            max_conversations=payload.max_conversations,
            max_messages_per_conversation=payload.max_messages_per_conversation,
            max_candidates_per_conversation=payload.max_candidates_per_conversation,
            max_new_memories=payload.max_new_memories,
            min_confidence=payload.min_confidence,
            provider=payload.provider,
            model=model,
            api_base_url=api_base_url,
            api_key=api_key,
            concurrency=payload.concurrency,
            require_llm_configured=require_llm_configured,
        )
        if str(response.get("status") or "").lower() == "busy":
            return response
        return response.get("result", {})
    except HTTPException:
        raise
    except Exception as e:
        raise _internal_error("Failed to run conversation analysis.", e)


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: str):
    """Get conversation details including messages."""
    try:
        db = get_db()

        if "conversations" not in db.table_names():
            raise HTTPException(status_code=404, detail="Conversation not found")

        conv_tbl = db.open_table("conversations")
        escaped_id = _escape_sql(conversation_id)
        matches = conv_tbl.search().where(f"id = '{escaped_id}'").limit(1).to_list()

        if not matches:
            raise HTTPException(status_code=404, detail="Conversation not found")

        conversation = matches[0]
        if conversation.get("status") == "deleted":
            raise HTTPException(status_code=404, detail="Conversation not found")

        messages = []
        if "messages" in db.table_names():
            msg_tbl = db.open_table("messages")
            msgs = msg_tbl.search().where(f"conversation_id = '{escaped_id}'").limit(5000).to_list()
            msgs.sort(key=lambda x: _to_dt(x.get("timestamp")))
            messages = msgs

        conversation["messages"] = messages
        return conversation

    except HTTPException:
        raise
    except Exception as e:
        raise _internal_error("Failed to load conversation.", e)
