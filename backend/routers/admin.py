import asyncio
from datetime import datetime, timezone, timedelta
import logging
from typing import Any
import uuid
import json
import os

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from backend.auth import normalize_client_scopes
from backend.config import CONFIG_DIR, CONFIG_PATH, load_config, save_config, rotate_snapshot_token as rotate_token_logic
from backend.database.client import get_db
from backend.database.schema import Conversation, Message, EMBEDDING_DIM
from backend.insights.service import get_insights_config_public, update_insights_config
from backend.memory.write_queue import enqueue_write
from backend.memory.embedder import get_status as get_embedding_status
from backend.memory.model_manager import model_manager
from backend.remote import get_remote_access_status
from backend.security import (
    bootstrap_bridge_mcp_key,
    collect_security_audit,
    get_request_metrics_snapshot,
    security_runtime_overview,
    strict_security_patch,
)
from backend.sync.service import (
    get_sync_public_status,
    lock_sync,
    run_sync_now,
    unlock_sync,
    update_sync_config,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
logger = logging.getLogger(__name__)


def _internal_error(message: str, exc: Exception | None = None) -> HTTPException:
    if exc is not None:
        logger.exception(message)
    return HTTPException(status_code=500, detail=message)


def _bad_request(message: str, exc: Exception | None = None) -> HTTPException:
    if exc is not None:
        logger.warning(f"{message}: {exc}")
    return HTTPException(status_code=400, detail=message)


def _to_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception:
            pass
    if isinstance(value, str) and value:
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception:
            pass
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            pass
    return datetime.fromtimestamp(0, tz=timezone.utc)


def _conversation_key(row: dict) -> tuple:
    raw_hash = str(row.get("raw_file_hash") or "").strip().lower()
    if raw_hash:
        return ("hash", raw_hash)

    title = str(row.get("title") or "").strip().lower()
    started_at = _to_dt(row.get("started_at")).isoformat()
    source_llm = str(row.get("source_llm") or "").strip().lower()
    message_count = max(0, int(row.get("message_count", 0) or 0))

    if title or source_llm or message_count > 0:
        return ("fp", title, started_at, source_llm, message_count)

    row_id = row.get("id")
    if row_id:
        return ("id", str(row_id))
    return ("fp", title, started_at, source_llm, message_count)


def _message_key(row: dict) -> tuple:
    role = str(row.get("role") or "").strip().lower()
    content = str(row.get("content") or "").strip()
    timestamp = _to_dt(row.get("timestamp")).isoformat()
    if content:
        return ("fp", role, content, timestamp)

    row_id = row.get("id")
    if row_id:
        return ("id", str(row_id))
    return ("fp", str(row.get("conversation_id") or "").strip(), role, content, timestamp)


def _is_newer(row_a: dict, row_b: dict) -> bool:
    # True when row_a should replace row_b.
    a_updated = _to_dt(row_a.get("updated_at") or row_a.get("timestamp") or row_a.get("imported_at"))
    b_updated = _to_dt(row_b.get("updated_at") or row_b.get("timestamp") or row_b.get("imported_at"))
    return a_updated >= b_updated


def _sanitize_conversation_row(row: dict) -> Conversation:
    now = datetime.now(timezone.utc)
    return Conversation(
        id=str(row.get("id") or uuid.uuid4()),
        title=str(row.get("title") or "Untitled"),
        source_llm=str(row.get("source_llm") or "imported"),
        started_at=_to_dt(row.get("started_at")),
        ended_at=_to_dt(row.get("ended_at")) if row.get("ended_at") else None,
        message_count=max(0, int(row.get("message_count", 0) or 0)),
        memory_ids=row.get("memory_ids") if isinstance(row.get("memory_ids"), list) else [],
        tags=row.get("tags") if isinstance(row.get("tags"), list) else [],
        summary=str(row.get("summary") or ""),
        status=str(row.get("status") or "archived"),
        raw_file_hash=str(row.get("raw_file_hash") or ""),
        imported_at=_to_dt(row.get("imported_at") or now),
    )


def _sanitize_message_row(row: dict) -> Message:
    vector = row.get("vector")
    safe_vector = vector if isinstance(vector, list) and len(vector) == EMBEDDING_DIM else None
    return Message(
        id=str(row.get("id") or uuid.uuid4()),
        conversation_id=str(row.get("conversation_id") or ""),
        role=str(row.get("role") or "user"),
        content=str(row.get("content") or ""),
        timestamp=_to_dt(row.get("timestamp")),
        vector=None,
    )

@router.post("/onboarding-complete")
async def complete_onboarding():
    """Mark onboarding as complete in config."""
    try:
        config = load_config()
        config['onboarding_completed'] = True
        save_config(config)
        autoconfig_result = None
        try:
            from backend.config_watcher import run_first_launch_autoconfigure

            autoconfig_result = run_first_launch_autoconfigure(force=False)
        except Exception as e:
            logger.warning(f"MCP autoconfig during onboarding failed: {e}")
            autoconfig_result = {"status": "error", "message": "MCP autoconfiguration failed."}
        return {"status": "ok", "mcp_autoconfig": autoconfig_result}
    except Exception as e:
        raise _internal_error("Failed to complete onboarding.", e)

_SENSITIVE_CONFIG_KEYS = {"snapshot_read_token", "secret_access_key", "webdav_password"}


def _safe_config(config: dict) -> dict:
    """Return config with sensitive values masked. Never expose secrets over HTTP."""
    return {k: ("***" if k in _SENSITIVE_CONFIG_KEYS else v) for k, v in config.items()}


@router.get("/config")
async def get_config(response: Response):
    """Get current configuration (sensitive fields masked)."""
    try:
        config = load_config()
        # Ensure default structure if missing
        if 'decay_rates' not in config:
            config['decay_rates'] = {'semantic': 0.001, 'episodic': 0.05, 'working': 0.3}

        # Do not cache: onboarding/token values must be read fresh
        response.headers["Cache-Control"] = "no-store"
        return _safe_config(config)
    except Exception as e:
        raise _internal_error("Failed to load config.", e)


@router.get("/snapshot-token")
async def get_snapshot_token():
    """Get the current snapshot read token (used by tray and HTTP clients)."""
    try:
        config = load_config()
        return {"token": config.get("snapshot_read_token", "")}
    except Exception as e:
        raise _internal_error("Failed to load snapshot token.", e)


@router.post("/snapshot-token/rotate")
async def rotate_snapshot_token():
    """Rotate the snapshot read token."""
    try:
        new_token = rotate_token_logic()
        return {"token": new_token}
    except Exception as e:
        raise _internal_error("Failed to rotate snapshot token.", e)


class SyncConfigUpdate(BaseModel):
    enabled: bool | None = None
    provider: str | None = None
    endpoint_url: str | None = None
    force_path_style: bool | None = None
    webdav_url: str | None = None
    webdav_username: str | None = None
    webdav_password: str | None = None
    bucket: str | None = None
    region: str | None = None
    access_key_id: str | None = None
    secret_access_key: str | None = None
    object_prefix: str | None = None
    device_id: str | None = None
    auto_sync: bool | None = None
    auto_sync_interval_minutes: int | None = None


class SyncUnlockPayload(BaseModel):
    passphrase: str


class SyncRunPayload(BaseModel):
    passphrase: str | None = None
    source: str = "manual"


class SyncTestPayload(BaseModel):
    provider: str
    # S3 / R2
    endpoint_url: str | None = None
    bucket: str | None = None
    region: str | None = None
    access_key_id: str | None = None
    secret_access_key: str | None = None
    # WebDAV
    webdav_url: str | None = None
    webdav_username: str | None = None
    webdav_password: str | None = None


class InsightsConfigUpdate(BaseModel):
    enabled: bool | None = None
    provider: str | None = None
    model: str | None = None
    api_key: str | None = None
    api_base_url: str | None = None


class McpAutoconfigPayload(BaseModel):
    force: bool = False


class DeduplicateConversationsPayload(BaseModel):
    dry_run: bool = True
    include_messages: bool = True


class PurgeConversationsPayload(BaseModel):
    include_messages: bool = True


class DeleteConversationsByIdPayload(BaseModel):
    conversation_ids: list[str]
    include_messages: bool = True


class RunBackgroundAnalysisPayload(BaseModel):
    force_reanalyze: bool = False
    provider: str | None = None
    conversation_ids: list[str] | None = None
    max_conversations: int | None = None
    max_messages_per_conversation: int | None = None
    max_candidates_per_conversation: int | None = None
    max_new_memories: int | None = None
    min_confidence: float | None = None
    concurrency: int | None = None
    wait_for_completion: bool = False


class SecurityConfigUpdate(BaseModel):
    enforce_mcp_auth: bool | None = None
    allow_snapshot_token_for_mcp: bool | None = None
    allow_snapshot_query_token: bool | None = None
    require_client_mutation_header: bool | None = None
    client_mutation_header_name: str | None = None
    allowed_client_mutation_header_values: list[str] | None = None
    allowed_mutation_origins: list[str] | None = None
    rate_limit: dict[str, Any] | None = None
    audit: dict[str, Any] | None = None


class SecurityHardenPayload(BaseModel):
    force_disable_snapshot_mcp_fallback: bool = False
    bootstrap_bridge_key: bool = True


class RemoteAccessConfigUpdate(BaseModel):
    enabled: bool | None = None
    relay_url: str | None = None
    project_id: str | None = None
    device_id: str | None = None
    device_secret: str | None = None
    device_name: str | None = None
    poll_interval_seconds: int | None = None
    request_timeout_seconds: int | None = None
    max_tasks_per_poll: int | None = None
    rotate_device_secret: bool | None = None


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
    try:
        with open(path, "w") as f:
            json.dump(state or {}, f, default=str, indent=2)
    except Exception:
        pass


def _merge_security_config(existing: dict, patch: dict) -> dict:
    merged = dict(existing or {})
    for key, value in (patch or {}).items():
        if value is None:
            continue
        if key in {"rate_limit", "audit"} and isinstance(value, dict):
            current = merged.get(key, {})
            if not isinstance(current, dict):
                current = {}
            merged[key] = {**current, **value}
            if key == "rate_limit":
                buckets = value.get("buckets")
                if isinstance(buckets, dict):
                    current_buckets = current.get("buckets", {})
                    if not isinstance(current_buckets, dict):
                        current_buckets = {}
                    merged[key]["buckets"] = {**current_buckets, **buckets}
            continue
        merged[key] = value
    return merged


def _analysis_tag_info(tags: list[str]) -> tuple[bool, bool]:
    has_analysis = False
    has_msgcount = False
    for tag in tags:
        value = str(tag or "").strip().lower()
        if value == "auto:conversation-analysis":
            has_analysis = True
        if value.startswith("auto:conversation-analysis:msgcount:"):
            has_msgcount = True
    return has_analysis, has_msgcount


def _merge_max_iso(current: str | None, candidate: Any) -> str | None:
    if not candidate:
        return current
    candidate_dt = _to_dt(candidate)
    if not current:
        return candidate_dt.isoformat()
    current_dt = _to_dt(current)
    return candidate_dt.isoformat() if candidate_dt >= current_dt else current


def _configured_clients_from_config(cfg: dict) -> dict[str, dict]:
    raw = cfg.get("llm_client_keys", {}) if isinstance(cfg.get("llm_client_keys"), dict) else {}
    out: dict[str, dict] = {}
    for key_name, key_value in raw.items():
        name = str(key_name or "").strip().lower()
        if not name:
            continue
        if isinstance(key_value, dict):
            if key_value.get("enabled") is False:
                continue
            scopes = sorted(normalize_client_scopes(key_value.get("scopes")))
        else:
            scopes = sorted(normalize_client_scopes(None))
        out[name] = {"name": name, "configured": True, "scopes": scopes}
    return out


def _collect_runtime_metrics_history(
    db,
    *,
    period_hours: int = 24,
    limit: int = 120000,
    recent_limit: int = 120,
) -> dict:
    default = {
        "period_hours": int(max(1, period_hours)),
        "rows_considered": 0,
        "by_client": {},
        "recent": [],
    }
    if "client_runtime_metrics" not in db.table_names():
        return default

    try:
        rows = db.open_table("client_runtime_metrics").search().limit(max(1, int(limit))).to_list()
    except Exception:
        return default

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, int(period_hours)))
    by_client: dict[str, dict] = {}
    recent_rows: list[dict] = []

    for row in rows:
        captured = _to_dt(row.get("captured_at"))
        if captured < cutoff:
            continue
        client = str(row.get("client") or "unknown").strip().lower() or "unknown"
        delta_requests = max(0, int(row.get("delta_requests", row.get("total_requests", 0)) or 0))
        delta_errors = max(0, int(row.get("delta_errors", row.get("error_requests", 0)) or 0))
        avg_latency = float(row.get("avg_latency_ms", 0.0) or 0.0)
        p95_latency = float(row.get("p95_latency_ms", 0.0) or 0.0)

        entry = by_client.setdefault(
            client,
            {
                "requests_24h": 0,
                "errors_24h": 0,
                "windows_24h": 0,
                "avg_latency_24h_ms": 0.0,
                "p95_latency_24h_ms": 0.0,
                "last_captured_at": None,
                "_latency_weight_sum": 0.0,
                "_latency_weight": 0,
                "_latency_sample_sum": 0.0,
                "_latency_sample_count": 0,
            },
        )
        entry["requests_24h"] = int(entry.get("requests_24h", 0) or 0) + delta_requests
        entry["errors_24h"] = int(entry.get("errors_24h", 0) or 0) + delta_errors
        entry["windows_24h"] = int(entry.get("windows_24h", 0) or 0) + 1
        entry["last_captured_at"] = _merge_max_iso(entry.get("last_captured_at"), captured)
        entry["p95_latency_24h_ms"] = round(max(float(entry.get("p95_latency_24h_ms", 0.0) or 0.0), p95_latency), 2)
        if delta_requests > 0:
            entry["_latency_weight_sum"] = float(entry.get("_latency_weight_sum", 0.0) or 0.0) + (
                avg_latency * float(delta_requests)
            )
            entry["_latency_weight"] = int(entry.get("_latency_weight", 0) or 0) + delta_requests
        else:
            entry["_latency_sample_sum"] = float(entry.get("_latency_sample_sum", 0.0) or 0.0) + avg_latency
            entry["_latency_sample_count"] = int(entry.get("_latency_sample_count", 0) or 0) + 1

        recent_rows.append(
            {
                "client": client,
                "captured_at": captured.isoformat(),
                "delta_requests": delta_requests,
                "delta_errors": delta_errors,
                "avg_latency_ms": round(avg_latency, 2),
                "p95_latency_ms": round(p95_latency, 2),
            }
        )

    for entry in by_client.values():
        weight = int(entry.get("_latency_weight", 0) or 0)
        if weight > 0:
            avg_24h = float(entry.get("_latency_weight_sum", 0.0) or 0.0) / float(weight)
        else:
            sample_count = int(entry.get("_latency_sample_count", 0) or 0)
            sample_sum = float(entry.get("_latency_sample_sum", 0.0) or 0.0)
            avg_24h = (sample_sum / float(sample_count)) if sample_count > 0 else 0.0
        entry["avg_latency_24h_ms"] = round(avg_24h, 2)
        entry.pop("_latency_weight_sum", None)
        entry.pop("_latency_weight", None)
        entry.pop("_latency_sample_sum", None)
        entry.pop("_latency_sample_count", None)

    recent_rows.sort(key=lambda item: _to_dt(item.get("captured_at")), reverse=True)
    return {
        "period_hours": int(max(1, period_hours)),
        "rows_considered": len(recent_rows),
        "by_client": by_client,
        "recent": recent_rows[: max(1, int(recent_limit))],
    }


