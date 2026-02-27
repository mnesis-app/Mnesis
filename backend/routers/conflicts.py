import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from backend.memory.core import count_pending_conflicts, list_pending_conflicts, resolve_pending_conflict

router = APIRouter(prefix="/api/v1/conflicts", tags=["conflicts"])
logger = logging.getLogger(__name__)


def _internal_error(message: str, exc: Exception | None = None) -> HTTPException:
    if exc is not None:
        logger.exception(message)
    return HTTPException(status_code=500, detail=message)


@router.get("/")
async def list_conflicts(limit: int = 100):
    try:
        return await list_pending_conflicts(limit=limit)
    except Exception as e:
        raise _internal_error("Failed to list conflicts.", e)


@router.get("/count")
async def count_conflicts():
    pending = await count_pending_conflicts(limit=200000)
    return {"pending": pending}


class ConflictResolve(BaseModel):
    resolution: str  # "merged" | "versioned" | "overwritten"
    merged_content: Optional[str] = None


@router.post("/{conflict_id}/resolve")
async def resolve_conflict(conflict_id: str, payload: ConflictResolve):
    try:
        result = await resolve_pending_conflict(
            conflict_id=conflict_id,
            resolution=payload.resolution,
            merged_content=payload.merged_content,
            resolver_source="manual",
        )
    except Exception as e:
        raise _internal_error("Failed to resolve conflict.", e)

    if result.get("status") == "error":
        msg = result.get("message", "Unable to resolve conflict")
        code = 404 if "not found" in msg.lower() else 400
        raise HTTPException(status_code=code, detail=msg)
    return result
