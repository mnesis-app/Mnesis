from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import stat
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from backend.config import CONFIG_PATH, load_config

MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_KNOWN_KEY_SCOPES = {"read", "write", "sync", "admin"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            return None
    return None


def sha256_hex(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def constant_time_equal(left: str, right: str) -> bool:
    if not isinstance(left, str) or not isinstance(right, str):
        return False
    return hmac.compare_digest(left, right)


def extract_bearer_token_from_header(auth_header: str) -> str | None:
    raw = str(auth_header or "").strip()
    if not raw:
        return None
    parts = raw.split(None, 1)
    if len(parts) != 2:
        return None
    if parts[0].strip().lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def extract_bearer_token(request: Request) -> str | None:
    token = extract_bearer_token_from_header(request.headers.get("Authorization", ""))
    if token:
        return token
    # Fallback to query parameter for HTTP clients (like AnythingLLM, ChatGPT, Gemini)
    # where setting custom Authorization headers is difficult.
    return request.query_params.get("token")


def _normalize_key_scopes(value: Any) -> set[str]:
    if isinstance(value, str):
        raw_items = [part.strip().lower() for part in value.split(",") if part.strip()]
    elif isinstance(value, (list, tuple, set)):
        raw_items = [str(part).strip().lower() for part in value if str(part).strip()]
    else:
        raw_items = []

    scopes = set()
    if not raw_items:
        scopes.update({"read", "write", "sync"})
    else:
        for item in raw_items:
            if item in {"*", "all"}:
                scopes.update({"admin", "sync", "read", "write"})
                continue
            if item in _KNOWN_KEY_SCOPES:
                scopes.add(item)
    if not scopes:
        scopes.update({"read", "write", "sync"})
    if "admin" in scopes:
        scopes.update({"sync", "read", "write"})
    if "sync" in scopes:
        scopes.update({"read", "write"})
    return scopes


def _iter_mcp_key_entries(config: dict) -> list[dict[str, Any]]:
    keys = config.get("llm_client_keys", {})
    if not isinstance(keys, dict):
        keys = {}

    out: list[dict[str, Any]] = []
    for raw_name, raw_value in keys.items():
        name = str(raw_name or "").strip() or "mcp"
        if isinstance(raw_value, dict):
            if raw_value.get("enabled") is False:
                continue
            scopes = _normalize_key_scopes(raw_value.get("scopes"))
        else:
            scopes = {"read", "write", "sync"}
        out.append(
            {
                "name": name,
                "scopes": sorted(scopes),
            }
        )
    return out


def _security_cfg(config: dict | None = None) -> dict:
    cfg = config if isinstance(config, dict) else load_config()
    security = cfg.get("security", {}) if isinstance(cfg, dict) else {}
    if not isinstance(security, dict):
        security = {}
    rate_limit = security.get("rate_limit", {})
    if not isinstance(rate_limit, dict):
        rate_limit = {}
    buckets = rate_limit.get("buckets", {})
    if not isinstance(buckets, dict):
        buckets = {}
    audit = security.get("audit", {})
    if not isinstance(audit, dict):
        audit = {}
    return {
        "enforce_mcp_auth": bool(security.get("enforce_mcp_auth", True)),
        "allow_snapshot_token_for_mcp": bool(security.get("allow_snapshot_token_for_mcp", True)),
        "allow_snapshot_query_token": bool(security.get("allow_snapshot_query_token", True)),
        "require_client_mutation_header": bool(security.get("require_client_mutation_header", True)),
        "client_mutation_header_name": str(
            security.get("client_mutation_header_name", "X-Mnesis-Client")
        ).strip()
        or "X-Mnesis-Client",
        "allowed_client_mutation_header_values": [
            str(v).strip().lower()
            for v in (
                security.get(
                    "allowed_client_mutation_header_values",
                    ["mnesis-desktop", "mnesis-electron", "mnesis-cli", "mnesis-tests"],
                )
                or []
            )
            if str(v).strip()
        ],
        "allowed_mutation_origins": [
            str(v).strip().lower()
            for v in (
                security.get(
                    "allowed_mutation_origins",
                    ["http://127.0.0.1", "http://localhost", "app://."],
                )
                or []
            )
            if str(v).strip()
        ],
        "rate_limit": {
            "enabled": bool(rate_limit.get("enabled", True)),
            "window_seconds": max(1, int(rate_limit.get("window_seconds", 60) or 60)),
            "buckets": {
                "health": max(1, int(buckets.get("health", 120) or 120)),
                "mcp": max(1, int(buckets.get("mcp", 240) or 240)),
                "snapshot": max(1, int(buckets.get("snapshot", 40) or 40)),
                "admin": max(1, int(buckets.get("admin", 160) or 160)),
                "api_mutation": max(1, int(buckets.get("api_mutation", 200) or 200)),
            },
        },
        "audit": {
            "enabled": bool(audit.get("enabled", True)),
            "interval_minutes": max(5, int(audit.get("interval_minutes", 60) or 60)),
        },
    }


def security_runtime_overview(config: dict | None = None) -> dict:
    cfg = config if isinstance(config, dict) else load_config()
    sec = _security_cfg(cfg)
    key_entries = _iter_mcp_key_entries(cfg if isinstance(cfg, dict) else {})
    scope_counts = {"read": 0, "write": 0, "sync": 0, "admin": 0}
    for entry in key_entries:
        scopes = set(entry.get("scopes") or [])
        for scope in scope_counts.keys():
            if scope in scopes:
                scope_counts[scope] += 1
    snapshot_token = str((cfg or {}).get("snapshot_read_token") or "")
    return {
        "generated_at": _utc_now_iso(),
        "mcp_auth_enforced": bool(sec.get("enforce_mcp_auth", True)),
        "snapshot_token_for_mcp_enabled": bool(sec.get("allow_snapshot_token_for_mcp", True)),
        "snapshot_query_token_enabled": bool(sec.get("allow_snapshot_query_token", True)),
        "mutation_header_guard_enabled": bool(sec.get("require_client_mutation_header", True)),
        "mutation_header_name": sec.get("client_mutation_header_name", "X-Mnesis-Client"),
        "mutation_allowed_origins": sec.get("allowed_mutation_origins", []),
        "rate_limit_enabled": bool(sec.get("rate_limit", {}).get("enabled", True)),
        "mcp_registered_keys": len(key_entries),
        "mcp_scope_counts": scope_counts,
        "snapshot_token_present": bool(snapshot_token),
    }


def strict_security_patch(config: dict | None = None) -> dict:
    """
    Build a strict-mode patch while avoiding accidental MCP lockout.
    """
    cfg = config if isinstance(config, dict) else load_config(force_reload=True)
    keys = cfg.get("llm_client_keys", {})
    has_mcp_keys = isinstance(keys, dict) and bool(keys)
    return {
        "enforce_mcp_auth": True,
        # Keep this enabled when no dedicated MCP key exists, to avoid breaking clients.
        "allow_snapshot_token_for_mcp": False if has_mcp_keys else True,
        "allow_snapshot_query_token": False,
        "require_client_mutation_header": True,
        "client_mutation_header_name": "X-Mnesis-Client",
        "allowed_client_mutation_header_values": [
            "mnesis-desktop",
            "mnesis-electron",
            "mnesis-cli",
            "mnesis-tests",
        ],
        "allowed_mutation_origins": [
            "http://127.0.0.1",
            "http://localhost",
            "app://.",
        ],
        "rate_limit": {
            "enabled": True,
            "window_seconds": 60,
            "buckets": {
                "health": 120,
                "mcp": 240,
                "snapshot": 40,
                "admin": 160,
                "api_mutation": 200,
            },
        },
        "audit": {
            "enabled": True,
            "interval_minutes": 30,
        },
        "_meta": {
            "has_mcp_keys": has_mcp_keys,
            "lockout_safe_mode": not has_mcp_keys,
            "note": (
                "Snapshot token fallback kept for MCP because no dedicated MCP key is configured yet."
                if not has_mcp_keys
                else "Full strict mode applied (snapshot MCP fallback disabled)."
            ),
        },
    }


def bootstrap_bridge_mcp_key(config: dict | None = None) -> dict:
    """
    Ensure at least one MCP key exists by hashing the current snapshot token.
    This enables disabling snapshot fallback without breaking existing bridge clients.
    """
    cfg = config if isinstance(config, dict) else load_config(force_reload=True)
    token = str(cfg.get("snapshot_read_token") or "").strip()
    keys = cfg.get("llm_client_keys", {})
    if not isinstance(keys, dict):
        keys = {}
    if keys:
        return {"created": False, "key_name": None, "reason": "already_has_keys"}
    if not token:
        return {"created": False, "key_name": None, "reason": "missing_snapshot_token"}

    key_name = "mnesis-bridge"
    keys[key_name] = {
        "hash": sha256_hex(token),
        "scopes": ["read", "write", "sync"],
        "enabled": True,
        "created_at": _utc_now_iso(),
    }
    cfg["llm_client_keys"] = keys
    return {"created": True, "key_name": key_name, "reason": "bootstrapped"}


def _compute_score(checks: list[dict[str, Any]]) -> tuple[int, str]:
    penalties = {
        "critical": {"fail": 30, "warn": 15},
        "high": {"fail": 20, "warn": 10},
        "medium": {"fail": 12, "warn": 6},
        "low": {"fail": 6, "warn": 3},
    }
    score = 100
    for check in checks:
        status = str(check.get("status") or "pass").lower()
        severity = str(check.get("severity") or "low").lower()
        if status not in {"fail", "warn"}:
            continue
        score -= penalties.get(severity, penalties["low"]).get(status, 0)
    score = max(0, min(100, int(score)))
    if score >= 90:
        grade = "A"
    elif score >= 80:
        grade = "B"
    elif score >= 70:
        grade = "C"
    elif score >= 60:
        grade = "D"
    else:
        grade = "E"
    return score, grade


def collect_security_audit(config: dict | None = None) -> dict:
    cfg = config if isinstance(config, dict) else load_config(force_reload=True)
    sec = _security_cfg(cfg)
    checks: list[dict[str, Any]] = []

    def add_check(
        *,
        check_id: str,
        status: str,
        severity: str,
        message: str,
        recommendation: str | None = None,
    ) -> None:
        checks.append(
            {
                "id": check_id,
                "status": status,
                "severity": severity,
                "message": message,
                "recommendation": recommendation or "",
            }
        )

    if sec["enforce_mcp_auth"]:
        add_check(
            check_id="mcp_auth_enabled",
            status="pass",
            severity="high",
            message="MCP authentication is enabled.",
        )
    else:
        add_check(
            check_id="mcp_auth_enabled",
            status="fail",
            severity="critical",
            message="MCP authentication is disabled.",
            recommendation="Enable security.enforce_mcp_auth immediately.",
        )

    key_entries = _iter_mcp_key_entries(cfg)
    key_count = len(key_entries)
    scope_counts = {"read": 0, "write": 0, "sync": 0, "admin": 0}
    for entry in key_entries:
        scopes = set(entry.get("scopes") or [])
        for scope in scope_counts.keys():
            if scope in scopes:
                scope_counts[scope] += 1
    snapshot_token = str(cfg.get("snapshot_read_token") or "")
    if key_count:
        add_check(
            check_id="mcp_credentials_present",
            status="pass",
            severity="high",
            message=f"{key_count} dedicated MCP credential(s) configured.",
        )
    elif snapshot_token:
        add_check(
            check_id="mcp_credentials_present",
            status="warn",
            severity="medium",
            message="No dedicated MCP client key found; fallback snapshot token is used.",
            recommendation="Add per-client MCP keys in Settings for better key isolation.",
        )
    else:
        add_check(
            check_id="mcp_credentials_present",
            status="fail",
            severity="critical",
            message="No MCP credential is configured.",
            recommendation="Configure at least one MCP key before exposing MCP access.",
        )

    if key_count:
        missing = [scope for scope in ("read", "write", "sync") if scope_counts.get(scope, 0) <= 0]
        if missing:
            add_check(
                check_id="mcp_scope_coverage",
                status="warn",
                severity="medium",
                message=f"MCP key scopes are incomplete (missing: {', '.join(missing)}).",
                recommendation="Ensure at least one key provides each required scope: read, write, sync.",
            )
        else:
            add_check(
                check_id="mcp_scope_coverage",
                status="pass",
                severity="medium",
                message="MCP key scope coverage includes read, write, and sync.",
            )

    if sec["allow_snapshot_token_for_mcp"]:
        add_check(
            check_id="snapshot_token_mcp_fallback",
            status="warn",
            severity="medium",
            message="Snapshot token can authenticate MCP requests.",
            recommendation="Disable security.allow_snapshot_token_for_mcp after migrating to dedicated MCP keys.",
        )
    else:
        add_check(
            check_id="snapshot_token_mcp_fallback",
            status="pass",
            severity="low",
            message="Snapshot token fallback for MCP is disabled.",
        )

    if sec["allow_snapshot_query_token"]:
        add_check(
            check_id="snapshot_query_token",
            status="warn",
            severity="medium",
            message="Snapshot endpoint accepts token in query string.",
            recommendation="Disable security.allow_snapshot_query_token and use Authorization: Bearer.",
        )
    else:
        add_check(
            check_id="snapshot_query_token",
            status="pass",
            severity="medium",
            message="Snapshot endpoint requires header-based token auth.",
        )

    if sec["require_client_mutation_header"]:
        allowed = sec["allowed_client_mutation_header_values"]
        if allowed:
            add_check(
                check_id="mutation_header_guard",
                status="pass",
                severity="high",
                message=f"Mutation header guard is enabled ({len(allowed)} allowed client id(s)).",
            )
        else:
            add_check(
                check_id="mutation_header_guard",
                status="fail",
                severity="high",
                message="Mutation header guard enabled but allowed values list is empty.",
                recommendation="Define security.allowed_client_mutation_header_values.",
            )
    else:
        add_check(
            check_id="mutation_header_guard",
            status="warn",
            severity="medium",
            message="Mutation header guard is disabled.",
            recommendation="Enable security.require_client_mutation_header to reduce localhost CSRF risk.",
        )

    if sec["allowed_mutation_origins"]:
        add_check(
            check_id="mutation_origin_allowlist",
            status="pass",
            severity="high",
            message=f"Mutation origin allowlist configured ({len(sec['allowed_mutation_origins'])} origin pattern(s)).",
        )
    else:
        add_check(
            check_id="mutation_origin_allowlist",
            status="fail",
            severity="high",
            message="No trusted origin is configured for mutating API routes.",
            recommendation="Set security.allowed_mutation_origins.",
        )

    rate_limit = sec["rate_limit"]
    if rate_limit["enabled"]:
        add_check(
            check_id="rate_limit_enabled",
            status="pass",
            severity="high",
            message="Rate limiting is enabled on sensitive routes.",
        )
    else:
        add_check(
            check_id="rate_limit_enabled",
            status="fail",
            severity="high",
            message="Rate limiting is disabled.",
            recommendation="Enable security.rate_limit.enabled.",
        )

    if len(snapshot_token) >= 24:
        add_check(
            check_id="snapshot_token_strength",
            status="pass",
            severity="medium",
            message="Snapshot token length is acceptable.",
        )
    else:
        add_check(
            check_id="snapshot_token_strength",
            status="fail",
            severity="high",
            message="Snapshot token appears too short.",
            recommendation="Rotate token and keep minimum 24+ random chars.",
        )

    insights = cfg.get("insights", {})
    has_embedded_secret = bool(str(insights.get("api_key") or "").strip()) if isinstance(insights, dict) else False
    if has_embedded_secret:
        add_check(
            check_id="plaintext_provider_key",
            status="warn",
            severity="low",
            message="An external provider API key is stored in local config.yaml.",
            recommendation="Prefer OS keychain/secret manager storage for provider secrets.",
        )
    else:
        add_check(
            check_id="plaintext_provider_key",
            status="pass",
            severity="low",
            message="No external provider key is stored in config.",
        )

    if os.name != "nt":
        try:
            st = os.stat(CONFIG_PATH)
            mode = stat.S_IMODE(st.st_mode)
            if mode & (stat.S_IRWXG | stat.S_IRWXO):
                add_check(
                    check_id="config_file_permissions",
                    status="warn",
                    severity="medium",
                    message=f"Config permissions are broader than owner-only ({oct(mode)}).",
                    recommendation=f"Run: chmod 600 {CONFIG_PATH}",
                )
            else:
                add_check(
                    check_id="config_file_permissions",
                    status="pass",
                    severity="medium",
                    message="Config file permissions are owner-only.",
                )
        except Exception:
            add_check(
                check_id="config_file_permissions",
                status="warn",
                severity="low",
                message="Unable to verify config file permissions.",
            )
    else:
        add_check(
            check_id="config_file_permissions",
            status="pass",
            severity="low",
            message="Windows ACL model in use (POSIX permission audit skipped).",
        )

    summary = {
        "pass": sum(1 for c in checks if c["status"] == "pass"),
        "warn": sum(1 for c in checks if c["status"] == "warn"),
        "fail": sum(1 for c in checks if c["status"] == "fail"),
    }
    score, grade = _compute_score(checks)
    return {
        "generated_at": _utc_now_iso(),
        "score": score,
        "grade": grade,
        "summary": summary,
        "checks": checks,
        "runtime": security_runtime_overview(cfg),
    }


class MutationClientGuardMiddleware:
    """
    Protect mutating localhost API routes against unauthenticated cross-origin form posts.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        request = Request(scope, receive)
        method = request.method.upper()
        path = request.url.path
        if method not in MUTATION_METHODS:
            return await self.app(scope, receive, send)
        if not (path.startswith("/api/v1/") or path.startswith("/api/import/")):
            return await self.app(scope, receive, send)

        sec = _security_cfg()
        origin = str(request.headers.get("Origin", "")).strip().lower()
        allowed_origins = sec.get("allowed_mutation_origins", []) or []
        if origin:
            if not any(origin.startswith(candidate) for candidate in allowed_origins):
                response = JSONResponse(
                    status_code=403,
                    content={"detail": "Blocked mutating API request from non-trusted origin."},
                )
                return await response(scope, receive, send)

        # Non-browser clients (no Origin) are allowed for local automation/CLI.
        if not origin:
            return await self.app(scope, receive, send)

        if not sec["require_client_mutation_header"]:
            return await self.app(scope, receive, send)

        header_name = sec["client_mutation_header_name"]
        allowed = set(sec["allowed_client_mutation_header_values"])
        if not allowed:
            allowed = {"mnesis-desktop"}
        provided = str(request.headers.get(header_name, "")).strip().lower()
        if provided in allowed:
            try:
                request.state.mnesis_client = provided
            except Exception:
                pass
            return await self.app(scope, receive, send)

        response = JSONResponse(
            status_code=403,
            content={
                "detail": f"Missing or invalid {header_name} header for mutating API route."
            },
        )
        return await response(scope, receive, send)


def _is_loopback_ip(value: str) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    if raw.count(":") == 1 and "." in raw:
        host, port = raw.rsplit(":", 1)
        if port.isdigit():
            raw = host.strip()
    try:
        return bool(ipaddress.ip_address(raw).is_loopback)
    except Exception:
        lowered = raw.lower()
        return lowered in {"localhost", "::1"}


def _extract_forwarded_for_ip(header_value: str) -> str:
    # Header can contain a comma-separated chain, the left-most client is what we need.
    first = str(header_value or "").split(",")[0].strip()
    if first.startswith('"') and first.endswith('"') and len(first) >= 2:
        first = first[1:-1]
    return first.strip()


def _is_proxy_or_tunnel_request(request: Request) -> bool:
    xff = _extract_forwarded_for_ip(str(request.headers.get("X-Forwarded-For", "") or ""))
    if xff and not _is_loopback_ip(xff):
        return True

    x_real_ip = str(request.headers.get("X-Real-IP", "") or "").strip()
    if x_real_ip and not _is_loopback_ip(x_real_ip):
        return True

    forwarded = str(request.headers.get("Forwarded", "") or "").strip().lower()
    if forwarded:
        # Minimal RFC 7239 parse for "for=<ip>" tokens.
        parts = [p.strip() for p in forwarded.split(";") if p.strip()]
        for part in parts:
            if not part.startswith("for="):
                continue
            candidate = part.split("=", 1)[1].strip().strip('"').strip("[]")
            if candidate and not _is_loopback_ip(candidate):
                return True
    return False


class AdminRouteAccessMiddleware:
    """
    Keep local DX unchanged while hardening BYO-tunnel scenarios:
    - Local direct API calls remain allowed.
    - If request is proxied/tunneled, require scoped Bearer auth on /api routes.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        request = Request(scope, receive)
        path = request.url.path
        if not (path.startswith("/api/v1/") or path.startswith("/api/import/")):
            return await self.app(scope, receive, send)
        if request.method.upper() == "OPTIONS":
            return await self.app(scope, receive, send)

        if not _is_proxy_or_tunnel_request(request):
            return await self.app(scope, receive, send)

        # Snapshot route has its own strict token checks in the router.
        if path.startswith("/api/v1/snapshot/text"):
            return await self.app(scope, receive, send)

        method = request.method.upper()
        if path.startswith("/api/v1/admin"):
            required_scope = "admin"
        elif method in MUTATION_METHODS:
            required_scope = "write"
        else:
            required_scope = "read"

        bearer = extract_bearer_token(request)
        if bearer:
            try:
                from backend.auth import authenticate_mcp_token, token_scope_allowed

                auth_ctx = authenticate_mcp_token(bearer)
                if auth_ctx and token_scope_allowed(auth_ctx.get("scopes"), required_scope):
                    try:
                        request.state.mcp_client_name = str(auth_ctx.get("name") or "mcp")
                        request.state.mcp_client_scopes = list(auth_ctx.get("scopes") or [])
                        request.state.mcp_auth_kind = str(auth_ctx.get("kind") or "llm_client_key")
                    except Exception:
                        pass
                    return await self.app(scope, receive, send)
            except Exception:
                pass

        from fastapi.responses import JSONResponse
        response = JSONResponse(
            status_code=401,
            content={
                "detail": (
                    f"Proxied API access requires a Bearer token with '{required_scope}' scope."
                )
            },
        )
        return await response(scope, receive, send)


class _SlidingWindowLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int, int]:
        now = time.monotonic()
        cutoff = now - float(window_seconds)
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= cutoff:
                q.popleft()
            if len(q) >= int(limit):
                retry_after = max(1, int(window_seconds - (now - q[0])))
                return False, retry_after, len(q)
            q.append(now)
            remaining = max(0, int(limit) - len(q))
            return True, 0, remaining


_RATE_LIMITER = _SlidingWindowLimiter()


class _RequestMetricsStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._by_client: dict[str, dict[str, Any]] = {}
        self._last_flush_totals: dict[str, dict[str, int]] = {}

    def record(
        self,
        *,
        client: str,
        path: str,
        method: str,
        status_code: int,
        duration_ms: float,
    ) -> None:
        key = str(client or "unknown").strip().lower() or "unknown"
        now_iso = _utc_now_iso()
        with self._lock:
            entry = self._by_client.setdefault(
                key,
                {
                    "client": key,
                    "total_requests": 0,
                    "error_requests": 0,
                    "last_seen_at": None,
                    "last_error_at": None,
                    "paths": {},
                    "latency_samples_ms": deque(maxlen=1200),
                },
            )
            entry["total_requests"] = int(entry.get("total_requests", 0) or 0) + 1
            if int(status_code or 0) >= 400:
                entry["error_requests"] = int(entry.get("error_requests", 0) or 0) + 1
                entry["last_error_at"] = now_iso
            entry["last_seen_at"] = now_iso
            entry["latency_samples_ms"].append(float(max(0.0, duration_ms)))
            paths = entry.get("paths")
            if not isinstance(paths, dict):
                paths = {}
                entry["paths"] = paths
            route_key = f"{str(method or '').upper()} {str(path or '').strip()}"
            route_entry = paths.get(route_key, {"requests": 0, "errors": 0})
            route_entry["requests"] = int(route_entry.get("requests", 0) or 0) + 1
            if int(status_code or 0) >= 400:
                route_entry["errors"] = int(route_entry.get("errors", 0) or 0) + 1
            paths[route_key] = route_entry

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            out: dict[str, Any] = {}
            for client, raw in self._by_client.items():
                samples = list(raw.get("latency_samples_ms", []))
                avg_latency = (sum(samples) / len(samples)) if samples else 0.0
                p95_latency = 0.0
                if samples:
                    sorted_samples = sorted(samples)
                    idx = min(len(sorted_samples) - 1, max(0, int(round(0.95 * (len(sorted_samples) - 1)))))
                    p95_latency = float(sorted_samples[idx])
                out[client] = {
                    "client": client,
                    "total_requests": int(raw.get("total_requests", 0) or 0),
                    "error_requests": int(raw.get("error_requests", 0) or 0),
                    "last_seen_at": raw.get("last_seen_at"),
                    "last_error_at": raw.get("last_error_at"),
                    "avg_latency_ms": round(float(avg_latency), 2),
                    "p95_latency_ms": round(float(p95_latency), 2),
                    "paths": raw.get("paths", {}),
                }
            return out

    def flush_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        captured_at = datetime.now(timezone.utc)
        with self._lock:
            for client, raw in self._by_client.items():
                total_requests = int(raw.get("total_requests", 0) or 0)
                error_requests = int(raw.get("error_requests", 0) or 0)
                previous = self._last_flush_totals.get(client, {})
                previous_total = int(previous.get("total_requests", 0) or 0)
                previous_errors = int(previous.get("error_requests", 0) or 0)
                delta_requests = max(0, total_requests - previous_total)
                delta_errors = max(0, error_requests - previous_errors)
                if delta_requests <= 0 and delta_errors <= 0:
                    continue

                samples = list(raw.get("latency_samples_ms", []))
                avg_latency = (sum(samples) / len(samples)) if samples else 0.0
                p95_latency = 0.0
                if samples:
                    sorted_samples = sorted(samples)
                    idx = min(len(sorted_samples) - 1, max(0, int(round(0.95 * (len(sorted_samples) - 1)))))
                    p95_latency = float(sorted_samples[idx])

                paths = raw.get("paths")
                if not isinstance(paths, dict):
                    paths = {}
                top_paths: list[dict[str, Any]] = []
                for route, stats in sorted(
                    paths.items(),
                    key=lambda item: int((item[1] or {}).get("requests", 0) or 0),
                    reverse=True,
                )[:24]:
                    entry = stats if isinstance(stats, dict) else {}
                    top_paths.append(
                        {
                            "route": str(route or ""),
                            "requests": int(entry.get("requests", 0) or 0),
                            "errors": int(entry.get("errors", 0) or 0),
                        }
                    )

                rows.append(
                    {
                        "id": str(uuid.uuid4()),
                        "client": str(client or "unknown"),
                        "captured_at": captured_at,
                        "total_requests": total_requests,
                        "error_requests": error_requests,
                        "delta_requests": delta_requests,
                        "delta_errors": delta_errors,
                        "avg_latency_ms": round(float(avg_latency), 4),
                        "p95_latency_ms": round(float(p95_latency), 4),
                        "unique_paths": len(paths),
                        "top_paths_json": json.dumps(top_paths),
                        "last_seen_at": _parse_iso_datetime(raw.get("last_seen_at")),
                        "last_error_at": _parse_iso_datetime(raw.get("last_error_at")),
                    }
                )
                self._last_flush_totals[client] = {
                    "total_requests": total_requests,
                    "error_requests": error_requests,
                }
        return rows


_REQUEST_METRICS = _RequestMetricsStore()


def _client_id_for_rate_limit(request: Request) -> str:
    """
    Return the client identifier for rate limiting.

    X-Forwarded-For and X-Real-IP are only trusted when the direct connection
    IP is in TRUSTED_PROXY_IPS (configured via security.trusted_proxy_ips in
    config.yaml). Without a trusted proxy, the real TCP connection IP is used
    to prevent rate-limit bypass via header spoofing.
    """
    from backend.config import load_config
    direct_ip = str(request.client.host) if request.client else None
    try:
        trusted = set(load_config().get("security", {}).get("trusted_proxy_ips", []))
    except Exception:
        trusted = set()

    if direct_ip and trusted and direct_ip in trusted:
        xff = _extract_forwarded_for_ip(str(request.headers.get("X-Forwarded-For", "") or ""))
        if xff:
            return xff
        x_real_ip = str(request.headers.get("X-Real-IP", "") or "").strip()
        if x_real_ip:
            return x_real_ip

    return direct_ip or "unknown"


def _client_id_for_request_metrics(request: Request) -> str:
    try:
        name = str(getattr(request.state, "mcp_client_name", "") or "").strip().lower()
        if name:
            return name
    except Exception:
        pass
    header_name = str(request.headers.get("X-Mnesis-Client", "")).strip().lower()
    if header_name:
        return header_name
    if request.client and request.client.host:
        return str(request.client.host).strip().lower() or "unknown"
    return "unknown"


def get_request_metrics_snapshot() -> dict[str, Any]:
    return _REQUEST_METRICS.snapshot()


async def flush_request_metrics_to_db() -> dict[str, Any]:
    rows = _REQUEST_METRICS.flush_rows()
    if not rows:
        return {"status": "no-data", "rows_written": 0, "clients": 0}

    try:
        from backend.database.client import get_db
        from backend.memory.write_queue import enqueue_write

        db = get_db()
        if "client_runtime_metrics" not in db.table_names():
            from backend.database.schema import ClientRuntimeMetric

            try:
                db.create_table("client_runtime_metrics", schema=ClientRuntimeMetric)
            except TypeError:
                try:
                    db.create_table("client_runtime_metrics", schema=ClientRuntimeMetric, exist_ok=True)
                except Exception:
                    pass
            except Exception:
                # Table may already exist in race conditions.
                pass

        table = db.open_table("client_runtime_metrics")

        async def _write_op():
            table.add(rows)
            return len(rows)

        written = await enqueue_write(_write_op)
        return {
            "status": "ok",
            "rows_written": int(written or 0),
            "clients": len(rows),
            "captured_at": _utc_now_iso(),
        }
    except Exception as e:
        return {"status": "error", "rows_written": 0, "clients": 0, "error": str(e)}


def _bucket_for_request(request: Request) -> str | None:
    path = request.url.path
    method = request.method.upper()
    if method == "OPTIONS":
        return None
    if path.startswith("/health"):
        return "health"
    if path.startswith("/mcp"):
        return "mcp"
    if path.startswith("/api/v1/snapshot/text"):
        return "snapshot"
    if path.startswith("/api/v1/admin"):
        return "admin"
    if method in MUTATION_METHODS and (path.startswith("/api/v1/") or path.startswith("/api/import/")):
        return "api_mutation"
    return None


class RateLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        request = Request(scope, receive)
        sec = _security_cfg()
        rate_cfg = sec.get("rate_limit", {})
        if not bool(rate_cfg.get("enabled", True)):
            return await self.app(scope, receive, send)

        bucket = _bucket_for_request(request)
        if not bucket:
            return await self.app(scope, receive, send)

        limit = int(rate_cfg.get("buckets", {}).get(bucket, 0) or 0)
        if limit <= 0:
            return await self.app(scope, receive, send)
        window_seconds = int(rate_cfg.get("window_seconds", 60) or 60)
        key = f"{bucket}:{_client_id_for_rate_limit(request)}"
        allowed, retry_after, remaining = _RATE_LIMITER.allow(key, limit, window_seconds)
        if not allowed:
            from fastapi.responses import JSONResponse
            response = JSONResponse(
                status_code=429,
                content={"detail": f"Rate limit exceeded for {bucket} routes."},
                headers={"Retry-After": str(retry_after)},
            )
            return await response(scope, receive, send)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.append((b"x-ratelimit-limit", str(limit).encode("latin1")))
                headers.append((b"x-ratelimit-remaining", str(remaining).encode("latin1")))
            await send(message)

        return await self.app(scope, receive, send_wrapper)


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.append((b"x-content-type-options", b"nosniff"))
                headers.append((b"x-frame-options", b"deny"))
                headers.append((b"referrer-policy", b"no-referrer"))
                headers.append((b"permissions-policy", b"camera=(), microphone=(), geolocation=(), usb=(), payment=()"))
                headers.append((b"content-security-policy",
                    b"default-src 'self'; "
                    b"script-src 'self' 'wasm-unsafe-eval'; "
                    b"style-src 'self' 'unsafe-inline'; "
                    b"img-src 'self' data: blob:; "
                    b"connect-src 'self' http://127.0.0.1:* ws://127.0.0.1:*; "
                    b"font-src 'self' data:"
                ))
                headers.append((b"x-mnesis-security", b"hardened"))
            await send(message)

        return await self.app(scope, receive, send_wrapper)


class RequestMetricsMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        if not path.startswith("/mcp"):
            return await self.app(scope, receive, send)

        method = scope.get("method", "").upper()
        if path.startswith("/mcp/sse"):
            # Don't track SSE stream duration tightly here
            return await self.app(scope, receive, send)

        request = Request(scope, receive)
        client = _client_id_for_request_metrics(request)
        started = time.perf_counter()
        status_code = [500]

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_code[0] = message.get("status", 500)
            await send(message)

        try:
            response = await self.app(scope, receive, send_wrapper)
            duration_ms = (time.perf_counter() - started) * 1000.0
            _REQUEST_METRICS.record(
                client=client,
                path=path,
                method=method,
                status_code=status_code[0],
                duration_ms=duration_ms,
            )
            return response
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000.0
            _REQUEST_METRICS.record(
                client=client,
                path=path,
                method=method,
                status_code=500,
                duration_ms=duration_ms,
            )
            raise
