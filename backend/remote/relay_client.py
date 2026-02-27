import asyncio
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Awaitable, Callable
from urllib.parse import urljoin
import uuid

import httpx

from backend.config import load_config, save_config
from backend.mcp_server import conversation_sync, memory_bootstrap, memory_write
from backend.utils.context import session_id_ctx, mcp_client_name_ctx, mcp_client_scopes_ctx

_REGISTER_PATH = "/api/v1/relay/register"
_POLL_PATH = "/api/v1/relay/poll"
_REPORT_PATH = "/api/v1/relay/report"

_TASK_HANDLERS: dict[str, Callable[..., Awaitable[Any]]] = {
    "memory_bootstrap": memory_bootstrap,
    "memory_write": memory_write,
    "conversation_sync": conversation_sync,
}

_runtime_lock = RLock()
_runtime: dict[str, Any] = {
    "worker_alive": False,
    "running": False,
    "status": "disabled",
    "last_poll_at": None,
    "last_success_at": None,
    "last_error_at": None,
    "last_error": None,
    "last_http_status": None,
    "registered_at": None,
    "polls_total": 0,
    "polls_failed": 0,
    "tasks_received": 0,
    "tasks_succeeded": 0,
    "tasks_failed": 0,
    "last_results": [],
}

_worker_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None
_poll_now_event: asyncio.Event | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _clamp_int(value: Any, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(min_value, min(max_value, parsed))


def _normalize_remote_cfg(raw: dict | None) -> dict:
    source = raw if isinstance(raw, dict) else {}
    relay_url = str(source.get("relay_url") or "").strip().rstrip("/")
    return {
        "enabled": bool(source.get("enabled", False)),
        "relay_url": relay_url,
        "project_id": str(source.get("project_id") or "").strip(),
        "device_id": str(source.get("device_id") or "").strip(),
        "device_secret": str(source.get("device_secret") or "").strip(),
        "device_name": str(source.get("device_name") or "mnesis-desktop").strip() or "mnesis-desktop",
        "poll_interval_seconds": _clamp_int(source.get("poll_interval_seconds"), 12, 5, 300),
        "request_timeout_seconds": _clamp_int(source.get("request_timeout_seconds"), 20, 5, 120),
        "max_tasks_per_poll": _clamp_int(source.get("max_tasks_per_poll"), 4, 1, 40),
    }


def _is_ready_for_remote(remote_cfg: dict) -> bool:
    return bool(
        remote_cfg.get("enabled")
        and remote_cfg.get("relay_url")
        and remote_cfg.get("project_id")
        and remote_cfg.get("device_id")
        and remote_cfg.get("device_secret")
    )


def _public_remote_config(remote_cfg: dict) -> dict:
    return {
        "enabled": bool(remote_cfg.get("enabled", False)),
        "relay_url": str(remote_cfg.get("relay_url") or ""),
        "project_id": str(remote_cfg.get("project_id") or ""),
        "device_id": str(remote_cfg.get("device_id") or ""),
        "device_name": str(remote_cfg.get("device_name") or "mnesis-desktop"),
        "has_device_secret": bool(str(remote_cfg.get("device_secret") or "").strip()),
        "poll_interval_seconds": _clamp_int(remote_cfg.get("poll_interval_seconds"), 12, 5, 300),
        "request_timeout_seconds": _clamp_int(remote_cfg.get("request_timeout_seconds"), 20, 5, 120),
        "max_tasks_per_poll": _clamp_int(remote_cfg.get("max_tasks_per_poll"), 4, 1, 40),
    }


def _set_runtime(**patch: Any):
    with _runtime_lock:
        _runtime.update(patch)


def _append_result(entry: dict):
    with _runtime_lock:
        rows = list(_runtime.get("last_results", []) or [])
        rows.insert(0, entry)
        _runtime["last_results"] = rows[:8]


def _snapshot_runtime() -> dict:
    with _runtime_lock:
        return dict(_runtime)


def _json_serialize(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, default=str))
    except Exception:
        return {"value": str(value)}


