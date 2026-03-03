"""
LanceDBMemoryRepository
========================
Implements MemoryRepository on top of LanceDB (the default local backend).

Direct DB reads (get, list, search, update_scores, get_stats) are synchronous
because LanceDB's Python client is synchronous; they are safe to call from async
FastAPI handlers since LanceDB uses mmap I/O (no blocking network).

Write operations (create, update, delete) delegate to backend.memory.core,
which runs them through the serialised write queue.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class LanceDBMemoryRepository:
    """LanceDB-backed implementation of MemoryRepository."""

    def __init__(self, db=None) -> None:
        if db is None:
            from backend.database.client import get_db
            db = get_db()
        self._db = db

    # ── Internal helpers ──────────────────────────────────────────────────────

    def table_exists(self) -> bool:
        return "memories" in self._db.table_names()

    def _open_table(self):
        return self._db.open_table("memories")

    # ── Protocol: query methods ───────────────────────────────────────────────

    async def get(self, memory_id: str) -> dict | None:
        """Return a single non-archived memory by ID, or None."""
        if not self.table_exists():
            return None
        tbl = self._open_table()
        rows = tbl.search().where(f"id = '{memory_id}'").limit(1).to_list()
        if not rows or rows[0].get("status") == "archived":
            return None
        return rows[0]

    async def list(
        self,
        *,
        where: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """Return memories matching the where clause (LanceDB SQL subset)."""
        if not self.table_exists():
            return []
        tbl = self._open_table()
        clause = where if where is not None else "status = 'active'"
        return tbl.search().where(clause).limit(limit).to_list()

    async def search(self, query: str, limit: int = 50) -> list[dict]:
        """Simple lexical search over active memories.

        For semantic/vector search use backend.memory.core.search_memories()
        directly — it requires the embedding model and is async end-to-end.
        """
        if not self.table_exists():
            return []
        tbl = self._open_table()
        scan_limit = min(5000, max(limit * 20, 600))
        rows = tbl.search().where("status = 'active'").limit(scan_limit).to_list()
        q = str(query).strip().lower()
        if q:
            rows = [r for r in rows if q in str(r.get("content") or "").lower()]
        return rows[:limit]

    # ── Protocol: write methods (delegate to core) ────────────────────────────

    async def create(self, **kwargs: Any) -> dict:
        from backend.memory.core import create_memory
        return await create_memory(**kwargs)

    async def update(self, memory_id: str, **kwargs: Any) -> dict:
        from backend.memory.core import update_memory
        return await update_memory(
            memory_id,
            kwargs["content"],
            kwargs.get("source_llm", "manual"),
        )

    async def delete(self, memory_id: str) -> dict:
        from backend.memory.core import delete_memory
        return await delete_memory(memory_id)

    # ── Extra methods (not in Protocol, used by routers) ──────────────────────

    def update_scores(self, memory_id: str, updates: dict) -> None:
        """Direct score update, bypasses write queue (same as pre-repo behaviour)."""
        tbl = self._open_table()
        tbl.update(where=f"id = '{memory_id}'", values=updates)

    def get_stats(self) -> dict:
        if not self.table_exists():
            return {"total_memories": 0, "active": 0}
        tbl = self._open_table()
        rows = tbl.search().where("status != 'archived'").limit(200000).to_list()
        total = len(rows)
        return {"total_memories": total, "active": total}


# ── FastAPI dependency ────────────────────────────────────────────────────────

def get_memory_repo() -> LanceDBMemoryRepository:
    """FastAPI dependency: inject a LanceDBMemoryRepository instance."""
    return LanceDBMemoryRepository()
