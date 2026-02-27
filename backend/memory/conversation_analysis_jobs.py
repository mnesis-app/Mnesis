from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from backend.config import CONFIG_DIR
from backend.database.client import get_db
from backend.memory.write_queue import enqueue_write

logger = logging.getLogger(__name__)

JOBS_TABLE = "conversation_analysis_jobs"
INDEX_TABLE = "conversation_analysis_index"

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

_TERMINAL_STATUSES = {STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED}

_worker_task: asyncio.Task | None = None
_worker_state: dict[str, Any] = {
    "running": False,
    "current_job_id": None,
    "current_job_trigger": None,
    "current_job_started_at": None,
    "current_step_index": 0,
    "current_step_total": 0,
    "current_step_key": "",
    "current_step_label": "",
    "current_step_started_at": None,
    "processed_count": 0,
    "last_error": None,
    "last_heartbeat": None,
    "last_completed_at": None,
}


def _escape_sql(value: str) -> str:
    return str(value).replace("'", "''")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            pass
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception:
            pass
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception:
            pass
    return datetime.fromtimestamp(0, tz=timezone.utc)


def _scheduler_state_path() -> str:
    return os.path.join(CONFIG_DIR, "scheduler_state.json")


def _load_scheduler_state() -> dict:
    path = _scheduler_state_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _save_scheduler_state(state: dict):
    path = _scheduler_state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f, default=str, indent=2)


def _analysis_stats_from_result(result: dict | None) -> dict:
    result = result if isinstance(result, dict) else {}
    write_stats = result.get("write_stats", {}) if isinstance(result.get("write_stats"), dict) else {}
    details = result.get("details", []) if isinstance(result.get("details"), list) else []
    metrics = result.get("metrics", {}) if isinstance(result.get("metrics"), dict) else {}
    quality_metrics = (
        result.get("quality_metrics", {})
        if isinstance(result.get("quality_metrics"), dict)
        else {}
    )
    sample_errors: list[str] = []
    seen_errors: set[str] = set()
    for item in details:
        if not isinstance(item, dict):
            continue
        msg = str(item.get("message") or "").strip()
        action = str(item.get("action") or "").strip().lower()
        if msg and action == "error":
            key = msg.lower()
            if key in seen_errors:
                continue
            seen_errors.add(key)
            sample_errors.append(msg[:220])
        if len(sample_errors) >= 3:
            break
    llm_errors = result.get("llm_errors", [])
    if isinstance(llm_errors, list):
        for raw in llm_errors:
            msg = str(raw or "").strip()
            if not msg:
                continue
            key = msg.lower()
            if key in seen_errors:
                continue
            seen_errors.add(key)
            sample_errors.append(msg[:220])
            if len(sample_errors) >= 3:
                break
    return {
        "conversations_selected": int(result.get("conversations_selected", 0) or 0),
        "candidates_total": int(result.get("candidates_total", 0) or 0),
        "created": int(write_stats.get("created", 0) or 0),
        "merged": int(write_stats.get("merged", 0) or 0),
        "skipped": int(write_stats.get("skipped", 0) or 0),
        "conflict_pending": int(write_stats.get("conflict_pending", 0) or 0),
        "rejected": int(write_stats.get("rejected", 0) or 0),
        "generic_rate": float(quality_metrics.get("generic_rate", 0.0) or 0.0),
        "duplicate_rate": float(quality_metrics.get("duplicate_rate", 0.0) or 0.0),
        "accepted_rate": float(quality_metrics.get("accepted_rate", 0.0) or 0.0),
        "context_coverage_rate": float(quality_metrics.get("context_coverage_rate", 0.0) or 0.0),
        "duration_ms": int(metrics.get("total_ms", 0) or 0),
        "sample_errors": sample_errors,
    }


def _analysis_stats_from_error(message: str) -> dict:
    msg = str(message or "").strip()
    return {
        "conversations_selected": 0,
        "candidates_total": 0,
        "created": 0,
        "merged": 0,
        "skipped": 0,
        "conflict_pending": 0,
        "rejected": 1,
        "generic_rate": 0.0,
        "duplicate_rate": 0.0,
        "accepted_rate": 0.0,
        "context_coverage_rate": 0.0,
        "duration_ms": 0,
        "sample_errors": [msg[:220]] if msg else [],
    }


