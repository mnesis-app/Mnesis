"""
Database Migrations
====================
Applies schema changes incrementally, tracked in data/schema_version.txt.
Each migration is a simple Python function.

Usage: Called by backend/database/client.py at startup (after init_tables).
"""
import os
import logging
from typing import Callable, Dict
from datetime import datetime, timezone
import uuid

logger = logging.getLogger(__name__)

MIGRATIONS: Dict[int, Callable] = {}


def migration(version: int):
    """Decorator to register a migration."""
    def decorator(fn: Callable):
        MIGRATIONS[version] = fn
        return fn
    return decorator


def _get_schema_file() -> str:
    from backend.database.client import DATA_DIR
    return os.path.join(DATA_DIR, "schema_version.txt")


def _read_version() -> int:
    path = _get_schema_file()
    if not os.path.exists(path):
        return 0
    try:
        return int(open(path).read().strip())
    except Exception:
        return 0


def _write_version(v: int):
    path = _get_schema_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(str(v))


def run_migrations(db):
    """Run any pending migrations in order."""
    current_version = _read_version()
    pending = sorted(v for v in MIGRATIONS if v > current_version)

    if not pending:
        return

    logger.info(f"Running {len(pending)} DB migration(s) from v{current_version}...")

    for version in pending:
        try:
            logger.info(f"Applying migration v{version}...")
            MIGRATIONS[version](db)
            _write_version(version)
            logger.info(f"Migration v{version} applied successfully")
        except Exception as e:
            logger.error(f"Migration v{version} failed: {e}")
            raise


# ─── Migration Definitions ─────────────────────────────────────────────────────

@migration(1)
def initial_schema(db):
    """v1: Initial schema — tables created by init_tables()."""
    # Tables are created in init_tables() so this is a no-op that records the version.
    pass


@migration(2)
def add_confidence_score_column(db):
    """v2: Add confidence_score to memories if missing (for upgrades from pre-v2)."""
    if "memories" not in db.table_names():
        return
    tbl = db.open_table("memories")
    # LanceDB supports adding columns via alter_table in newer versions.
    # If the column already exists (new installs), this is a no-op.
    try:
        sample = tbl.search().limit(1).to_list()
        if sample and "confidence_score" not in sample[0]:
            # Add the column with default value 0.7
            tbl.add_column("confidence_score", "FLOAT", default=0.7)
            logger.info("Added confidence_score column to memories")
    except Exception as e:
        logger.warning(f"confidence_score migration: {e} (may already exist)")


@migration(3)
def add_privacy_field(db):
    """v3: Ensure privacy field exists on memories (default: public)."""
    if "memories" not in db.table_names():
        return
    try:
        tbl = db.open_table("memories")
        sample = tbl.search().limit(1).to_list()
        if sample and "privacy" not in sample[0]:
            tbl.add_column("privacy", "VARCHAR", default="public")
            logger.info("Added privacy column to memories")
    except Exception as e:
        logger.warning(f"privacy migration: {e} (may already exist)")


def _safe_add_column(tbl, name: str, dtype: str, default):
    try:
        existing = {str(n) for n in (getattr(tbl.schema, "names", []) or [])}
        if name in existing:
            return
    except Exception:
        pass
    try:
        # LanceDB API uses add_columns with SQL transforms.
        # Keep compatibility with older runtimes if add_column exists.
        if hasattr(tbl, "add_columns"):
            if default is None:
                transform = "NULL"
            elif isinstance(default, bool):
                transform = "true" if default else "false"
            elif isinstance(default, (int, float)):
                transform = str(default)
            else:
                escaped = str(default).replace("'", "''")
                transform = f"'{escaped}'"
            tbl.add_columns({name: transform})
        else:
            tbl.add_column(name, dtype, default=default)
        logger.info(f"Added column {name}")
    except Exception as e:
        logger.warning(f"Column {name} migration skipped: {e}")