def _collect_client_observability(
    db,
    cfg: dict,
    *,
    session_limit: int = 500000,
    runtime_history_limit: int = 120000,
    runtime_recent_limit: int = 120,
) -> dict:
    configured = _configured_clients_from_config(cfg)
    runtime_history = _collect_runtime_metrics_history(
        db,
        period_hours=24,
        limit=max(1, int(runtime_history_limit)),
        recent_limit=max(1, int(runtime_recent_limit)),
    )
    runtime_metrics = get_request_metrics_snapshot()

    def _new_entry(name: str, *, configured_flag: bool, scopes: list[str]) -> dict:
        return {
            "name": name,
            "configured": configured_flag,
            "scopes": scopes,
            "sessions_total": 0,
            "sessions_with_reads": 0,
            "sessions_with_writes": 0,
            "sessions_with_feedback": 0,
            "read_before_write_sessions": 0,
            "write_without_read_sessions": 0,
            "memory_reads_total": 0,
            "memory_writes_total": 0,
            "memory_feedback_total": 0,
            "last_seen_at": None,
            "last_read_at": None,
            "last_write_at": None,
            "last_feedback_at": None,
            "runtime_total_requests": 0,
            "runtime_error_requests": 0,
            "runtime_avg_latency_ms": 0.0,
            "runtime_p95_latency_ms": 0.0,
            "runtime_last_error_at": None,
            "runtime_requests_24h": 0,
            "runtime_errors_24h": 0,
            "runtime_windows_24h": 0,
            "runtime_avg_latency_24h_ms": 0.0,
            "runtime_p95_latency_24h_ms": 0.0,
            "runtime_last_captured_at": None,
            "reads_before_response": "no-data",
            "read_before_response_rate": 0.0,
            "usage_rate": 0.0,
        }

    clients: dict[str, dict] = {
        name: _new_entry(name, configured_flag=True, scopes=data.get("scopes", []))
        for name, data in configured.items()
    }

    all_sessions: list[dict] = []
    if "sessions" in db.table_names():
        try:
            all_sessions = db.open_table("sessions").search().limit(max(1, int(session_limit))).to_list()
        except Exception:
            all_sessions = []

    for row in all_sessions:
        client_name = str(row.get("api_key_id") or row.get("source_llm") or "").strip().lower()
        if not client_name:
            client_name = "unknown"
        entry = clients.setdefault(
            client_name,
            _new_entry(
                client_name,
                configured_flag=(client_name in configured),
                scopes=configured.get(client_name, {}).get("scopes", []),
            ),
        )

        ts = _to_dt(row.get("ended_at") or row.get("started_at"))
        entry["sessions_total"] = int(entry.get("sessions_total", 0) or 0) + 1
        entry["last_seen_at"] = _merge_max_iso(entry.get("last_seen_at"), ts)

        read_ids = [str(v) for v in (row.get("memory_ids_read") or []) if str(v)]
        write_ids = [str(v) for v in (row.get("memory_ids_written") or []) if str(v)]
        feedback_ids = [str(v) for v in (row.get("memory_ids_feedback") or []) if str(v)]

        if read_ids:
            entry["sessions_with_reads"] = int(entry.get("sessions_with_reads", 0) or 0) + 1
            entry["memory_reads_total"] = int(entry.get("memory_reads_total", 0) or 0) + len(read_ids)
            entry["last_read_at"] = _merge_max_iso(entry.get("last_read_at"), ts)
        if write_ids:
            entry["sessions_with_writes"] = int(entry.get("sessions_with_writes", 0) or 0) + 1
            entry["memory_writes_total"] = int(entry.get("memory_writes_total", 0) or 0) + len(write_ids)
            entry["last_write_at"] = _merge_max_iso(entry.get("last_write_at"), ts)
            if read_ids:
                entry["read_before_write_sessions"] = int(entry.get("read_before_write_sessions", 0) or 0) + 1
            else:
                entry["write_without_read_sessions"] = int(entry.get("write_without_read_sessions", 0) or 0) + 1
        if feedback_ids:
            entry["sessions_with_feedback"] = int(entry.get("sessions_with_feedback", 0) or 0) + 1
            entry["memory_feedback_total"] = int(entry.get("memory_feedback_total", 0) or 0) + len(feedback_ids)
            entry["last_feedback_at"] = _merge_max_iso(entry.get("last_feedback_at"), ts)

    for client_name, metrics in (runtime_metrics or {}).items():
        key = str(client_name or "").strip().lower() or "unknown"
        entry = clients.setdefault(
            key,
            _new_entry(
                key,
                configured_flag=(key in configured),
                scopes=configured.get(key, {}).get("scopes", []),
            ),
        )
        entry["runtime_total_requests"] = int(metrics.get("total_requests", 0) or 0)
        entry["runtime_error_requests"] = int(metrics.get("error_requests", 0) or 0)
        entry["runtime_avg_latency_ms"] = float(metrics.get("avg_latency_ms", 0.0) or 0.0)
        entry["runtime_p95_latency_ms"] = float(metrics.get("p95_latency_ms", 0.0) or 0.0)
        entry["runtime_last_error_at"] = metrics.get("last_error_at")
        entry["last_seen_at"] = _merge_max_iso(entry.get("last_seen_at"), metrics.get("last_seen_at"))

    history_by_client = runtime_history.get("by_client", {}) if isinstance(runtime_history, dict) else {}
    if isinstance(history_by_client, dict):
        for client_name, stats in history_by_client.items():
            key = str(client_name or "").strip().lower() or "unknown"
            entry = clients.setdefault(
                key,
                _new_entry(
                    key,
                    configured_flag=(key in configured),
                    scopes=configured.get(key, {}).get("scopes", []),
                ),
            )
            entry["runtime_requests_24h"] = int(stats.get("requests_24h", 0) or 0)
            entry["runtime_errors_24h"] = int(stats.get("errors_24h", 0) or 0)
            entry["runtime_windows_24h"] = int(stats.get("windows_24h", 0) or 0)
            entry["runtime_avg_latency_24h_ms"] = float(stats.get("avg_latency_24h_ms", 0.0) or 0.0)
            entry["runtime_p95_latency_24h_ms"] = float(stats.get("p95_latency_24h_ms", 0.0) or 0.0)
            entry["runtime_last_captured_at"] = stats.get("last_captured_at")

    total_sessions = max(1, sum(int(item.get("sessions_total", 0) or 0) for item in clients.values()))
    for entry in clients.values():
        write_sessions = int(entry.get("sessions_with_writes", 0) or 0)
        read_write_sessions = int(entry.get("read_before_write_sessions", 0) or 0)
        if write_sessions > 0:
            rate = read_write_sessions / float(write_sessions)
            entry["read_before_response_rate"] = round(rate, 4)
            entry["reads_before_response"] = "yes" if rate >= 0.95 else "no"
        else:
            entry["read_before_response_rate"] = 0.0
            entry["reads_before_response"] = "no-data"
        entry["usage_rate"] = round((int(entry.get("sessions_total", 0) or 0) / float(total_sessions)), 4)

    rows = sorted(
        list(clients.values()),
        key=lambda x: (
            1 if x.get("configured") else 0,
            int(x.get("sessions_total", 0) or 0),
            int(x.get("runtime_total_requests", 0) or 0),
        ),
        reverse=True,
    )

    write_sessions_total = sum(int(item.get("sessions_with_writes", 0) or 0) for item in rows)
    read_before_write_total = sum(int(item.get("read_before_write_sessions", 0) or 0) for item in rows)
    cross_llm_read_reliability = (
        (read_before_write_total / float(write_sessions_total)) if write_sessions_total > 0 else 0.0
    )
    active_clients = [
        item
        for item in rows
        if int(item.get("sessions_total", 0) or 0) > 0 or int(item.get("runtime_total_requests", 0) or 0) > 0
    ]
    runtime_requests_24h_total = sum(int(item.get("runtime_requests_24h", 0) or 0) for item in rows)
    runtime_errors_24h_total = sum(int(item.get("runtime_errors_24h", 0) or 0) for item in rows)
    return {
        "clients": rows,
        "summary": {
            "total_clients": len(rows),
            "configured_clients": sum(1 for item in rows if item.get("configured")),
            "active_clients": len(active_clients),
            "sessions_total": sum(int(item.get("sessions_total", 0) or 0) for item in rows),
            "write_sessions_total": write_sessions_total,
            "read_before_write_sessions_total": read_before_write_total,
            "cross_llm_read_reliability": round(cross_llm_read_reliability, 4),
            "runtime_requests_24h_total": runtime_requests_24h_total,
            "runtime_errors_24h_total": runtime_errors_24h_total,
            "runtime_error_rate_24h": round(
                (runtime_errors_24h_total / float(runtime_requests_24h_total))
                if runtime_requests_24h_total > 0
                else 0.0,
                4,
            ),
            "runtime_rows_24h": int(runtime_history.get("rows_considered", 0) or 0),
        },
        "history": {
            "period_hours": int(runtime_history.get("period_hours", 24) or 24),
            "rows_considered": int(runtime_history.get("rows_considered", 0) or 0),
            "recent": runtime_history.get("recent", []),
        },
    }


