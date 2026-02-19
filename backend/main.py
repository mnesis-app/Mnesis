from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
import asyncio
import threading
import logging

from backend.database.client import init_tables
from backend.memory.write_queue import start_write_worker
from backend.routers import memories, admin, conflicts, conversations, snapshot, import_export
from backend.auth import MCPAuthMiddleware

logger = logging.getLogger(__name__)

app = FastAPI(title="Mnesis API", version="0.1.0")

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
app.add_middleware(MCPAuthMiddleware)

# ─── Session Context Middleware ───────────────────────────────────────────────
from backend.utils.context import session_id_ctx

@app.middleware("http")
async def session_middleware(request: Request, call_next):
    """Propagate X-Mnesis-Session-Id header to the async context."""
    session_id = request.headers.get("X-Mnesis-Session-Id")
    token = session_id_ctx.set(session_id)
    try:
        return await call_next(request)
    finally:
        session_id_ctx.reset(token)

# ─── Model Warmup ─────────────────────────────────────────────────────────────
from backend.memory.model_manager import model_manager
from backend.memory.embedder import get_model, get_status


def _warmup_model():
    if not model_manager.check_model_exists():
        model_manager.download_model()
    if model_manager.get_progress()["status"] == "error":
        logger.error("Model download failed — model_ready will remain false")
        return
    try:
        get_model()
        logger.info("Embedding model loaded and ready")
    except Exception as e:
        logger.error(f"Model warmup failed: {e}")


# ─── Startup ──────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    # 1. Initialize / migrate DB tables
    init_tables()

    # 2. Start the async write queue
    await start_write_worker()

    # 3. Load embedding model in background thread (non-blocking)
    threading.Thread(target=_warmup_model, daemon=True, name="mnesis-warmup").start()

    # 4. Start asyncio scheduler (Ebbinghaus decay, maintenance, token rotation)
    from backend.scheduler import start_scheduler
    start_scheduler()
    logger.info("Scheduler started")

    # 5. Start config watcher (background daemon thread)
    from backend.config_watcher import start_config_watcher
    start_config_watcher()
    logger.info("Config watcher started")


# ─── Routers ──────────────────────────────────────────────────────────────────
app.include_router(memories.router)
app.include_router(admin.router)
app.include_router(conflicts.router)
app.include_router(conversations.router)
app.include_router(snapshot.router)
app.include_router(import_export.router)

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
