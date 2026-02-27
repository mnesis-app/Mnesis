// TypeScript interfaces mirroring the Python Pydantic schemas in backend/database/schema.py

export type MemoryLevel = 'semantic' | 'episodic' | 'working'
export type MemoryStatus = 'active' | 'archived' | 'pending_review' | 'rejected'
export type MemoryPrivacy = 'public' | 'sensitive' | 'private'
export type DecayProfile = 'permanent' | 'stable' | 'semi-stable' | 'volatile' | 'event-based'
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
    decay_profile: DecayProfile
    expires_at: string | null
    needs_review: boolean
    review_due_at: string | null
    event_date: string | null
    suggestion_reason: string | null
    review_note: string | null
    // vector is intentionally excluded - never sent to the frontend
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
    messages?: ConversationMessage[]
}

export interface ConversationMessage {
    id: string
    conversation_id: string
    role: 'user' | 'assistant' | 'system' | 'tool' | string
    content: string
    timestamp: string
}

export interface ConversationMemoryCandidate {
    content: string
    category: MemoryCategory | string
    level: MemoryLevel | string
    confidence: number
    conversation_id: string
    conversation_title: string
    source_message_id: string
    method: 'llm' | 'heuristic' | string
    suggestion_reason?: string
}

export interface ConversationMemoryMiningWriteStats {
    created: number
    merged: number
    skipped: number
    conflict_pending: number
    rejected: number
}

export interface ConversationMemoryMiningResult {
    status: 'ok' | string
    mode: 'dry_run' | 'import' | string
    provider: string
    llm_enabled: boolean
    conversations_scanned: number
    conversations_selected: number
    skipped_already_analyzed: number
    candidates_total: number
    candidate_sources: {
        llm: number
        heuristic: number
    }
    write_stats?: ConversationMemoryMiningWriteStats
    linked_conversations?: number
    analyzed_marked?: number
    preview: ConversationMemoryCandidate[]
    details?: Array<{
        conversation_id: string
        source_message_id: string
        content: string
        action: string
        memory_id: string | null
        message?: string
    }>
    llm_error_count: number
    llm_errors: string[]
}

export interface Conflict {
    id: string
    memory_id_existing: string
    similarity_score: number
    detected_at: string
    resolved_at: string | null
    resolution: string | null
    status: 'pending' | 'resolved' | 'archived'
    memory_a?: Memory
    memory_b?: Partial<Memory> & { content: string }
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
    llm_client_keys: Record<string, string | { hash?: string; sha256?: string; token_hash?: string; scopes?: string[]; enabled?: boolean }>
    rest_port: number
    mcp_port: number
    sync: SyncConfig
    sync_status: SyncStatus
    insights: InsightsConfig
    insights_cache: InsightsCache
    mcp_autoconfig?: {
        enabled: boolean
        first_launch_done: boolean
        last_run_at: string | null
        detected_clients: string[]
        configured_clients: string[]
        last_error: string | null
    }
    remote_access?: RemoteAccessConfig
}

export interface SyncConfig {
    enabled: boolean
    provider: 's3' | 'r2' | 'minio' | 'custom' | 'webdav' | 'nextcloud' | string
    endpoint_url: string
    force_path_style: boolean
    webdav_url: string
    webdav_username: string
    webdav_password: string
    bucket: string
    region: string
    access_key_id: string
    secret_access_key: string
    object_prefix: string
    device_id: string
    auto_sync: boolean
    auto_sync_interval_minutes: number
}

export interface SyncStatus {
    last_sync_at: string | null
    last_sync_size_bytes: number
    last_sync_result: 'never' | 'ok' | 'error' | string
    devices: string[]
    last_error: string | null
}

export interface SyncPublicStatus {
    sync: SyncConfig
    sync_status: SyncStatus
    unlocked: boolean
}

export interface RemoteAccessConfig {
    enabled: boolean
    relay_url: string
    project_id: string
    device_id: string
    device_name: string
    poll_interval_seconds: number
    request_timeout_seconds: number
    max_tasks_per_poll: number
    has_device_secret?: boolean
}

export interface InsightsConfig {
    enabled: boolean
    provider: 'openai' | 'anthropic' | 'ollama' | string
    model: string
    api_key: string
    api_base_url: string
}

export interface InsightsCache {
    date: string
    generated_at: string | null
    source: string
    insights: Array<{ title: string; detail: string }>
    last_error: string | null
}

export interface InsightsConfigPublicStatus {
    insights: InsightsConfig
    insights_cache: InsightsCache
}

export interface DashboardInsights {
    generated_at: string
    source: string
    insights: Array<{
        title: string
        detail: string
    }>
    analytics: {
        summary: {
            total_memories: number
            levels: Record<string, number>
            conflicts_total: number
            conflicts_resolved: number
            conflict_resolution_rate: number
            auto_suggestions_pending?: number
            most_active_llm: { name: string; writes: number } | null
            top_referenced_memories: Array<{
                id: string
                content_preview: string
                reference_count: number
                category: string
                level: string
            }>
        }
        category_evolution: Array<Record<string, string | number>>
        domain_activity: Array<{
            date: string
            code: number
            business: number
            personal: number
            casual: number
            total: number
        }>
        recurrent_topics: Array<{
            topic: string
            count: number
        }>
        auto_memory_suggestions?: Array<{
            id: string
            content_preview: string
            category: string
            level: string
            confidence_score: number
            source_conversation_id: string
            updated_at: string
        }>
        window_days: number
    }
    cache: {
        date: string
        source: string
        last_error: string | null
    }
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
        original_level?: string
        category?: string
        level?: string
        [key: string]: unknown
    }>
    status: 'ready_to_confirm'
}

export interface ChatGPTImportPreview {
    status: 'ready_to_confirm'
    preview_id: string
    detected_memories: number
    ignored: number
    samples: Array<{
        content: string
        category: string
        level: string
    }>
}

export interface ChatGPTImportReport {
    status: 'completed'
    imported: number
    deduplicated: number
    ignored: number
    imported_conversations?: number
    imported_messages?: number
    deduplicated_conversations?: number
    deduplicated_messages?: number
    skipped_conversations?: number
    skipped_messages?: number
}

export interface MemoryGraphNode {
    id: string
    content_preview: string
    category?: string
    level?: string
}

export interface MemoryGraphEdge {
    id: string
    source: string
    target: string
    type: 'BELONGS_TO' | 'CONTRADICTS' | 'REINFORCES' | 'PRECEDES' | 'DEPENDS_ON' | 'INVOLVES_PERSON'
    score: number
}

export interface MemoryGraphSubgraph {
    start_memory_id: string
    depth: number
    nodes: MemoryGraphNode[]
    edges: MemoryGraphEdge[]
}