def _release_gates(
    *,
    security_result: dict,
    last_analysis_stats: dict,
    client_observability: dict,
) -> dict:
    sec_summary = security_result.get("summary", {}) if isinstance(security_result, dict) else {}
    sec_fail = int(sec_summary.get("fail", 0) or 0)
    sec_score = int(security_result.get("score", 0) or 0)
    gate_a_pass = sec_fail == 0 and sec_score >= 90

    generic_rate = float(last_analysis_stats.get("generic_rate", 0.0) or 0.0)
    duplicate_rate = float(last_analysis_stats.get("duplicate_rate", 0.0) or 0.0)
    accepted_rate = float(last_analysis_stats.get("accepted_rate", 0.0) or 0.0)
    candidates_total = int(last_analysis_stats.get("candidates_total", 0) or 0)
    gate_b_has_data = candidates_total > 0
    gate_b_pass = (not gate_b_has_data) or (
        accepted_rate >= 0.85 and duplicate_rate <= 0.2 and generic_rate <= 0.25
    )

    summary = client_observability.get("summary", {}) if isinstance(client_observability, dict) else {}
    write_sessions_total = int(summary.get("write_sessions_total", 0) or 0)
    reliability = float(summary.get("cross_llm_read_reliability", 0.0) or 0.0)
    gate_c_has_data = write_sessions_total > 0
    gate_c_pass = (not gate_c_has_data) or (reliability >= 0.95)

    gates = [
        {
            "id": "A",
            "name": "Security validated",
            "pass": gate_a_pass,
            "thresholds": {"failures": 0, "score_min": 90},
            "actual": {"failures": sec_fail, "score": sec_score},
        },
        {
            "id": "B",
            "name": "Memory quality stable",
            "pass": gate_b_pass,
            "pending_data": not gate_b_has_data,
            "has_data": gate_b_has_data,
            "thresholds": {"accepted_rate_min": 0.85, "duplicate_rate_max": 0.2, "generic_rate_max": 0.25},
            "actual": {
                "accepted_rate": round(accepted_rate, 4),
                "duplicate_rate": round(duplicate_rate, 4),
                "generic_rate": round(generic_rate, 4),
                "candidates_total": candidates_total,
            },
        },
        {
            "id": "C",
            "name": "Cross-LLM read reliability",
            "pass": gate_c_pass,
            "pending_data": not gate_c_has_data,
            "has_data": gate_c_has_data,
            "thresholds": {"read_reliability_min": 0.95},
            "actual": {
                "read_reliability": round(reliability, 4),
                "write_sessions_total": write_sessions_total,
            },
        },
    ]
    blockers = [g["id"] for g in gates if not g.get("pass")]
    return {
        "ready_for_v1": len(blockers) == 0,
        "blockers": blockers,
        "gates": gates,
    }


