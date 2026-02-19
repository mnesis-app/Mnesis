"""
MCP Bearer Token Authentication Middleware
==========================================
Validates Authorization: Bearer <token> headers on all /mcp routes.
Tokens are stored in config.yaml under llm_client_keys: {name: sha256(token)}.

Authentication tiers:
  - /mcp/* routes: require a registered Bearer token (per LLM client key)
  - /api/v1/* routes: no auth required (local UI only — protected by CORS)
  - /api/v1/snapshot/text: requires snapshot_read_token (handled in router)
"""
import hashlib
import logging
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from backend.config import load_config

logger = logging.getLogger(__name__)


class MCPAuthMiddleware(BaseHTTPMiddleware):
    """
    Validates Bearer tokens for /mcp/* routes only.
    Other routes pass through unmodified.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Only protect MCP routes
        if not path.startswith("/mcp"):
            return await call_next(request)

        # Allow SSE subscribe endpoint without auth (needed for handshake)
        # The spec allows this as the actual tool calls come via POST anyway.
        # Uncomment to enforce strict auth on SSE endpoint too:
        # if path == "/mcp/sse":
        #     return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "MCP routes require a Bearer token. Register a client in Settings."}
            )

        raw_token = auth_header.removeprefix("Bearer ").strip()
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

        config = load_config()
        registered_keys = config.get("llm_client_keys", {})  # {name: sha256_hash}

        if token_hash in registered_keys.values():
            # Token valid — proceed
            return await call_next(request)

        # Also allow the snapshot read token as a fallback (handles ChatGPT fallback scenario)
        snapshot_token = config.get("snapshot_read_token", "")
        if snapshot_token and raw_token == snapshot_token:
            return await call_next(request)

        logger.warning(f"Rejected MCP request with invalid token from {request.client.host}")
        return JSONResponse(
            status_code=403,
            content={"detail": "Invalid token. Check the API key in Settings → LLM Clients."}
        )
