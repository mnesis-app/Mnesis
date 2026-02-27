from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
import os
import asyncio
import threading
import logging
import json

from backend.database.client import init_tables
from backend.memory.write_queue import start_write_worker
from backend.memory.conversation_analysis_jobs import start_analysis_job_worker
from backend.routers import memories, admin, conflicts, conversations, snapshot, import_export, search, chat
from backend.auth import MCPAuthMiddleware
from backend.config import load_config
from backend.security import (
    AdminRouteAccessMiddleware,
    MutationClientGuardMiddleware,
    RequestMetricsMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="Mnesis API", version="0.1.0")


def _trusted_hosts_from_config() -> list[str]:
    defaults = ["127.0.0.1", "localhost", "testserver"]
    hosts: list[str] = list(defaults)

    env_hosts = str(os.environ.get("MNESIS_TRUSTED_HOSTS") or "").strip()
    if env_hosts:
        hosts = [h.strip() for h in env_hosts.split(",") if h.strip()]

    try:
        cfg = load_config()
        security_cfg = cfg.get("security", {}) if isinstance(cfg.get("security"), dict) else {}
        configured = security_cfg.get("trusted_hosts")
        if isinstance(configured, list):
            for raw in configured:
                value = str(raw or "").strip()
                if value and value not in hosts:
                    hosts.append(value)
    except Exception:
        pass

    deduped: list[str] = []
    seen: set[str] = set()
    for host in hosts:
        key = host.lower().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(host)
    return deduped or defaults

# ─── Trusted Host Guard ───────────────────────────────────────────────────────
app.add_middleware(TrustedHostMiddleware, allowed_hosts=_trusted_hosts_from_config())