@router.get("/sync/status")
async def get_sync_status():
    try:
        return get_sync_public_status()
    except Exception as e:
        raise _internal_error("Internal server error.", e)


@router.post("/sync/config")
async def save_sync_config(payload: SyncConfigUpdate):
    try:
        partial = payload.model_dump(exclude_none=True)
        return update_sync_config(partial)
    except Exception as e:
        raise _bad_request("Invalid request.", e)


@router.post("/sync/unlock")
async def unlock_sync_key(payload: SyncUnlockPayload):
    try:
        return unlock_sync(payload.passphrase)
    except Exception as e:
        raise _bad_request("Invalid request.", e)


@router.post("/sync/lock")
async def lock_sync_key():
    try:
        return lock_sync()
    except Exception as e:
        raise _internal_error("Internal server error.", e)


@router.post("/sync/run")
async def run_sync(payload: SyncRunPayload):
    try:
        return await run_sync_now(passphrase=payload.passphrase, source=payload.source or "manual")
    except Exception as e:
        raise _bad_request("Invalid request.", e)


@router.post("/sync/test")
async def test_sync_connection(payload: SyncTestPayload):
    """Verify sync credentials without saving config or triggering a sync."""
    provider = str(payload.provider or "").strip().lower()
    try:
        if provider in ("s3", "r2"):
            import boto3
            from botocore.config import Config as BotocoreConfig

            s3 = boto3.client(
                "s3",
                endpoint_url=payload.endpoint_url or None,
                aws_access_key_id=payload.access_key_id or None,
                aws_secret_access_key=payload.secret_access_key or None,
                region_name=payload.region or "auto",
                config=BotocoreConfig(connect_timeout=5, read_timeout=5),
            )
            bucket = str(payload.bucket or "").strip()
            if not bucket:
                raise HTTPException(status_code=400, detail="bucket is required")
            s3.head_bucket(Bucket=bucket)
            return {"ok": True, "provider": provider}

        elif provider == "webdav":
            import httpx

            url = str(payload.webdav_url or "").rstrip("/")
            if not url:
                raise HTTPException(status_code=400, detail="webdav_url is required")
            auth = None
            if payload.webdav_username:
                auth = (payload.webdav_username, payload.webdav_password or "")
            async with httpx.AsyncClient(timeout=6) as client:
                r = await client.request("PROPFIND", url + "/", auth=auth,
                                         headers={"Depth": "0"})
            if r.status_code in (207, 200, 301, 302):
                return {"ok": True, "provider": provider}
            raise HTTPException(status_code=400, detail=f"WebDAV server returned {r.status_code}")

        else:
            raise HTTPException(status_code=400, detail=f"Unknown provider: {provider!r}")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Connection failed: {e}")


@router.get("/insights/config")
async def get_insights_config():
    try:
        return get_insights_config_public()
    except Exception as e:
        raise _internal_error("Internal server error.", e)


