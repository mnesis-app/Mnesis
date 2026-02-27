"""
MCP Bearer Token Authentication Middleware
==========================================
Validates Authorization: Bearer <token> headers on all /mcp routes.
Tokens are stored in config.yaml under llm_client_keys.
"""
import logging
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from backend.config import load_config
from backend.security import constant_time_equal, extract_bearer_token, sha256_hex

logger = logging.getLogger(__name__)

_KNOWN_SCOPES = {"read", "write", "sync", "admin"}
_DEFAULT_SCOPES = {"read", "write", "sync"}


def _is_sha256_hex(value: str) -> bool:
    text = str(value or "").strip().lower()
    if len(text) != 64:
        return False
    return all(ch in "0123456789abcdef" for ch in text)


def normalize_client_scopes(value: Any) -> set[str]:
    if isinstance(value, str):
        raw_items = [part.strip().lower() for part in value.split(",") if part.strip()]
    elif isinstance(value, (list, tuple, set)):
        raw_items = [str(part).strip().lower() for part in value if str(part).strip()]
    else:
        raw_items = []

    if not raw_items:
        scopes = set(_DEFAULT_SCOPES)
    else:
        scopes = set()
        for item in raw_items:
            if item in {"*", "all"}:
                scopes.update({"admin", "sync", "read", "write"})
                continue
            if item in _KNOWN_SCOPES:
                scopes.add(item)
        if not scopes:
            scopes = set(_DEFAULT_SCOPES)

    if "admin" in scopes:
        scopes.update({"sync", "read", "write"})
    if "sync" in scopes:
        scopes.update({"read", "write"})
    return scopes


def token_scope_allowed(
    scopes: set[str] | list[str] | tuple[str, ...] | None,
    required_scope: str,
) -> bool:
    required = str(required_scope or "").strip().lower()
    if not required:
        return True
    current = normalize_client_scopes(scopes)
    if "admin" in current:
        return True
    if required in current:
        return True
    if required in {"read", "write"} and "sync" in current:
        return True
    return False


def _iter_client_key_entries(config: dict) -> list[dict[str, Any]]:
    raw_keys = config.get("llm_client_keys", {})
    if not isinstance(raw_keys, dict):
        raw_keys = {}

    entries: list[dict[str, Any]] = []
    for raw_name, raw_value in raw_keys.items():
        name = str(raw_name or "").strip() or "mcp"
        if isinstance(raw_value, dict):
            if raw_value.get("enabled") is False:
                continue
            credential = (
                str(raw_value.get("hash") or "").strip()
                or str(raw_value.get("sha256") or "").strip()
                or str(raw_value.get("token_hash") or "").strip()
                or str(raw_value.get("value") or "").strip()
                or str(raw_value.get("token") or "").strip()
            )
            scopes = normalize_client_scopes(raw_value.get("scopes"))
        else:
            credential = str(raw_value or "").strip()
            scopes = set(_DEFAULT_SCOPES)

        if not credential:
            continue
        entries.append(
            {
                "name": name,
                "credential": credential,
                "is_hash": _is_sha256_hex(credential),
                "scopes": sorted(scopes),
            }
        )
    return entries


def authenticate_mcp_token(raw_token: str, config: dict | None = None) -> dict[str, Any] | None:
    """
    Returns auth context when token is accepted, else None.
    """
    cfg = config if isinstance(config, dict) else load_config()
    sec = cfg.get("security", {}) if isinstance(cfg.get("security"), dict) else {}
    if not bool(sec.get("enforce_mcp_auth", True)):
        return {
            "name": "mcp-auth-disabled",
            "scopes": sorted({"admin", "sync", "read", "write"}),
            "kind": "security_bypass",
        }

    token = str(raw_token or "").strip()
    if not token:
        return None

    token_hash = sha256_hex(token)
    for entry in _iter_client_key_entries(cfg):
        candidate = str(entry.get("credential") or "").strip()
        if not candidate:
            continue
        if bool(entry.get("is_hash")):
            if constant_time_equal(token_hash, candidate.lower()):
                return {
                    "name": str(entry.get("name") or "mcp"),
                    "scopes": sorted(normalize_client_scopes(entry.get("scopes"))),
                    "kind": "llm_client_key",
                }
        elif constant_time_equal(token, candidate):
            # Legacy plaintext support (kept for migration safety).
            return {
                "name": str(entry.get("name") or "mcp"),
                "scopes": sorted(normalize_client_scopes(entry.get("scopes"))),
                "kind": "llm_client_key",
            }

    allow_snapshot_fallback = bool(sec.get("allow_snapshot_token_for_mcp", True))
    snapshot_token = str(cfg.get("snapshot_read_token") or "")
    if allow_snapshot_fallback and snapshot_token and constant_time_equal(token, snapshot_token):
        return {
            "name": "snapshot",
            "scopes": sorted({"read"}),
            "kind": "snapshot_fallback",
        }

    return None


def classify_mcp_token(raw_token: str, config: dict | None = None) -> str | None:
    auth_ctx = authenticate_mcp_token(raw_token, config=config)
    if not auth_ctx:
        return None
    return str(auth_ctx.get("name") or "mcp")


class MCPAuthMiddleware:
    """
    Validates Bearer tokens for /mcp/* routes only.
    Other routes pass through unmodified.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        if not path.startswith("/mcp"):
            return await self.app(scope, receive, send)

        request = Request(scope, receive)
        raw_token = extract_bearer_token(request)
        if not raw_token:
            response = JSONResponse(
                status_code=401,
                content={"detail": "MCP routes require a Bearer token. Register a client in Settings."},
            )
            return await response(scope, receive, send)

        config = load_config()
        auth_ctx = authenticate_mcp_token(raw_token, config=config)
        if auth_ctx:
            try:
                request.state.mcp_client_name = str(auth_ctx.get("name") or "mcp")
                request.state.mcp_client_scopes = sorted(normalize_client_scopes(auth_ctx.get("scopes")))
                request.state.mcp_auth_kind = str(auth_ctx.get("kind") or "llm_client_key")
            except Exception:
                pass
            return await self.app(scope, receive, send)

        client_host = request.client.host if request.client else "unknown"
        logger.warning(f"Rejected MCP request with invalid token from {client_host}")
        response = JSONResponse(
            status_code=403,
            content={"detail": "Invalid token. Check the API key in Settings → LLM Clients."},
        )
        return await response(scope, receive, send)
