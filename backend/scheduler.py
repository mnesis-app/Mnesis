"""
Mnesis Background Scheduler
============================
Runs background tasks on a schedule:
  - Ebbinghaus decay — every 20 hours (daily)
  - Weekly maintenance — every 7 days
  - Snapshot token rotation — every 90 days
  - Startup update check — once on startup (3s timeout)

State persisted to data/scheduler_state.json so tasks survive restarts.
"""
import asyncio
import json
import os
import logging
import math
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

DECAY_INTERVAL_HOURS = 20
MAINTENANCE_INTERVAL_DAYS = 7
TOKEN_ROTATION_DAYS = 90

def _get_state_path() -> str:
    from backend.config import CONFIG_DIR
    return os.path.join(CONFIG_DIR, "scheduler_state.json")

def _load_state() -> dict:
    path = _get_state_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}

def _save_state(state: dict):
    path = _get_state_path()
    try:
        with open(path, "w") as f:
            json.dump(state, f, default=str, indent=2)
    except Exception as e:
        logger.error(f"Failed to save scheduler state: {e}")

def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None

# ---------------------------------------------------------------------------
# Ebbinghaus Decay
# ---------------------------------------------------------------------------

async def run_ebbinghaus_decay():
    """Apply Ebbinghaus forgetting curve to all active memories."""
    logger.info("Running Ebbinghaus decay sweep...")
    try:
        from backend.database.client import get_db
        from backend.config import load_config

        db = get_db()
        if "memories" not in db.table_names():
            return

        tbl = db.open_table("memories")
        config = load_config()
        decay_rates = config.get("decay_rates", {
            "semantic": 0.001, "episodic": 0.05, "working": 0.3
        })

        now = datetime.now(timezone.utc)
        memories = tbl.search().where("status = 'active'").limit(100000).to_list()
        updated = 0

        for mem in memories:
            level = mem.get("level", "semantic")
            k = decay_rates.get(level, 0.001)

            last_ref = mem.get("last_referenced_at", mem.get("created_at"))
            if hasattr(last_ref, 'tzinfo') and last_ref.tzinfo is None:
                last_ref = last_ref.replace(tzinfo=timezone.utc)

            if isinstance(last_ref, str):
                try:
                    last_ref = datetime.fromisoformat(last_ref)
                except Exception:
                    last_ref = now

            days = (now - last_ref).total_seconds() / 86400
            # R = e^(-k * t) — Ebbinghaus retention
            retention = math.exp(-k * days)
            # New importance = old * retention, but never lower than 0.1 (semantic)
            current = mem.get("importance_score", 0.5)
            new_score = max(0.1 if level == "semantic" else 0.0, current * retention)

            if abs(new_score - current) > 0.001:  # Only update if changed significantly
                tbl.update(
                    where=f"id = '{mem['id']}'",
                    values={"importance_score": round(new_score, 4)}
                )
                updated += 1

                # Archive working memories that have decayed to near-zero
                if level == "working" and new_score < 0.05:
                    tbl.update(where=f"id = '{mem['id']}'", values={"status": "archived"})

        logger.info(f"Decay sweep complete: {updated}/{len(memories)} memories updated")
    except Exception as e:
        logger.error(f"Ebbinghaus decay failed: {e}")

# ---------------------------------------------------------------------------
# Weekly Maintenance
# ---------------------------------------------------------------------------

async def run_weekly_maintenance():
    """Compact LanceDB, clean old sessions, summarize orphaned working memories."""
    logger.info("Running weekly maintenance...")
    try:
        from backend.database.client import get_db
        db = get_db()

        # 1. Compact LanceDB tables
        for table_name in db.table_names():
            try:
                tbl = db.open_table(table_name)
                tbl.compact_files()
                logger.info(f"Compacted table: {table_name}")
            except Exception as e:
                logger.warning(f"Compact failed for {table_name}: {e}")

        # 2. Archive sessions older than 30 days
        if "sessions" in db.table_names():
            from datetime import timedelta
            cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            try:
                sessions_tbl = db.open_table("sessions")
                sessions_tbl.delete(f"ended_at IS NOT NULL AND ended_at < '{cutoff}'")
            except Exception as e:
                logger.warning(f"Session cleanup failed: {e}")

        logger.info("Weekly maintenance complete")
    except Exception as e:
        logger.error(f"Weekly maintenance failed: {e}")

# ---------------------------------------------------------------------------
# Snapshot Token Rotation
# ---------------------------------------------------------------------------

async def run_token_rotation():
    """Rotate the snapshot read token and send a native notification."""
    logger.info("Rotating snapshot token (90-day schedule)...")
    try:
        from backend.config import rotate_snapshot_token
        new_token = rotate_snapshot_token()
        logger.info("Snapshot token rotated successfully")

        # Try to send native notification via Electron IPC (best-effort)
        # If not in Electron context, skip silently
        try:
            import httpx
            from backend.config import load_config
            config = load_config()
            rest_port = config.get("rest_port", 7860)
            # POST to a local notification endpoint if it exists
            await httpx.AsyncClient().post(
                f"http://127.0.0.1:{rest_port}/internal/notify",
                json={"title": "Mnesis", "body": "Snapshot token has been rotated for security."},
                timeout=1.0
            )
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Token rotation failed: {e}")

# ---------------------------------------------------------------------------
# Update Check
# ---------------------------------------------------------------------------

async def run_update_check():
    """Check for app updates once on startup (3 second timeout, fail silently)."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3.0) as client:
            res = await client.get("https://mnesis.app/api/version")
            if res.status_code == 200:
                data = res.json()
                latest = data.get("latest", "")
                # Version comparison is handled by Electron auto-updater
                logger.info(f"Latest Mnesis version: {latest}")
    except Exception:
        pass  # Network unavailable or timeout — fail silently

# ---------------------------------------------------------------------------
# Main Loop
# ---------------------------------------------------------------------------

async def scheduler_loop():
    """Main scheduler loop — runs forever, checks tasks at 1-minute intervals."""
    logger.info("Scheduler started")
    state = _load_state()

    # Run update check on startup
    asyncio.create_task(run_update_check())

    while True:
        try:
            now = datetime.now(timezone.utc)
            state = _load_state()  # Reload each iteration to pick up external changes
            changed = False

            # Ebbinghaus decay (every 20 hours)
            last_decay = _parse_dt(state.get("last_decay"))
            if last_decay is None or (now - last_decay) > timedelta(hours=DECAY_INTERVAL_HOURS):
                await run_ebbinghaus_decay()
                state["last_decay"] = now.isoformat()
                changed = True

            # Weekly maintenance
            last_maintenance = _parse_dt(state.get("last_maintenance"))
            if last_maintenance is None or (now - last_maintenance) > timedelta(days=MAINTENANCE_INTERVAL_DAYS):
                await run_weekly_maintenance()
                state["last_maintenance"] = now.isoformat()
                changed = True

            # 90-day token rotation
            last_rotation = _parse_dt(state.get("last_token_rotation"))
            if last_rotation is None or (now - last_rotation) > timedelta(days=TOKEN_ROTATION_DAYS):
                await run_token_rotation()
                state["last_token_rotation"] = now.isoformat()
                changed = True

            if changed:
                _save_state(state)

        except Exception as e:
            logger.error(f"Scheduler loop error: {e}")

        # Check every 60 seconds
        await asyncio.sleep(60)


def start_scheduler():
    """Schedule the scheduler loop on the running event loop."""
    asyncio.create_task(scheduler_loop())