@router.post("/insights/config")
async def save_insights_config(payload: InsightsConfigUpdate):
    try:
        partial = payload.model_dump(exclude_none=True)
        return update_insights_config(partial)
    except Exception as e:
        raise _bad_request("Invalid request.", e)


@router.post("/mcp/autoconfigure")
async def run_mcp_autoconfigure(payload: McpAutoconfigPayload):
    try:
        from backend.config_watcher import run_first_launch_autoconfigure

        result = run_first_launch_autoconfigure(force=bool(payload.force))
        return {"status": "ok", "result": result}
    except Exception as e:
        raise _internal_error("Internal server error.", e)


@router.get("/mcp/auth-status")
async def get_mcp_auth_status():
    """Diagnostic: current MCP authentication configuration state."""
    try:
        config = load_config()
        token = config.get("snapshot_read_token", "")
        llm_client_keys = config.get("llm_client_keys", {})
        security_cfg = config.get("security", {})
        allow_snapshot_fallback = bool(security_cfg.get("allow_snapshot_token_for_mcp", True))

        client_keys = llm_client_keys if isinstance(llm_client_keys, dict) else {}
        client_keys_count = len(client_keys)
        token_configured = bool(str(token or "").strip())

        return {
            "token_configured": token_configured,
            "client_keys_count": client_keys_count,
            "allow_snapshot_fallback": allow_snapshot_fallback,
            "auth_mode": "dedicated_keys" if client_keys_count > 0 else "snapshot_token",
        }
    except Exception as e:
        raise _internal_error("Failed to get MCP auth status.", e)


