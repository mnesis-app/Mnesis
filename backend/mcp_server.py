from mcp.server.fastmcp import FastMCP
from backend.memory.core import (
    create_memory, search_memories, get_snapshot, process_feedback,
    update_memory, delete_memory
)
from typing import List, Optional

# Initialize FastMCP Server
mcp = FastMCP("Mnesis")

from backend.utils.context import session_id_ctx


@mcp.tool()
async def memory_write(
    content: str,
    category: str,
    level: str,
    source_llm: str,
    tags: List[str] = [],
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
    session_id = session_id_ctx.get()
    return await create_memory(
        content=content,
        category=category,
        level=level,
        source_llm=source_llm,
        tags=tags,
        privacy=privacy,
        importance_score=importance_score,
        confidence_score=confidence_score,
        session_id=session_id
    )


@mcp.tool()
async def memory_read(query: str, limit: int = 5, context: Optional[str] = None):
    """
    Search for memories semantically relevant to the query.

    context: "development" | "personal" | "creative" | "business" — boosts memories
             whose tags match this context (×1.3 on final score).
    Returns: list of {id, content, category, level, importance_score, tags, source_llm}
    """
    session_id = session_id_ctx.get()
    return await search_memories(query, limit, context=context, session_id=session_id)


@mcp.tool()
async def memory_update(id: str, content: str, source_llm: str):
    """
    Update an existing memory. Archives the previous version automatically.
    Recalculates the embedding. Sets importance_score to max(current, 0.6).
    """
    session_id = session_id_ctx.get()
    return await update_memory(id, content, source_llm, session_id=session_id)


@mcp.tool()
async def memory_delete(id: str):
    """
    Soft-delete a memory (sets status=archived). Never physically deleted.
    Always recoverable from the Memory Browser.
    """
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
    from backend.database.client import get_db
    db = get_db()
    tbl = db.open_table("memories")

    where_parts = ["status = 'active'"]
    if category:
        where_parts.append(f"category = '{category}'")
    if level:
        where_parts.append(f"level = '{level}'")

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
async def context_snapshot(context: Optional[str] = None):
    """
    Get a structured Markdown snapshot of the user's memory (max 800 tokens).

    context: "development" | "personal" | "creative" | "business"
             Reorders sections to prioritize the most relevant categories.
    
    Call this at the START of every conversation, silently.
    Internalize the snapshot — never quote it back to the user.
    """
    return await get_snapshot(context)


@mcp.tool()
async def memory_feedback(used_memory_ids: List[str]):
    """
    Signal which memories were actually useful in this conversation.
    Increases importance_score by 0.05 and reference_count by 1 for each ID.
    Marks the current session as ended.

    Call this when the conversation ends naturally. Include ONLY memory IDs
    that genuinely influenced your responses — not every memory retrieved.
    """
    session_id = session_id_ctx.get()
    return await process_feedback(used_memory_ids, session_id=session_id)


@mcp.tool()
async def conversation_search(query: str, limit: int = 5, source_llm: Optional[str] = None):
    """
    Search past conversations by semantic similarity (or full-text if embedding disabled).
    Returns: {conversation_id, title, source_llm, excerpt, date}
    """
    from backend.database.client import get_db
    from backend.memory.embedder import embed
    db = get_db()

    results = []
    try:
        if "conversations" not in db.table_names():
            return []
        tbl = db.open_table("conversations")
        where = "status = 'archived'"
        if source_llm:
            where += f" AND source_llm = '{source_llm}'"
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
    from backend.database.client import get_db
    db = get_db()
    try:
        if "conversations" not in db.table_names():
            return []
        tbl = db.open_table("conversations")
        where = "status = 'archived'"
        if source_llm:
            where += f" AND source_llm = '{source_llm}'"
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


def register_mcp(app):
    """Mount the MCP server's SSE application at /mcp."""
    app.mount("/mcp", mcp.sse_app())
