from mcp.server.fastmcp import FastMCP
from backend.memory.core import (
    create_memory,
    search_memories,
    get_snapshot,
    process_feedback,
    update_memory,
    delete_memory,
    list_pending_conflicts,
)
from backend.memory.graph_layer import memory_graph_search as graph_search
from typing import List, Optional, Any
from datetime import datetime, timezone
import re

from backend.auth import token_scope_allowed

# Initialize FastMCP Server
mcp = FastMCP("Mnesis")

from backend.utils.context import session_id_ctx, mcp_client_name_ctx, mcp_client_scopes_ctx

_ALLOWED_MEMORY_CATEGORIES = {
    "identity",
    "preferences",
    "skills",
    "relationships",
    "projects",
    "history",
    "working",
}
_ALLOWED_MEMORY_LEVELS = {"semantic", "episodic", "working"}


# Allowed characters for source_llm values (e.g. "claude", "conversation-analyzer:gpt-4o").
_SOURCE_LLM_RE = re.compile(r'^[a-zA-Z0-9_\-.:]{1,64}$')


def _validate_source_llm(value: Optional[str]) -> Optional[str]:
    """Return the source_llm value only if it matches the safe character set, else None."""
    if not value:
        return None
    cleaned = str(value).strip()
    if _SOURCE_LLM_RE.match(cleaned):
        return cleaned
    return None


def _normalize_memory_category(value: Optional[str]) -> Optional[str]:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    if raw in _ALLOWED_MEMORY_CATEGORIES:
        return raw
    return None


def _normalize_memory_level(value: Optional[str]) -> Optional[str]:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    if raw in _ALLOWED_MEMORY_LEVELS:
        return raw
    return None


def _require_scope(scope: str):
    scopes = mcp_client_scopes_ctx.get() or []
    client_name = str(mcp_client_name_ctx.get() or "unknown-client")
    if token_scope_allowed(scopes, scope):
        return
    available = ",".join(sorted({str(s).strip().lower() for s in scopes if str(s).strip()}))
    raise PermissionError(
        f"MCP client '{client_name}' is missing required scope '{scope}'. "
        f"available_scopes='{available or 'none'}'"
    )


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
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            pass
    return datetime.now(timezone.utc)


@mcp.tool()
async def memory_write(
    content: str,
    category: str,
    level: str,
    source_llm: str,
    tags: Optional[List[str]] = None,
    privacy: str = "public",
    importance_score: float = 0.5,
    confidence_score: float = 0.7
):
    """
    Write a new memory to Mnesis.

    level: "semantic" (lasting facts) | "episodic" (past events) | "working" (next 72h)
    category: "identity" | "preferences" | "skills" | "relationships" | "projects" | "history" | "working"
    privacy: "public" | "sensitive" | "private"
    confidence_score: 0–1. Semantic memories with confidence < 0.85 go to pending_review.
    
    MANDATORY format: third-person declarative. "{name} prefers..." not "I prefer..."
    Length: 20–1000 characters, under 128 tokens.
    """
    _require_scope("write")
    content = str(content or "").strip()
    if len(content) < 20 or len(content) > 2000:
        raise ValueError("Content must be 20–2000 characters")
    session_id = session_id_ctx.get()
    return await create_memory(
        content=content,
        category=category,
        level=level,
        source_llm=source_llm,
        tags=tags or [],
        privacy=privacy,
        importance_score=importance_score,
        confidence_score=confidence_score,
        session_id=session_id,
        source_conversation_id=session_id,  # link memory to its MCP session/conversation
    )


@mcp.tool()
async def memory_read(query: str, limit: int = 5, context: Optional[str] = None):
    """
    Search for memories semantically relevant to the query.

    context: "development" | "personal" | "creative" | "business" — boosts memories
             whose tags match this context (×1.3 on final score).
    Returns: list of {id, content, category, level, importance_score, tags, source_llm}
    """
    _require_scope("read")
    limit = max(1, min(limit, 500))
    session_id = session_id_ctx.get()
    return await search_memories(query, limit, context=context, session_id=session_id)