def _set_worker_step(step_index: int, step_total: int, step_key: str, step_label: str):
    safe_total = max(0, int(step_total or 0))
    safe_index = max(0, min(int(step_index or 0), safe_total if safe_total > 0 else int(step_index or 0)))
    _worker_state["current_step_index"] = safe_index
    _worker_state["current_step_total"] = safe_total
    _worker_state["current_step_key"] = str(step_key or "").strip().lower()
    _worker_state["current_step_label"] = str(step_label or "").strip()
    _worker_state["current_step_started_at"] = _now().isoformat()


def _reset_worker_step():
    _worker_state["current_step_index"] = 0
    _worker_state["current_step_total"] = 0
    _worker_state["current_step_key"] = ""
    _worker_state["current_step_label"] = ""
    _worker_state["current_step_started_at"] = None


def _persist_analysis_state(trigger: str, result: dict | None = None, error: str | None = None):
    state = _load_scheduler_state()
    stamp = _now().isoformat()
    is_auto = str(trigger or "").strip().lower().startswith("auto")
    if is_auto:
        state["last_auto_conversation_analysis"] = stamp
        if error:
            state["last_auto_conversation_analysis_stats"] = _analysis_stats_from_error(error)
        else:
            state["last_auto_conversation_analysis_stats"] = _analysis_stats_from_result(result)
    else:
        state["last_manual_conversation_analysis"] = stamp
        if error:
            state["last_manual_conversation_analysis_stats"] = _analysis_stats_from_error(error)
        else:
            state["last_manual_conversation_analysis_stats"] = _analysis_stats_from_result(result)
    _save_scheduler_state(state)


def _safe_json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        return "{}"


def _safe_json_loads(value: Any, default: Any) -> Any:
    if not isinstance(value, str) or not value.strip():
        return default
    try:
        parsed = json.loads(value)
        return parsed
    except Exception:
        return default


def _ensure_tables():
    db = get_db()
    from backend.database.schema import (
        ConversationAnalysisCandidate,
        ConversationAnalysisIndex,
        ConversationAnalysisJob,
    )

    def _safe_create(name: str, schema):
        try:
            if name in set(db.table_names()):
                db.open_table(name)
                return
        except Exception:
            pass

        try:
            db.create_table(name, schema=schema)
        except TypeError:
            try:
                db.create_table(name, schema=schema, exist_ok=True)
            except Exception as e:
                if "already exists" not in str(e).lower():
                    raise
                db.open_table(name)
        except Exception as e:
            if "already exists" not in str(e).lower():
                raise
            db.open_table(name)

    _safe_create(JOBS_TABLE, ConversationAnalysisJob)
    _safe_create(INDEX_TABLE, ConversationAnalysisIndex)
    _safe_create("conversation_analysis_candidates", ConversationAnalysisCandidate)


def _job_result_summary(result: dict | None) -> dict:
    data = result if isinstance(result, dict) else {}
    write_stats = data.get("write_stats", {}) if isinstance(data.get("write_stats"), dict) else {}
    metrics = data.get("metrics", {}) if isinstance(data.get("metrics"), dict) else {}
    quality_metrics = data.get("quality_metrics", {}) if isinstance(data.get("quality_metrics"), dict) else {}
    return {
        "conversations_selected": int(data.get("conversations_selected", 0) or 0),
        "candidates_total": int(data.get("candidates_total", 0) or 0),
        "created": int(write_stats.get("created", 0) or 0),
        "rejected": int(write_stats.get("rejected", 0) or 0),
        "generic_rate": float(quality_metrics.get("generic_rate", 0.0) or 0.0),
        "duplicate_rate": float(quality_metrics.get("duplicate_rate", 0.0) or 0.0),
        "accepted_rate": float(quality_metrics.get("accepted_rate", 0.0) or 0.0),
        "duration_ms": int(metrics.get("total_ms", 0) or 0),
    }


