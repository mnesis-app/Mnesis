from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.database.client import get_db
from backend.database.schema import Conversation, Message
from backend.memory.write_queue import enqueue_write

logger = logging.getLogger(__name__)

_AUTO_TAG = "source:mcp"
_AUTO_TAG_V2 = "source:mcp:auto-capture:v1"
_TRANSCRIPT_TAG = "source:transcript:ingest:v1"


def _escape_sql(value: str) -> str:
    return str(value).replace("'", "''")


def _truncate(value: str, max_chars: int) -> str:
    raw = str(value or "").strip()
    if len(raw) <= max_chars:
        return raw
    return raw[: max(0, max_chars - 3)].rstrip() + "..."


def _json_preview(payload: Any, max_chars: int = 2000) -> str:
    try:
        rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    except Exception:
        rendered = str(payload or "")
    return _truncate(rendered, max_chars=max_chars)


def _safe_source(source_hint: str, tool_name: str, arguments: dict[str, Any]) -> str:
    value = str(arguments.get("source_llm") or "").strip()
    if value:
        return value[:80]
    hint = str(source_hint or "").strip()
    if hint:
        return hint[:80]
    if tool_name:
        return "mcp"
    return "unknown"


def _message_id(session_id: str, request_id: Any, tool_name: str) -> str:
    if request_id is None:
        return str(uuid.uuid4())
    key = f"{session_id}|{request_id}|{tool_name}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


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
    if isinstance(value, str) and value.strip():
        raw = value.strip()
        try:
            return datetime.fromtimestamp(float(raw), tz=timezone.utc)
        except Exception:
            pass
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            pass
    return datetime.now(timezone.utc)


def _normalize_role(value: Any) -> str:
    role = str(value or "").strip().lower()
    if role in {"assistant", "system", "tool"}:
        return role
    return "user"


def _stable_message_id(
    *,
    conversation_id: str,
    explicit_id: Any,
    role: str,
    content: str,
    timestamp: datetime,
) -> str:
    if explicit_id:
        return str(explicit_id)
    key = f"{conversation_id}|{role}|{timestamp.isoformat()}|{content[:260]}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


def _message_fingerprint(role: str, content: str, timestamp: datetime) -> str:
    return f"{role}|{content}|{timestamp.isoformat()}"


async def append_mcp_tool_call(
    *,
    session_id: str,
    request_id: Any,
    tool_name: str,
    arguments: dict[str, Any],
    source_hint: str = "mcp",
):
    sid = str(session_id or "").strip()
    name = str(tool_name or "").strip()
    if not sid or not name:
        return

    args = arguments if isinstance(arguments, dict) else {}
    source_llm = _safe_source(source_hint=source_hint, tool_name=name, arguments=args)
    msg_id = _message_id(sid, request_id, name)
    now = datetime.now(timezone.utc)
    args_preview = _json_preview(args, max_chars=2000)
    content = _truncate(f"tool:{name} args={args_preview}", max_chars=2600)
    title = _truncate(f"MCP · {source_llm}", max_chars=140)

    async def _write_op():
        db = get_db()
        if "conversations" not in db.table_names() or "messages" not in db.table_names():
            return {"status": "skipped", "reason": "missing_tables"}

        conv_tbl = db.open_table("conversations")
        msg_tbl = db.open_table("messages")
        escaped_sid = _escape_sql(sid)
        escaped_mid = _escape_sql(msg_id)

        msg_rows = msg_tbl.search().where(f"id = '{escaped_mid}'").limit(1).to_list()
        if msg_rows:
            return {"status": "deduplicated"}

        conv_rows = conv_tbl.search().where(f"id = '{escaped_sid}'").limit(1).to_list()
        if not conv_rows:
            conv_tbl.add(
                [
                    Conversation(
                        id=sid,
                        title=title,
                        source_llm=source_llm,
                        started_at=now,
                        ended_at=now,
                        message_count=0,
                        memory_ids=[],
                        tags=[_AUTO_TAG, _AUTO_TAG_V2],
                        summary="Auto-captured MCP session",
                        status="archived",
                        raw_file_hash="",
                        imported_at=now,
                    )
                ]
            )
            conv_rows = conv_tbl.search().where(f"id = '{escaped_sid}'").limit(1).to_list()

        current = conv_rows[0]
        message_count = max(0, int(current.get("message_count") or 0))
        tags = [str(t) for t in (current.get("tags") or []) if t]
        lowered = {t.lower() for t in tags}
        if _AUTO_TAG not in lowered:
            tags.append(_AUTO_TAG)
        if _AUTO_TAG_V2 not in lowered:
            tags.append(_AUTO_TAG_V2)

        msg_tbl.add(
            [
                Message(
                    id=msg_id,
                    conversation_id=sid,
                    role="assistant",
                    content=content,
                    timestamp=now,
                    vector=None,
                )
            ]
        )

        conv_tbl.update(
            where=f"id = '{escaped_sid}'",
            values={
                "message_count": message_count + 1,
                "ended_at": now,
                "tags": tags,
                "source_llm": source_llm,
            },
        )
        return {"status": "captured"}

    try:
        await enqueue_write(_write_op)
    except Exception as e:
        logger.warning(f"MCP conversation capture failed: {e}")


