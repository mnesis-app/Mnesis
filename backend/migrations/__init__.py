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