def _signed_headers(*, remote_cfg: dict, body_bytes: bytes) -> dict[str, str]:
    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
    payload_hash = hashlib.sha256(body_bytes).hexdigest()
    signed = f"{timestamp}.{nonce}.{payload_hash}"
    signature = hmac.new(
        str(remote_cfg.get("device_secret") or "").encode("utf-8"),
        signed.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Mnesis-Project-Id": str(remote_cfg.get("project_id") or ""),
        "X-Mnesis-Device-Id": str(remote_cfg.get("device_id") or ""),
        "X-Mnesis-Timestamp": timestamp,
        "X-Mnesis-Nonce": nonce,
        "X-Mnesis-Signature": signature,
    }


async def _post_signed(client: httpx.AsyncClient, remote_cfg: dict, path: str, payload: dict) -> httpx.Response:
    url = urljoin(f"{str(remote_cfg.get('relay_url') or '').rstrip('/')}/", path.lstrip("/"))
    body = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
    headers = _signed_headers(remote_cfg=remote_cfg, body_bytes=body)
    return await client.post(url, content=body, headers=headers)


def _resolve_task_handler(tool_name: str) -> Callable[..., Awaitable[Any]] | None:
    direct = _TASK_HANDLERS.get(tool_name)
    if direct:
        return direct
    alias = tool_name.replace(".", "_").strip().lower()
    return _TASK_HANDLERS.get(alias)


def _tool_args_for_handler(handler: Callable[..., Awaitable[Any]], raw_args: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw_args, dict):
        return {}
    # Avoid hard import at module level; inspect only when needed.
    import inspect

    try:
        sig = inspect.signature(handler)
    except Exception:
        return dict(raw_args)
    allowed = set(sig.parameters.keys())
    return {k: v for k, v in raw_args.items() if k in allowed}


async def _execute_task(remote_cfg: dict, task: dict[str, Any]) -> dict:
    task_id = str(task.get("id") or task.get("task_id") or uuid.uuid4())
    tool = str(task.get("tool") or task.get("name") or "").strip()
    handler = _resolve_task_handler(tool)
    if handler is None:
        return {
            "task_id": task_id,
            "tool": tool,
            "ok": False,
            "error": f"Unsupported tool '{tool}'. Allowed: {', '.join(sorted(_TASK_HANDLERS.keys()))}",
        }

    raw_args = task.get("args")
    if not isinstance(raw_args, dict):
        raw_args = task.get("arguments")
    if not isinstance(raw_args, dict):
        raw_args = task.get("input")
    if not isinstance(raw_args, dict):
        raw_args = {}
    args = _tool_args_for_handler(handler, raw_args)

    session_id = str(task.get("session_id") or f"relay:{uuid.uuid4().hex}")
    client_name = f"relay:{str(remote_cfg.get('project_id') or 'project')}"
    scopes = ["read", "write", "sync"]
    sid_token = session_id_ctx.set(session_id)
    name_token = mcp_client_name_ctx.set(client_name)
    scopes_token = mcp_client_scopes_ctx.set(scopes)
    try:
        result = await handler(**args)
        return {
            "task_id": task_id,
            "tool": tool,
            "ok": True,
            "result": _json_serialize(result),
        }
    except Exception as e:
        return {
            "task_id": task_id,
            "tool": tool,
            "ok": False,
            "error": str(e),
        }
    finally:
        session_id_ctx.reset(sid_token)
        mcp_client_name_ctx.reset(name_token)
        mcp_client_scopes_ctx.reset(scopes_token)


async def _register_device_if_supported(client: httpx.AsyncClient, remote_cfg: dict):
    payload = {
        "project_id": remote_cfg["project_id"],
        "device_id": remote_cfg["device_id"],
        "device_name": remote_cfg["device_name"],
        "capabilities": sorted(_TASK_HANDLERS.keys()),
        "transport": "long-poll",
        "client_version": "mnesis-desktop",
    }
    res = await _post_signed(client, remote_cfg, _REGISTER_PATH, payload)
    _set_runtime(last_http_status=int(res.status_code))
    if res.status_code in {200, 201, 202, 204, 404}:
        if res.status_code != 404:
            _set_runtime(registered_at=_utc_now_iso())
        return
    raise RuntimeError(f"Relay register failed ({res.status_code})")