def _safe_create_table(db, name: str, schema):
    """
    Idempotent table creation for migrations.
    Handles startup races where table discovery can be stale.
    """
    try:
        if name in set(db.table_names()):
            db.open_table(name)
            return
    except Exception:
        pass

    try:
        db.create_table(name, schema=schema)
        logger.info(f"Created table {name}")
        return
    except TypeError:
        # Some LanceDB versions expose exist_ok.
        try:
            db.create_table(name, schema=schema, exist_ok=True)
            logger.info(f"Created table {name}")
            return
        except Exception as e:
            msg = str(e).lower()
            if "already exists" in msg:
                try:
                    db.open_table(name)
                except Exception:
                    pass
                return
            raise
    except Exception as e:
        msg = str(e).lower()
        if "already exists" in msg:
            try:
                db.open_table(name)
            except Exception:
                pass
            return
        raise


@migration(4)
def add_decay_fields(db):
    """v4: Add temporal decay fields to memories."""
    if "memories" not in db.table_names():
        return
    tbl = db.open_table("memories")
    _safe_add_column(tbl, "decay_profile", "VARCHAR", "stable")
    _safe_add_column(tbl, "expires_at", "TIMESTAMP", None)
    _safe_add_column(tbl, "needs_review", "BOOLEAN", False)
    _safe_add_column(tbl, "review_due_at", "TIMESTAMP", None)
    _safe_add_column(tbl, "event_date", "TIMESTAMP", None)


@migration(5)
def add_pending_conflicts_and_context_logs(db):
    """v5: Create new tables for conflict workflow and context routing analytics."""
    from backend.database.schema import PendingConflict, ContextRouteLog

    _safe_create_table(db, "pending_conflicts", PendingConflict)
    _safe_create_table(db, "context_route_logs", ContextRouteLog)


@migration(6)
def add_memory_graph_edges_table(db):
    """v6: Add LanceDB edge table used by the knowledge graph layer."""
    from backend.database.schema import MemoryGraphEdge

    _safe_create_table(db, "memory_graph_edges", MemoryGraphEdge)