async def capture_mcp_request_payload(
    *,
    payload: Any,
    session_id: str,
    source_hint: str,
):
    sid = str(session_id or "").strip()
    if not sid:
        return

    entries: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        entries = [payload]
    elif isinstance(payload, list):
        entries = [item for item in payload if isinstance(item, dict)]
    else:
        return

    for entry in entries:
        method = str(entry.get("method") or "").strip()
        if method != "tools/call":
            continue
        params = entry.get("params")
        if not isinstance(params, dict):
            continue
        tool_name = str(params.get("name") or params.get("tool_name") or "").strip()
        if not tool_name:
            continue
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        await append_mcp_tool_call(
            session_id=sid,
            request_id=entry.get("id"),
            tool_name=tool_name,
            arguments=arguments,
            source_hint=source_hint,
        )


async def append_exchange_messages(
    *,
    conversation_id: str,
    user_message: str,
    assistant_summary: str,
    source_llm: str,
) -> None:
    """
    Store one user/assistant exchange as two Message rows inside the conversation.

    Unlike append_mcp_tool_call which records raw tool invocations, this captures
    the actual human question and assistant response — the information the user
    cares about when browsing conversation history.

    If the conversation doesn't exist yet it is created with the auto-capture tag
    so it can still be paired with any tool-call entries from the same session.
    """
    conv_id = str(conversation_id or "").strip()
    user_text = _truncate(str(user_message or "").strip(), max_chars=3000)
    asst_text = _truncate(str(assistant_summary or "").strip(), max_chars=3000)
    if not conv_id or not (user_text or asst_text):
        return

    src = _truncate(str(source_llm or "mcp").strip(), max_chars=80) or "mcp"
    now = datetime.now(timezone.utc)

    async def _write_op():
        db = get_db()
        if "conversations" not in db.table_names() or "messages" not in db.table_names():
            return {"status": "skipped", "reason": "missing_tables"}

        conv_tbl = db.open_table("conversations")
        msg_tbl = db.open_table("messages")
        escaped_conv_id = _escape_sql(conv_id)

        # Ensure the conversation row exists.
        conv_rows = conv_tbl.search().where(f"id = '{escaped_conv_id}'").limit(1).to_list()
        if not conv_rows:
            conv_tbl.add([
                Conversation(
                    id=conv_id,
                    title=_truncate(f"Exchange with {src}", max_chars=140),
                    source_llm=src,
                    started_at=now,
                    ended_at=now,
                    message_count=0,
                    memory_ids=[],
                    tags=[_AUTO_TAG, _AUTO_TAG_V2],
                    summary="",
                    status="archived",
                    raw_file_hash="",
                    imported_at=now,
                )
            ])
            conv_rows = conv_tbl.search().where(f"id = '{escaped_conv_id}'").limit(1).to_list()

        current = conv_rows[0] if conv_rows else {}
        message_count = max(0, int(current.get("message_count") or 0))

        # Deduplicate by a stable ID derived from content + timestamp truncated to the minute.
        minute_key = now.strftime("%Y%m%dT%H%M")
        user_mid = _message_id(conv_id, f"user:{minute_key}", user_text[:80])
        asst_mid = _message_id(conv_id, f"asst:{minute_key}", asst_text[:80])
        existing_ids = {
            str(r.get("id") or "")
            for r in msg_tbl.search().where(
                f"conversation_id = '{escaped_conv_id}'"
            ).limit(2000).to_list()
        }

        new_msgs = []
        if user_text and user_mid not in existing_ids:
            new_msgs.append(Message(
                id=user_mid,
                conversation_id=conv_id,
                role="user",
                content=user_text,
                timestamp=now,
                vector=None,
            ))
        if asst_text and asst_mid not in existing_ids:
            new_msgs.append(Message(
                id=asst_mid,
                conversation_id=conv_id,
                role="assistant",
                content=asst_text,
                timestamp=now,
                vector=None,
            ))

        if new_msgs:
            msg_tbl.add(new_msgs)
            conv_tbl.update(
                where=f"id = '{escaped_conv_id}'",
                values={
                    "message_count": message_count + len(new_msgs),
                    "ended_at": now,
                    "source_llm": src,
                },
            )
        return {"status": "captured", "messages_added": len(new_msgs)}

    try:
        await enqueue_write(_write_op)
    except Exception as e:
        logger.warning(f"append_exchange_messages failed: {e}")