# ─── CORS ───────────────────────────────────────────────────────────────────
# Allow Vite dev server and the Electron renderer (app://.)
origins = [
    "http://localhost:5173",
    "http://localhost:7860",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:7860",
    "app://.",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── MCP Auth Middleware ──────────────────────────────────────────────────────
# Must be added AFTER CORS so CORS headers are still set on 401/403 responses
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(AdminRouteAccessMiddleware)
app.add_middleware(MutationClientGuardMiddleware)
app.add_middleware(RequestMetricsMiddleware)
app.add_middleware(MCPAuthMiddleware)

# ─── Session Context Middleware ───────────────────────────────────────────────
from backend.utils.context import session_id_ctx, mcp_client_name_ctx, mcp_client_scopes_ctx

class SessionContextASGIMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        request = Request(scope, receive)
        session_id = request.headers.get("X-Mnesis-Session-Id")
        try:
            client_name = str(getattr(request.state, "mcp_client_name", "") or "") or None
            client_scopes = getattr(request.state, "mcp_client_scopes", None)
            if not isinstance(client_scopes, list):
                client_scopes = []
        except Exception:
            client_name = None
            client_scopes = []

        token = session_id_ctx.set(session_id)
        name_token = mcp_client_name_ctx.set(client_name)
        scopes_token = mcp_client_scopes_ctx.set([str(v).strip().lower() for v in client_scopes if str(v).strip()])
        try:
            return await self.app(scope, receive, send)
        finally:
            session_id_ctx.reset(token)
            mcp_client_name_ctx.reset(name_token)
            mcp_client_scopes_ctx.reset(scopes_token)

app.add_middleware(SessionContextASGIMiddleware)


class MCPCaptureASGIMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        if scope["method"].upper() == "POST" and scope["path"].startswith("/mcp/messages"):
            body_chunks = []
            
            async def _receive():
                message = await receive()
                if message["type"] == "http.request":
                    body_chunks.append(message.get("body", b""))
                return message
            
            await self.app(scope, _receive, send)
            
            body_bytes = b"".join(body_chunks)
            if not body_bytes:
                return
            
            try:
                payload = json.loads(body_bytes.decode("utf-8"))
            except Exception:
                payload = None
                
            headers = dict(scope.get("headers", []))
            session_id = headers.get(b"x-mnesis-session-id", b"").decode("utf-8")
            if not session_id:
                from urllib.parse import parse_qs
                query = scope.get("query_string", b"").decode("utf-8")
                parsed = parse_qs(query)
                session_id = parsed.get("session_id", parsed.get("sessionId", [""]))[0] if parsed else ""
            # Fallback: generate a stable session ID per client IP + calendar day
            # so all MCP calls in a day from the same client group into one conversation
            if not session_id:
                import hashlib
                import datetime as _dt
                client_ip = headers.get(b"x-forwarded-for", b"").decode("utf-8") or "local"
                day = _dt.datetime.utcnow().strftime("%Y%m%d")
                session_id = "auto-" + hashlib.md5(f"{client_ip}:{day}".encode()).hexdigest()[:12]

            source_hint = "mcp"
            try:
                from backend.memory.conversation_capture import capture_mcp_request_payload
                import asyncio
                asyncio.create_task(
                    capture_mcp_request_payload(
                        payload=payload,
                        session_id=str(session_id),
                        source_hint=source_hint
                    )
                )
            except Exception as e:
                logger.warning(f"MCP capture background task failed: {e}")
            return
            
        return await self.app(scope, receive, send)

app.add_middleware(MCPCaptureASGIMiddleware)


# ─── Model Warmup ─────────────────────────────────────────────────────────────
from backend.memory.model_manager import model_manager
from backend.memory.embedder import get_model, get_status


def _warmup_model():
    if not model_manager.check_model_exists():
        model_manager.download_model()
    if model_manager.get_progress()["status"] == "error":
        logger.warning("Model download failed. Trying cache/repo fallback for model load.")
    try:
        get_model()
        model_manager.mark_complete()
        logger.info("Embedding model loaded and ready")
    except Exception as e:
        logger.error(f"Model warmup failed: {e}")


# ─── Startup ──────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    # 1. Initialize / migrate DB tables
    init_tables()

    # 1.b Apply secure-by-default config baseline (keys/scopes/fallback/permissions)
    load_config(force_reload=True)

    # 2. Start the async write queue
    await start_write_worker()

    # 3. Start persistent background job worker for conversation analysis.
    start_analysis_job_worker()

    # 4. Load embedding model in background thread (non-blocking)
    threading.Thread(target=_warmup_model, daemon=True, name="mnesis-warmup").start()

    # 5. Start asyncio scheduler (Ebbinghaus decay, maintenance, token rotation)
    from backend.scheduler import start_scheduler
    start_scheduler()
    logger.info("Scheduler started")

    # 6. Start config watcher (background daemon thread)
    from backend.config_watcher import run_first_launch_autoconfigure, start_config_watcher
    try:
        autoconfig_result = run_first_launch_autoconfigure(force=False)
        logger.info(
            "MCP autoconfig: status=%s detected=%s configured=%s errors=%s",
            autoconfig_result.get("status"),
            len(autoconfig_result.get("detected_clients", []) or []),
            len(autoconfig_result.get("configured_clients", []) or []),
            int(autoconfig_result.get("error_count", 0) or 0),
        )
    except Exception as e:
        logger.warning(f"MCP first-launch autoconfig failed: {e}")
    start_config_watcher()
    logger.info("Config watcher started")

# ─── Routers ──────────────────────────────────────────────────────────────────
app.include_router(memories.router)
app.include_router(admin.router)
app.include_router(conflicts.router)
app.include_router(conversations.router)
app.include_router(snapshot.router)
app.include_router(import_export.router)
app.include_router(search.router)
app.include_router(chat.router)

# Compatibility alias requested by the feature brief.
app.add_api_route(
    "/api/import/chatgpt",
    import_export.import_chatgpt_memory,
    methods=["POST"],
    tags=["import"],
)

# ─── MCP Server ───────────────────────────────────────────────────────────────
from backend.mcp_server import register_mcp
register_mcp(app)

# ─── Health Endpoint ──────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    """
    Health check endpoint.
    Electron polls this every 500ms until model_ready: true before showing the UI.
    """
    emb_status = get_status()
    progress = model_manager.get_progress()

    final_status = emb_status
    # If the embedder is ready, that's the source of truth for frontend status.
    if emb_status != "ready":
        if progress["status"] == "downloading":
            final_status = "downloading"
        elif progress["status"] == "error":
            final_status = "error"

    return {
        "status": "ok",
        "version": "0.1.0",
        "model_ready": emb_status == "ready",
        "model_status": final_status,
        "download_percent": progress.get("percent", 0),
        "download_file": progress.get("file", ""),
    }

# ─── Static Files (Production Only) ──────────────────────────────────────────
# In production, FastAPI serves the compiled React SPA.
# In dev: Vite dev server runs separately on port 5173.
if os.path.exists("dist"):
    app.mount("/", StaticFiles(directory="dist", html=True), name="ui")

# ─── Entry Point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("MNESIS_PORT", 7860))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
