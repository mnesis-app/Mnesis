import json
from datetime import datetime
from typing import List, Generator
from backend.memory.importers.base import BaseImporter, RawMemory
import logging

logger = logging.getLogger(__name__)

CLAUDE_CATEGORY_MAP = {
    "General Preferences": ("semantic", "preferences"),
    "Personal Information": ("semantic", "identity"),
    "Technical Preferences": ("semantic", "preferences"),
    "Professional Background": ("semantic", "identity"),
    "Projects": ("semantic", "projects"),
    "Relationships": ("semantic", "relationships"),
    "Skills": ("semantic", "skills"),
    "Goals": ("semantic", "projects"),
    "Communication Style": ("semantic", "preferences"),
    "_default": ("semantic", "preferences"),
}

class ClaudeImporter(BaseImporter):
    def parse_memories(self, file_path: str) -> List[RawMemory]:
        results = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            for item in data:
                # Format 1: Conversations Memory (Markdown)
                if "conversations_memory" in item:
                    markdown_content = item.get("conversations_memory", "")
                    # Parse markdown sections
                    # Heuristic: headers are **Title** or ## Title
                    import re
                    # Split by **Title** pattern, keeping the delimiters
                    # Pattern: match start of line or newline, followed by **Title**, followed by newline
                    
                    # Simple approach: iterate lines
                    lines = markdown_content.split('\n')
                    current_section = "_default"
                    current_content = []
                    
                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue
                            
                        # Check for header **Title**
                        header_match = re.match(r'^\*\*(.+)\*\*$', line)
                        if header_match:
                            # Save previous section if exists
                            if current_content:
                                text = "\n".join(current_content).strip()
                                if text:
                                    results.append(RawMemory(
                                        content=text,
                                        source="claude",
                                        original_created_at=None,
                                        original_category=current_section,
                                        metadata={"original_id": str(item.get("account_uuid", "")) + f"_{current_section}"}
                                    ))
                            # Start new section
                            current_section = header_match.group(1)
                            current_content = []
                        else:
                            current_content.append(line)
                            
                    # Save last section
                    if current_content:
                        text = "\n".join(current_content).strip()
                        if text:
                            results.append(RawMemory(
                                content=text,
                                source="claude",
                                original_created_at=None,
                                original_category=current_section,
                                metadata={"original_id": str(item.get("account_uuid", "")) + f"_{current_section}"}
                            ))
                            
                else:
                    # Format 2: Standard JSON export (Individual items)
                    content = item.get("content", "")
                    created_at_str = item.get("created_at")
                    title = item.get("title", "_default")
                    
                    created_at = None
                    if created_at_str:
                        try:
                            created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                        except ValueError:
                            pass
                    
                    if content:
                        results.append(RawMemory(
                            content=content,
                            source="claude",
                            original_created_at=created_at,
                            original_category=title,
                            metadata={"original_id": str(item.get("uuid", ""))}
                        ))

        except Exception as e:
            logger.error(f"Failed to parse Claude memories: {e}")
            raise e
            
        return results

    def parse_conversations(self, file_path: str) -> Generator[dict, None, None]:
        # Implementation for streaming conversations.json if needed
        # For now, simplistic JSON load (Claude exports can be large but usually manageable)
        # If huge, use ijson.
        import ijson
        
        try:
            with open(file_path, 'rb') as f:
                # Ensure we parse array items
                parser = ijson.items(f, 'item')
                for item in parser:
                    # Skip if it's a memory export (has conversations_memory key)
                    if "conversations_memory" in item:
                        continue
                        
                    # Skip if no chat_messages (invalid conversation)
                    if "chat_messages" not in item:
                        continue
                        
                    yield {
                        "id": item.get("uuid"),
                        "title": item.get("name", "Untitled"),
                        "source_llm": "claude",
                        "started_at": item.get("created_at"), # Need parsing
                        "updated_at": item.get("updated_at"),
                        "message_count": len(item.get("chat_messages", [])),
                        "chat_messages": item.get("chat_messages", []) # Heavy payload, might need filtering
                    }
        except Exception as e:
            logger.error(f"Failed to parse Claude conversations: {e}")
            raise e
