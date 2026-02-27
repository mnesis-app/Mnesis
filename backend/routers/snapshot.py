from fastapi import APIRouter, HTTPException, Query, Request
from backend.config import get_snapshot_token, load_config
from backend.memory.core import get_snapshot
from backend.security import constant_time_equal, extract_bearer_token
from backend.auth import authenticate_mcp_token, token_scope_allowed

router = APIRouter(prefix="/api/v1/snapshot", tags=["snapshot"])


def _is_snapshot_token_valid(candidate: str) -> bool:
    token = str(candidate or "").strip()
    if not token:
        return False
    valid_token = get_snapshot_token()
    return constant_time_equal(token, valid_token)


@router.get("/text")
async def get_snapshot_text(request: Request, token: str | None = Query(default=None)):
    cfg = load_config()
    security = cfg.get("security", {}) if isinstance(cfg.get("security"), dict) else {}
    allow_query = bool(security.get("allow_snapshot_query_token", True))

    bearer = extract_bearer_token(request)
    if bearer:
        # Dedicated snapshot token path.
        if _is_snapshot_token_valid(bearer):
            snapshot_md = await get_snapshot()
            return snapshot_md
        # Dedicated MCP key path (requires read scope).
        auth_ctx = authenticate_mcp_token(bearer, config=cfg)
        auth_kind = str((auth_ctx or {}).get("kind") or "")
        if auth_kind == "llm_client_key" and auth_ctx and token_scope_allowed(auth_ctx.get("scopes"), "read"):
            snapshot_md = await get_snapshot()
            return snapshot_md
        if auth_kind == "llm_client_key" and auth_ctx and not token_scope_allowed(auth_ctx.get("scopes"), "read"):
            raise HTTPException(status_code=403, detail="Token is missing required 'read' scope.")

    if allow_query and token and _is_snapshot_token_valid(token):
        snapshot_md = await get_snapshot()
        return snapshot_md

    detail = "Invalid or missing snapshot token"
    if not allow_query:
        detail = "Invalid snapshot token. Query token disabled; use Authorization: Bearer."
    raise HTTPException(status_code=401, detail=detail)
