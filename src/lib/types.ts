// TypeScript interfaces mirroring the Python Pydantic schemas in backend/database/schema.py

export type MemoryLevel = 'semantic' | 'episodic' | 'working'
export type MemoryStatus = 'active' | 'archived' | 'pending_review' | 'rejected'
export type MemoryPrivacy = 'public' | 'sensitive' | 'private'
export type MemoryCategory =
    | 'identity'
    | 'preferences'
    | 'skills'
    | 'relationships'
    | 'projects'
    | 'history'
    | 'working'

export interface Memory {
    id: string
    content: string
    level: MemoryLevel
    category: MemoryCategory
    importance_score: number
    confidence_score: number
    privacy: MemoryPrivacy
    tags: string[]
    source_llm: string
    source_conversation_id: string | null
    version: number
    status: MemoryStatus
    created_at: string // ISO 8601
    updated_at: string // ISO 8601
    last_referenced_at: string // ISO 8601
    reference_count: number
    // vector is intentionally excluded — never sent to the frontend
}

export interface MemoryVersion {
    id: string
    memory_id: string
    content: string
    version: number
    changed_by: string
    created_at: string
}

export interface Conversation {
    id: string
    title: string
    source_llm: string
    started_at: string
    ended_at: string | null
    message_count: number
    memory_ids: string[]
    tags: string[]
    summary: string
    status: 'active' | 'archived'
    raw_file_hash: string
    imported_at: string
}

export interface Message {
    id: string
    conversation_id: string
    role: 'user' | 'assistant'
    content: string
    timestamp: string
}

export interface Conflict {
    id: string
    memory_id_a: string
    memory_id_b: string
    similarity_score: number
    detected_at: string
    resolved_at: string | null
    resolution: string | null
    status: 'pending' | 'resolved' | 'dismissed'
}

export interface Session {
    id: string
    api_key_id: string
    source_llm: string
    started_at: string
    ended_at: string | null
    end_reason: string | null
    memory_ids_read: string[]
    memory_ids_written: string[]
    memory_ids_feedback: string[]
}

// API response types
export interface HealthResponse {
    status: 'ok' | 'error'
    model_ready: boolean
    model_name?: string
}

export interface MemoryWriteResult {
    id: string | null
    status: string
    action: 'created' | 'merged' | 'skipped' | 'created_with_conflict' | 'error'
    message?: string
}

export interface DashboardStats {
    total_memories: number
    active: number
}

export interface Config {
    onboarding_completed: boolean
    snapshot_read_token: string
    validation_mode: 'auto' | 'review' | 'strict'
    decay_rates: {
        semantic: number
        episodic: number
        working: number
    }
    llm_client_keys: Record<string, string>
    rest_port: number
    mcp_port: number
}

export interface ImportPreview {
    preview_id: string
    total_memories: number
    total_conversations: number
    categories: Record<string, number>
    samples: Array<{
        content?: string
        source?: string
        original_category?: string
        [key: string]: unknown
    }>
    status: 'ready_to_confirm'
}
