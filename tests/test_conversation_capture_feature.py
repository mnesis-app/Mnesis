import asyncio
import re
from copy import deepcopy

from backend.memory import conversation_capture


def _row_to_dict(row):
    if isinstance(row, dict):
        return deepcopy(row)
    if hasattr(row, "model_dump"):
        return deepcopy(row.model_dump())
    if hasattr(row, "dict"):
        return deepcopy(row.dict())
    data = {}
    for key in dir(row):
        if key.startswith("_"):
            continue
        value = getattr(row, key)
        if callable(value):
            continue
        data[key] = value
    return deepcopy(data)


class FakeQuery:
    def __init__(self, rows):
        self._rows = list(rows)

    def where(self, clause):
        clause = str(clause or "")
        match = re.search(r"(id|conversation_id)\s*=\s*'([^']+)'", clause)
        if not match:
            return FakeQuery(self._rows)
        field = match.group(1)
        value = match.group(2)
        return FakeQuery([row for row in self._rows if str(row.get(field) or "") == value])

    def limit(self, n):
        return FakeQuery(self._rows[: int(n)])

    def to_list(self):
        return list(self._rows)


class FakeTable:
    def __init__(self):
        self.rows = []

    def search(self, *_args, **_kwargs):
        return FakeQuery(self.rows)

    def add(self, rows):
        for row in rows:
            self.rows.append(_row_to_dict(row))

    def update(self, where, values):
        match = re.search(r"id\s*=\s*'([^']+)'", str(where or ""))
        if not match:
            return
        target = match.group(1)
        for row in self.rows:
            if str(row.get("id") or "") == target:
                row.update(deepcopy(values or {}))


class FakeDb:
    def __init__(self):
        self.tables = {
            "conversations": FakeTable(),
            "messages": FakeTable(),
        }

    def table_names(self):
        return list(self.tables.keys())

    def open_table(self, name):
        return self.tables[name]


def test_ingest_conversation_transcript_is_incremental(monkeypatch):
    fake_db = FakeDb()
    monkeypatch.setattr(conversation_capture, "get_db", lambda: fake_db)

    async def _run_inline(write_op):
        return await write_op()

    monkeypatch.setattr(conversation_capture, "enqueue_write", _run_inline)

    payload = dict(
        conversation_id="conv-1",
        title="Planning session",
        source_llm="chatgpt",
        messages=[
            {"id": "m1", "role": "user", "content": "We should build HomeBoard for teams.", "timestamp": "2026-02-20T10:00:00+00:00"},
            {"id": "m2", "role": "assistant", "content": "Great idea, let's define the architecture.", "timestamp": "2026-02-20T10:00:20+00:00"},
        ],
        tags=["import:chatgpt"],
        summary="Planning notes",
        started_at="2026-02-20T10:00:00+00:00",
        ended_at="2026-02-20T10:00:20+00:00",
        status="archived",
    )

    first = asyncio.run(conversation_capture.ingest_conversation_transcript(**payload))
    second = asyncio.run(conversation_capture.ingest_conversation_transcript(**payload))

    assert first["status"] == "ok"
    assert first["inserted_messages"] == 2
    assert first["deduplicated_messages"] == 0
    assert second["status"] == "ok"
    assert second["inserted_messages"] == 0
    assert second["deduplicated_messages"] == 2
