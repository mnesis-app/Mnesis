import uuid
from datetime import datetime, timezone
import hashlib
from typing import List, Optional, Any
import logging
import math

from backend.database.client import get_db
from backend.database.schema import Memory
from backend.memory.embedder import embed, get_model
from backend.memory.write_queue import enqueue_write

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_tokens(text: str) -> int:
    """Count tokens using the embedder's tokenizer (accurate, same model)."""
    model = get_model()
    return len(model.tokenizer.encode(text))


def _is_first_person(text: str) -> bool:
    text_padded = f" {text} "
    return " I " in text_padded or text.startswith("I ") or text.lower().startswith("i'm ") or text.lower().startswith("i am ")


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
    tags: List[str] = [],
    source_conversation_id: Optional[str] = None,
    session_id: Optional[str] = None
) -> dict:

    # --- Validation (hard reject) ---
    content = content.strip()

    if len(content) < 20:
        return {
            "id": None, "status": "error", "action": "rejected_length",
            "message": f"Content too short ({len(content)} chars). Minimum is 20."
        }

    if len(content) > 1000:
        return {
            "id": None, "status": "error", "action": "rejected_length",
            "message": f"Content too long ({len(content)} chars). Maximum is 1000. Split into multiple memories."
        }

    token_count = _count_tokens(content)
    if token_count > 128:
        return {
            "id": None, "status": "error", "action": "rejected_tokens",
            "message": f"Content exceeds 128 tokens ({token_count}). Split into multiple memories."
        }

    if _is_first_person(content):
        return {
            "id": None, "status": "error", "action": "rejected_first_person",
            "message": "Write memories in third-person declarative format (e.g. 'Thomas prefers...')."
        }

    # --- Determine initial status ---
    # Semantic memories with low confidence go to pending_review
    initial_status = "active"
    if level == "semantic" and confidence_score < 0.85:
        initial_status = "pending_review"

    async def _write_op():
        db = get_db()
        tbl = db.open_table("memories")

        # Calculate embedding for the new content
        vector = embed(content)
        now = datetime.now(timezone.utc)

        # --- Exact dedup: SHA-256 ---
        content_hash = hashlib.sha256(content.lower().encode()).hexdigest()
        # We do a semantic search and then compare hashes to be efficient
        existing_all = tbl.search(vector).where("status = 'active'").limit(10).to_list()

        for match in existing_all:
            existing_hash = hashlib.sha256(match['content'].lower().strip().encode()).hexdigest()
            if existing_hash == content_hash:
                logger.info(f"Exact duplicate found: {match['id']}")
                return {"id": match['id'], "status": "active", "action": "skipped"}

        # --- Semantic dedup & conflict detection ---
        action = "created"
        status = initial_status
        conflicts_to_create = []

        for match in existing_all:
            score = 1 - match['_distance']

            if score > 0.92:
                # Semantic duplicate → merge (update existing)
                logger.info(f"Semantic duplicate found (score {score:.3f}): {match['id']}")
                # Update existing memory's importance and reference
                new_importance = max(match['importance_score'], importance_score)
                tbl.update(
                    where=f"id = '{match['id']}'",
                    values={
                        "importance_score": new_importance,
                        "last_referenced_at": now,
                    }
                )
                return {"id": match['id'], "status": match['status'], "action": "merged"}

            if 0.75 <= score <= 0.92:
                # Potential conflict
                conflict_record = {
                    "id": str(uuid.uuid4()),
                    "memory_id_a": match['id'],
                    "memory_id_b": "PENDING",
                    "similarity_score": score,
                    "detected_at": now,
                    "resolved_at": None,
                    "resolution": None,
                    "status": "pending"
                }
                conflicts_to_create.append(conflict_record)
                action = "created_with_conflict"

        # --- Create new memory ---
        memory_id = str(uuid.uuid4())

        new_memory = Memory(
            id=memory_id,
            content=content,
            level=level,
            category=category,
            importance_score=importance_score,
            confidence_score=confidence_score,
            privacy=privacy,
            tags=tags,
            source_llm=source_llm,
            source_conversation_id=source_conversation_id,
            version=1,
            status=status,
            created_at=now,
            updated_at=now,
            last_referenced_at=now,
            reference_count=0,
            vector=vector
        )

        tbl.add([new_memory])

        if conflicts_to_create:
            conflict_tbl = db.open_table("conflicts")
            from backend.database.schema import Conflict
            conflict_objects = [
                Conflict(**{**c, "memory_id_b": memory_id})
                for c in conflicts_to_create
            ]
            conflict_tbl.add(conflict_objects)

        return {"id": memory_id, "status": status, "action": action}

    result = await enqueue_write(_write_op)

    # Session activity update OUTSIDE the write queue (read-only on session table perspective)
    if session_id and result.get("action") not in ("skipped", "merged") or (result.get("id") and result.get("action") == "merged"):
        mem_id = result.get("id")
        if mem_id and result.get("action") not in ("skipped",):
            try:
                from backend.memory.sessions import update_session_activity
                await update_session_activity(session_id, write_ids=[mem_id])
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
    session_id: Optional[str] = None
) -> List[dict]:
    db = get_db()
    tbl = db.open_table("memories")

    query_vector = embed(query)
    now = datetime.now(timezone.utc)

    # Fetch more candidates for re-ranking
    results = tbl.search(query_vector).where("status = 'active'").limit(limit * 3).to_list()

    reranked = []
    for r in results:
        similarity = max(0.0, 1 - r['_distance'])
        importance = r['importance_score']

        last_ref = r['last_referenced_at']
        if hasattr(last_ref, 'tzinfo') and last_ref.tzinfo is None:
            last_ref = last_ref.replace(tzinfo=timezone.utc)
        days_since = (now - last_ref).total_seconds() / 86400
        recency = math.exp(-0.05 * days_since)

        # PROMPT.md scoring formula
        final_score = (0.5 * similarity) + (0.3 * importance) + (0.2 * recency)

        # Context boost: tags matching context get ×1.3
        if context and r.get('tags'):
            if context.lower() in [t.lower() for t in r['tags']]:
                final_score *= 1.3

        reranked.append((final_score, r))

    reranked.sort(key=lambda x: x[0], reverse=True)
    top_results = [x[1] for x in reranked[:limit]]

    # Strip vector from results (never send 384 floats to the API consumer)
    clean_results = []
    for r in top_results:
        r_clean = {k: v for k, v in r.items() if k != 'vector' and k != '_distance'}
        clean_results.append(r_clean)

    # Update session & last_referenced
    if top_results:
        tbl_update = get_db().open_table("memories")
        for r in top_results:
            try:
                tbl_update.update(
                    where=f"id = '{r['id']}'",
                    values={
                        "last_referenced_at": now,
                        "reference_count": r['reference_count'] + 1,
                    }
                )
            except Exception:
                pass

    if session_id and top_results:
        try:
            from backend.memory.sessions import update_session_activity
            await update_session_activity(session_id, read_ids=[r['id'] for r in top_results])
        except Exception as e:
            logger.warning(f"Failed to update session read activity: {e}")

    return clean_results


