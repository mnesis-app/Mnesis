#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class CheckResult:
    name: str
    status: str  # pass | fail | warn | skip
    detail: str


def _run_command(name: str, cmd: list[str]) -> CheckResult:
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except Exception as exc:
        return CheckResult(name=name, status="fail", detail=f"command error: {exc}")
    if completed.returncode == 0:
        return CheckResult(name=name, status="pass", detail="ok")
    stderr = (completed.stderr or "").strip()
    stdout = (completed.stdout or "").strip()
    payload = stderr or stdout or f"exit code {completed.returncode}"
    payload = payload.replace("\n", " ")[:500]
    return CheckResult(name=name, status="fail", detail=payload)


def _http_get_json(url: str, timeout_seconds: float = 2.0) -> dict[str, Any]:
    req = urllib.request.Request(url=url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        body = resp.read().decode("utf-8")
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("unexpected non-object JSON response")
    return data


def _check_backend_release_gates(base_url: str, require_api: bool) -> CheckResult:
    base = base_url.rstrip("/")
    health_url = f"{base}/health"
    status_url = f"{base}/api/v1/admin/background/status?{urllib.parse.urlencode({'include_heavy': 'true'})}"
    try:
        _http_get_json(health_url, timeout_seconds=2.0)
        status = _http_get_json(status_url, timeout_seconds=4.0)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        if require_api:
            return CheckResult(
                name="backend live gates",
                status="fail",
                detail=f"backend unreachable at {base}: {exc}",
            )
        return CheckResult(
            name="backend live gates",
            status="skip",
            detail=f"backend unreachable at {base} (skipped; run backend for live gates)",
        )

    gates = status.get("release_gates", {}) if isinstance(status, dict) else {}
    ready = bool(gates.get("ready_for_v1"))
    blockers = gates.get("blockers", [])
    if ready:
        return CheckResult(name="backend live gates", status="pass", detail="A/B/C gates passing")

    blocker_text = ", ".join(str(b) for b in blockers) if isinstance(blockers, list) and blockers else "unknown"
    return CheckResult(
        name="backend live gates",
        status="fail",
        detail=f"release blockers: {blocker_text}",
    )


def _run() -> int:
    parser = argparse.ArgumentParser(
        description="Run Mnesis v1 public readiness checks (build, tests, and live release gates)."
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:7860",
        help="Backend base URL for live gates (default: http://127.0.0.1:7860)",
    )
    parser.add_argument(
        "--require-api",
        action="store_true",
        help="Fail if backend live gate endpoint is unreachable.",
    )
    args = parser.parse_args()

    results: list[CheckResult] = []

    results.append(_run_command("backend compile", [sys.executable, "-m", "compileall", "-q", "backend"]))
    results.append(_run_command("frontend build", ["npm", "run", "build:ui"]))
    smoke_script = "scripts/backend_smoke_checks.py"
    if os.path.exists(smoke_script):
        results.append(_run_command("backend smoke checks", [sys.executable, smoke_script]))
    else:
        results.append(CheckResult(name="backend smoke checks", status="skip", detail="scripts/backend_smoke_checks.py not found (skipped)"))

    has_pytest = importlib.util.find_spec("pytest") is not None
    if not has_pytest:
        results.append(
            CheckResult(
                name="backend tests",
                status="warn",
                detail="pytest not installed (full backend test suite skipped)",
            )
        )
    else:
        results.append(_run_command("backend tests", [sys.executable, "-m", "pytest", "-q", "tests"]))

    results.append(_check_backend_release_gates(args.base_url, require_api=bool(args.require_api)))

    status_rank = {"pass": 0, "skip": 1, "warn": 2, "fail": 3}
    worst = 0
    for row in results:
        worst = max(worst, status_rank.get(row.status, 3))

    print("Mnesis v1 public readiness")
    print("==========================")
    for row in results:
        label = row.status.upper().ljust(4)
        print(f"[{label}] {row.name}: {row.detail}")

    if worst >= 3:
        print("\nRESULT: NOT READY")
        return 1
    if worst == 2:
        print("\nRESULT: READY WITH WARNINGS")
        return 0
    print("\nRESULT: READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
