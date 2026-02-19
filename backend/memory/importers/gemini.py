import zipfile
import json
import ijson
from typing import List, Generator
from datetime import datetime
from backend.memory.importers.base import BaseImporter, RawMemory
import logging
import io

logger = logging.getLogger(__name__)

class GeminiImporter(BaseImporter):
    def parse_memories(self, file_path: str) -> List[RawMemory]:
        # Gemini Takeout typically doesn't have a distinct "memories" file yet
        # (unless "Saved Prompts" counts?).
        # For now, return empty list or extract from conversations if requested.
        # PROMPT.md implies generic support.
        return []

    def parse_conversations(self, file_path: str) -> Generator[dict, None, None]:
        # Iterate over ZIP, look for "conversations.json" or similar inside directories.
        try:
            with zipfile.ZipFile(file_path, 'r') as z:
                # Find the right file
                target_file = None
                for name in z.namelist():
                    if name.endswith("conversations.json") or name.endswith("history.json"): # heuristics
                         target_file = name
                         break
                
                # Fallback: look for generic JSONs in "Gemini" folder
                if not target_file:
                    for name in z.namelist():
                         if "Gemini" in name and name.endswith(".json"):
                             target_file = name
                             break

                if not target_file:
                    logger.warning("No conversation JSON found in Gemini ZIP")
                    return

                # Stream from zip
                with z.open(target_file) as f:
                    # ijson needs a seekable stream or bytes? 
                    # ZipExtFile is seekable if uncompressed? 
                    # ijson works with file-like objects.
                    
                    # PROMPT.md example used open(filepath).
                    # Here we have a stream.
                    parser = ijson.items(f, 'item')
                    for item in parser:
                        yield {
                            "id": str(item.get("conversationId") or item.get("id")),
                            "title": item.get("title", "Gemini Chat"),
                            "source_llm": "gemini",
                            "started_at": item.get("createdTime"), # Needs parsing
                            "updated_at": None,
                            "message_count": len(item.get("events", [])),
                            "chat_messages": []
                        }
        except Exception as e:
            logger.error(f"Failed to parse Gemini ZIP: {e}")
            raise e
