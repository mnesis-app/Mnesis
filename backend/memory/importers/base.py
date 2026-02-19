from abc import ABC, abstractmethod
from typing import List, Optional, Any, Generator
from pydantic import BaseModel
from datetime import datetime

class RawMemory(BaseModel):
    content: str
    source: str # "claude", "chatgpt", "gemini"
    original_created_at: Optional[datetime] = None
    original_category: Optional[str] = None # For mapping
    metadata: dict = {}

class BaseImporter(ABC):
    @abstractmethod
    def parse_memories(self, file_path: str) -> List[RawMemory]:
        """Parse memories file into standard RawMemory objects."""
        pass

    @abstractmethod
    def parse_conversations(self, file_path: str) -> Generator[dict, None, None]:
        """
        Parse conversations file. Yields dicts matching Conversation schema structure.
        Uses generator/streaming for large files.
        """
        pass
