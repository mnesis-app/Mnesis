from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional
from backend.memory.core import create_memory, search_memories, get_snapshot
from backend.database.client import get_db

router = APIRouter(prefix="/api/v1/memories", tags=["memories"])

class MemoryCreate(BaseModel):
    content: str
    category: str
    level: str
    source_llm: str
    importance_score: float = 0.5
    privacy: str = "public"
    tags: List[str] = []

@router.post("/")
async def create_memory_endpoint(mem: MemoryCreate):
    try:
        result = await create_memory(
            content=mem.content,
            category=mem.category,
            level=mem.level,
            source_llm=mem.source_llm,
            importance_score=mem.importance_score,
            privacy=mem.privacy,
            tags=mem.tags
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/")
async def list_memories(query: Optional[str] = None, limit: int = 10):
    if query:
        return await search_memories(query, limit)
    else:
        # Return recent memories
        tbl = get_db().open_table("memories")
        return tbl.search().where("status != 'archived'").limit(limit).to_list()

@router.get("/snapshot")
async def get_snapshot_endpoint(context: Optional[str] = None):
    return {"snapshot": await get_snapshot(context)}

class MemoryUpdate(BaseModel):
    content: str
    source_llm: str

@router.put("/{memory_id}")
async def update_memory_endpoint(memory_id: str, mem: MemoryUpdate):
    from backend.memory.core import update_memory
    try:
        return await update_memory(memory_id, mem.content, mem.source_llm)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/stats")
async def get_stats():
    from backend.database.client import get_db
    db = get_db()
    try:
        if "memories" not in db.table_names():
             return {"total": 0}
        
        tbl = db.open_table("memories")
        # Count only non-archived memories
        # search() returns all matching rows. 
        # We need to filter by status != 'archived'.
        try:
             # This is an approximation if table is huge, but accurate for <100k
             active_memories = tbl.search().where("status != 'archived'").limit(100000).to_list()
             total = len(active_memories)
        except Exception:
             total = 0

        return {
            "total_memories": total,
            "active": total, 
        }
    except Exception:
        return {"total_memories": 0}

@router.delete("/{memory_id}")
async def delete_memory_endpoint(memory_id: str):
    from backend.memory.core import delete_memory
    try:
        return await delete_memory(memory_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
