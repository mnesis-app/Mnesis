#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from backend.memory import conversation_mining, core
from backend.routers import admin as admin_router


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run() -> int:
    # 1) Generic-definition memories must be filtered consistently.
    generic_fact = (
        "The user says C++ is a high-performance, compiled language that provides direct access "
        "to hardware resources such as memory and I/O operations."
    )
    personal_signal = "The user uses C++ daily for embedded systems at work."

    _assert(
        conversation_mining._looks_generic_non_memory(generic_fact) is True,
        "conversation_mining generic guardrail regression",
    )
    _assert(
        core._looks_generic_non_memory(generic_fact) is True,
        "core generic guardrail regression",
    )
    _assert(
        conversation_mining._looks_generic_non_memory(personal_signal) is False,
        "conversation_mining personal memory false-positive",
    )
    _assert(
        core._looks_generic_non_memory(personal_signal) is False,
        "core personal memory false-positive",
    )

    # 2) Release gates should not block fresh installs with no data.
    gates = admin_router._release_gates(
        security_result={"summary": {"fail": 0}, "score": 100},
        last_analysis_stats={
            "accepted_rate": 0.0,
            "duplicate_rate": 0.0,
            "generic_rate": 0.0,
            "candidates_total": 0,
        },
        client_observability={"summary": {"write_sessions_total": 0, "cross_llm_read_reliability": 0.0}},
    )
    _assert(bool(gates.get("ready_for_v1")) is True, "fresh install should not fail v1 gates")
    blockers = gates.get("blockers", [])
    _assert(isinstance(blockers, list) and len(blockers) == 0, "unexpected blockers for no-data scenario")

    print(json.dumps({"status": "ok", "checks": 2}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)
