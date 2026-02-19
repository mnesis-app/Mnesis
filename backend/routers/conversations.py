from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from backend.database.client import get_db

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])

@router.get("/")
async def list_conversations(
    source_llm: Optional[str] = None, 
    limit: int = 20, 
    offset: int = 0
):
    try:
        db = get_db()
        if "conversations" not in db.table_names():
            return []
            
        tbl = db.open_table("conversations")
        
        query = tbl.search().where("status != 'deleted'")
        if source_llm:
            query = query.where(f"source_llm = '{source_llm}'")
            
        # Offset not directly supported in LanceDB search(), need to slice
        # limit(offset + limit).to_list()[offset:]
        
        results = query.limit(offset + limit).to_list()
        return results[offset:]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{conversation_id}")
async def delete_conversation(conversation_id: str):
    """Soft delete a conversation."""
    try:
        db = get_db()
        if "conversations" not in db.table_names():
            raise HTTPException(status_code=404, detail="Conversation not found")
            
        tbl = db.open_table("conversations")
        
        # Check existence
        matches = tbl.search().where(f"id = '{conversation_id}'").limit(1).to_list()
        if not matches:
             raise HTTPException(status_code=404, detail="Conversation not found")
             
        # Soft delete
        tbl.update(
            where=f"id = '{conversation_id}'",
            values={"status": "deleted"}
        )
        return {"id": conversation_id, "status": "deleted", "action": "deleted"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/search")
async def search_conversations(
    query: str, 
    limit: int = 5,
    source_llm: Optional[str] = None
):
    # Conversations might not be embedded if 'embed_messages=False' (default).
    # If not embedded, we use full text search or simple filtering?
    # LanceDB FTS requires index.
    # For now, we'll do simple string matching on summary or title if no vector.
    # If we had vectors, we'd use embed(query).
    
    # Assuming no vectors on conversations table itself, only messages?
    # Schema says messages have vector. Conversations have title/summary.
    
    # We will implement simple filter for now.
    try:
        db = get_db()
        if "conversations" not in db.table_names():
            return []
        
        tbl = db.open_table("conversations")
        
        # LanceDB basic SQL-like filter
        # "title LIKE '%query%' OR summary LIKE '%query%'"
        # WARNING: SQL injection risk if not parameterized.
        # But LanceDB SQL is limited. 
        # Safer: fetch recent and filter in Python for now (MVP).
        
        all_convs = tbl.search().limit(100).to_list()
        
        q_lower = query.lower()
        filtered = [
            c for c in all_convs 
            if q_lower in (c.get('title') or '').lower() or q_lower in (c.get('summary') or '').lower()
        ]
        
        if source_llm:
            filtered = [c for c in filtered if c.get('source_llm') == source_llm]
            
        return filtered[:limit]
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.get("/{conversation_id}")
async def get_conversation(conversation_id: str):
    """Get conversation details including messages."""
    try:
        db = get_db()
        
        # Fetch conversation
        if "conversations" not in db.table_names():
            raise HTTPException(status_code=404, detail="Conversation not found")
            
        conv_tbl = db.open_table("conversations")
        matches = conv_tbl.search().where(f"id = '{conversation_id}'").limit(1).to_list()
        
        if not matches:
             raise HTTPException(status_code=404, detail="Conversation not found")
             
        conversation = matches[0]
        
        # Fetch messages
        messages = []
        if "messages" in db.table_names():
            msg_tbl = db.open_table("messages")
            # LanceDB sort might be limited, but we can sort in python
            try:
                # Filter by conversation_id
                msgs = msg_tbl.search().where(f"conversation_id = '{conversation_id}'").limit(1000).to_list()
                # Sort by timestamp
                messages = sorted(msgs, key=lambda x: x.get('timestamp') or 0)
            except Exception as e:
                print(f"Error fetching messages: {e}")
                
        # Combine
        conversation['messages'] = messages
        return conversation
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