async def _poll_once(remote_cfg: dict) -> int:
    timeout = max(5, int(remote_cfg["request_timeout_seconds"]))
    async with httpx.AsyncClient(timeout=timeout) as client:
        await _register_device_if_supported(client, remote_cfg)

        payload = {
            "project_id": remote_cfg["project_id"],
            "device_id": remote_cfg["device_id"],
            "max_tasks": int(remote_cfg["max_tasks_per_poll"]),
            "capabilities": sorted(_TASK_HANDLERS.keys()),
        }
        res = await _post_signed(client, remote_cfg, _POLL_PATH, payload)
        _set_runtime(last_http_status=int(res.status_code), last_poll_at=_utc_now_iso())
        if res.status_code == 204:
            return int(remote_cfg["poll_interval_seconds"])
        if res.status_code != 200:
            raise RuntimeError(f"Relay poll failed ({res.status_code})")

        data = res.json() if res.content else {}
        tasks = data.get("tasks", [])
        if not isinstance(tasks, list):
            tasks = []
        tasks = tasks[: int(remote_cfg["max_tasks_per_poll"])]
        _set_runtime(tasks_received=int(_snapshot_runtime().get("tasks_received", 0) or 0) + len(tasks))

        results: list[dict] = []
        success_count = 0
        failed_count = 0
        for task in tasks:
            if not isinstance(task, dict):
                continue
            task_result = await _execute_task(remote_cfg, task)
            results.append(task_result)
            if task_result.get("ok"):
                success_count += 1
            else:
                failed_count += 1
            _append_result(
                {
                    "at": _utc_now_iso(),
                    "task_id": str(task_result.get("task_id") or ""),
                    "tool": str(task_result.get("tool") or ""),
                    "ok": bool(task_result.get("ok")),
                    "error": str(task_result.get("error") or "")[:240] if not task_result.get("ok") else "",
                }
            )

        if results:
            report_payload = {
                "project_id": remote_cfg["project_id"],
                "device_id": remote_cfg["device_id"],
                "results": results,
            }
            report_res = await _post_signed(client, remote_cfg, _REPORT_PATH, report_payload)
            _set_runtime(last_http_status=int(report_res.status_code))

        snapshot = _snapshot_runtime()
        _set_runtime(
            tasks_succeeded=int(snapshot.get("tasks_succeeded", 0) or 0) + int(success_count),
            tasks_failed=int(snapshot.get("tasks_failed", 0) or 0) + int(failed_count),
            last_success_at=_utc_now_iso(),
            last_error=None,
            last_error_at=None,
        )

        poll_after = _clamp_int(
            data.get("poll_after_seconds", remote_cfg["poll_interval_seconds"]),
            int(remote_cfg["poll_interval_seconds"]),
            5,
            300,
        )
        return poll_after


async def _run_loop():
    _set_runtime(worker_alive=True, running=True, status="running")
    next_wait = 1
    backoff = 0
    while True:
        if _stop_event is not None and _stop_event.is_set():
            break

        cfg = load_config(force_reload=True)
        remote_cfg = _normalize_remote_cfg(cfg.get("remote_access"))
        if not _is_ready_for_remote(remote_cfg):
            _set_runtime(
                running=False,
                status="disabled",
                worker_alive=False,
                last_error="Remote access is disabled or incomplete.",
                last_error_at=_utc_now_iso(),
            )
            return

        try:
            snapshot = _snapshot_runtime()
            _set_runtime(
                polls_total=int(snapshot.get("polls_total", 0) or 0) + 1,
                status="running",
                running=True,
                worker_alive=True,
            )
            next_wait = await _poll_once(remote_cfg)
            backoff = 0
        except asyncio.CancelledError:
            raise
        except Exception as e:
            snapshot = _snapshot_runtime()
            _set_runtime(
                status="error",
                running=True,
                worker_alive=True,
                polls_failed=int(snapshot.get("polls_failed", 0) or 0) + 1,
                last_error=str(e)[:360],
                last_error_at=_utc_now_iso(),
            )
            if backoff <= 0:
                backoff = int(remote_cfg["poll_interval_seconds"])
            else:
                backoff = min(180, backoff * 2)
            next_wait = backoff

        if _poll_now_event is None:
            await asyncio.sleep(next_wait)
            continue
        try:
            await asyncio.wait_for(_poll_now_event.wait(), timeout=max(1, int(next_wait)))
            _poll_now_event.clear()
        except asyncio.TimeoutError:
            pass

    _set_runtime(worker_alive=False, running=False, status="stopped")


