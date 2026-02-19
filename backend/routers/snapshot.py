from fastapi import APIRouter, HTTPException, Query
from backend.config import get_snapshot_token
from backend.memory.core import get_snapshot

router = APIRouter(prefix="/api/v1/snapshot", tags=["snapshot"])

@router.get("/text")
async def get_snapshot_text(token: str = Query(...)):
    # Verify token
    valid_token = get_snapshot_token()
    # Constant-time comparison in production, but here simple string eq is fine for MVP
    if token != valid_token:
        # Check against admin token? No, specific snapshot token.
        raise HTTPException(status_code=401, detail="Invalid or missing snapshot token")
        
    # Return plain text snapshot
    snapshot_md = await get_snapshot()
    # Since it's markdown, we return as plain text
    return snapshot_md