async def ingest_conversation_transcript(
    *,
    conversation_id: str,
    title: str,
    source_llm: str,
    messages: list[dict[str, Any]],
    tags: list[str] | None = None,
    summary: str = "",
    started_at: Any = None,
    ended_at: Any = None,
    status: str = "archived",
) -> dict:
    conv_id = str(conversation_id or "").strip()
    if not conv_id:
        return {"status": "error", "action": "missing_conversation_id"}

    normalized_messages = [m for m in (messages or []) if isinstance(m, dict)]
    if not normalized_messages:
        return {"status": "error", "action": "missing_messages"}

    safe_title = _truncate(str(title or "Untitled conversation"), max_chars=140)
    safe_source = _truncate(str(source_llm or "imported"), max_chars=80)
    safe_summary = _truncate(str(summary or ""), max_chars=3000)
    safe_status = str(status or "archived").strip().lower() or "archived"
    if safe_status not in {"active", "archived", "deleted"}:
        safe_status = "archived"

    started = _to_dt(started_at)
    ended = _to_dt(ended_at) if ended_at is not None else started

    input_tags = [str(t).strip() for t in (tags or []) if str(t).strip()]
    lowered_input_tags = {t.lower() for t in input_tags}
    if _TRANSCRIPT_TAG not in lowered_input_tags:
        input_tags.append(_TRANSCRIPT_TAG)

    async def _write_op():
        db = get_db()
        if "conversations" not in db.table_names() or "messages" not in db.table_names():
            return {"status": "error", "action": "missing_tables"}

        conv_tbl = db.open_table("conversations")
        msg_tbl = db.open_table("messages")
        escaped_conv_id = _escape_sql(conv_id)
        conv_rows = conv_tbl.search().where(f"id = '{escaped_conv_id}'").limit(1).to_list()

        now = datetime.now(timezone.utc)
        if not conv_rows:
            conv_tbl.add(
                [
                    Conversation(
                        id=conv_id,
                        title=safe_title,
                        source_llm=safe_source,
                        started_at=started,
                        ended_at=ended,
                        message_count=0,
                        memory_ids=[],
                        tags=input_tags,
                        summary=safe_summary,
                        status=safe_status,
                        raw_file_hash="",
                        imported_at=now,
                    )
                ]
            )
            conv_rows = conv_tbl.search().where(f"id = '{escaped_conv_id}'").limit(1).to_list()

        conv = conv_rows[0]
        existing_messages = msg_tbl.search().where(f"conversation_id = '{escaped_conv_id}'").limit(200000).to_list()
        existing_ids = {str(row.get("id") or "") for row in existing_messages if row.get("id")}
        existing_fps = {
            _message_fingerprint(
                _normalize_role(row.get("role")),
                str(row.get("content") or "").strip(),
                _to_dt(row.get("timestamp")),
            )
            for row in existing_messages
            if str(row.get("content") or "").strip()
        }

        to_add: list[Message] = []
        inserted = 0
        deduplicated = 0
        skipped = 0
        message_max_dt = _to_dt(conv.get("ended_at") or conv.get("started_at") or now)
        message_min_dt = _to_dt(conv.get("started_at") or started)

        for raw in normalized_messages:
            content = str(raw.get("content") or raw.get("text") or "").strip()
            if not content:
                skipped += 1
                continue
            role = _normalize_role(raw.get("role") or raw.get("sender"))
            timestamp = _to_dt(raw.get("timestamp") or raw.get("created_at"))
            msg_id = _stable_message_id(
                conversation_id=conv_id,
                explicit_id=raw.get("id"),
                role=role,
                content=content,
                timestamp=timestamp,
            )
            fp = _message_fingerprint(role, content, timestamp)
            if msg_id in existing_ids or fp in existing_fps:
                deduplicated += 1
                continue

            to_add.append(
                Message(
                    id=msg_id,
                    conversation_id=conv_id,
                    role=role,
                    content=content,
                    timestamp=timestamp,
                    vector=None,
                )
            )
            existing_ids.add(msg_id)
            existing_fps.add(fp)
            inserted += 1
            if timestamp > message_max_dt:
                message_max_dt = timestamp
            if timestamp < message_min_dt:
                message_min_dt = timestamp

        if to_add:
            msg_tbl.add(to_add)

        existing_tags = [str(t) for t in (conv.get("tags") or []) if t]
        merged_tags = []
        seen_tags = set()
        for tag in existing_tags + input_tags:
            lowered = str(tag or "").strip().lower()
            if not lowered or lowered in seen_tags:
                continue
            seen_tags.add(lowered)
            merged_tags.append(str(tag).strip())

        existing_count = max(int(conv.get("message_count") or 0), len(existing_messages))
        updated_count = existing_count + inserted
        started_final = min(_to_dt(conv.get("started_at") or message_min_dt), message_min_dt, started)
        ended_final = max(_to_dt(conv.get("ended_at") or message_max_dt), message_max_dt, ended)
        summary_final = safe_summary or str(conv.get("summary") or "")

        conv_tbl.update(
            where=f"id = '{escaped_conv_id}'",
            values={
                "title": safe_title or str(conv.get("title") or "Untitled conversation"),
                "source_llm": safe_source or str(conv.get("source_llm") or "imported"),
                "message_count": updated_count,
                "tags": merged_tags,
                "summary": summary_final,
                "status": "active" if safe_status == "active" else str(conv.get("status") or safe_status),
                "started_at": started_final,
                "ended_at": ended_final,
            },
        )

        return {
            "status": "ok",
            "action": "ingested",
            "conversation_id": conv_id,
            "inserted_messages": inserted,
            "deduplicated_messages": deduplicated,
            "skipped_messages": skipped,
            "message_count": updated_count,
        }

    try:
        return await enqueue_write(_write_op)
    except Exception as e:
        logger.warning(f"Conversation transcript ingestion failed: {e}")
        return {"status": "error", "action": "ingest_failed", "message": str(e)}
