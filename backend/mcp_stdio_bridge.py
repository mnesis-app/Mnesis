#!/usr/bin/env python3
"""
Mnesis MCP stdio bridge
=======================
Bridges stdio JSON-RPC <-> FastMCP SSE transport exposed by backend at /mcp.

Design goals:
- Never crash on transient SSE/HTTP failures.
- Reconnect automatically and refresh message endpoint session.
- Return deterministic JSON-RPC errors for failed requests (instead of hanging).
- Keep stdout strictly JSON-RPC payloads and send diagnostics to stderr only.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from contextlib import suppress
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from httpx_sse import SSEError, aconnect_sse

MCP_HTTP_URL = os.environ.get("MNESIS_MCP_URL", "http://127.0.0.1:7860")
API_KEY = os.environ.get("MNESIS_API_KEY", "")
TRACE_SESSION_ID = str(os.environ.get("MNESIS_SESSION_ID", "") or uuid.uuid4())

CONNECT_TIMEOUT_SECONDS = 4.0
POST_READ_TIMEOUT_SECONDS = 20.0
POST_WRITE_TIMEOUT_SECONDS = 20.0
ENDPOINT_WAIT_TIMEOUT_SECONDS = 2.5


def _stderr(line: str) -> None:
    sys.stderr.write(line.rstrip() + "\n")
    sys.stderr.flush()


def _stdout_json(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _normalize_base_url(raw_url: str) -> str:
    url = str(raw_url or "").strip().rstrip("/")
    for suffix in ("/mcp/sse", "/mcp-http", "/mcp"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
            break
    return url or "http://127.0.0.1:7860"


def _sse_stream_url(base_url: str) -> str:
    return f"{base_url}/mcp/sse"


def _is_jsonrpc_payload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("jsonrpc") != "2.0":
        return False
    if isinstance(payload.get("method"), str):
        return True
    if "id" in payload and "result" in payload:
        return True
    if "id" in payload and isinstance(payload.get("error"), dict):
        return True
    return False


def _extract_detail(payload: Any) -> str:
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
        err = payload.get("error")
        if isinstance(err, dict):
            message = err.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
    return ""


def _jsonrpc_error_for(message: dict[str, Any], text: str, *, code: int = -32098) -> dict[str, Any]:
    req_id = message.get("id", "bridge-error")
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {
            "code": int(code),
            "message": str(text or "MCP request failed."),
        },
    }


def _extract_endpoint_value(raw_data: str) -> str:
    data = str(raw_data or "").strip()
    if not data:
        return ""

    if data.startswith("{"):
        try:
            obj = json.loads(data)
            if isinstance(obj, dict):
                for key in ("endpoint", "url", "path"):
                    value = obj.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
        except Exception:
            pass
    return data


def _normalize_messages_url(raw_url: str) -> str:
    # FastMCP can emit /mcp/messages/?session_id=... (with trailing slash).
    # Some deployments accept only /mcp/messages?session_id=... (without slash).
    url = str(raw_url or "").strip().replace("/messages/?", "/messages?")
    parsed = urlparse(url)
    if parsed.path.endswith("/") and "session_id=" in str(parsed.query or ""):
        parsed = parsed._replace(path=parsed.path.rstrip("/"))
        return urlunparse(parsed)
    return url


def _candidate_message_urls(raw_url: str) -> list[str]:
    out: list[str] = []

    def add(value: str) -> None:
        v = str(value or "").strip()
        if v and v not in out:
            out.append(v)

    normalized = _normalize_messages_url(raw_url)
    add(normalized)

    parsed = urlparse(normalized)
    if parsed.path.endswith("/"):
        add(urlunparse(parsed._replace(path=parsed.path.rstrip("/"))))
    else:
        add(urlunparse(parsed._replace(path=parsed.path + "/")))

    return out


async def _wait_for_endpoint(state: dict[str, Any], timeout_seconds: float = ENDPOINT_WAIT_TIMEOUT_SECONDS) -> bool:
    endpoint_ready: asyncio.Event = state["endpoint_ready"]
    try:
        await asyncio.wait_for(endpoint_ready.wait(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        return False
    return bool(state.get("message_urls"))


def _clear_endpoint(state: dict[str, Any]) -> None:
    state["message_urls"] = []
    state["message_url_index"] = 0
    endpoint_ready: asyncio.Event = state["endpoint_ready"]
    endpoint_ready.clear()


def _advance_endpoint(state: dict[str, Any]) -> str | None:
    urls = list(state.get("message_urls") or [])
    idx = int(state.get("message_url_index", 0) or 0)
    if idx + 1 < len(urls):
        state["message_url_index"] = idx + 1
        return str(urls[idx + 1])
    return None


async def _sse_reader(
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
    state: dict[str, Any],
    stop_event: asyncio.Event,
) -> None:
    sse_url = _sse_stream_url(base_url)
    backoff = 0.2
    _stderr(f"Bridge mode: sse · base={base_url}")
    _stderr(f"Bridge SSE stream: {sse_url}")

    while not stop_event.is_set():
        try:
            async with aconnect_sse(
                client,
                method="GET",
                url=sse_url,
                headers=headers,
                timeout=None,
            ) as event_source:
                backoff = 0.2
                async for event in event_source.aiter_sse():
                    if stop_event.is_set():
                        return

                    event_name = str(getattr(event, "event", "") or "").strip().lower()
                    data = str(getattr(event, "data", "") or "").strip()
                    if not data:
                        continue

                    if event_name == "endpoint":
                        endpoint_value = _extract_endpoint_value(data)
                        if not endpoint_value:
                            continue
                        absolute = urljoin(base_url + "/", endpoint_value)
                        candidates = _candidate_message_urls(absolute)
                        if candidates:
                            state["message_urls"] = candidates
                            state["message_url_index"] = 0
                            endpoint_ready: asyncio.Event = state["endpoint_ready"]
                            endpoint_ready.set()
                            _stderr(f"Bridge SSE endpoint ready: {candidates[0]}")
                        continue

                    if event_name not in ("message", ""):
                        continue

                    try:
                        payload = json.loads(data)
                    except Exception:
                        continue

                    if isinstance(payload, list):
                        for item in payload:
                            if _is_jsonrpc_payload(item):
                                _stdout_json(item)
                        continue

                    if _is_jsonrpc_payload(payload):
                        _stdout_json(payload)
                        continue

                    detail = _extract_detail(payload)
                    if detail:
                        _stderr(f"Bridge ignored non-JSONRPC SSE payload: {detail}")

        except asyncio.CancelledError:
            raise
        except SSEError as exc:
            _stderr(f"Bridge SSE protocol error: {exc}; reconnecting in {backoff:.1f}s...")
        except Exception as exc:
            _stderr(f"Bridge SSE error: {exc}; reconnecting in {backoff:.1f}s...")

        _clear_endpoint(state)
        if stop_event.is_set():
            return
        await asyncio.sleep(backoff)
        backoff = min(2.0, backoff * 2)


async def _post_message(
    client: httpx.AsyncClient,
    message: dict[str, Any],
    headers: dict[str, str],
    state: dict[str, Any],
    stop_event: asyncio.Event,
) -> None:
    is_request = "id" in message
    method = str(message.get("method") or "").strip().lower()
    max_attempts = 40 if method == "initialize" else 20
    attempt = 0

    while attempt < max_attempts and not stop_event.is_set():
        has_endpoint = await _wait_for_endpoint(state)
        if not has_endpoint:
            attempt += 1
            continue

        urls = list(state.get("message_urls") or [])
        if not urls:
            attempt += 1
            continue

        idx = int(state.get("message_url_index", 0) or 0)
        idx = max(0, min(idx, len(urls) - 1))
        endpoint = str(urls[idx])

        try:
            response = await client.post(
                endpoint,
                json=message,
                headers=headers,
                timeout=httpx.Timeout(
                    connect=CONNECT_TIMEOUT_SECONDS,
                    read=POST_READ_TIMEOUT_SECONDS,
                    write=POST_WRITE_TIMEOUT_SECONDS,
                    pool=None,
                ),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            attempt += 1
            delay = min(2.0, 0.2 * (2 ** max(0, attempt - 1)))
            _stderr(f"Bridge POST error: {exc}; retrying in {delay:.1f}s...")
            await asyncio.sleep(delay)
            continue

        status = int(response.status_code)
        if status in (200, 202, 204):
            raw = str(response.text or "").strip()
            if raw:
                try:
                    payload = json.loads(raw)
                except Exception:
                    payload = None
                if isinstance(payload, list):
                    for item in payload:
                        if _is_jsonrpc_payload(item):
                            _stdout_json(item)
                elif _is_jsonrpc_payload(payload):
                    _stdout_json(payload)
            return

        if status in (404, 405, 409, 410):
            alternative = _advance_endpoint(state)
            if alternative:
                _stderr(f"Bridge endpoint {endpoint} returned {status}; trying {alternative}")
            else:
                _clear_endpoint(state)
            attempt += 1
            await asyncio.sleep(min(1.5, 0.15 * (2 ** max(0, attempt - 1))))
            continue

        if status in (401, 403):
            if is_request:
                _stdout_json(
                    _jsonrpc_error_for(
                        message,
                        "MCP authentication failed. Verify MNESIS_API_KEY.",
                        code=-32001,
                    )
                )
            return

        if status >= 500 or status in (408, 425, 429):
            attempt += 1
            delay = min(2.0, 0.2 * (2 ** max(0, attempt - 1)))
            _stderr(f"Bridge HTTP error: {status} from {endpoint}; retrying in {delay:.1f}s...")
            await asyncio.sleep(delay)
            continue

        detail = ""
        raw = str(response.text or "").strip()
        if raw:
            try:
                detail = _extract_detail(json.loads(raw))
            except Exception:
                detail = ""
        detail = detail or f"HTTP {status}"
        if is_request:
            _stdout_json(_jsonrpc_error_for(message, f"MCP request failed: {detail}"))
        return

    if is_request and not stop_event.is_set():
        _stdout_json(
            _jsonrpc_error_for(
                message,
                "MCP backend unavailable. Request timed out while waiting for endpoint.",
            )
        )


async def _stdin_reader(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    state: dict[str, Any],
    stop_event: asyncio.Event,
) -> None:
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    while not stop_event.is_set():
        try:
            line = await reader.readline()
            if not line:
                stop_event.set()
                return

            stripped = line.strip()
            if not stripped:
                continue

            try:
                message = json.loads(stripped)
            except json.JSONDecodeError:
                continue

            if not isinstance(message, dict):
                continue

            await _post_message(
                client=client,
                message=message,
                headers=headers,
                state=state,
                stop_event=stop_event,
            )
        except (asyncio.CancelledError, EOFError, ConnectionResetError, BrokenPipeError):
            stop_event.set()
            return
        except Exception as e:
            _stderr(f"Bridge stdin error: {e}")
            await asyncio.sleep(0.5)


async def bridge() -> None:
    base_url = _normalize_base_url(MCP_HTTP_URL)

    sse_headers: dict[str, str] = {
        "Accept": "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Mnesis-Session-Id": TRACE_SESSION_ID,
    }
    post_headers: dict[str, str] = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Mnesis-Session-Id": TRACE_SESSION_ID,
    }
    if API_KEY:
        auth_value = f"Bearer {API_KEY}"
        sse_headers["Authorization"] = auth_value
        post_headers["Authorization"] = auth_value

    timeout = httpx.Timeout(
        connect=CONNECT_TIMEOUT_SECONDS,
        read=None,
        write=POST_WRITE_TIMEOUT_SECONDS,
        pool=None,
    )

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        stop_event = asyncio.Event()
        state: dict[str, Any] = {
            "message_urls": [],
            "message_url_index": 0,
            "endpoint_ready": asyncio.Event(),
        }

        sse_task = asyncio.create_task(
            _sse_reader(
                client=client,
                base_url=base_url,
                headers=sse_headers,
                state=state,
                stop_event=stop_event,
            )
        )

        try:
            await _stdin_reader(
                client=client,
                headers=post_headers,
                state=state,
                stop_event=stop_event,
            )
        finally:
            stop_event.set()
            sse_task.cancel()
            with suppress(asyncio.CancelledError):
                await sse_task


if __name__ == "__main__":
    try:
        asyncio.run(bridge())
    except KeyboardInterrupt:
        pass