def _public_job(row: dict) -> dict:
    result = _safe_json_loads(row.get("result_json"), default={})
    payload = _safe_json_loads(row.get("payload_json"), default={})
    return {
        "id": str(row.get("id") or ""),
        "trigger": str(row.get("trigger") or ""),
        "status": str(row.get("status") or ""),
        "priority": int(row.get("priority") or 0),
        "dedupe_key": str(row.get("dedupe_key") or ""),
        "attempt_count": int(row.get("attempt_count") or 0),
        "max_attempts": int(row.get("max_attempts") or 0),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "started_at": row.get("started_at"),
        "completed_at": row.get("completed_at"),
        "error": str(row.get("error") or ""),
        "payload": payload,
        "result": result,
        "result_summary": _job_result_summary(result),
    }


def _build_dedupe_key(trigger: str, payload: dict, explicit: Optional[str]) -> str:
    if explicit:
        return str(explicit).strip()
    normalized = {
        "trigger": str(trigger or "").strip().lower(),
        "payload": payload,
    }
    digest = hashlib.sha1(_safe_json_dumps(normalized).encode("utf-8")).hexdigest()
    return digest


def _build_run_payload(payload: dict) -> dict:
    allowed_keys = {
        "dry_run",
        "force_reanalyze",
        "conversation_ids",
        "include_assistant_messages",
        "max_conversations",
        "max_messages_per_conversation",
        "max_candidates_per_conversation",
        "max_new_memories",
        "min_confidence",
        "provider",
        "model",
        "api_base_url",
        "api_key",
        "concurrency",
        "require_llm_configured",
    }
    clean = {k: v for k, v in (payload or {}).items() if k in allowed_keys}
    clean["dry_run"] = bool(clean.get("dry_run", False))
    clean["require_llm_configured"] = bool(clean.get("require_llm_configured", True))
    if isinstance(clean.get("conversation_ids"), list):
        seen = set()
        ids = []
        for raw in clean.get("conversation_ids", []):
            value = str(raw or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            ids.append(value)
            if len(ids) >= 500:
                break
        clean["conversation_ids"] = ids or None
    else:
        clean["conversation_ids"] = None
    return clean


async def enqueue_analysis_job(
    *,
    trigger: str,
    payload: dict,
    priority: int = 0,
    max_attempts: int = 2,
    dedupe_key: str | None = None,
    dedupe_active: bool = True,
) -> dict:
    _ensure_tables()
    normalized_payload = _build_run_payload(payload)
    payload_json = _safe_json_dumps(normalized_payload)
    dedupe = _build_dedupe_key(trigger, normalized_payload, dedupe_key)
    now = _now()
    safe_priority = max(-20, min(20, int(priority)))
    safe_attempts = max(1, min(6, int(max_attempts)))

    async def _write_op():
        db = get_db()
        tbl = db.open_table(JOBS_TABLE)

        if dedupe_active:
            active = tbl.search().where("status = 'pending' OR status = 'running'").limit(2000).to_list()
            for row in active:
                if str(row.get("dedupe_key") or "") == dedupe:
                    return {
                        "status": "duplicate",
                        "job": _public_job(row),
                    }

        row = {
            "id": str(uuid.uuid4()),
            "trigger": str(trigger or "manual"),
            "status": STATUS_PENDING,
            "priority": safe_priority,
            "dedupe_key": dedupe,
            "payload_json": payload_json,
            "result_json": "",
            "error": "",
            "attempt_count": 0,
            "max_attempts": safe_attempts,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "completed_at": None,
        }
        tbl.add([row])
        return {
            "status": "accepted",
            "job": _public_job(row),
        }

    return await enqueue_write(_write_op)


def get_analysis_job(job_id: str) -> Optional[dict]:
    _ensure_tables()
    db = get_db()
    if JOBS_TABLE not in db.table_names():
        return None
    tbl = db.open_table(JOBS_TABLE)
    escaped = _escape_sql(job_id)
    rows = tbl.search().where(f"id = '{escaped}'").limit(1).to_list()
    if not rows:
        return None
    return _public_job(rows[0])


def get_analysis_jobs_overview(limit: int = 20) -> dict:
    _ensure_tables()
    db = get_db()
    if JOBS_TABLE not in db.table_names():
        return {
            "counts": {
                STATUS_PENDING: 0,
                STATUS_RUNNING: 0,
                STATUS_COMPLETED: 0,
                STATUS_FAILED: 0,
                STATUS_CANCELLED: 0,
            },
            "recent": [],
        }

    safe_limit = max(1, min(int(limit), 80))
    scan_limit = min(200000, max(1000, safe_limit * 200))
    rows = db.open_table(JOBS_TABLE).search().limit(scan_limit).to_list()

    counts = {
        STATUS_PENDING: 0,
        STATUS_RUNNING: 0,
        STATUS_COMPLETED: 0,
        STATUS_FAILED: 0,
        STATUS_CANCELLED: 0,
    }
    for row in rows:
        status = str(row.get("status") or "").strip().lower()
        if status in counts:
            counts[status] += 1

    rows.sort(key=lambda r: _to_dt(r.get("created_at")), reverse=True)
    recent = [_public_job(r) for r in rows[:safe_limit]]
    return {
        "counts": counts,
        "recent": recent,
    }


def has_active_jobs(trigger: Optional[str] = None) -> bool:
    _ensure_tables()
    db = get_db()
    if JOBS_TABLE not in db.table_names():
        return False
    rows = db.open_table(JOBS_TABLE).search().where("status = 'pending' OR status = 'running'").limit(2000).to_list()
    if not rows:
        return False
    if not trigger:
        return True
    t = str(trigger).strip().lower()
    for row in rows:
        if str(row.get("trigger") or "").strip().lower().startswith(t):
            return True
    return False


async def cancel_analysis_job(job_id: str) -> Optional[dict]:
    _ensure_tables()
    escaped = _escape_sql(job_id)
    now = _now()

    async def _write_op():
        db = get_db()
        if JOBS_TABLE not in db.table_names():
            return None
        tbl = db.open_table(JOBS_TABLE)
        rows = tbl.search().where(f"id = '{escaped}'").limit(1).to_list()
        if not rows:
            return None
        row = rows[0]
        if str(row.get("status") or "").strip().lower() != STATUS_PENDING:
            return _public_job(row)
        tbl.update(
            where=f"id = '{escaped}'",
            values={
                "status": STATUS_CANCELLED,
                "updated_at": now,
                "completed_at": now,
            },
        )
        updated = tbl.search().where(f"id = '{escaped}'").limit(1).to_list()
        return _public_job(updated[0]) if updated else None

    return await enqueue_write(_write_op)


async def _recover_running_jobs():
    _ensure_tables()
    db = get_db()
    if JOBS_TABLE not in db.table_names():
        return
    tbl = db.open_table(JOBS_TABLE)
    rows = tbl.search().where("status = 'running'").limit(2000).to_list()
    if not rows:
        return

    now = _now()

    async def _write_op():
        recovered = 0
        for row in rows:
            job_id = str(row.get("id") or "")
            if not job_id:
                continue
            escaped = _escape_sql(job_id)
            attempts = int(row.get("attempt_count") or 0)
            max_attempts = int(row.get("max_attempts") or 2)
            next_status = STATUS_PENDING if attempts < max_attempts else STATUS_FAILED
            suffix = "Recovered after application restart during execution."
            prior = str(row.get("error") or "").strip()
            error_msg = f"{prior} {suffix}".strip()[:500]
            values = {
                "status": next_status,
                "updated_at": now,
                "error": error_msg,
            }
            if next_status == STATUS_FAILED:
                values["completed_at"] = now
            else:
                values["started_at"] = None
            tbl.update(where=f"id = '{escaped}'", values=values)
            recovered += 1
        return recovered

    recovered = await enqueue_write(_write_op)
    if recovered:
        logger.info(f"Recovered {recovered} in-flight conversation analysis job(s)")


async def _claim_next_job() -> Optional[dict]:
    _ensure_tables()
    db = get_db()
    if JOBS_TABLE not in db.table_names():
        return None
    tbl = db.open_table(JOBS_TABLE)
    rows = tbl.search().where("status = 'pending'").limit(5000).to_list()
    if not rows:
        return None
    rows.sort(key=lambda r: (-int(r.get("priority") or 0), _to_dt(r.get("created_at")).timestamp()))
    selected = rows[0]
    selected_id = str(selected.get("id") or "")
    if not selected_id:
        return None
    escaped = _escape_sql(selected_id)
    now = _now()

    async def _write_op():
        db_write = get_db()
        if JOBS_TABLE not in db_write.table_names():
            return None
        jobs = db_write.open_table(JOBS_TABLE)
        current_rows = jobs.search().where(f"id = '{escaped}'").limit(1).to_list()
        if not current_rows:
            return None
        current = current_rows[0]
        if str(current.get("status") or "").strip().lower() != STATUS_PENDING:
            return None
        attempts = int(current.get("attempt_count") or 0) + 1
        jobs.update(
            where=f"id = '{escaped}'",
            values={
                "status": STATUS_RUNNING,
                "attempt_count": attempts,
                "started_at": now,
                "updated_at": now,
                "error": "",
            },
        )
        updated = jobs.search().where(f"id = '{escaped}'").limit(1).to_list()
        return updated[0] if updated else None

    claimed = await enqueue_write(_write_op)
    return claimed if isinstance(claimed, dict) else None


async def _set_job_status(
    *,
    job_id: str,
    status: str,
    result: dict | None = None,
    error: str = "",
    requeue: bool = False,
):
    escaped = _escape_sql(job_id)
    now = _now()

    async def _write_op():
        db = get_db()
        if JOBS_TABLE not in db.table_names():
            return None
        tbl = db.open_table(JOBS_TABLE)
        values: dict[str, Any] = {
            "status": status,
            "updated_at": now,
            "error": str(error or "")[:500],
        }
        if requeue:
            values["started_at"] = None
        if status in _TERMINAL_STATUSES:
            values["completed_at"] = now
            values["result_json"] = _safe_json_dumps(result if isinstance(result, dict) else {})
        tbl.update(where=f"id = '{escaped}'", values=values)
        rows = tbl.search().where(f"id = '{escaped}'").limit(1).to_list()
        return rows[0] if rows else None

    return await enqueue_write(_write_op)


async def _run_job(job: dict):
    from backend.memory.conversation_mining import run_mining_singleflight

    job_id = str(job.get("id") or "")
    trigger = str(job.get("trigger") or "manual")
    attempts = int(job.get("attempt_count") or 0)
    max_attempts = int(job.get("max_attempts") or 2)
    payload = _safe_json_loads(job.get("payload_json"), default={})
    if not isinstance(payload, dict):
        payload = {}
    payload = _build_run_payload(payload)

    created_at = _to_dt(job.get("created_at"))
    started_at = _to_dt(job.get("started_at"))
    queue_wait_ms = max(0, int((started_at - created_at).total_seconds() * 1000))
    _set_worker_step(2, 5, "analyze", "Analyzing conversation contexts")

    try:
        start = time.monotonic()
        response = await run_mining_singleflight(
            trigger=trigger,
            wait_if_busy=True,
            **payload,
        )
        if str(response.get("status") or "").strip().lower() == "busy":
            raise RuntimeError(response.get("message") or "Conversation analysis is busy.")
        result = response.get("result", {}) if isinstance(response, dict) else {}
        if not isinstance(result, dict):
            result = {}
        write_stats = result.get("write_stats", {}) if isinstance(result.get("write_stats"), dict) else {}
        configured_provider = str(payload.get("provider") or "").strip().lower()
        should_try_fallback = (
            str(trigger).strip().lower().startswith("auto")
            and not bool(payload.get("require_llm_configured", True))
            and configured_provider not in {"", "heuristic"}
            and str(result.get("status") or "").strip().lower() != "blocked"
            and int(write_stats.get("created", 0) or 0) == 0
            and int(write_stats.get("merged", 0) or 0) == 0
            and int(write_stats.get("skipped", 0) or 0) == 0
            and int(write_stats.get("conflict_pending", 0) or 0) == 0
            and int(write_stats.get("rejected", 0) or 0) > 0
        )
        if should_try_fallback:
            _set_worker_step(3, 5, "fallback", "Retrying with heuristic fallback")
            fallback_payload = dict(payload)
            fallback_payload["provider"] = "heuristic"
            fallback_payload["force_reanalyze"] = True
            fallback_response = await run_mining_singleflight(
                trigger=trigger,
                wait_if_busy=True,
                **fallback_payload,
            )
            fallback_result = fallback_response.get("result", {}) if isinstance(fallback_response, dict) else {}
            fallback_stats = (
                fallback_result.get("write_stats", {})
                if isinstance(fallback_result, dict) and isinstance(fallback_result.get("write_stats"), dict)
                else {}
            )
            if int(fallback_stats.get("created", 0) or 0) >= int(write_stats.get("created", 0) or 0):
                result = fallback_result if isinstance(fallback_result, dict) else result
                if isinstance(result, dict):
                    result["fallback_provider"] = "heuristic"
                    result["fallback_used"] = True
        metrics = result.get("metrics", {}) if isinstance(result.get("metrics"), dict) else {}
        if "total_ms" not in metrics:
            metrics["total_ms"] = int((time.monotonic() - start) * 1000)
        metrics["queue_wait_ms"] = queue_wait_ms
        result["metrics"] = metrics
        _set_worker_step(4, 5, "finalize", "Finalizing and persisting results")

        await _set_job_status(job_id=job_id, status=STATUS_COMPLETED, result=result)
        _set_worker_step(5, 5, "complete", "Completed")
        try:
            _persist_analysis_state(trigger=trigger, result=result)
        except Exception:
            pass
    except Exception as e:
        _set_worker_step(5, 5, "error", "Failed")
        error = str(e).strip() or "Conversation analysis run failed."
        can_retry = attempts < max_attempts
        if can_retry:
            await _set_job_status(
                job_id=job_id,
                status=STATUS_PENDING,
                error=error,
                requeue=True,
            )
        else:
            await _set_job_status(
                job_id=job_id,
                status=STATUS_FAILED,
                error=error,
                result={},
            )
            try:
                _persist_analysis_state(trigger=trigger, error=error)
            except Exception:
                pass
        raise


async def _worker_loop():
    await _recover_running_jobs()
    logger.info("Conversation analysis worker started")
    while True:
        _worker_state["last_heartbeat"] = _now().isoformat()
        try:
            job = await _claim_next_job()
            if not job:
                _worker_state["running"] = False
                _worker_state["current_job_id"] = None
                _worker_state["current_job_trigger"] = None
                _worker_state["current_job_started_at"] = None
                _reset_worker_step()
                await asyncio.sleep(1.0)
                continue

            job_id = str(job.get("id") or "")
            _worker_state["running"] = True
            _worker_state["current_job_id"] = job_id
            _worker_state["current_job_trigger"] = str(job.get("trigger") or "").strip().lower() or None
            _worker_state["current_job_started_at"] = _now().isoformat()
            _worker_state["last_error"] = None
            _set_worker_step(1, 5, "prepare", "Preparing job")
            try:
                await _run_job(job)
            except Exception as e:
                _worker_state["last_error"] = str(e)
                logger.warning(f"Conversation analysis job {job_id} failed: {e}")
            finally:
                _worker_state["processed_count"] = int(_worker_state.get("processed_count", 0) or 0) + 1
                _worker_state["last_completed_at"] = _now().isoformat()
                _worker_state["current_job_id"] = None
                _worker_state["current_job_trigger"] = None
                _worker_state["current_job_started_at"] = None
                _worker_state["running"] = False
                _reset_worker_step()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _worker_state["last_error"] = str(e)
            _reset_worker_step()
            logger.error(f"Conversation analysis worker loop error: {e}")
            await asyncio.sleep(1.5)


def start_analysis_job_worker():
    global _worker_task
    if _worker_task and not _worker_task.done():
        return
    _worker_task = asyncio.create_task(_worker_loop())


def get_analysis_worker_state() -> dict:
    alive = bool(_worker_task and not _worker_task.done())
    state = dict(_worker_state)
    state["task_alive"] = alive
    step_total = max(0, int(state.get("current_step_total") or 0))
    step_index = max(0, int(state.get("current_step_index") or 0))
    if step_total > 0:
        state["current_step_progress"] = max(0.0, min(1.0, float(step_index) / float(step_total)))
    else:
        state["current_step_progress"] = 0.0
    return state