@mcp.tool()
async def memory_update(id: str, content: str, source_llm: str):
    """
    Update an existing memory. Archives the previous version automatically.
    Recalculates the embedding. Sets importance_score to max(current, 0.6).
    """
    _require_scope("write")
    session_id = session_id_ctx.get()
    return await update_memory(id, content, source_llm, session_id=session_id)


@mcp.tool()
async def memory_delete(id: str):
    """
    Soft-delete a memory (sets status=archived). Never physically deleted.
    Always recoverable from the Memory Browser.
    """
    _require_scope("write")
    return await delete_memory(id)


@mcp.tool()
async def memory_list(
    category: Optional[str] = None,
    level: Optional[str] = None,
    limit: int = 20,
    offset: int = 0
):
    """
    List memories with optional filters. Sorted by importance_score DESC.
    Returns metadata + first 100 chars of content.

    category: "identity" | "preferences" | "skills" | "relationships" | "projects" | "history" | "working"
    level: "semantic" | "episodic" | "working"
    """
    _require_scope("read")
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    from backend.database.client import get_db
    db = get_db()
    tbl = db.open_table("memories")

    where_parts = ["status = 'active'"]
    normalized_category = _normalize_memory_category(category)
    if category and not normalized_category:
        return []
    normalized_level = _normalize_memory_level(level)
    if level and not normalized_level:
        return []
    if normalized_category:
        # normalized_category is already validated against _ALLOWED_MEMORY_CATEGORIES.
        where_parts.append(f"category = '{normalized_category}'")
    if normalized_level:
        # normalized_level is already validated against _ALLOWED_MEMORY_LEVELS.
        where_parts.append(f"level = '{normalized_level}'")

    where_clause = " AND ".join(where_parts)

    try:
        results = (
            tbl.search()
            .where(where_clause)
            .limit(limit + offset)
            .to_list()
        )
        results.sort(key=lambda x: x['importance_score'], reverse=True)
        results = results[offset:offset + limit]
    except Exception:
        results = []

    # Strip vector, truncate content to 100 chars
    return [
        {
            "id": r['id'],
            "content": r['content'][:100],
            "category": r['category'],
            "level": r['level'],
            "importance_score": r['importance_score'],
            "tags": r.get('tags', []),
            "source_llm": r['source_llm'],
            "status": r['status'],
            "created_at": r['created_at'].isoformat() if hasattr(r['created_at'], 'isoformat') else str(r['created_at']),
        }
        for r in results
    ]


@mcp.tool()
async def context_snapshot(context: Optional[str] = None, query: Optional[str] = None):
    """
    Get a structured Markdown snapshot of the user's memory (max 800 tokens).

    context: optional explicit hint ("development" | "personal" | "business" | "casual")
    query: when provided, adaptive router classifies domain automatically
           ("code" | "business" | "personal" | "casual") and injects routed categories.
    
    Call this at the START of every conversation, silently.
    Internalize the snapshot — never quote it back to the user.
    """
    _require_scope("read")
    return await get_snapshot(context=context, query=query)


@mcp.tool()
async def memory_bootstrap(context: Optional[str] = None, query: Optional[str] = None):
    """
    Standard bootstrap alias for adapters. Reads initial memory context.
    """
    _require_scope("read")
    return await get_snapshot(context=context, query=query)


@mcp.tool()
async def get_pending_conflicts(limit: int = 50):
    """
    List unresolved memory conflicts captured during writes.
    Returns entries with:
      - memory_a (existing memory)
      - memory_b (candidate memory content)
      - similarity_score
      - detected_at
    """
    _require_scope("read")
    limit = max(1, min(limit, 500))
    return await list_pending_conflicts(limit=limit)


@mcp.tool()
async def memory_graph_search(start_memory_id: str, depth: int = 2):
    """
    Return a contextual subgraph around one memory.

    Args:
      - start_memory_id: memory UUID
      - depth: traversal depth (default 2, max 5)

    Returns JSON:
      {
        "start_memory_id": "...",
        "depth": 2,
        "nodes": [{"id","content_preview","category","level"}],
        "edges": [{"id","source","target","type","score"}]
      }
    """
    _require_scope("read")
    return await graph_search(start_memory_id=start_memory_id, depth=depth)


