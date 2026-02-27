from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from numbers import Number
import os
import re
import shutil
from typing import Any, Optional
import uuid

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from backend.database.client import get_db
from backend.database.schema import Conversation, Message
from backend.memory.core import create_memory
from backend.memory.importers.chatgpt import ChatGPTImporter
from backend.memory.importers.claude import CLAUDE_CATEGORY_MAP, ClaudeImporter
from backend.memory.importers.gemini import GeminiImporter
from backend.memory.write_queue import enqueue_write

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/import", tags=["import"])

_previews: dict[str, dict[str, Any]] = {}
_chatgpt_previews: dict[str, dict[str, Any]] = {}
_GENERIC_FACT_PATTERN = re.compile(
    r"\b("
    r"is\s+(an?|the)\s+(?:[a-z0-9][a-z0-9_\-]*\s+){0,4}(open|standard|protocol|framework|library|language|concept|method|tool|model)\b|"
    r"refers to\b|means\b|defined as\b|"
    r"est\s+(un|une|le|la)\s+(?:[a-z0-9à-ÿ][a-z0-9à-ÿ_\-]*\s+){0,4}(protocole|standard|framework|biblioth[eè]que|langage|concept|m[eé]thode|outil|mod[eè]le)\b|"
    r"fait r[eé]f[eé]rence [aà]\b|d[eé]signe\b"
    r")",
    flags=re.IGNORECASE,
)
_PERSONAL_MEMORY_HINT_PATTERN = re.compile(
    r"\b("
    r"the user|user's|l'utilisateur|utilisateur|"
    r"i\b|i'm|my|mine|me|je\b|j'|moi|mon|ma|mes|"
    r"prefer|like|love|hate|always|never|use|works on|working on|build|goal|plan|"
    r"pr[eé]f[eè]re|aime|d[eé]teste|utilise|travaille sur|d[eé]veloppe|objectif|projet|"
    r"name|nom|role|r[oô]le|job|m[eé]tier|team|[eé]quipe|relationship|relation"
    r")\b",
    flags=re.IGNORECASE,
)


def _ensure_data_dir() -> str:
    data_dir = "data"
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def _parse_datetime(value: Any) -> datetime:
    parsed = _parse_datetime_optional(value)
    if parsed is not None:
        return parsed
    return datetime.fromtimestamp(0, tz=timezone.utc)


def _parse_datetime_optional(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, Number):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception:
            return None
    if isinstance(value, str) and value:
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception:
            pass
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            return None
    return None


def _datetime_fingerprint(value: Any) -> str:
    parsed = _parse_datetime_optional(value)
    if parsed is None:
        return "__missing_timestamp__"
    return parsed.isoformat()


def _internal_error(message: str, exc: Exception | None = None) -> HTTPException:
    if exc is not None:
        logger.exception(message)
    return HTTPException(status_code=500, detail=message)


def _is_relevant_chatgpt_memory(content: str) -> bool:
    text = content.strip()
    if len(text) < 20:
        return False
    if not any(ch.isalpha() for ch in text):
        return False
    words = re.findall(r"\b[\w\-']+\b", text, flags=re.UNICODE)
    if len(words) < 4:
        return False
    lowered = text.lower()
    has_personal_signal = bool(_PERSONAL_MEMORY_HINT_PATTERN.search(lowered))
    if _GENERIC_FACT_PATTERN.search(lowered) and not has_personal_signal:
        return False
    if not has_personal_signal:
        # Avoid importing encyclopedic facts as personal memories.
        return False
    return True