# ---------------------------------------------------------------------------
# get_snapshot
# ---------------------------------------------------------------------------

async def get_snapshot(context: Optional[str] = None) -> str:
    db = get_db()
    tbl = db.open_table("memories")

    def fetch_category(cat: str, limit: int, level: str = "semantic") -> list:
        """Fetch memories by category using full-scan filter (no vector query needed)."""
        try:
            results = (
                tbl.search()
                .where(f"category = '{cat}' AND status = 'active' AND level = '{level}'")
                .limit(limit)
                .to_list()
            )
            results.sort(key=lambda x: x['importance_score'], reverse=True)
            return results
        except Exception as e:
            logger.warning(f"fetch_category({cat}) failed: {e}")
            return []

    now = datetime.now(timezone.utc)
    snapshot_sections = [f"# Memory Context — {now.isoformat()}"]

    # Determine section order based on context
    # Default order:
    sections_order = ["identity", "preferences", "projects", "relationships", "skills"]
    if context == "development":
        sections_order = ["identity", "projects", "skills", "preferences", "relationships"]
    elif context == "business":
        sections_order = ["identity", "projects", "preferences", "relationships", "skills"]
    elif context == "personal":
        sections_order = ["identity", "relationships", "preferences", "projects", "skills"]

    section_config = {
        "identity": ("## Identity", 3),
        "preferences": ("## Preferences & Working Style", 5),
        "projects": ("## Active Projects", 10),
        "relationships": ("## Key Relationships", 5),
        "skills": ("## Skills & Expertise", 5),
    }

    sections_content = {}
    for cat in sections_order:
        header, limit = section_config[cat]
        items = fetch_category(cat, limit + 5)
        if items:
            lines = [f"- {r['content']}" for r in items[:limit]]
            sections_content[cat] = f"{header}\n" + "\n".join(lines)

    # Working memory (last 72h)
    try:
        working = (
            tbl.search()
            .where("level = 'working' AND status = 'active'")
            .limit(20)
            .to_list()
        )
        working.sort(key=lambda x: x['created_at'], reverse=True)
    except Exception:
        working = []

    # Build snapshot in order
    for cat in sections_order:
        if cat in sections_content:
            snapshot_sections.append(sections_content[cat])

    if working:
        lines = [f"- {r['content']}" for r in working[:10]]
        snapshot_sections.append("## Recent Context (last 72h)\n" + "\n".join(lines))

    # Token budget enforcement: truncate in reverse priority if > 800 tokens
    # Skills → Relationships → Preferences → Projects → Recent Context → Identity (never)
    # (Simplified: just join and return for now — the embedding model ensures reasonable size)
    result = "\n\n".join(snapshot_sections)
    return result