def _to_dt(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            pass
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception:
            pass
    return datetime.now(timezone.utc)


def _safe_vector(value, dim: int) -> list[float]:
    if isinstance(value, list) and len(value) == dim:
        out = []
        for item in value:
            try:
                out.append(float(item))
            except Exception:
                out.append(0.0)
        return out
    return [0.0] * dim


@migration(7)
def repair_legacy_memories_schema(db):
    """
    v7: Repair legacy memories tables that missed temporal columns by rebuilding
    the table with the current Memory schema.
    """
    if "memories" not in db.table_names():
        return

    tbl = db.open_table("memories")
    try:
        present = {str(n) for n in (getattr(tbl.schema, "names", []) or [])}
    except Exception:
        present = set()
    required_temporal = {"decay_profile", "expires_at", "needs_review", "review_due_at", "event_date"}
    missing = sorted(list(required_temporal - present))
    if not missing:
        return

    logger.warning(f"Legacy memories schema detected, missing fields: {', '.join(missing)}")
    rows = tbl.search().limit(2_000_000).to_list()
    old_schema = tbl.schema

    from backend.database.schema import Memory, EMBEDDING_DIM

    backup_name = f"memories_legacy_backup_v7_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:6]}"
    backup_created = False

    try:
        # LanceDB OSS does not support rename_table; create a backup table explicitly.
        if rows:
            db.create_table(backup_name, data=rows)
        else:
            db.create_table(backup_name, schema=old_schema)
        backup_created = True
    except Exception as e:
        logger.warning(f"Could not create backup table before schema repair: {e}")

    try:
        db.drop_table("memories", ignore_missing=True)
        new_tbl = db.create_table("memories", schema=Memory)

        batch: list[dict] = []
        inserted = 0
        for row in rows:
            now = datetime.now(timezone.utc)
            normalized = {
                "id": str(row.get("id") or uuid.uuid4()),
                "content": str(row.get("content") or ""),
                "level": str(row.get("level") or "semantic"),
                "category": str(row.get("category") or "preferences"),
                "importance_score": float(row.get("importance_score") or 0.5),
                "confidence_score": float(row.get("confidence_score") or 0.7),
                "privacy": str(row.get("privacy") or "public"),
                "tags": row.get("tags") if isinstance(row.get("tags"), list) else [],
                "source_llm": str(row.get("source_llm") or "legacy"),
                "source_conversation_id": str(row.get("source_conversation_id")) if row.get("source_conversation_id") else None,
                "source_message_id": str(row.get("source_message_id")) if row.get("source_message_id") else None,
                "source_excerpt": str(row.get("source_excerpt")) if row.get("source_excerpt") else None,
                "version": int(row.get("version") or 1),
                "status": str(row.get("status") or "active"),
                "created_at": _to_dt(row.get("created_at") or now),
                "updated_at": _to_dt(row.get("updated_at") or now),
                "last_referenced_at": _to_dt(row.get("last_referenced_at") or now),
                "reference_count": int(row.get("reference_count") or 0),
                "decay_profile": str(row.get("decay_profile") or "stable"),
                "expires_at": _to_dt(row.get("expires_at")) if row.get("expires_at") else None,
                "needs_review": bool(row.get("needs_review") or False),
                "review_due_at": _to_dt(row.get("review_due_at")) if row.get("review_due_at") else None,
                "event_date": _to_dt(row.get("event_date")) if row.get("event_date") else None,
                "suggestion_reason": str(row.get("suggestion_reason") or ""),
                "review_note": str(row.get("review_note") or ""),
                "vector": _safe_vector(row.get("vector"), EMBEDDING_DIM),
            }
            batch.append(normalized)
            if len(batch) >= 1000:
                new_tbl.add(batch)
                inserted += len(batch)
                batch = []
        if batch:
            new_tbl.add(batch)
            inserted += len(batch)

        if backup_created:
            logger.info(f"Memories schema repair completed. rows={inserted}, backup_table={backup_name}")
        else:
            logger.info(f"Memories schema repair completed. rows={inserted}")
    except Exception as e:
        logger.error(f"Failed to repair memories schema: {e}")
        try:
            db.drop_table("memories", ignore_missing=True)
        except Exception:
            pass
        try:
            if backup_created and backup_name in db.table_names():
                backup_rows = db.open_table(backup_name).search().limit(2_000_000).to_list()
                if backup_rows:
                    db.create_table("memories", data=backup_rows)
                else:
                    db.create_table("memories", schema=old_schema)
        except Exception:
            pass
        raise


@migration(8)
def add_conversation_analysis_tables(db):
    """v8: Add persistent queue + incremental index for conversation analysis."""
    from backend.database.schema import ConversationAnalysisJob, ConversationAnalysisIndex

    _safe_create_table(db, "conversation_analysis_jobs", ConversationAnalysisJob)
    _safe_create_table(db, "conversation_analysis_index", ConversationAnalysisIndex)


@migration(9)
def add_memory_review_metadata_fields(db):
    """v9: Add review metadata fields used by inbox transparency features."""
    if "memories" not in db.table_names():
        return
    tbl = db.open_table("memories")
    _safe_add_column(tbl, "suggestion_reason", "VARCHAR", "")
    _safe_add_column(tbl, "review_note", "VARCHAR", "")


@migration(10)
def add_conversation_analysis_candidates_table(db):
    """v10: Persist conversation analysis candidates before memory promotion."""
    from backend.database.schema import ConversationAnalysisCandidate

    _safe_create_table(db, "conversation_analysis_candidates", ConversationAnalysisCandidate)


@migration(11)
def add_memory_provenance_fields(db):
    """v11: Persist provenance on memories for traceability."""
    if "memories" not in db.table_names():
        return
    tbl = db.open_table("memories")
    _safe_add_column(tbl, "source_message_id", "VARCHAR", "")
    _safe_add_column(tbl, "source_excerpt", "VARCHAR", "")


@migration(12)
def add_memory_events_table(db):
    """v12: Append-only memory events journal."""
    from backend.database.schema import MemoryEvent

    _safe_create_table(db, "memory_events", MemoryEvent)


@migration(13)
def add_client_runtime_metrics_table(db):
    """v13: Persist MCP client runtime metrics snapshots for observability history."""
    from backend.database.schema import ClientRuntimeMetric

    _safe_create_table(db, "client_runtime_metrics", ClientRuntimeMetric)
