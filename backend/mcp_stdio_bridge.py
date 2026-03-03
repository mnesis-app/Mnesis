#!/usr/bin/env python3
"""
Mnesis MCP stdio bridge
=======================
Bridges stdio JSON-RPC <-> FastMCP streamable-http transport exposed by backend at /mcp.

Design goals:
- Never crash on transient HTTP failures.
- Reconnect automatically on errors.
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

import httpx
from httpx_sse import EventSource, SSEError

MCP_HTTP_URL = os.environ.get("MNESIS_MCP_URL", "http://127.0.0.1:7860")
API_KEY = os.environ.get("MNESIS_API_KEY", "")
TRACE_SESSION_ID = str(os.environ.get("MNESIS_SESSION_ID", "") or uuid.uuid4())

CONNECT_TIMEOUT_SECONDS = 4.0
POST_READ_TIMEOUT_SECONDS = 20.0
POST_WRITE_TIMEOUT_SECONDS = 20.0


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


def _mcp_url(base_url: str) -> str:
    return f"{base_url}/mcp"


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


def _emit_jsonrpc(payload: Any) -> None:
    if isinstance(payload, list):
        for item in payload:
            if _is_jsonrpc_payload(item):
                _stdout_json(item)
    elif _is_jsonrpc_payload(payload):
        _stdout_json(payload)


async def _post_message(
    client: httpx.AsyncClient,
    message: dict[str, Any],
    headers: dict[str, str],
    mcp_url: str,
    stop_event: asyncio.Event,
) -> None:
    is_request = "id" in message
    method = str(message.get("method") or "").strip().lower()
    max_attempts = 40 if method == "initialize" else 20
    attempt = 0

    while attempt < max_attempts and not stop_event.is_set():
        try:
            async with client.stream(
                "POST",
                mcp_url,
                json=message,
                headers=headers,
                timeout=httpx.Timeout(
                    connect=CONNECT_TIMEOUT_SECONDS,
                    read=POST_READ_TIMEOUT_SECONDS,
                    write=POST_WRITE_TIMEOUT_SECONDS,
                    pool=None,
                ),
            ) as response:
                status = int(response.status_code)

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
                    _stderr(f"Bridge HTTP error: {status} from {mcp_url}; retrying in {delay:.1f}s...")
                    await asyncio.sleep(delay)
                    continue

                content_type = response.headers.get("content-type", "").lower()

                if "text/event-stream" in content_type:
                    async for event in EventSource(response).aiter_sse():
                        if stop_event.is_set():
                            return
                        data = str(getattr(event, "data", "") or "").strip()
                        if not data:
                            continue
                        try:
                            payload = json.loads(data)
                        except Exception:
                            continue
                        _emit_jsonrpc(payload)
                else:
                    raw = await response.aread()
                    text = raw.decode("utf-8", errors="replace").strip()
                    if text:
                        try:
                            payload = json.loads(text)
                            _emit_jsonrpc(payload)
                        except Exception:
                            detail = _extract_detail({})
                            if detail:
                                _stderr(f"Bridge non-JSON response: {detail}")
                return

        except asyncio.CancelledError:
            raise
        except SSEError as exc:
            attempt += 1
            delay = min(2.0, 0.2 * (2 ** max(0, attempt - 1)))
            _stderr(f"Bridge SSE error: {exc}; retrying in {delay:.1f}s...")
            await asyncio.sleep(delay)
        except Exception as exc:
            attempt += 1
            delay = min(2.0, 0.2 * (2 ** max(0, attempt - 1)))
            _stderr(f"Bridge POST error: {exc}; retrying in {delay:.1f}s...")
            await asyncio.sleep(delay)

    if is_request and not stop_event.is_set():
        _stdout_json(
            _jsonrpc_error_for(
                message,
                "MCP backend unavailable. Request timed out while waiting for response.",
            )
        )


async def _stdin_reader(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    mcp_url: str,
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
                mcp_url=mcp_url,
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
    mcp_url = _mcp_url(base_url)

    headers: dict[str, str] = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "X-Mnesis-Session-Id": TRACE_SESSION_ID,
    }
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"

    _stderr(f"Bridge mode: streamable-http · endpoint={mcp_url}")

    timeout = httpx.Timeout(
        connect=CONNECT_TIMEOUT_SECONDS,
        read=None,
        write=POST_WRITE_TIMEOUT_SECONDS,
        pool=None,
    )

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        stop_event = asyncio.Event()
        await _stdin_reader(
            client=client,
            headers=headers,
            mcp_url=mcp_url,
            stop_event=stop_event,
        )


if __name__ == "__main__":
    try:
        asyncio.run(bridge())
    except KeyboardInterrupt:
        pass