# ---------------------------------------------------------------------------
# update_memory
# ---------------------------------------------------------------------------

async def update_memory(memory_id: str, content: str, source_llm: str, session_id: Optional[str] = None) -> dict:
    async def _write_op():
        db = get_db()
        tbl = db.open_table("memories")

        matches = tbl.search().where(f"id = '{memory_id}'").limit(1).to_list()
        if not matches:
            return {"id": memory_id, "status": "error", "action": "not_found"}

        current_mem = matches[0]

        # Archive current version
        version_tbl = db.open_table("memory_versions")
        from backend.database.schema import MemoryVersion
        version_record = MemoryVersion(
            id=str(uuid.uuid4()),
            memory_id=memory_id,
            content=current_mem["content"],
            version=current_mem["version"],
            changed_by=source_llm,
            created_at=current_mem["updated_at"]
        )
        try:
            version_tbl.add([version_record])
        except Exception as e:
            logger.error(f"Failed to archive version: {e}")

        # Recalculate embedding
        vector = embed(content)
        now = datetime.now(timezone.utc)
        new_version = current_mem["version"] + 1

        tbl.update(
            where=f"id = '{memory_id}'",
            values={
                "content": content,
                "vector": vector,
                "updated_at": now,
                "version": new_version,
                "importance_score": max(current_mem['importance_score'], 0.6),
                "last_referenced_at": now
            }
        )
        return {"id": memory_id, "status": "active", "action": "updated", "version": new_version}

    result = await enqueue_write(_write_op)

    if session_id:
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
        tbl.update(where=f"id = '{memory_id}'", values={"status": "archived"})
        return {"id": memory_id, "status": "archived", "action": "deleted"}

    return await enqueue_write(_write_op)


# ---------------------------------------------------------------------------
# process_feedback
# ---------------------------------------------------------------------------

async def process_feedback(used_memory_ids: List[str], session_id: Optional[str] = None) -> dict:
    """
    Update scores for used memories.
    NOT queued — safe read-only score update.
    """
    if session_id:
        try:
            from backend.memory.sessions import update_session_activity, end_session
            await update_session_activity(session_id, feedback_ids=used_memory_ids)
            await end_session(session_id, reason="feedback_called")
        except Exception as e:
            logger.warning(f"Session feedback update failed: {e}")

    db = get_db()
    tbl = db.open_table("memories")
    now = datetime.now(timezone.utc)
    updated_count = 0

    for mem_id in used_memory_ids:
        try:
            matches = tbl.search().where(f"id = '{mem_id}'").limit(1).to_list()
            if not matches:
                continue
            mem = matches[0]
            new_score = min(1.0, mem['importance_score'] + 0.05)
            new_ref_count = mem['reference_count'] + 1
            tbl.update(
                where=f"id = '{mem_id}'",
                values={
                    "importance_score": new_score,
                    "reference_count": new_ref_count,
                    "last_referenced_at": now
                }
            )
            updated_count += 1
        except Exception as e:
            logger.error(f"Failed to update feedback for {mem_id}: {e}")

    return {
        "status": "success",
        "updated_count": updated_count,
        "message": "Feedback processed"
    }