def _normalize_chatgpt_memories(raw_items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    normalized: list[dict[str, Any]] = []
    ignored = 0

    for item in raw_items:
        content = (item.get("content") or "").strip()
        if not _is_relevant_chatgpt_memory(content):
            ignored += 1
            continue
        category = item.get("original_category") or "preferences"
        level = item.get("original_level") or item.get("level") or "semantic"
        normalized.append(
            {
                "content": content,
                "source": "chatgpt",
                "category": category,
                "level": level,
                "confidence_score": 0.9,
                "original_created_at": item.get("original_created_at"),
            }
        )

    return normalized, ignored


async def _import_chatgpt_memories(memories: list[dict[str, Any]]) -> dict[str, int]:
    imported = 0
    deduplicated = 0
    ignored = 0

    for memory in memories:
        result = await create_memory(
            content=memory["content"],
            category=memory["category"],
            level=memory["level"],
            source_llm="chatgpt",
            confidence_score=memory.get("confidence_score", 0.9),
            tags=["import:chatgpt"],
            created_at=memory.get("original_created_at"),
            event_date=memory.get("original_created_at"),
        )
        action = result.get("action")
        if action == "created":
            imported += 1
        elif action in ("merged", "skipped"):
            deduplicated += 1
        else:
            ignored += 1

    return {"imported": imported, "deduplicated": deduplicated, "ignored": ignored}


def _extract_importer_conversations(importer: ChatGPTImporter, file_path: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    conversations: list[dict[str, Any]] = []
    messages: list[dict[str, Any]] = []

    for conv in importer.parse_conversations(file_path):
        if not isinstance(conv, dict):
            continue

        conv_id = str(conv.get("id") or uuid.uuid4())
        chat_messages = conv.get("chat_messages") or []
        if not isinstance(chat_messages, list):
            chat_messages = []

        conversation_payload = dict(conv)
        conversation_payload["id"] = conv_id
        if "message_count" not in conversation_payload:
            conversation_payload["message_count"] = len(chat_messages)
        conversations.append(conversation_payload)

        for msg in chat_messages:
            if not isinstance(msg, dict):
                continue
            message_payload = dict(msg)
            message_payload["conversation_id"] = message_payload.get("conversation_id") or conv_id
            messages.append(message_payload)

    return conversations, messages


async def _import_conversations_messages(
    raw_conversations: list[dict[str, Any]],
    raw_messages: list[dict[str, Any]],
) -> dict[str, int]:
    if not raw_conversations and not raw_messages:
        return {
            "conversations": 0,
            "messages": 0,
            "deduplicated_conversations": 0,
            "deduplicated_messages": 0,
            "skipped_conversations": 0,
            "skipped_messages": 0,
        }

    async def _write_op():
        db = get_db()
        now = datetime.now(timezone.utc)
        conversations_added = 0
        messages_added = 0
        deduplicated_conversations = 0
        deduplicated_messages = 0
        skipped_conversations = 0
        skipped_messages = 0
        conversation_id_aliases: dict[str, str] = {}

        def _chunks(rows: list[Any], size: int = 500):
            for i in range(0, len(rows), size):
                yield rows[i : i + size]

        if raw_conversations and "conversations" not in db.table_names():
            try:
                db.create_table("conversations", schema=Conversation)
            except Exception as e:
                if "already exists" not in str(e).lower():
                    logger.warning(f"Unable to create conversations table before import: {e}")

        if raw_messages and "messages" not in db.table_names():
            try:
                db.create_table("messages", schema=Message)
            except Exception as e:
                if "already exists" not in str(e).lower():
                    logger.warning(f"Unable to create messages table before import: {e}")

        if raw_conversations and "conversations" in db.table_names():
            conv_tbl = db.open_table("conversations")
            existing_conversation_rows = conv_tbl.search().limit(500000).to_list()

            def _conversation_fingerprint(row: dict[str, Any]) -> tuple[str, str, str, int]:
                return (
                    str(row.get("title") or "").strip().lower(),
                    _datetime_fingerprint(row.get("started_at") or row.get("create_time")),
                    str(row.get("source_llm") or "imported").strip().lower(),
                    max(0, int(row.get("message_count", 0) or 0)),
                )

            existing_conversation_ids = {
                str(row.get("id"))
                for row in existing_conversation_rows
                if row.get("id")
            }
            existing_conversation_fp_to_id = {
                _conversation_fingerprint(row): str(row.get("id") or "")
                for row in existing_conversation_rows
                if row.get("id")
            }
            existing_conversation_fingerprints = {
                _conversation_fingerprint(row)
                for row in existing_conversation_rows
            }
            seen_conversation_ids: set[str] = set()
            seen_conversation_fingerprints: set[tuple[str, str, str, int]] = set()
            seen_conversation_fp_to_id: dict[tuple[str, str, str, int], str] = {}
            conv_objects = []
            for conv in raw_conversations:
                try:
                    conv_id = str(conv.get("id") or uuid.uuid4())
                    conv_fp = _conversation_fingerprint(conv)
                    if conv_id in existing_conversation_ids:
                        conversation_id_aliases[conv_id] = conv_id
                        deduplicated_conversations += 1
                        continue
                    if conv_id in seen_conversation_ids:
                        conversation_id_aliases[conv_id] = conv_id
                        deduplicated_conversations += 1
                        continue
                    if conv_fp in existing_conversation_fingerprints:
                        mapped = existing_conversation_fp_to_id.get(conv_fp)
                        if mapped:
                            conversation_id_aliases[conv_id] = mapped
                        deduplicated_conversations += 1
                        continue
                    if conv_fp in seen_conversation_fingerprints:
                        mapped = seen_conversation_fp_to_id.get(conv_fp)
                        if mapped:
                            conversation_id_aliases[conv_id] = mapped
                        deduplicated_conversations += 1
                        continue
                    seen_conversation_ids.add(conv_id)
                    seen_conversation_fingerprints.add(conv_fp)
                    seen_conversation_fp_to_id[conv_fp] = conv_id
                    conversation_id_aliases[conv_id] = conv_id
                    started_at = (
                        _parse_datetime_optional(conv.get("started_at"))
                        or _parse_datetime_optional(conv.get("create_time"))
                        or now
                    )
                    conv_objects.append(
                        Conversation(
                            id=conv_id,
                            title=str(conv.get("title") or "Untitled"),
                            source_llm=str(conv.get("source_llm") or "imported"),
                            started_at=started_at,
                            ended_at=_parse_datetime(conv.get("updated_at")) if conv.get("updated_at") else None,
                            message_count=max(0, int(conv.get("message_count", 0) or 0)),
                            memory_ids=[],
                            tags=[],
                            summary=str(conv.get("summary") or ""),
                            status="archived",
                            raw_file_hash=str(conv.get("raw_file_hash") or ""),
                            imported_at=now,
                        )
                    )
                except Exception:
                    skipped_conversations += 1
            if conv_objects:
                for batch in _chunks(conv_objects, size=500):
                    try:
                        conv_tbl.add(batch)
                        conversations_added += len(batch)
                        for row in batch:
                            row_id = getattr(row, "id", None)
                            if row_id:
                                existing_conversation_ids.add(str(row_id))
                                conversation_id_aliases[str(row_id)] = str(row_id)
                            existing_conversation_fingerprints.add(
                                (
                                    str(getattr(row, "title", "")).strip().lower(),
                                    _datetime_fingerprint(getattr(row, "started_at", None)),
                                    str(getattr(row, "source_llm", "imported")).strip().lower(),
                                    max(0, int(getattr(row, "message_count", 0) or 0)),
                                )
                            )
                    except Exception:
                        # Fallback: isolate invalid rows inside the batch.
                        for row in batch:
                            try:
                                conv_tbl.add([row])
                                conversations_added += 1
                                row_id = getattr(row, "id", None)
                                if row_id:
                                    existing_conversation_ids.add(str(row_id))
                                    conversation_id_aliases[str(row_id)] = str(row_id)
                                existing_conversation_fingerprints.add(
                                    (
                                        str(getattr(row, "title", "")).strip().lower(),
                                        _datetime_fingerprint(getattr(row, "started_at", None)),
                                        str(getattr(row, "source_llm", "imported")).strip().lower(),
                                        max(0, int(getattr(row, "message_count", 0) or 0)),
                                    )
                                )
                            except Exception:
                                skipped_conversations += 1

        if raw_messages and "messages" in db.table_names():
            msg_tbl = db.open_table("messages")
            existing_message_rows = msg_tbl.search().limit(1000000).to_list()

            def _message_fingerprint(row: dict[str, Any]) -> tuple[str, str, str, str]:
                return (
                    str(row.get("conversation_id") or "").strip(),
                    str(row.get("role", row.get("sender", "user"))).strip().lower(),
                    str(row.get("content", row.get("text", ""))).strip(),
                    _datetime_fingerprint(row.get("timestamp") or row.get("created_at") or row.get("create_time")),
                )

            existing_message_ids = {
                str(row.get("id"))
                for row in existing_message_rows
                if row.get("id")
            }
            existing_message_fingerprints = {
                _message_fingerprint(row)
                for row in existing_message_rows
                if str(row.get("content", row.get("text", ""))).strip()
            }
            seen_message_ids: set[str] = set()
            seen_message_fingerprints: set[tuple[str, str, str]] = set()
            msg_objects = []
            for msg in raw_messages:
                try:
                    conversation_id = str(msg.get("conversation_id") or "").strip()
                    if not conversation_id:
                        skipped_messages += 1
                        continue
                    conversation_id = conversation_id_aliases.get(conversation_id, conversation_id)
                    content = msg.get("text", msg.get("content", ""))
                    if not content:
                        skipped_messages += 1
                        continue
                    msg_id = str(msg.get("id") or uuid.uuid4())
                    msg_for_fp = dict(msg)
                    msg_for_fp["conversation_id"] = conversation_id
                    msg_fp = _message_fingerprint(msg_for_fp)
                    if (
                        msg_id in existing_message_ids
                        or msg_id in seen_message_ids
                        or msg_fp in existing_message_fingerprints
                        or msg_fp in seen_message_fingerprints
                    ):
                        deduplicated_messages += 1
                        continue
                    seen_message_ids.add(msg_id)
                    seen_message_fingerprints.add(msg_fp)
                    msg_ts = (
                        _parse_datetime_optional(msg.get("created_at") or msg.get("timestamp") or msg.get("create_time"))
                        or now
                    )
                    msg_objects.append(
                        Message(
                            id=msg_id,
                            conversation_id=str(conversation_id),
                            role=str(msg.get("sender", msg.get("role", "user"))),
                            content=str(content),
                            timestamp=msg_ts,
                            vector=None,
                        )
                    )
                except Exception:
                    skipped_messages += 1
            if msg_objects:
                for batch in _chunks(msg_objects, size=1000):
                    try:
                        msg_tbl.add(batch)
                        messages_added += len(batch)
                        for row in batch:
                            row_id = getattr(row, "id", None)
                            if row_id:
                                existing_message_ids.add(str(row_id))
                            existing_message_fingerprints.add(
                                (
                                    str(getattr(row, "conversation_id", "")).strip(),
                                    str(getattr(row, "role", "user")).strip().lower(),
                                    str(getattr(row, "content", "")).strip(),
                                    _datetime_fingerprint(getattr(row, "timestamp", None)),
                                )
                            )
                    except Exception:
                        for row in batch:
                            try:
                                msg_tbl.add([row])
                                messages_added += 1
                                row_id = getattr(row, "id", None)
                                if row_id:
                                    existing_message_ids.add(str(row_id))
                                existing_message_fingerprints.add(
                                    (
                                        str(getattr(row, "conversation_id", "")).strip(),
                                        str(getattr(row, "role", "user")).strip().lower(),
                                        str(getattr(row, "content", "")).strip(),
                                        _datetime_fingerprint(getattr(row, "timestamp", None)),
                                    )
                                )
                            except Exception:
                                skipped_messages += 1

        return {
            "conversations": conversations_added,
            "messages": messages_added,
            "deduplicated_conversations": deduplicated_conversations,
            "deduplicated_messages": deduplicated_messages,
            "skipped_conversations": skipped_conversations,
            "skipped_messages": skipped_messages,
        }

    return await enqueue_write(_write_op)


@router.get("/export")
async def export_data():
    try:
        db = get_db()
        export = {
            "version": "1.1",
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "memories": [],
            "conversations": [],
            "messages": [],
        }

        if "memories" in db.table_names():
            export["memories"] = db.open_table("memories").search().limit(100000).to_list()

        if "conversations" in db.table_names():
            export["conversations"] = db.open_table("conversations").search().limit(100000).to_list()

        if "messages" in db.table_names():
            export["messages"] = db.open_table("messages").search().limit(50000).to_list()

        filename = f"mnesis_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        return JSONResponse(
            content=json.loads(json.dumps(export, default=str)),
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.error(f"Export failed: {e}")
        raise _internal_error("Failed to export data.", e)


@router.post("/chatgpt")
async def import_chatgpt_memory(
    file: Optional[UploadFile] = File(None),
    confirm: bool = Form(False),
    preview_id: Optional[str] = Form(None),
):
    if not file and not (confirm and preview_id):
        raise HTTPException(status_code=400, detail="A JSON file is required for ChatGPT import preview")

    temp_path: Optional[str] = None
    try:
        normalized: list[dict[str, Any]] = []
        parsed_conversations: list[dict[str, Any]] = []
        parsed_messages: list[dict[str, Any]] = []
        ignored_count = 0

        if file:
            temp_path = os.path.join(_ensure_data_dir(), f"temp_{uuid.uuid4()}_{file.filename}")
            with open(temp_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)

            importer = ChatGPTImporter()
            parsed = [m.model_dump() if hasattr(m, "model_dump") else m.dict() for m in importer.parse_memories(temp_path)]
            normalized, ignored_count = _normalize_chatgpt_memories(parsed)
            parsed_conversations, parsed_messages = _extract_importer_conversations(importer, temp_path)

        if not confirm:
            pid = str(uuid.uuid4())
            _chatgpt_previews[pid] = {
                "memories": normalized,
                "conversations": parsed_conversations,
                "messages": parsed_messages,
                "ignored": ignored_count,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            samples: list[dict[str, Any]]
            if normalized:
                samples = [{"content": m["content"], "category": m["category"], "level": m["level"]} for m in normalized[:8]]
            else:
                samples = [
                    {
                        "content": c.get("title", "Untitled conversation"),
                        "category": "conversation",
                        "level": "episodic",
                    }
                    for c in parsed_conversations[:8]
                ]
            return {
                "status": "ready_to_confirm",
                "preview_id": pid,
                "detected_memories": len(normalized),
                "total_conversations": len(parsed_conversations),
                "total_messages": len(parsed_messages),
                "ignored": ignored_count,
                "samples": samples,
            }

        # Confirm import
        selected_memories = normalized
        selected_conversations = parsed_conversations
        selected_messages = parsed_messages
        ignored_from_preview = ignored_count
        if preview_id:
            saved = _chatgpt_previews.pop(preview_id, None)
            if not saved:
                raise HTTPException(status_code=404, detail="Preview not found or expired")
            selected_memories = saved.get("memories", [])
            selected_conversations = saved.get("conversations", [])
            selected_messages = saved.get("messages", [])
            ignored_from_preview = int(saved.get("ignored", 0))

        report = await _import_chatgpt_memories(selected_memories)
        conv_report = await _import_conversations_messages(selected_conversations, selected_messages)
        report["ignored"] += ignored_from_preview
        report["detected_conversations"] = len(selected_conversations)
        report["detected_messages"] = len(selected_messages)
        report["imported_conversations"] = conv_report.get("conversations", 0)
        report["imported_messages"] = conv_report.get("messages", 0)
        report["deduplicated_conversations"] = conv_report.get("deduplicated_conversations", 0)
        report["deduplicated_messages"] = conv_report.get("deduplicated_messages", 0)
        report["skipped_conversations"] = conv_report.get("skipped_conversations", 0)
        report["skipped_messages"] = conv_report.get("skipped_messages", 0)
        return {"status": "completed", **report}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"ChatGPT import failed: {e}")
        raise _internal_error("ChatGPT import failed.", e)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


@router.post("/upload")
async def upload_import(
    file: UploadFile = File(...),
    source: str = Form(...),
):
    temp_path = os.path.join(_ensure_data_dir(), f"temp_{uuid.uuid4()}_{file.filename}")

    try:
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        if source == "mnesis-backup":
            with open(temp_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            parsed_memories = [
                {
                    "content": m.get("content"),
                    "source": m.get("source_llm", "manual"),
                    "original_created_at": m.get("created_at"),
                    "original_category": m.get("category"),
                    "original_level": m.get("level"),
                    "metadata": m,
                }
                for m in data.get("memories", [])
            ]
            parsed_conversations = data.get("conversations", [])
            parsed_messages = data.get("messages", [])
        else:
            if source == "claude":
                importer = ClaudeImporter()
            elif source == "chatgpt":
                importer = ChatGPTImporter()
            elif source == "gemini":
                importer = GeminiImporter()
            else:
                raise HTTPException(status_code=400, detail="Unknown source")

            parsed_memories = [m.model_dump() if hasattr(m, "model_dump") else m.dict() for m in importer.parse_memories(temp_path)]
            parsed_conversations = []
            parsed_messages = []

            try:
                for conv in importer.parse_conversations(temp_path):
                    msgs = conv.pop("chat_messages", [])
                    parsed_conversations.append(conv)
                    for msg in msgs:
                        if not msg.get("conversation_id"):
                            msg["conversation_id"] = conv.get("id")
                        parsed_messages.append(msg)
            except Exception as e:
                logger.warning(f"Conversation parsing failed: {e}")

        preview_id = str(uuid.uuid4())
        _previews[preview_id] = {
            "memories": parsed_memories,
            "conversations": parsed_conversations,
            "messages": parsed_messages,
        }

        categories: dict[str, int] = {}
        for memory in parsed_memories:
            cat = memory.get("original_category") or "unknown"
            categories[cat] = categories.get(cat, 0) + 1

        samples = parsed_memories[:5] if parsed_memories else [
            {
                "content": conv.get("title", "Untitled conversation"),
                "source": conv.get("source_llm", source),
                "original_category": "conversation",
                "original_level": "episodic",
            }
            for conv in parsed_conversations[:5]
        ]

        return {
            "preview_id": preview_id,
            "total_memories": len(parsed_memories),
            "total_conversations": len(parsed_conversations),
            "categories": categories,
            "samples": samples,
            "status": "ready_to_confirm",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Import upload failed: {e}")
        raise _internal_error("Import upload failed.", e)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@router.post("/confirm/{preview_id}")
async def confirm_import(preview_id: str, background_tasks: BackgroundTasks):
    if preview_id not in _previews:
        raise HTTPException(status_code=404, detail="Preview not found or expired")
    data = _previews.pop(preview_id)
    background_tasks.add_task(_process_import, data)
    count = len(data.get("memories", [])) + len(data.get("conversations", []))
    return {"status": "started", "count": count}


async def _process_import(data: dict[str, Any]):
    raw_memories = data.get("memories", [])
    raw_conversations = data.get("conversations", [])
    raw_messages = data.get("messages", [])

    logger.info(
        f"Processing import: {len(raw_memories)} memories, {len(raw_conversations)} conversations, {len(raw_messages)} messages"
    )

    # 1. Memories (via create_memory -> write_queue)
    for raw in raw_memories:
        try:
            content = raw.get("content")
            source = raw.get("source") or "imported"
            original_cat = raw.get("original_category")
            original_level = raw.get("original_level") or raw.get("level")
            if not content:
                continue

            category = original_cat or "preferences"
            level = original_level or "semantic"
            if source == "claude" and original_cat:
                level, category = CLAUDE_CATEGORY_MAP.get(original_cat, CLAUDE_CATEGORY_MAP["_default"])
            elif source == "chatgpt":
                category = original_cat or category
                level = original_level or level
            elif source == "gemini":
                category = "history"
                level = "episodic"

            await create_memory(
                content=content,
                category=category,
                level=level,
                source_llm=source,
                confidence_score=float(raw.get("confidence_score", 0.9)),
                tags=[f"import:{source or 'unknown'}"],
                created_at=raw.get("original_created_at"),
                event_date=raw.get("original_created_at"),
            )
        except Exception as e:
            logger.error(f"Failed to import memory: {e}")

    # 2. Conversations + messages
    try:
        await _import_conversations_messages(raw_conversations, raw_messages)
    except Exception as e:
        logger.error(f"Failed to import conversations/messages: {e}")
