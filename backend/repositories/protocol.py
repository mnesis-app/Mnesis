"""
MemoryRepository protocol
=========================
Defines the interface for all memory storage backends.

Implementations:
- LanceDBMemoryRepository  (local desktop, default)
- Future: SQLiteMemoryRepository, PostgresMemoryRepository (hosted)
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class MemoryRepository(Protocol):
    """Abstract interface for memory CRUD operations.

    All methods are async so implementations can wrap both sync (LanceDB)
    and async (Postgres, SQLite via aiosqlite) backends uniformly.
    """

    async def get(self, memory_id: str) -> dict | None:
        """Return a single non-archived memory by ID, or None if not found."""
        ...

    async def list(
        self,
        *,
        where: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """Return memories matching an optional SQL-style where clause."""
        ...

    async def search(self, query: str, limit: int = 50) -> list[dict]:
        """Lexical search over active memories by content."""
        ...

    async def create(self, **kwargs: Any) -> dict:
        """Create a new memory and return the result dict."""
        ...

    async def update(self, memory_id: str, **kwargs: Any) -> dict:
        """Update memory content/source and return the result dict."""
        ...

    async def delete(self, memory_id: str) -> dict:
        """Soft-delete (archive) a memory and return the result dict."""
        ...
