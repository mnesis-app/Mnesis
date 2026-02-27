import lancedb
import os
import logging
from typing import Any

logger = logging.getLogger(__name__)

if os.environ.get("MNESIS_APPDATA_DIR"):
    DATA_DIR = os.path.join(os.environ["MNESIS_APPDATA_DIR"], "data")
elif os.name == 'nt':
    DATA_DIR = os.path.join(os.environ['APPDATA'], 'Mnesis', 'data')
else:
    DATA_DIR = os.path.join(os.path.expanduser('~'), '.mnesis', 'data')

DB_PATH = os.path.join(DATA_DIR, "lancedb")

_db = None


def _extract_listed_tables(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value if str(v)]
    if isinstance(value, dict):
        tables = value.get("tables")
        if isinstance(tables, (list, tuple, set)):
            return [str(v) for v in tables if str(v)]
        return []
    tables_attr = getattr(value, "tables", None)
    if isinstance(tables_attr, (list, tuple, set)):
        return [str(v) for v in tables_attr if str(v)]
    return []


def _safe_table_names(db) -> list[str]:
    # LanceDB `table_names()` can return a partial list on some versions.
    # Prefer `list_tables()` when available and fallback to original method.
    try:
        if hasattr(db, "list_tables"):
            listed = _extract_listed_tables(db.list_tables())
            if listed:
                return listed
    except Exception:
        pass

    original = getattr(db, "_mnesis_original_table_names", None)
    if callable(original):
        try:
            names = original()
            return _extract_listed_tables(names) or [str(v) for v in names]
        except Exception:
            return []
    return []

def get_db():
    global _db
    if _db is None:
        os.makedirs(DB_PATH, exist_ok=True)
        _db = lancedb.connect(DB_PATH)
        try:
            original = getattr(_db, "table_names", None)
            if callable(original):
                setattr(_db, "_mnesis_original_table_names", original)
                _db.table_names = lambda: _safe_table_names(_db)
        except Exception:
            # Non-fatal: callers can still use list_tables/open_table.
            pass
    return _db


def _safe_create_table(db, name: str, schema):
    """
    Create table idempotently.
    Handles races on startup/reload where the table can be created between
    existence check and create call.
    """
    try:
        if name in set(db.table_names()):
            db.open_table(name)
            return
    except Exception:
        # If table listing fails, keep going and rely on create/open fallback.
        pass

    try:
        db.create_table(name, schema=schema)
        return
    except TypeError:
        # Some LanceDB versions expose different create_table signatures.
        try:
            db.create_table(name, schema=schema, exist_ok=True)
            return
        except Exception as e:
            msg = str(e).lower()
            if "already exists" in msg or "schema error" in msg:
                db.open_table(name)
                return
            raise
    except Exception as e:
        msg = str(e).lower()
        if "already exists" in msg or "schema error" in msg:
            db.open_table(name)
            return
        raise

def init_tables():
    db = get_db()
    from .schema import (
        Memory,
        MemoryVersion,
        MemoryEvent,
        ClientRuntimeMetric,
        Conversation,
        Message,
        Conflict,
        Session,
        PendingConflict,
        ContextRouteLog,
        MemoryGraphEdge,
        ConversationAnalysisJob,
        ConversationAnalysisIndex,
        ConversationAnalysisCandidate,
    )
    
    # Create tables if not exist
    # Note: LanceDB create_table with exist_ok=True and schema
    
    _safe_create_table(db, "memories", Memory)
    _safe_create_table(db, "memory_versions", MemoryVersion)
    _safe_create_table(db, "memory_events", MemoryEvent)
    _safe_create_table(db, "client_runtime_metrics", ClientRuntimeMetric)
    _safe_create_table(db, "conversations", Conversation)
    _safe_create_table(db, "messages", Message)
    _safe_create_table(db, "conflicts", Conflict)
    _safe_create_table(db, "pending_conflicts", PendingConflict)
    _safe_create_table(db, "sessions", Session)
    _safe_create_table(db, "context_route_logs", ContextRouteLog)
    _safe_create_table(db, "memory_graph_edges", MemoryGraphEdge)
    _safe_create_table(db, "conversation_analysis_jobs", ConversationAnalysisJob)
    _safe_create_table(db, "conversation_analysis_index", ConversationAnalysisIndex)
    _safe_create_table(db, "conversation_analysis_candidates", ConversationAnalysisCandidate)

    # Run pending migrations (schema upgrades for existing installs)
    try:
        from backend.migrations import run_migrations
        run_migrations(db)
    except Exception as e:
        logger.warning(f"Migration step failed (non-fatal for new installs): {e}")
