import json
from datetime import datetime
from typing import List, Generator, Tuple
from backend.memory.importers.base import BaseImporter, RawMemory
import logging

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
            
            # If data is dict with "list" key, or just list.
            items = data if isinstance(data, list) else data.get("list", [])
            
            for item in items:
                content = item.get("memory", "") or item.get("content", "")
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
                    metadata={}
                ))
        except Exception as e:
            logger.error(f"Failed to parse ChatGPT memories: {e}")
            raise e
            
        return results

    def parse_conversations(self, file_path: str) -> Generator[dict, None, None]:
        # ChatGPT conversations.json
        import ijson
        
        try:
            with open(file_path, 'rb') as f:
                # Root is list of conversations
                parser = ijson.items(f, 'item')
                for item in parser:
                    # Extract fields
                    # ChatGPT structure varies, but usually:
                    # title, create_time, mapping (for messages)
                    
                    title = item.get("title", "Untitled")
                    create_time = item.get("create_time")
                    start_at = datetime.fromtimestamp(create_time) if create_time else None
                    
                    # Message count & extraction from "mapping"
                    mapping = item.get("mapping", {})
                    # mapping is dict of id -> node.
                    # Linearize or just count?
                    # For MVP, maybe just count keys - system ones.
                    
                    yield {
                        "id": item.get("id"),
                        "title": title,
                        "source_llm": "chatgpt",
                        "started_at": start_at,
                        "updated_at": item.get("update_time"),
                        "message_count": len(mapping),
                        "chat_messages": [] # Skipping full content for now unless needed
                    }
        except Exception as e:
             logger.error(f"Failed to parse ChatGPT conversations: {e}")
             raise e
