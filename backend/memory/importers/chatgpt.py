import logging
import json
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Generator, List, Optional, Tuple

from backend.memory.importers.base import BaseImporter, RawMemory

logger = logging.getLogger(__name__)

# (keywords_in_content, level, category)
CHATGPT_KEYWORD_MAP: List[Tuple[List[str], str, str]] = [
    (["name is", "called", "my name"], "semantic", "identity"),
    (["work", "job", "profession", "developer", "engineer", "designer", "role"], "semantic", "identity"),
    (["project", "building", "working on", "creating", "dev", "app"], "semantic", "projects"),
    (["prefer", "like", "love", "hate", "dislike", "always use", "never use", "want", "need"], "semantic", "preferences"),
    (["skill", "expert", "know", "experienced", "familiar with", "stack", "use"], "semantic", "skills"),
    (["wife", "husband", "partner", "colleague", "friend", "boss", "client", "family"], "semantic", "relationships"),
    (["_default"], "semantic", "preferences"),
]

class ChatGPTImporter(BaseImporter):
    def _classify(self, content: str) -> Tuple[str, str]:
        content_lower = content.lower()
        for keywords, level, category in CHATGPT_KEYWORD_MAP:
            if keywords == ["_default"]:
                return level, category
            for kw in keywords:
                if kw in content_lower:
                    return level, category
        return "semantic", "preferences"

    def parse_memories(self, file_path: str) -> List[RawMemory]:
        results = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # ChatGPT export: usually "memories" key inside a larger JSON or just a list?
            # PROMPT.md implies "memories.json" is the file.
            # Format: [{"memory": "...", "created_at": "..."}]
            
            if isinstance(data, list):
                items = data
            else:
                items = data.get("memories") or data.get("list") or data.get("items") or []
            
            for item in items:
                if not isinstance(item, dict):
                    continue
                # Skip full conversation exports (they contain a mapping tree).
                if "mapping" in item:
                    continue

                raw_content = item.get("memory", "") or item.get("content", "") or item.get("text", "")
                content = raw_content if isinstance(raw_content, str) else ""
                if not content:
                    continue
                    
                created_at_str = item.get("created_at")
                created_at = None
                if created_at_str:
                    try:
                        created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                    except ValueError:
                        pass
                
                # Classify
                level, category = self._classify(content)
                
                results.append(RawMemory(
                    content=content,
                    source="chatgpt",
                    original_created_at=created_at,
                    original_category=category,
                    original_level=level,
                    metadata={}
                ))
        except Exception as e:
            logger.error(f"Failed to parse ChatGPT memories: {e}")
            raise e
            
        return results

    def parse_conversations(self, file_path: str) -> Generator[dict, None, None]:
        import ijson

        def _to_datetime(value: Any) -> Optional[datetime]:
            if value is None:
                return None
            if isinstance(value, datetime):
                if value.tzinfo is None:
                    return value.replace(tzinfo=timezone.utc)
                return value.astimezone(timezone.utc)
            if isinstance(value, str):
                try:
                    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
                except Exception:
                    return None
            try:
                return datetime.fromtimestamp(float(value), tz=timezone.utc)
            except Exception:
                return None

        def _message_text(content: Any) -> str:
            if not isinstance(content, dict):
                return ""
            parts = content.get("parts")
            if isinstance(parts, list):
                chunks = [str(part).strip() for part in parts if isinstance(part, str) and part.strip()]
                if chunks:
                    return "\n".join(chunks)
            text = content.get("text")
            if isinstance(text, str):
                return text.strip()
            return ""

        def _extract_messages(mapping: Any, conversation_id: str, fallback_time: Optional[datetime]) -> list[dict]:
            if not isinstance(mapping, dict):
                return []

            messages: list[dict] = []
            for node in mapping.values():
                if not isinstance(node, dict):
                    continue
                message = node.get("message")
                if not isinstance(message, dict):
                    continue

                metadata = message.get("metadata")
                if isinstance(metadata, dict):
                    if metadata.get("is_visually_hidden_from_conversation") or metadata.get("is_user_system_message"):
                        continue

                author = message.get("author")
                role = "user"
                if isinstance(author, dict) and author.get("role"):
                    role = str(author.get("role"))
                elif message.get("role"):
                    role = str(message.get("role"))

                text = _message_text(message.get("content"))
                if not text:
                    continue

                msg_time = _to_datetime(message.get("create_time")) or _to_datetime(node.get("create_time")) or fallback_time
                msg_id = message.get("id") or node.get("id") or str(uuid.uuid4())

                messages.append(
                    {
                        "id": str(msg_id),
                        "conversation_id": conversation_id,
                        "role": role,
                        "content": text,
                        "created_at": msg_time,
                    }
                )

            messages.sort(key=lambda x: x.get("created_at") or datetime.fromtimestamp(0, tz=timezone.utc))
            return messages

        def _extract_from_chat_messages(chat_messages: Any, conversation_id: str, fallback_time: Optional[datetime]) -> list[dict]:
            if not isinstance(chat_messages, list):
                return []
            messages: list[dict] = []
            for row in chat_messages:
                if not isinstance(row, dict):
                    continue
                content = row.get("text", row.get("content", ""))
                if not isinstance(content, str) or not content.strip():
                    continue
                role = row.get("sender", row.get("role", "user"))
                messages.append(
                    {
                        "id": str(row.get("id") or uuid.uuid4()),
                        "conversation_id": conversation_id,
                        "role": str(role),
                        "content": content.strip(),
                        "created_at": _to_datetime(row.get("created_at") or row.get("timestamp")) or fallback_time,
                    }
                )
            messages.sort(key=lambda x: x.get("created_at") or datetime.fromtimestamp(0, tz=timezone.utc))
            return messages

        def _stable_conversation_id(item: dict[str, Any], mapping: Any, chat_messages: Any) -> str:
            explicit = item.get("id")
            if explicit:
                return str(explicit)

            mapping_ids: list[str] = []
            if isinstance(mapping, dict):
                mapping_ids = sorted(str(k) for k in mapping.keys() if k)[:120]

            chat_fingerprint: list[dict[str, str]] = []
            if isinstance(chat_messages, list):
                for row in chat_messages[:20]:
                    if not isinstance(row, dict):
                        continue
                    chat_fingerprint.append(
                        {
                            "id": str(row.get("id") or ""),
                            "role": str(row.get("sender") or row.get("role") or ""),
                            "timestamp": str(row.get("created_at") or row.get("timestamp") or ""),
                            "content": str(row.get("text") or row.get("content") or "")[:80],
                        }
                    )

            payload = {
                "title": str(item.get("title") or ""),
                "create_time": str(item.get("create_time") or ""),
                "update_time": str(item.get("update_time") or ""),
                "mapping_ids": mapping_ids,
                "chat_fingerprint": chat_fingerprint,
            }
            digest = hashlib.sha1(
                json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()[:24]
            return f"chatgpt-{digest}"

        try:
            with open(file_path, 'rb') as f:
                parser = ijson.items(f, 'item')
                for item in parser:
                    if not isinstance(item, dict):
                        continue

                    mapping = item.get("mapping")
                    chat_messages = item.get("chat_messages")
                    if not isinstance(mapping, dict) and not isinstance(chat_messages, list):
                        continue

                    title = item.get("title") or "Untitled"
                    start_at = _to_datetime(item.get("create_time"))
                    updated_at = _to_datetime(item.get("update_time"))
                    conversation_id = _stable_conversation_id(item, mapping, chat_messages)
                    messages = _extract_messages(mapping or {}, conversation_id, start_at or updated_at)
                    if not messages:
                        messages = _extract_from_chat_messages(chat_messages, conversation_id, start_at or updated_at)
                    if not isinstance(mapping, dict) and not messages:
                        continue

                    yield {
                        "id": conversation_id,
                        "title": title,
                        "source_llm": "chatgpt",
                        "started_at": start_at,
                        "updated_at": updated_at,
                        "message_count": len(messages),
                        "chat_messages": messages,
                    }
        except Exception as e:
            logger.error(f"Failed to parse ChatGPT conversations: {e}")
            raise e
