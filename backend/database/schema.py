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
    source_message_id: Optional[str]
    source_excerpt: Optional[str]
    version: int
    status: str
    created_at: datetime
    updated_at: datetime
    last_referenced_at: datetime
    reference_count: int
    decay_profile: str
    expires_at: Optional[datetime]
    needs_review: bool
    review_due_at: Optional[datetime]
    event_date: Optional[datetime]
    suggestion_reason: Optional[str]
    review_note: Optional[str]
    vector: Vector(EMBEDDING_DIM)

class MemoryVersion(LanceModel):
    id: str
    memory_id: str
    content: str
    version: int
    changed_by: str
    created_at: datetime


class MemoryEvent(LanceModel):
    id: str
    memory_id: Optional[str]
    event_type: str
    source: str
    details_json: str
    created_at: datetime


class ClientRuntimeMetric(LanceModel):
    id: str
    client: str
    captured_at: datetime
    total_requests: int
    error_requests: int
    delta_requests: int
    delta_errors: int
    avg_latency_ms: float
    p95_latency_ms: float
    unique_paths: int
    top_paths_json: str
    last_seen_at: Optional[datetime]
    last_error_at: Optional[datetime]


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


class PendingConflict(LanceModel):
    id: str
    memory_id_existing: str
    candidate_content: str
    candidate_level: str
    candidate_category: str
    candidate_source_llm: str
    similarity_score: float
    detected_at: datetime
    resolved_at: Optional[datetime]
    resolution: Optional[str]  # "merged" | "versioned" | "overwritten" | "auto_archived"
    status: str  # "pending" | "resolved" | "archived"
    candidate_memory_id: Optional[str]


class ContextRouteLog(LanceModel):
    id: str
    query_preview: str
    detected_domain: str
    scores_json: str
    created_at: datetime


class MemoryGraphEdge(LanceModel):
    id: str
    source_memory_id: str
    target_memory_id: str
    edge_type: str  # BELONGS_TO | CONTRADICTS | REINFORCES | PRECEDES | DEPENDS_ON | INVOLVES_PERSON
    score: float
    created_at: datetime

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


class ConversationAnalysisJob(LanceModel):
    id: str
    trigger: str
    status: str  # pending | running | completed | failed | cancelled
    priority: int
    dedupe_key: str
    payload_json: str
    result_json: str
    error: str
    attempt_count: int
    max_attempts: int
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]


class ConversationAnalysisIndex(LanceModel):
    id: str  # conversation_id
    conversation_id: str
    message_count: int
    conversation_hash: str
    latest_message_at: Optional[datetime]
    last_result: str  # has_memory | none | error
    provider: str
    signal_score: int
    candidates_count: int
    created_count: int
    error_count: int
    duration_ms: int
    last_analyzed_at: datetime


class ConversationAnalysisCandidate(LanceModel):
    id: str
    canonical_key: str
    content: str
    normalized_content: str
    category: str
    level: str
    confidence_score: float
    source_provider: str
    source_llm: str
    evidence_count: int
    conversation_ids: List[str]
    source_message_ids: List[str]
    methods: List[str]
    first_seen_at: datetime
    last_seen_at: datetime
    promotion_score: float
    status: str  # pending | promoted | merged | rejected | conflict_pending
    promoted_memory_id: Optional[str]
    last_result: str
    last_error: str
    created_at: datetime
    updated_at: datetime
    vector: Vector(EMBEDDING_DIM)
