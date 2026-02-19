from lancedb.pydantic import LanceModel, Vector
from datetime import datetime
from typing import List, Optional

# Dimension for bge-small-en-v1.5
EMBEDDING_DIM = 384

class Memory(LanceModel):
    id: str
    content: str
    level: str
    category: str
    importance_score: float
    confidence_score: float
    privacy: str
    tags: List[str]
    source_llm: str
    source_conversation_id: Optional[str]
    version: int
    status: str
    created_at: datetime
    updated_at: datetime
    last_referenced_at: datetime
    reference_count: int
    vector: Vector(EMBEDDING_DIM)

class MemoryVersion(LanceModel):
    id: str
    memory_id: str
    content: str
    version: int
    changed_by: str
    created_at: datetime

class Conversation(LanceModel):
    id: str
    title: str
    source_llm: str
    started_at: datetime
    ended_at: Optional[datetime]
    message_count: int
    memory_ids: List[str]
    tags: List[str]
    summary: str
    status: str
    raw_file_hash: str
    imported_at: datetime

class Message(LanceModel):
    id: str
    conversation_id: str
    role: str
    content: str
    timestamp: datetime
    vector: Optional[Vector(EMBEDDING_DIM)]

class Conflict(LanceModel):
    id: str
    memory_id_a: str
    memory_id_b: str
    similarity_score: float
    detected_at: datetime
    resolved_at: Optional[datetime]
    resolution: Optional[str]  # "kept_a"|"kept_b"|"merged"|"both_valid"
    status: str      # "pending" | "resolved"

class Session(LanceModel):
    id: str
    api_key_id: str
    source_llm: str
    started_at: datetime
    ended_at: Optional[datetime]
    memory_ids_read: List[str]
    memory_ids_written: List[str]
    memory_ids_feedback: List[str]
    end_reason: Optional[str]