@router.post("/insights/test")
async def test_insights_connection():
    """Test the configured LLM connection for memory analysis without running any analysis."""
    import time

    try:
        import httpx
    except ImportError:
        raise HTTPException(status_code=500, detail="httpx not available")

    try:
        config = load_config()
        insights = config.get("insights", {})
        provider = str(insights.get("provider") or "openai").strip().lower()
        model = str(insights.get("model") or "").strip()
        api_key = str(insights.get("api_key") or "").strip()
        api_base_url = str(insights.get("api_base_url") or "").strip()

        if not model:
            raise HTTPException(
                status_code=400,
                detail="No model configured. Set a model in Insights AI settings first."
            )

        start = time.monotonic()

        if provider == "anthropic":
            base = (api_base_url or "https://api.anthropic.com/v1").rstrip("/")
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            body = {
                "model": model,
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "ping"}],
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(f"{base}/messages", headers=headers, json=body)
            r.raise_for_status()

        elif provider == "ollama":
            base = (api_base_url or "http://127.0.0.1:11434").rstrip("/")
            body = {
                "model": model,
                "messages": [{"role": "user", "content": "ping"}],
                "stream": False,
                "options": {"num_predict": 1},
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(f"{base}/api/chat", json=body)
            r.raise_for_status()

        else:  # openai-compatible
            base = (api_base_url or "https://api.openai.com/v1").rstrip("/")
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            body = {
                "model": model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(f"{base}/chat/completions", headers=headers, json=body)
            r.raise_for_status()

        latency_ms = int((time.monotonic() - start) * 1000)
        return {"ok": True, "provider": provider, "model": model, "latency_ms": latency_ms}

    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        detail = f"HTTP {e.response.status_code}"
        try:
            err_body = e.response.json()
            if isinstance(err_body.get("error"), dict):
                detail = str(err_body["error"].get("message") or err_body["error"])
            elif "error" in err_body:
                detail = str(err_body["error"])
            elif "message" in err_body:
                detail = str(err_body["message"])
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=f"LLM connection failed: {detail}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Connection failed: {e}")


@router.get("/background/status")
async def get_background_status(include_heavy: bool = False):
    cfg = load_config(force_reload=True)
    state = _load_scheduler_state()
    db = get_db()
    scan_limits = {
        "memories": 300000 if include_heavy else 60000,
        "conversations": 300000 if include_heavy else 60000,
        "candidates": 500000 if include_heavy else 80000,
        "sessions": 500000 if include_heavy else 80000,
        "runtime_metrics": 120000 if include_heavy else 30000,
        "runtime_recent": 120 if include_heavy else 40,
    }
    analysis_runtime = {}
    analysis_jobs = {"counts": {}, "recent": []}
    analysis_worker = {}
    try:
        from backend.memory.conversation_mining import (
            get_analysis_llm_gate_status,
            get_analysis_runtime_status,
        )

        analysis_runtime = get_analysis_runtime_status()
        if isinstance(analysis_runtime, dict):
            try:
                gate = await get_analysis_llm_gate_status(preflight=False)
                analysis_runtime["llm_gate"] = {
                    "required": bool(gate.get("required", True)),
                    "analysis_allowed": bool(gate.get("analysis_allowed", True)),
                    "llm_enabled": bool(gate.get("llm_enabled", False)),
                    "configured": bool(gate.get("configured", False)),
                    "reason": gate.get("reason"),
                    "runtime": gate.get("runtime_public", {}),
                }
            except Exception as gate_error:
                analysis_runtime["llm_gate"] = {
                    "required": bool(analysis_runtime.get("llm_required", True)),
                    "analysis_allowed": bool(not analysis_runtime.get("llm_required", True) or analysis_runtime.get("llm_configured", False)),
                    "llm_enabled": bool(analysis_runtime.get("llm_configured", False)),
                    "configured": bool(analysis_runtime.get("llm_configured", False)),
                    "reason": str(gate_error)[:220],
                    "runtime": {
                        "provider": str(analysis_runtime.get("llm_provider") or ""),
                        "model": "",
                        "api_base_url": "",
                    },
                }
    except Exception:
        analysis_runtime = {}
    try:
        from backend.memory.conversation_analysis_jobs import (
            get_analysis_jobs_overview,
            get_analysis_worker_state,
        )

        analysis_jobs = get_analysis_jobs_overview(limit=12)
        analysis_worker = get_analysis_worker_state()
    except Exception:
        analysis_jobs = {"counts": {}, "recent": []}
        analysis_worker = {}
    memory_schema_columns: list[str] = []
    memory_schema_missing_temporal: list[str] = []

    memory_counts = {
        "total": 0,
        "active": 0,
        "pending_review": 0,
        "rejected": 0,
        "archived": 0,
        "auto_nonarchived": 0,
        "auto_pending_review": 0,
    }
    conversation_counts = {
        "total": 0,
        "active": 0,
        "tagged_analysis": 0,
        "tagged_msgcount": 0,
    }
    candidate_counts = {
        "total": 0,
        "pending": 0,
        "promoted": 0,
        "merged": 0,
        "rejected": 0,
        "conflict_pending": 0,
    }

    try:
        if "memories" in db.table_names():
            try:
                mem_tbl = db.open_table("memories")
                schema = getattr(mem_tbl, "schema", None)
                names = list(getattr(schema, "names", []) or [])
                memory_schema_columns = [str(n) for n in names]
                temporal_fields = {"decay_profile", "expires_at", "needs_review", "review_due_at", "event_date"}
                present = {str(n) for n in names}
                memory_schema_missing_temporal = sorted(list(temporal_fields - present))
            except Exception:
                memory_schema_columns = []
                memory_schema_missing_temporal = []
            rows = db.open_table("memories").search().limit(scan_limits["memories"]).to_list()
            memory_counts["scan_limit"] = int(scan_limits["memories"])
            memory_counts["scan_rows"] = len(rows)
            memory_counts["scan_truncated"] = len(rows) >= int(scan_limits["memories"])
            memory_counts["total"] = len(rows)
            for row in rows:
                status = str(row.get("status") or "").strip().lower() or "active"
                if status in memory_counts:
                    memory_counts[status] += 1
                else:
                    memory_counts[status] = memory_counts.get(status, 0) + 1

                source_llm = str(row.get("source_llm") or "").strip().lower()
                tags = [str(t) for t in (row.get("tags") or []) if t]
                has_auto_tag = any(str(t).strip().lower() == "auto:conversation-analysis" for t in tags)
                is_auto = source_llm.startswith("conversation-analyzer:") or has_auto_tag
                if is_auto and status != "archived":
                    memory_counts["auto_nonarchived"] += 1
                if is_auto and status == "pending_review":
                    memory_counts["auto_pending_review"] += 1
    except Exception as e:
        memory_counts["error"] = "unavailable"
        logger.warning(f"Failed to collect memory counts: {e}")

    try:
        if "conversations" in db.table_names():
            rows = db.open_table("conversations").search().limit(scan_limits["conversations"]).to_list()
            conversation_counts["scan_limit"] = int(scan_limits["conversations"])
            conversation_counts["scan_rows"] = len(rows)
            conversation_counts["scan_truncated"] = len(rows) >= int(scan_limits["conversations"])
            conversation_counts["total"] = len(rows)
            for row in rows:
                status = str(row.get("status") or "").strip().lower()
                if status != "deleted":
                    conversation_counts["active"] += 1
                tags = [str(t) for t in (row.get("tags") or []) if t]
                has_analysis, has_msgcount = _analysis_tag_info(tags)
                if has_analysis:
                    conversation_counts["tagged_analysis"] += 1
                if has_msgcount:
                    conversation_counts["tagged_msgcount"] += 1
    except Exception as e:
        conversation_counts["error"] = "unavailable"
        logger.warning(f"Failed to collect conversation counts: {e}")

    try:
        if "conversation_analysis_candidates" in db.table_names():
            rows = db.open_table("conversation_analysis_candidates").search().limit(scan_limits["candidates"]).to_list()
            candidate_counts["scan_limit"] = int(scan_limits["candidates"])
            candidate_counts["scan_rows"] = len(rows)
            candidate_counts["scan_truncated"] = len(rows) >= int(scan_limits["candidates"])
            candidate_counts["total"] = len(rows)
            for row in rows:
                status = str(row.get("status") or "").strip().lower()
                if status in candidate_counts:
                    candidate_counts[status] += 1
    except Exception as e:
        candidate_counts["error"] = "unavailable"
        logger.warning(f"Failed to collect candidate counts: {e}")

    auto_cfg = cfg.get("conversation_analysis", {}) if isinstance(cfg.get("conversation_analysis"), dict) else {}
    auto_stats = state.get("last_auto_conversation_analysis_stats", {})
    if not isinstance(auto_stats, dict):
        auto_stats = {}
    manual_stats = state.get("last_manual_conversation_analysis_stats", {})
    if not isinstance(manual_stats, dict):
        manual_stats = {}

    auto_at_raw = state.get("last_auto_conversation_analysis")
    manual_at_raw = state.get("last_manual_conversation_analysis")
    auto_at = _to_dt(auto_at_raw) if auto_at_raw else None
    manual_at = _to_dt(manual_at_raw) if manual_at_raw else None

    last_analysis = None
    last_analysis_source = "none"
    last_analysis_stats: dict = {}
    if auto_at is not None:
        last_analysis = auto_at_raw
        last_analysis_source = "auto"
        last_analysis_stats = auto_stats
    if manual_at is not None and (auto_at is None or manual_at >= auto_at):
        last_analysis = manual_at_raw
        last_analysis_source = "manual"
        last_analysis_stats = manual_stats

    security_last_audit = state.get("last_security_audit")
    security_last_result = state.get("last_security_audit_result")
    if not isinstance(security_last_result, dict):
        security_last_result = {}
    if include_heavy and not security_last_result:
        try:
            security_last_result = collect_security_audit(config=cfg)
        except Exception:
            security_last_result = {}

    client_observability = _collect_client_observability(
        db,
        cfg,
        session_limit=scan_limits["sessions"],
        runtime_history_limit=scan_limits["runtime_metrics"],
        runtime_recent_limit=scan_limits["runtime_recent"],
    )
    release_gates = _release_gates(
        security_result=security_last_result,
        last_analysis_stats=last_analysis_stats if isinstance(last_analysis_stats, dict) else {},
        client_observability=client_observability,
    )
    remote_access = get_remote_access_status()

    return {
        "config": {
            "config_path": CONFIG_PATH,
            "config_dir": CONFIG_DIR,
        },
        "model": {
            "embedding_status": get_embedding_status(),
            "download": model_manager.get_progress(),
        },
        "conversation_analysis": auto_cfg,
        "status_mode": "heavy" if include_heavy else "lite",
        "scan_limits": scan_limits,
        "security": {
            "runtime": security_runtime_overview(cfg),
            "last_audit": security_last_audit,
            "last_audit_summary": security_last_result.get("summary", {}),
            "last_audit_score": security_last_result.get("score"),
            "last_audit_grade": security_last_result.get("grade"),
        },
        "clients": client_observability,
        "release_gates": release_gates,
        "remote_access": remote_access,
        "runtime": {
            "memory_legacy_write_guard": "v2",
            "analysis": analysis_runtime,
            "analysis_worker": analysis_worker,
        },
        "jobs": analysis_jobs,
        "scheduler": {
            "state_path": _scheduler_state_path(),
            "last_decay": state.get("last_decay"),
            "last_hourly_checks": state.get("last_hourly_checks"),
            "last_client_metrics_flush": state.get("last_client_metrics_flush"),
            "last_client_metrics_flush_result": state.get("last_client_metrics_flush_result"),
            "last_auto_sync": state.get("last_auto_sync"),
            "last_auto_conversation_analysis_queued": state.get("last_auto_conversation_analysis_queued"),
            "last_auto_conversation_analysis": state.get("last_auto_conversation_analysis"),
            "last_auto_conversation_analysis_stats": auto_stats,
            "last_manual_conversation_analysis": state.get("last_manual_conversation_analysis"),
            "last_manual_conversation_analysis_stats": manual_stats,
            "last_analysis": last_analysis,
            "last_analysis_source": last_analysis_source,
            "last_analysis_stats": last_analysis_stats,
        },
        "counts": {
            "memories": memory_counts,
            "conversations": conversation_counts,
            "analysis_candidates": candidate_counts,
        },
        "schema": {
            "memories_columns": memory_schema_columns,
            "memories_missing_temporal_fields": memory_schema_missing_temporal,
        },
    }


@router.get("/security/status")
async def get_security_status():
    cfg = load_config(force_reload=True)
    state = _load_scheduler_state()
    latest = state.get("last_security_audit_result")
    if not isinstance(latest, dict):
        latest = collect_security_audit(config=cfg)
    return {
        "config_path": CONFIG_PATH,
        "runtime": security_runtime_overview(cfg),
        "last_audit": state.get("last_security_audit"),
        "audit": latest,
    }


@router.get("/security/config")
async def get_security_config():
    cfg = load_config(force_reload=True)
    security = cfg.get("security", {}) if isinstance(cfg.get("security"), dict) else {}
    return {
        "status": "ok",
        "security": security,
        "runtime": security_runtime_overview(cfg),
    }


@router.post("/security/config")
async def update_security_config(payload: SecurityConfigUpdate):
    cfg = load_config(force_reload=True)
    patch = payload.model_dump(exclude_none=True)
    current_security = cfg.get("security", {}) if isinstance(cfg.get("security"), dict) else {}
    cfg["security"] = _merge_security_config(current_security, patch)
    save_config(cfg)

    report = collect_security_audit(config=cfg)
    state = _load_scheduler_state()
    state["last_security_audit"] = report.get("generated_at")
    state["last_security_audit_result"] = report
    _save_scheduler_state(state)

    return {
        "status": "ok",
        "security": cfg.get("security", {}),
        "runtime": security_runtime_overview(cfg),
        "audit": report,
    }


@router.post("/security/harden")
async def harden_security_config(payload: SecurityHardenPayload):
    cfg = load_config(force_reload=True)
    bootstrap_meta = {"created": False, "reason": "disabled"}
    if payload.bootstrap_bridge_key:
        bootstrap_meta = bootstrap_bridge_mcp_key(config=cfg)
    strict_patch = strict_security_patch(config=cfg)
    meta = strict_patch.pop("_meta", {})
    if payload.force_disable_snapshot_mcp_fallback:
        strict_patch["allow_snapshot_token_for_mcp"] = False
        meta = {
            **(meta if isinstance(meta, dict) else {}),
            "forced_snapshot_mcp_fallback_disabled": True,
        }
    current_security = cfg.get("security", {}) if isinstance(cfg.get("security"), dict) else {}
    cfg["security"] = _merge_security_config(current_security, strict_patch)
    save_config(cfg)

    report = collect_security_audit(config=cfg)
    state = _load_scheduler_state()
    state["last_security_audit"] = report.get("generated_at")
    state["last_security_audit_result"] = report
    _save_scheduler_state(state)

    return {
        "status": "ok",
        "meta": {
            **(meta if isinstance(meta, dict) else {}),
            "bootstrap_bridge_key": bootstrap_meta,
        },
        "security": cfg.get("security", {}),
        "runtime": security_runtime_overview(cfg),
        "audit": report,
    }


@router.post("/security/audit/run")
async def run_security_audit():
    cfg = load_config(force_reload=True)
    report = collect_security_audit(config=cfg)
    state = _load_scheduler_state()
    state["last_security_audit"] = report.get("generated_at")
    state["last_security_audit_result"] = report
    _save_scheduler_state(state)
    return {"status": "ok", "audit": report}


@router.get("/remote/status")
async def get_remote_status():
    return {
        "status": "disabled",
        "mode": "byo_tunnel",
        "message": "Managed relay is disabled. Use BYO tunnel (see BYO_TUNNEL.md).",
    }


@router.post("/remote/config")
async def update_remote_config(payload: RemoteAccessConfigUpdate):
    raise HTTPException(
        status_code=410,
        detail="Managed relay configuration is disabled. Use BYO tunnel (see BYO_TUNNEL.md).",
    )


@router.post("/remote/poll-now")
async def poll_remote_now():
    raise HTTPException(
        status_code=410,
        detail="Managed relay is disabled. Use BYO tunnel (see BYO_TUNNEL.md).",
    )


@router.post("/background/analysis/run")
async def run_background_analysis_now(payload: RunBackgroundAnalysisPayload):
    try:
        from backend.memory.conversation_analysis_jobs import (
            enqueue_analysis_job,
            get_analysis_job,
            get_analysis_jobs_overview,
            get_analysis_worker_state,
        )
        from backend.memory.conversation_mining import (
            get_analysis_llm_gate_status,
            get_analysis_runtime_status,
        )
    except Exception as e:
        raise _internal_error("Internal server error.", e)

    cfg = load_config(force_reload=True)
    auto_cfg = cfg.get("conversation_analysis", {}) if isinstance(cfg.get("conversation_analysis"), dict) else {}
    provider = payload.provider or str(auto_cfg.get("provider", "auto"))
    model = (str(auto_cfg.get("model") or "").strip() or None)
    api_base_url = (str(auto_cfg.get("api_base_url") or "").strip() or None)
    api_key = (str(auto_cfg.get("api_key") or "").strip() or None)
    require_llm_configured = bool(auto_cfg.get("require_llm_configured", True))
    max_conversations = int(payload.max_conversations) if payload.max_conversations is not None else int(auto_cfg.get("max_conversations", 24))
    max_messages_per_conversation = (
        int(payload.max_messages_per_conversation)
        if payload.max_messages_per_conversation is not None
        else int(auto_cfg.get("max_messages_per_conversation", 24))
    )
    max_candidates_per_conversation = (
        int(payload.max_candidates_per_conversation)
        if payload.max_candidates_per_conversation is not None
        else int(auto_cfg.get("max_candidates_per_conversation", 4))
    )
    max_new_memories = int(payload.max_new_memories) if payload.max_new_memories is not None else int(auto_cfg.get("max_new_memories", 40))
    min_confidence = float(payload.min_confidence) if payload.min_confidence is not None else float(auto_cfg.get("min_confidence", 0.8))
    concurrency = int(payload.concurrency) if payload.concurrency is not None else int(auto_cfg.get("concurrency", 2))

    gate = await get_analysis_llm_gate_status(
        provider=provider,
        model=model,
        api_base_url=api_base_url,
        api_key=api_key,
        require_llm_configured=require_llm_configured,
    )
    if not bool(gate.get("analysis_allowed", True)):
        raise HTTPException(
            status_code=400,
            detail=str(gate.get("reason") or "Conversation analysis is blocked until LLM is configured."),
        )

    run_kwargs = dict(
        dry_run=False,
        force_reanalyze=bool(payload.force_reanalyze),
        conversation_ids=[str(v).strip() for v in (payload.conversation_ids or []) if str(v).strip()] or None,
        include_assistant_messages=bool(auto_cfg.get("include_assistant_messages", False)),
        max_conversations=max_conversations,
        max_messages_per_conversation=max_messages_per_conversation,
        max_candidates_per_conversation=max_candidates_per_conversation,
        max_new_memories=max_new_memories,
        min_confidence=min_confidence,
        provider=provider,
        model=model,
        api_base_url=api_base_url,
        api_key=api_key,
        concurrency=concurrency,
        require_llm_configured=require_llm_configured,
    )

    try:
        enqueue_result = await enqueue_analysis_job(
            trigger="manual",
            payload=run_kwargs,
            priority=6,
            max_attempts=2,
            dedupe_active=True,
        )
        status = str(enqueue_result.get("status") or "")
        job = enqueue_result.get("job", {}) if isinstance(enqueue_result, dict) else {}
        job_id = str(job.get("id") or "")

        if payload.wait_for_completion and job_id:
            deadline = asyncio.get_running_loop().time() + 1800.0
            while asyncio.get_running_loop().time() < deadline:
                current = get_analysis_job(job_id)
                if not current:
                    await asyncio.sleep(0.6)
                    continue
                current_status = str(current.get("status") or "").strip().lower()
                if current_status in {"completed", "failed", "cancelled"}:
                    if current_status == "completed":
                        return {
                            "status": "ok",
                            "trigger": "manual",
                            "job": current,
                            "result": current.get("result", {}),
                        }
                    return {
                        "status": current_status,
                        "trigger": "manual",
                        "job": current,
                        "message": current.get("error") or "Conversation analysis did not complete successfully.",
                    }
                await asyncio.sleep(0.6)
            current = get_analysis_job(job_id)
            return {
                "status": "accepted",
                "trigger": "manual",
                "message": "Analysis still running in background.",
                "job": current or job,
                "runtime": get_analysis_runtime_status(),
                "worker": get_analysis_worker_state(),
                "jobs": get_analysis_jobs_overview(limit=8),
            }

        if status == "duplicate":
            return {
                "status": "busy",
                "trigger": "manual",
                "message": "An equivalent analysis job is already pending/running.",
                "job": job,
                "runtime": get_analysis_runtime_status(),
                "worker": get_analysis_worker_state(),
                "jobs": get_analysis_jobs_overview(limit=8),
            }

        return {
            "status": "accepted",
            "trigger": "manual",
            "message": "Background analysis enqueued.",
            "job": job,
            "runtime": get_analysis_runtime_status(),
            "worker": get_analysis_worker_state(),
            "jobs": get_analysis_jobs_overview(limit=8),
        }
    except Exception as e:
        raise _internal_error("Internal server error.", e)


@router.get("/background/analysis/jobs")
async def list_background_analysis_jobs(limit: int = 20):
    try:
        from backend.memory.conversation_analysis_jobs import get_analysis_jobs_overview

        return get_analysis_jobs_overview(limit=limit)
    except Exception as e:
        raise _internal_error("Internal server error.", e)


@router.post("/background/analysis/jobs/{job_id}/cancel")
async def cancel_background_analysis_job(job_id: str):
    try:
        from backend.memory.conversation_analysis_jobs import cancel_analysis_job

        job = await cancel_analysis_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return {"status": "ok", "job": job}
    except HTTPException:
        raise
    except Exception as e:
        raise _internal_error("Internal server error.", e)


@router.post("/maintenance/conversations/deduplicate")
async def deduplicate_conversations(payload: DeduplicateConversationsPayload):
    db = get_db()
    if "conversations" not in db.table_names():
        return {
            "status": "ok",
            "dry_run": payload.dry_run,
            "conversations_total": 0,
            "conversations_kept": 0,
            "conversations_duplicates": 0,
            "messages_total": 0,
            "messages_kept": 0,
            "messages_duplicates": 0,
        }

    conv_tbl = db.open_table("conversations")
    conv_rows = conv_tbl.search().limit(500000).to_list()
    conv_by_key: dict[tuple, dict] = {}
    conv_dup = 0
    conv_duplicate_ids_preview: list[str] = []
    for row in conv_rows:
        key = _conversation_key(row)
        existing = conv_by_key.get(key)
        if existing is None:
            conv_by_key[key] = row
            continue
        conv_dup += 1
        dup_id = row.get("id")
        if dup_id and len(conv_duplicate_ids_preview) < 40:
            conv_duplicate_ids_preview.append(str(dup_id))
        if _is_newer(row, existing):
            conv_by_key[key] = row

    msg_rows: list[dict] = []
    msg_by_key: dict[tuple, dict] = {}
    msg_dup = 0
    msg_duplicate_ids_preview: list[str] = []
    if payload.include_messages and "messages" in db.table_names():
        msg_tbl = db.open_table("messages")
        msg_rows = msg_tbl.search().limit(2000000).to_list()
        for row in msg_rows:
            key = _message_key(row)
            existing = msg_by_key.get(key)
            if existing is None:
                msg_by_key[key] = row
                continue
            msg_dup += 1
            dup_id = row.get("id")
            if dup_id and len(msg_duplicate_ids_preview) < 40:
                msg_duplicate_ids_preview.append(str(dup_id))
            if _is_newer(row, existing):
                msg_by_key[key] = row

    if payload.dry_run:
        return {
            "status": "ok",
            "dry_run": True,
            "conversations_total": len(conv_rows),
            "conversations_kept": len(conv_by_key),
            "conversations_duplicates": conv_dup,
            "messages_total": len(msg_rows),
            "messages_kept": len(msg_by_key),
            "messages_duplicates": msg_dup,
            "conversation_duplicate_ids_preview": conv_duplicate_ids_preview,
            "message_duplicate_ids_preview": msg_duplicate_ids_preview,
        }

    async def _write_op():
        db_write = get_db()
        conv_clean = [_sanitize_conversation_row(r) for r in conv_by_key.values()]
        conv_clean.sort(key=lambda x: x.started_at, reverse=True)

        db_write.drop_table("conversations")
        db_write.create_table("conversations", schema=Conversation)
        if conv_clean:
            db_write.open_table("conversations").add(conv_clean)

        msg_kept = len(msg_by_key)
        if payload.include_messages and "messages" in db_write.table_names():
            msg_clean = [_sanitize_message_row(r) for r in msg_by_key.values()]
            db_write.drop_table("messages")
            db_write.create_table("messages", schema=Message)
            if msg_clean:
                db_write.open_table("messages").add(msg_clean)
            msg_kept = len(msg_clean)

        return {
            "status": "ok",
            "dry_run": False,
            "conversations_total": len(conv_rows),
            "conversations_kept": len(conv_clean),
            "conversations_duplicates": conv_dup,
            "messages_total": len(msg_rows),
            "messages_kept": msg_kept,
            "messages_duplicates": msg_dup,
            "conversation_duplicate_ids_preview": conv_duplicate_ids_preview,
            "message_duplicate_ids_preview": msg_duplicate_ids_preview,
        }

    try:
        return await enqueue_write(_write_op)
    except Exception as e:
        raise _internal_error("Internal server error.", e)


@router.post("/maintenance/conversations/delete-ids")
async def delete_conversations_by_ids(payload: DeleteConversationsByIdPayload):
    db = get_db()
    if "conversations" not in db.table_names():
        return {
            "status": "ok",
            "requested": 0,
            "matched": 0,
            "updated": 0,
            "messages_deleted": 0,
        }

    seen = set()
    ids: list[str] = []
    for raw in payload.conversation_ids:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        ids.append(value)
    if not ids:
        return {
            "status": "ok",
            "requested": 0,
            "matched": 0,
            "updated": 0,
            "messages_deleted": 0,
        }

    conv_tbl = db.open_table("conversations")
    rows = conv_tbl.search().limit(500000).to_list()
    matched_ids = [str(r.get("id")) for r in rows if str(r.get("id") or "") in set(ids)]

    async def _write_op():
        db_write = get_db()
        if "conversations" not in db_write.table_names():
            return {
                "status": "ok",
                "requested": len(ids),
                "matched": 0,
                "updated": 0,
                "messages_deleted": 0,
            }
        conv_tbl_w = db_write.open_table("conversations")
        now = datetime.now(timezone.utc)
        updated = 0
        for conv_id in matched_ids:
            escaped = _escape_sql(conv_id)
            conv_tbl_w.update(
                where=f"id = '{escaped}'",
                values={
                    "status": "deleted",
                    "ended_at": now,
                },
            )
            updated += 1

        messages_deleted = 0
        if payload.include_messages and "messages" in db_write.table_names():
            msg_tbl = db_write.open_table("messages")
            for conv_id in matched_ids:
                escaped = _escape_sql(conv_id)
                before = msg_tbl.search().where(f"conversation_id = '{escaped}'").limit(200000).to_list()
                if before:
                    msg_tbl.delete(f"conversation_id = '{escaped}'")
                    messages_deleted += len(before)

        return {
            "status": "ok",
            "requested": len(ids),
            "matched": len(matched_ids),
            "updated": updated,
            "messages_deleted": messages_deleted,
        }

    try:
        return await enqueue_write(_write_op)
    except Exception as e:
        raise _internal_error("Internal server error.", e)


@router.post("/maintenance/conversations/purge")
async def purge_conversations(payload: PurgeConversationsPayload):
    db = get_db()
    conv_total = 0
    msg_total = 0

    if "conversations" in db.table_names():
        conv_total = len(db.open_table("conversations").search().limit(500000).to_list())
    if payload.include_messages and "messages" in db.table_names():
        msg_total = len(db.open_table("messages").search().limit(2000000).to_list())

    async def _write_op():
        db_write = get_db()
        if "conversations" in db_write.table_names():
            db_write.drop_table("conversations")
        db_write.create_table("conversations", schema=Conversation)

        if payload.include_messages:
            if "messages" in db_write.table_names():
                db_write.drop_table("messages")
            db_write.create_table("messages", schema=Message)

        return {
            "status": "ok",
            "conversations_deleted": conv_total,
            "messages_deleted": msg_total if payload.include_messages else 0,
        }

    try:
        return await enqueue_write(_write_op)
    except Exception as e:
        raise _internal_error("Internal server error.", e)
