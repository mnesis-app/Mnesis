from datetime import datetime, timezone
import uuid
import logging
from typing import List, Optional
from backend.database.client import get_db
from backend.database.schema import Session

logger = logging.getLogger(__name__)

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
    
    try:
        tbl.add([session])
        return session_id
    except Exception as e:
        logger.error(f"Failed to create session: {e}")
        return session_id # Return ID anyway so flow continues?

async def update_session_activity(
    session_id: str, 
    read_ids: List[str] = [], 
    write_ids: List[str] = [],
    feedback_ids: List[str] = []
):
    if not session_id:
        return

    db = get_db()
    tbl = db.open_table("sessions")
    
    # Read-modify-write
    matches = tbl.search().where(f"id = '{session_id}'").limit(1).to_list()
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
            api_key_id="unknown",
            source_llm="mcp", # Default
            started_at=now,
            ended_at=None,
            end_reason=None,
            memory_ids_read=[],
            memory_ids_written=[],
            memory_ids_feedback=[]
        )
        try:
             tbl.add([session])
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
    
    # Verify types (list of str)
    # LanceDB strict typing might need explicit conversion if they are not strings?
    # They should be strings.
    
    try:
        # Delete old
        tbl.delete(f"id = '{session_id}'")
        # Insert new
        # We need to convert dict back to Session model to be safe?
        # Or just list of dicts.
        tbl.add([updated_session])
    except Exception as e:
        logger.error(f"Failed to update session {session_id}: {e}")

async def end_session(session_id: str, reason: str = "unknown"):
    if not session_id:
        return

    db = get_db()
    tbl = db.open_table("sessions")
    now = datetime.now(timezone.utc)
    
    try:
        tbl.update(
            where=f"id = '{session_id}'",
            values={
                "ended_at": now,
                "end_reason": reason
            }
        )
    except Exception as e:
        logger.error(f"Failed to end session {session_id}: {e}")