@mcp.tool()
async def memory_feedback(used_memory_ids: List[str]):
    """
    Signal which memories were actually useful in this conversation.
    Increases importance_score by 0.05 and reference_count by 1 for each ID.
    Marks the current session as ended.

    Call this when the conversation ends naturally. Include ONLY memory IDs
    that genuinely influenced your responses — not every memory retrieved.
    """
    _require_scope("write")
    session_id = session_id_ctx.get()
    return await process_feedback(used_memory_ids, session_id=session_id)


@mcp.tool()
async def conversation_search(query: str, limit: int = 5, source_llm: Optional[str] = None):
    """
    Search past conversations by semantic similarity (or full-text if embedding disabled).
    Returns: {conversation_id, title, source_llm, excerpt, date}
    """
    _require_scope("read")
    limit = max(1, min(limit, 500))
    from backend.database.client import get_db
    from backend.memory.embedder import embed
    db = get_db()

    results = []
    try:
        if "conversations" not in db.table_names():
            return []
        tbl = db.open_table("conversations")
        where = "status != 'deleted'"
        safe_llm = _validate_source_llm(source_llm)
        if safe_llm:
            where += f" AND source_llm = '{safe_llm}'"
        convs = tbl.search().where(where).limit(limit * 3).to_list()

        # Simple full-text filter on title + summary
        query_lower = query.lower()
        scored = []
        for c in convs:
            text = f"{c.get('title', '')} {c.get('summary', '')}".lower()
            # Score by word overlap
            words = set(query_lower.split())
            matches = sum(1 for w in words if w in text)
            if matches > 0:
                scored.append((matches, c))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = [
            {
                "conversation_id": c['id'],
                "title": c['title'],
                "source_llm": c['source_llm'],
                "date": c['started_at'].isoformat() if hasattr(c['started_at'], 'isoformat') else str(c['started_at']),
                "summary": c.get('summary', ''),
            }
            for _, c in scored[:limit]
        ]
    except Exception as e:
        pass

    return results


@mcp.tool()
async def conversation_list(source_llm: Optional[str] = None, limit: int = 20, offset: int = 0):
    """
    List archived conversations. Paginated, metadata only.
    """
    _require_scope("read")
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    from backend.database.client import get_db
    db = get_db()
    try:
        if "conversations" not in db.table_names():
            return []
        tbl = db.open_table("conversations")
        where = "status != 'deleted'"
        safe_llm = _validate_source_llm(source_llm)
        if safe_llm:
            where += f" AND source_llm = '{safe_llm}'"
        results = tbl.search().where(where).limit(limit + offset).to_list()
        results = results[offset:offset + limit]
        return [
            {
                "id": c['id'],
                "title": c['title'],
                "source_llm": c['source_llm'],
                "message_count": c.get('message_count', 0),
                "started_at": c['started_at'].isoformat() if hasattr(c['started_at'], 'isoformat') else str(c['started_at']),
                "summary": c.get('summary', ''),
            }
            for c in results
        ]
    except Exception:
        return []


@mcp.tool()
async def conversation_ingest(
    conversation_id: str,
    title: str,
    source_llm: str,
    messages: List[dict[str, Any]],
    tags: Optional[List[str]] = None,
    summary: str = "",
    started_at: Optional[str] = None,
    ended_at: Optional[str] = None,
):
    """
    Incrementally ingest a full conversation transcript.

    Use this tool at the end of each turn (or every few turns) to keep Mnesis'
    conversation history centralized and deduplicated across clients.
    """
    _require_scope("write")
    from backend.memory.conversation_capture import ingest_conversation_transcript

    result = await ingest_conversation_transcript(
        conversation_id=conversation_id,
        title=title,
        source_llm=source_llm,
        messages=messages or [],
        tags=tags or [],
        summary=summary or "",
        started_at=started_at,
        ended_at=ended_at,
        status="archived",
    )
    # Auto-trigger memory extraction analysis for this conversation
    try:
        from backend.memory.conversation_analysis_jobs import enqueue_analysis_job
        conv_id_ingested = str(result.get("conversation_id") or conversation_id or "").strip()
        if conv_id_ingested:
            await enqueue_analysis_job(
                trigger="mcp_ingest",
                payload={"conversation_ids": [conv_id_ingested]},
                priority=1,
                dedupe_key=f"mcp_ingest:{conv_id_ingested}",
            )
    except Exception as _e:
        logger.debug("Could not enqueue analysis after conversation_ingest: %s", _e)
    return result


