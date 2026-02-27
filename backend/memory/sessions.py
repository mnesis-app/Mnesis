from datetime import datetime, timezone
import uuid
import logging
from typing import List, Optional

from backend.database.client import get_db
from backend.database.schema import Session
from backend.memory.write_queue import enqueue_write
from backend.utils.context import mcp_client_name_ctx

logger = logging.getLogger(__name__)


def _escape_sql(value: str) -> str:
    return str(value or "").replace("'", "''")

async def start_session(source_llm: str, api_key_id: Optional[str] = None) -> str:
    db = get_db()
    tbl = db.open_table("sessions")
    
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    
    session = Session(
        id=session_id,
        api_key_id=api_key_id or "unknown",
        source_llm=source_llm,
        started_at=now,
        ended_at=None,
        end_reason=None,
        memory_ids_read=[],
        memory_ids_written=[],
        memory_ids_feedback=[]
    )
    
    async def _write_op():
        tbl.add([session])

    try:
        await enqueue_write(_write_op)
        return session_id
    except Exception as e:
        logger.error(f"Failed to create session: {e}")
        return session_id # Return ID anyway so flow continues?


def _session_identity_defaults() -> tuple[str, str]:
    client_name = str(mcp_client_name_ctx.get() or "").strip().lower()
    if client_name:
        return client_name, client_name
    return "mcp", "unknown"

async def update_session_activity(
    session_id: str, 
    read_ids: Optional[List[str]] = None,
    write_ids: Optional[List[str]] = None,
    feedback_ids: Optional[List[str]] = None
):
    if not session_id:
        return

    read_ids = read_ids or []
    write_ids = write_ids or []
    feedback_ids = feedback_ids or []

    db = get_db()
    tbl = db.open_table("sessions")
    
    # Read-modify-write
    escaped_session_id = _escape_sql(session_id)
    matches = tbl.search().where(f"id = '{escaped_session_id}'").limit(1).to_list()
    inferred_source_llm, inferred_api_key_id = _session_identity_defaults()
    if not matches:
        # Auto-create session if not found (lazy init)
        # We don't have source_llm here easily unless passed. 
        # But we can default it or try to fetch?
        # Let's just create with "unknown" or passed param?
        # We'll allow session_id to be created.
        logger.info(f"Session {session_id} not found, auto-creating.")
        # We need source_llm. Maybe we should pass it to update_session_activity too?
        # For now, "unknown" or "auto".
        
        # Calling start_session
        # We need to await? start_session is async.
        # But start_session generates new ID. We want to use specific ID.
        # Let's extract creation logic or just insert here.
        
        now = datetime.now(timezone.utc)
        session = Session(
            id=session_id,
            api_key_id=inferred_api_key_id,
            source_llm=inferred_source_llm,
            started_at=now,
            ended_at=None,
            end_reason=None,
            memory_ids_read=[],
            memory_ids_written=[],
            memory_ids_feedback=[]
        )
        async def _write_create():
            tbl.add([session])

        try:
             await enqueue_write(_write_create)
        except Exception:
             pass # Race condition?
             
        matches = [session.model_dump()]
        
    session = matches[0]
    
    # Merge lists
    # Note: simple list concatenation. De-dup if needed.
    new_read = list(set((session['memory_ids_read'] or []) + read_ids))
    new_write = list(set((session['memory_ids_written'] or []) + write_ids))
    new_feedback = list(set((session['memory_ids_feedback'] or []) + feedback_ids))
    
    # Create updated session object
    # We need to construct Session model or dict.
    # session is a dict from to_list().
    
    updated_session = session.copy()
    updated_session['memory_ids_read'] = new_read
    updated_session['memory_ids_written'] = new_write
    updated_session['memory_ids_feedback'] = new_feedback
    if str(updated_session.get("api_key_id") or "").strip().lower() in {"", "unknown"} and inferred_api_key_id != "unknown":
        updated_session["api_key_id"] = inferred_api_key_id
    if str(updated_session.get("source_llm") or "").strip().lower() in {"", "mcp", "unknown"} and inferred_source_llm:
        updated_session["source_llm"] = inferred_source_llm
    
    # Verify types (list of str)
    # LanceDB strict typing might need explicit conversion if they are not strings?
    # They should be strings.
    
    async def _write_update():
        tbl.delete(f"id = '{escaped_session_id}'")
        tbl.add([updated_session])

    try:
        await enqueue_write(_write_update)
    except Exception as e:
        logger.error(f"Failed to update session {session_id}: {e}")

async def end_session(session_id: str, reason: str = "unknown"):
    if not session_id:
        return

    db = get_db()
    tbl = db.open_table("sessions")
    now = datetime.now(timezone.utc)
    escaped_session_id = _escape_sql(session_id)
    
    async def _write_op():
        tbl.update(
            where=f"id = '{escaped_session_id}'",
            values={
                "ended_at": now,
                "end_reason": reason
            }
        )

    try:
        await enqueue_write(_write_op)
    except Exception as e:
        logger.error(f"Failed to end session {session_id}: {e}")