async def start_remote_access_client() -> dict:
    global _worker_task, _stop_event, _poll_now_event
    cfg = load_config(force_reload=True)
    remote_cfg = _normalize_remote_cfg(cfg.get("remote_access"))
    _set_runtime(config=_public_remote_config(remote_cfg))

    if not _is_ready_for_remote(remote_cfg):
        _set_runtime(status="disabled", worker_alive=False, running=False)
        return get_remote_access_status()

    if _worker_task is not None and not _worker_task.done():
        return get_remote_access_status()

    _stop_event = asyncio.Event()
    _poll_now_event = asyncio.Event()
    _worker_task = asyncio.create_task(_run_loop(), name="mnesis-remote-relay")
    _set_runtime(status="running", worker_alive=True, running=True, last_error=None, last_error_at=None)
    return get_remote_access_status()


async def stop_remote_access_client() -> dict:
    global _worker_task, _stop_event
    task = _worker_task
    if task is None:
        _set_runtime(status="stopped", worker_alive=False, running=False)
        return get_remote_access_status()

    if _stop_event is not None:
        _stop_event.set()
    if _poll_now_event is not None:
        _poll_now_event.set()

    try:
        await asyncio.wait_for(task, timeout=5.0)
    except asyncio.TimeoutError:
        task.cancel()
        try:
            await task
        except Exception:
            pass
    except Exception:
        pass

    _worker_task = None
    _set_runtime(status="stopped", worker_alive=False, running=False)
    return get_remote_access_status()


async def trigger_remote_access_poll_now() -> dict:
    if _worker_task is None or _worker_task.done():
        await start_remote_access_client()
    if _poll_now_event is not None:
        _poll_now_event.set()
    return get_remote_access_status()


async def apply_remote_access_config(patch: dict | None) -> dict:
    cfg = load_config(force_reload=True)
    current = cfg.get("remote_access", {}) if isinstance(cfg.get("remote_access"), dict) else {}
    merged = dict(current)
    patch_data = patch if isinstance(patch, dict) else {}
    rotate_secret = bool(patch_data.get("rotate_device_secret", False))

    for key, value in patch_data.items():
        if key == "rotate_device_secret":
            continue
        if value is None:
            continue
        merged[key] = value

    if rotate_secret:
        merged["device_secret"] = secrets.token_urlsafe(32)

    normalized = _normalize_remote_cfg(merged)
    if not normalized.get("device_id"):
        normalized["device_id"] = str(cfg.get("sync", {}).get("device_id") or uuid.uuid4())
    if not normalized.get("device_secret"):
        normalized["device_secret"] = secrets.token_urlsafe(32)

    cfg["remote_access"] = normalized
    save_config(cfg)

    if _is_ready_for_remote(normalized):
        await stop_remote_access_client()
        await start_remote_access_client()
    else:
        await stop_remote_access_client()

    return get_remote_access_status()


def get_remote_access_status() -> dict:
    cfg = load_config(force_reload=True)
    remote_cfg = _normalize_remote_cfg(cfg.get("remote_access"))
    runtime = _snapshot_runtime()
    runtime.pop("config", None)
    return {
        "status": str(runtime.get("status") or "disabled"),
        "config": _public_remote_config(remote_cfg),
        "runtime": runtime,
        "allowed_tools": sorted(_TASK_HANDLERS.keys()),
    }