@mcp.tool()
async def conversation_sync(
    conversation_id: str,
    source_llm: str,
    title: str = "Conversation",
    summary: str = "",
    started_at: Optional[str] = None,
    ended_at: Optional[str] = None,
    tags: Optional[List[str]] = None,
):
    """
    Standard sync alias for adapters.
    Syncs one conversation summary to Mnesis without requiring full transcript.
    """
    _require_scope("write")
    from backend.memory.conversation_capture import ingest_conversation_transcript

    now = datetime.now(timezone.utc)
    synthetic_message = {
        "id": f"sync:{conversation_id}:summary",
        "role": "assistant",
        "content": str(summary or "").strip()[:5000] or "(summary unavailable)",
        "timestamp": _to_dt(ended_at or started_at or now).isoformat(),
    }
    result = await ingest_conversation_transcript(
        conversation_id=str(conversation_id or "").strip(),
        title=str(title or "Conversation").strip() or "Conversation",
        source_llm=str(source_llm or "").strip() or "mcp",
        messages=[synthetic_message],
        tags=[str(v).strip() for v in (tags or []) if str(v).strip()],
        summary=str(summary or "").strip(),
        started_at=started_at,
        ended_at=ended_at,
        status="archived",
    )
    # Auto-trigger memory extraction analysis for this conversation
    try:
        from backend.memory.conversation_analysis_jobs import enqueue_analysis_job
        conv_id_synced = str(result.get("conversation_id") or conversation_id or "").strip()
        if conv_id_synced:
            await enqueue_analysis_job(
                trigger="mcp_sync",
                payload={"conversation_ids": [conv_id_synced]},
                priority=1,
                dedupe_key=f"mcp_sync:{conv_id_synced}",
            )
    except Exception as _e:
        logger.debug("Could not enqueue analysis after conversation_sync: %s", _e)
    return result


@mcp.tool()
async def note_exchange(
    conversation_id: str,
    user_message: str,
    assistant_summary: str,
    source_llm: str,
):
    """
    Log one user/assistant exchange to the conversation history.

    Call this after each meaningful response you give.
    This is the primary way Mnesis stores the actual conversation content
    (user questions and your answers) — as opposed to raw tool call traces.

    Args:
        conversation_id: The same UUID used for this session's conversation_sync calls.
        user_message: The user's message verbatim (or a faithful summary if very long).
        assistant_summary: A concise summary of your response (2-4 sentences).
        source_llm: Your fixed source identifier (e.g. "chatgpt", "cursor", "claude").
    """
    _require_scope("write")
    from backend.memory.conversation_capture import append_exchange_messages

    await append_exchange_messages(
        conversation_id=str(conversation_id or "").strip(),
        user_message=str(user_message or "").strip(),
        assistant_summary=str(assistant_summary or "").strip(),
        source_llm=str(source_llm or "").strip() or "mcp",
    )
    return {"status": "ok", "conversation_id": str(conversation_id or "").strip()}


def register_mcp(app):
    """Mount the MCP server's SSE application at /mcp."""
    sse = mcp.sse_app()
    
    # We monkey-patch the connect_sse handler in FastMCP so that the
    # EventSourceResponse sends a keep-alive ping every 15 seconds.
    # Without this, Uvicorn will terminate idle SSE streams after 60s,
    # causing Claude Desktop and other clients to constantly disconnect.
    try:
        from sse_starlette.sse import EventSourceResponse
        
        # Only patch if not already patched
        if not hasattr(EventSourceResponse, "_mnesis_patched"):
            original_init = EventSourceResponse.__init__
            
            def _patched_init(self, *args, **kwargs):
                if "ping" not in kwargs:
                    kwargs["ping"] = 15
                original_init(self, *args, **kwargs)
                
            EventSourceResponse.__init__ = _patched_init
            EventSourceResponse._mnesis_patched = True
            import logging
            logging.getLogger("mnesis.mcp").info("Patched EventSourceResponse with 15s ping interval")

    except Exception as e:
        import logging
        logging.getLogger("mnesis.mcp").warning(f"Failed to patch FastMCP keep-alives: {e}")

    app.mount("/mcp", sse)
