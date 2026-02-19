from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone
from backend.database.client import get_db

router = APIRouter(prefix="/api/v1/conflicts", tags=["conflicts"])

@router.get("/")
async def list_conflicts():
    db = get_db()
    try:
        if "conflicts" not in db.table_names():
            return []
            
        tbl = db.open_table("conflicts")
        # Pending conflicts
        conflicts = tbl.search().where("status = 'pending'").to_list()
        
        if not conflicts:
            return []
        
        # We need to enrich with memory content
        mem_tbl = db.open_table("memories")
        enriched = []
        for c in conflicts:
            # Fetch mem A and B
            try:
                mem_a_list = mem_tbl.search().where(f"id = '{c['memory_id_a']}'").limit(1).to_list()
                mem_b_list = mem_tbl.search().where(f"id = '{c['memory_id_b']}'").limit(1).to_list()
                
                if mem_a_list and mem_b_list:
                    c['memory_a'] = mem_a_list[0]
                    c['memory_b'] = mem_b_list[0]
                    enriched.append(c)
            except Exception:
                continue
                
        return enriched
    except Exception as e:
        print(f"Error listing conflicts: {e}")
        return []

class ConflictResolve(BaseModel):
    resolution: str # "kept_a" | "kept_b" | "merged" | "both_valid"
    merged_content: Optional[str] = None

@router.post("/{conflict_id}/resolve")
async def resolve_conflict(conflict_id: str, payload: ConflictResolve):
    db = get_db()
    tbl = db.open_table("conflicts")
    
    # Verify conflict exists
    conflicts = tbl.search().where(f"id = '{conflict_id}'").limit(1).to_list()
    if not conflicts:
         raise HTTPException(status_code=404, detail="Conflict not found")
    conflict = conflicts[0]
    
    now = datetime.now(timezone.utc)
    
    from backend.memory.core import update_memory, delete_memory
    
    try:
        if payload.resolution == "kept_a":
            # Delete B
            await delete_memory(conflict['memory_id_b'])
            
        elif payload.resolution == "kept_b":
            # Delete A
            await delete_memory(conflict['memory_id_a'])
            
        elif payload.resolution == "merged":
            if not payload.merged_content:
                 raise HTTPException(status_code=400, detail="Merged content required")
            # Update A with merged content
            await update_memory(conflict['memory_id_a'], payload.merged_content, "manual")
            # Delete B
            await delete_memory(conflict['memory_id_b'])
            
        elif payload.resolution == "both_valid":
            # Do nothing to memories
            pass
            
        # Update conflict status
        tbl.update(
            where=f"id = '{conflict_id}'",
            values={
                "status": "resolved",
                "resolution": payload.resolution,
                "resolved_at": now
            }
        )
        
        return {"status": "resolved"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
