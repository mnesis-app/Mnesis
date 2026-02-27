"""
Mnesis Background Scheduler
============================
Runs background tasks on a schedule:
  - Ebbinghaus decay — every 20 hours (daily)
  - Weekly maintenance — every 7 days
  - Snapshot token rotation — every 90 days
  - Optional encrypted auto-sync — configurable minutes interval
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
HOURLY_CHECK_INTERVAL_HOURS = 1
AUTO_SYNC_MIN_INTERVAL_MINUTES = 5
AUTO_CONVERSATION_ANALYSIS_MIN_INTERVAL_MINUTES = 5
SECURITY_AUDIT_MIN_INTERVAL_MINUTES = 5
CLIENT_METRICS_FLUSH_MIN_INTERVAL_MINUTES = 5

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

        from backend.memory.write_queue import enqueue_write

        async def _write_op():
            updated = 0
            for mem in memories:
                level = mem.get("level", "semantic")
                k = decay_rates.get(level, 0.001)

                last_ref = mem.get("last_referenced_at", mem.get("created_at"))
                if hasattr(last_ref, "tzinfo") and last_ref.tzinfo is None:
                    last_ref = last_ref.replace(tzinfo=timezone.utc)

                if isinstance(last_ref, str):
                    try:
                        last_ref = datetime.fromisoformat(last_ref)
                    except Exception:
                        last_ref = now

                days = (now - last_ref).total_seconds() / 86400
                retention = math.exp(-k * days)
                current = mem.get("importance_score", 0.5)
                new_score = max(0.1 if level == "semantic" else 0.0, current * retention)

                if abs(new_score - current) > 0.001:
                    tbl.update(
                        where=f"id = '{mem['id']}'",
                        values={"importance_score": round(new_score, 4)},
                    )
                    updated += 1

                    if level == "working" and new_score < 0.05:
                        tbl.update(where=f"id = '{mem['id']}'", values={"status": "archived"})
            return updated

        updated = await enqueue_write(_write_op)

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
                from backend.memory.write_queue import enqueue_write

                async def _write_op():
                    sessions_tbl.delete(f"ended_at IS NOT NULL AND ended_at < '{cutoff}'")

                await enqueue_write(_write_op)
            except Exception as e:
                logger.warning(f"Session cleanup failed: {e}")

        # 3. Trim memory_events older than 90 days (unbounded table guard)
        if "memory_events" in db.table_names():
            from datetime import timedelta
            events_cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
            try:
                events_tbl = db.open_table("memory_events")
                events_tbl.delete(f"created_at < '{events_cutoff}'")
                logger.info("Trimmed memory_events older than 90 days")
            except Exception as e:
                logger.warning(f"memory_events trim failed: {e}")

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
# Hourly Temporal Checks
# ---------------------------------------------------------------------------

async def run_hourly_temporal_checks():
    """
    Runs every hour:
      - archives expired memories based on decay profile / event date
      - toggles needs_review for semi-stable memories every 60 days
      - auto-archives pending conflicts older than 7 days
    """
    try:
        from backend.memory.core import apply_temporal_decay_and_reviews, archive_stale_pending_conflicts

        decay_result = await apply_temporal_decay_and_reviews()
        archived_conflicts = await archive_stale_pending_conflicts(max_age_days=7)
        logger.info(
            "Hourly checks complete: "
            f"expired_memories={decay_result.get('expired', 0)} "
            f"review_flags={decay_result.get('reviewed', 0)} "
            f"archived_conflicts={archived_conflicts}"
        )
    except Exception as e:
        logger.error(f"Hourly temporal checks failed: {e}")


async def run_auto_conversation_analysis() -> Optional[dict]:
    """
    Enqueue an incremental conversation analysis job (persistent queue).
    Returns enqueue metadata or None if disabled/skipped.
    """
    try:
        from backend.config import load_config
        from backend.memory.conversation_analysis_jobs import (
            enqueue_analysis_job,
            has_active_jobs,
        )
        from backend.memory.conversation_mining import get_analysis_llm_gate_status

        cfg = load_config(force_reload=True)
        auto_cfg = cfg.get("conversation_analysis", {}) if isinstance(cfg.get("conversation_analysis"), dict) else {}
        if not auto_cfg.get("enabled", True):
            return None
        require_llm_configured = bool(auto_cfg.get("require_llm_configured", True))

        provider = str(auto_cfg.get("provider", "auto"))
        model = (str(auto_cfg.get("model") or "").strip() or None)
        api_base_url = (str(auto_cfg.get("api_base_url") or "").strip() or None)
        api_key = (str(auto_cfg.get("api_key") or "").strip() or None)

        gate = await get_analysis_llm_gate_status(
            provider=provider,
            model=model,
            api_base_url=api_base_url,
            api_key=api_key,
            require_llm_configured=require_llm_configured,
        )
        if not bool(gate.get("analysis_allowed", True)):
            reason = str(gate.get("reason") or "LLM not configured")
            logger.info(f"Auto conversation analysis skipped: {reason}")
            return {
                "status": "blocked",
                "reason": reason,
            }

        payload = dict(
            dry_run=False,
            force_reanalyze=False,
            include_assistant_messages=bool(auto_cfg.get("include_assistant_messages", False)),
            max_conversations=int(auto_cfg.get("max_conversations", 24)),
            max_messages_per_conversation=int(auto_cfg.get("max_messages_per_conversation", 24)),
            max_candidates_per_conversation=int(auto_cfg.get("max_candidates_per_conversation", 4)),
            max_new_memories=int(auto_cfg.get("max_new_memories", 40)),
            min_confidence=float(auto_cfg.get("min_confidence", 0.8)),
            provider=provider,
            model=model,
            api_base_url=api_base_url,
            api_key=api_key,
            concurrency=int(auto_cfg.get("concurrency", 2)),
            require_llm_configured=require_llm_configured,
        )
        if has_active_jobs(trigger="auto"):
            logger.info("Auto conversation analysis skipped: pending/running job already exists")
            return None

        enqueue_result = await enqueue_analysis_job(
            trigger="auto",
            payload=payload,
            priority=2,
            max_attempts=2,
            dedupe_key="auto:scheduled",
            dedupe_active=True,
        )
        if str(enqueue_result.get("status") or "") == "duplicate":
            logger.info("Auto conversation analysis deduped: matching active job already queued")
            return None
        job = enqueue_result.get("job", {}) if isinstance(enqueue_result, dict) else {}
        logger.info(f"Auto conversation analysis queued: job_id={job.get('id')}")
        return {
            "status": "queued",
            "job_id": job.get("id"),
        }
    except Exception as e:
        logger.warning(f"Auto conversation analysis failed: {e}")
        return None


async def run_security_posture_audit() -> Optional[dict]:
    """
    Run security posture checks and return the report.
    """
    try:
        from backend.security import collect_security_audit

        report = collect_security_audit()
        summary = report.get("summary", {}) if isinstance(report, dict) else {}
        score = report.get("score") if isinstance(report, dict) else None
        grade = report.get("grade") if isinstance(report, dict) else None
        logger.info(
            "Security audit complete: score=%s grade=%s pass=%s warn=%s fail=%s",
            score,
            grade,
            summary.get("pass", 0),
            summary.get("warn", 0),
            summary.get("fail", 0),
        )
        return report
    except Exception as e:
        logger.warning(f"Security audit failed: {e}")
        return None


async def run_client_metrics_flush() -> Optional[dict]:
    """
    Persist in-memory MCP request metrics into the historical table.
    """
    try:
        from backend.security import flush_request_metrics_to_db

        result = await flush_request_metrics_to_db()
        status = str(result.get("status") or "unknown")
        if status == "ok":
            logger.info(
                "Client metrics flush complete: rows=%s clients=%s",
                result.get("rows_written", 0),
                result.get("clients", 0),
            )
        return result
    except Exception as e:
        logger.warning(f"Client metrics flush failed: {e}")
        return None

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

            # Hourly temporal checks
            last_hourly_checks = _parse_dt(state.get("last_hourly_checks"))
            if last_hourly_checks is None or (now - last_hourly_checks) > timedelta(hours=HOURLY_CHECK_INTERVAL_HOURS):
                await run_hourly_temporal_checks()
                state["last_hourly_checks"] = now.isoformat()
                changed = True

            # Configurable auto-sync (if enabled and unlocked)
            try:
                from backend.config import load_config
                from backend.sync.service import is_sync_unlocked, run_sync_now

                cfg = load_config(force_reload=True)
                sync_cfg = cfg.get("sync", {}) if isinstance(cfg.get("sync"), dict) else {}
                if sync_cfg.get("enabled") and sync_cfg.get("auto_sync"):
                    try:
                        interval_minutes = int(sync_cfg.get("auto_sync_interval_minutes", 60))
                    except Exception:
                        interval_minutes = 60
                    interval_minutes = max(AUTO_SYNC_MIN_INTERVAL_MINUTES, min(1440, interval_minutes))

                    last_auto_sync = _parse_dt(state.get("last_auto_sync"))
                    due = (
                        last_auto_sync is None
                        or (now - last_auto_sync) > timedelta(minutes=interval_minutes)
                    )
                    if due:
                        if is_sync_unlocked():
                            try:
                                await run_sync_now(source="auto")
                                state["last_auto_sync"] = now.isoformat()
                                changed = True
                                logger.info("Auto-sync completed")
                            except Exception as e:
                                logger.warning(f"Auto-sync failed: {e}")
                        else:
                            logger.info("Auto-sync skipped: sync key is locked")
            except Exception as e:
                logger.warning(f"Auto-sync check failed: {e}")

            # Configurable auto conversation analysis (incremental)
            try:
                from backend.config import load_config

                cfg = load_config(force_reload=True)
                auto_cfg = cfg.get("conversation_analysis", {}) if isinstance(cfg.get("conversation_analysis"), dict) else {}
                if auto_cfg.get("enabled", True):
                    try:
                        interval_minutes = int(auto_cfg.get("interval_minutes", 20))
                    except Exception:
                        interval_minutes = 20
                    interval_minutes = max(
                        AUTO_CONVERSATION_ANALYSIS_MIN_INTERVAL_MINUTES,
                        min(24 * 60, interval_minutes),
                    )
                    retry_interval_minutes = interval_minutes
                    last_stats = state.get("last_auto_conversation_analysis_stats")
                    if isinstance(last_stats, dict):
                        created_prev = int(last_stats.get("created", 0) or 0)
                        rejected_prev = int(last_stats.get("rejected", 0) or 0)
                        if created_prev == 0 and rejected_prev > 0:
                            # When the previous run failed completely, retry faster.
                            retry_interval_minutes = min(interval_minutes, 1)
                    last_auto_analysis = _parse_dt(state.get("last_auto_conversation_analysis"))
                    due = (
                        last_auto_analysis is None
                        or (now - last_auto_analysis) > timedelta(minutes=retry_interval_minutes)
                    )
                    if due:
                        enqueue_meta = await run_auto_conversation_analysis()
                        if enqueue_meta is not None:
                            status = str(enqueue_meta.get("status") or "").strip().lower() if isinstance(enqueue_meta, dict) else ""
                            if status == "queued":
                                state["last_auto_conversation_analysis_queued"] = now.isoformat()
                            elif status == "blocked":
                                reason = str(enqueue_meta.get("reason") or "LLM not configured")
                                state["last_auto_conversation_analysis"] = now.isoformat()
                                state["last_auto_conversation_analysis_stats"] = {
                                    "conversations_selected": 0,
                                    "candidates_total": 0,
                                    "created": 0,
                                    "merged": 0,
                                    "skipped": 1,
                                    "conflict_pending": 0,
                                    "rejected": 0,
                                    "generic_rate": 0.0,
                                    "duplicate_rate": 0.0,
                                    "accepted_rate": 0.0,
                                    "context_coverage_rate": 0.0,
                                    "duration_ms": 0,
                                    "sample_errors": [reason[:220]],
                                }
                            changed = True
            except Exception as e:
                logger.warning(f"Auto conversation analysis check failed: {e}")

            # Persist runtime client metrics history
            try:
                last_metrics_flush = _parse_dt(state.get("last_client_metrics_flush"))
                due = (
                    last_metrics_flush is None
                    or (now - last_metrics_flush) > timedelta(minutes=CLIENT_METRICS_FLUSH_MIN_INTERVAL_MINUTES)
                )
                if due:
                    flush_result = await run_client_metrics_flush()
                    state["last_client_metrics_flush"] = now.isoformat()
                    state["last_client_metrics_flush_result"] = flush_result or {}
                    changed = True
            except Exception as e:
                logger.warning(f"Client metrics flush check failed: {e}")

            # Configurable security audit
            try:
                from backend.config import load_config

                cfg = load_config(force_reload=True)
                security_cfg = cfg.get("security", {}) if isinstance(cfg.get("security"), dict) else {}
                audit_cfg = security_cfg.get("audit", {}) if isinstance(security_cfg.get("audit"), dict) else {}
                if bool(audit_cfg.get("enabled", True)):
                    try:
                        interval_minutes = int(audit_cfg.get("interval_minutes", 60))
                    except Exception:
                        interval_minutes = 60
                    interval_minutes = max(
                        SECURITY_AUDIT_MIN_INTERVAL_MINUTES,
                        min(24 * 60, interval_minutes),
                    )
                    last_security_audit = _parse_dt(state.get("last_security_audit"))
                    due = (
                        last_security_audit is None
                        or (now - last_security_audit) > timedelta(minutes=interval_minutes)
                    )
                    if due:
                        report = await run_security_posture_audit()
                        if isinstance(report, dict):
                            state["last_security_audit"] = report.get("generated_at") or now.isoformat()
                            state["last_security_audit_result"] = report
                            changed = True
            except Exception as e:
                logger.warning(f"Security audit check failed: {e}")

            if changed:
                _save_state(state)

        except Exception as e:
            logger.error(f"Scheduler loop error: {e}")

        # Check every 60 seconds
        await asyncio.sleep(60)


def start_scheduler():
    """Schedule the scheduler loop on the running event loop."""
    asyncio.create_task(scheduler_loop())
