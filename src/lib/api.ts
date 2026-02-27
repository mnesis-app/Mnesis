// Resolve the API base URL dynamically:
// - In Electron (production): use the dynamically-selected port via contextBridge
// - In browser dev (Vite only): fall back to 7860
export function getBaseUrl(): string {
    if (typeof window !== 'undefined' && (window as any).electronAPI?.getRestPort) {
        const port = (window as any).electronAPI.getRestPort()
        return `http://127.0.0.1:${port}`
    }
    return 'http://127.0.0.1:7860'
}

const BASE_URL = getBaseUrl()
const API_BASE = `${BASE_URL}/api/v1`

const MNESIS_CLIENT_HEADER = 'X-Mnesis-Client'
const MNESIS_CLIENT_ID = 'mnesis-desktop'

async function apiFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
    const nextInit = { ...(init || {}) }
    const headers = new Headers(nextInit.headers || {})
    const url =
        typeof input === 'string'
            ? input
            : input instanceof URL
                ? input.toString()
                : (input as Request).url || ''
    if (url.includes('/api/v1/') || url.includes('/api/import/')) {
        headers.set(MNESIS_CLIENT_HEADER, MNESIS_CLIENT_ID)
    }
    nextInit.headers = headers
    return globalThis.fetch(input, nextInit)
}

export const api = {
    memories: {
        list: async (params?: { query?: string; limit?: number; offset?: number; status?: string }) => {
            const url = new URL(`${API_BASE}/memories/`)
            if (params?.query) url.searchParams.append('query', params.query)
            if (params?.limit) url.searchParams.append('limit', params.limit.toString())
            if (params?.offset) url.searchParams.append('offset', params.offset.toString())
            if (params?.status) url.searchParams.append('status', params.status)

            const res = await apiFetch(url.toString())
            if (!res.ok) throw new Error('Failed to fetch memories')
            return res.json()
        },
        get: async (id: string) => {
            const res = await apiFetch(`${API_BASE}/memories/${id}`)
            if (!res.ok) throw new Error('Failed to fetch memory')
            return res.json()
        },
        create: async (data: any) => {
            const res = await apiFetch(`${API_BASE}/memories/`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            })
            if (!res.ok) throw new Error('Failed to create memory')
            return res.json()
        },
        update: async (id: string, data: any) => {
            const res = await apiFetch(`${API_BASE}/memories/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            })
            if (!res.ok) throw new Error('Failed to update memory')
            return res.json()
        },
        setStatus: async (id: string, data: { status: string; source_llm?: string; review_note?: string }) => {
            const res = await apiFetch(`${API_BASE}/memories/${id}/status`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            })
            if (!res.ok) {
                let msg = 'Failed to update memory status'
                try {
                    const err = await res.json()
                    msg = err?.detail || err?.message || msg
                } catch (e) { }
                throw new Error(msg)
            }
            return res.json()
        },
        setStatusBulk: async (data: { ids: string[]; status: string; source_llm?: string; review_note?: string }) => {
            const res = await apiFetch(`${API_BASE}/memories/status/bulk`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            })
            if (!res.ok) {
                let msg = 'Failed to update memory statuses'
                try {
                    const err = await res.json()
                    msg = err?.detail || err?.message || msg
                } catch (e) { }
                throw new Error(msg)
            }
            return res.json()
        },
        delete: async (id: string) => {
            const res = await apiFetch(`${API_BASE}/memories/${id}`, {
                method: 'DELETE',
            })
            if (!res.ok) throw new Error('Failed to delete memory')
            return res.json()
        },
        health: async (id: string) => {
            const res = await apiFetch(`${API_BASE}/memories/${id}/health`)
            if (!res.ok) throw new Error('Failed to fetch memory health')
            return res.json()
        },
        updateScores: async (id: string, data: { importance_score?: number; confidence_score?: number }) => {
            const res = await apiFetch(`${API_BASE}/memories/${id}/scores`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            })
            if (!res.ok) throw new Error('Failed to update scores')
            return res.json()
        },
        graph: async (id: string, depth = 2) => {
            const url = new URL(`${API_BASE}/memories/${id}/graph`)
            url.searchParams.append('depth', depth.toString())
            const res = await apiFetch(url.toString())
            if (!res.ok) throw new Error('Failed to fetch memory graph')
            return res.json()
        },
        graphOverview: async (params?: {
            depth?: number
            centerMemoryId?: string
            category?: string
            edgeType?: string
            maxNodes?: number
            includeConversations?: boolean
        }) => {
            const url = new URL(`${API_BASE}/memories/graph`)
            if (params?.depth) url.searchParams.append('depth', params.depth.toString())
            if (params?.centerMemoryId) url.searchParams.append('center_memory_id', params.centerMemoryId)
            if (params?.category) url.searchParams.append('category', params.category)
            if (params?.edgeType) url.searchParams.append('edge_type', params.edgeType)
            if (params?.maxNodes) url.searchParams.append('max_nodes', params.maxNodes.toString())
            if (typeof params?.includeConversations === 'boolean') {
                url.searchParams.append('include_conversations', String(params.includeConversations))
            }
            const res = await apiFetch(url.toString())
            if (!res.ok) throw new Error('Failed to fetch graph overview')
            return res.json()
        }
    },
    snapshot: {
        get: async (context?: string) => {
            const url = new URL(`${API_BASE}/memories/snapshot`)
            if (context) url.searchParams.append('context', context)
            const res = await apiFetch(url.toString())
            if (!res.ok) throw new Error('Failed to fetch snapshot')
            return res.json()
        },
        getText: async (token: string) => {
            const url = new URL(`${API_BASE}/snapshot/text`)
            const res = await apiFetch(url.toString(), {
                headers: {
                    Authorization: `Bearer ${token}`,
                },
            })
            if (!res.ok) throw new Error('Failed to fetch plain-text snapshot')
            return res.text()
        }
    },
    conversations: {
        list: async (params?: { search?: string; limit?: number; offset?: number }) => {
            if (params?.search) {
                const searchUrl = new URL(`${API_BASE}/conversations/search`)
                searchUrl.searchParams.append('query', params.search)
                if (params?.limit) searchUrl.searchParams.append('limit', params.limit.toString())
                const res = await apiFetch(searchUrl.toString())
                if (!res.ok) throw new Error('Failed to search conversations')
                return res.json()
            }
            const url = new URL(`${API_BASE}/conversations/`)
            if (params?.limit) url.searchParams.append('limit', params.limit.toString())
            if (params?.offset) url.searchParams.append('offset', params.offset.toString())
            const res = await apiFetch(url.toString())
            if (!res.ok) throw new Error('Failed to list conversations')
            return res.json()
        },
        get: async (id: string) => {
            const res = await apiFetch(`${API_BASE}/conversations/${id}`)
            if (!res.ok) throw new Error('Failed to get conversation')
            return res.json()
        },
        delete: async (id: string) => {
            const res = await apiFetch(`${API_BASE}/conversations/${id}`, { method: 'DELETE' })
            if (!res.ok) throw new Error('Failed to delete conversation')
            return res.json()
        },
        mineMemories: async (payload: {
            dry_run?: boolean
            force_reanalyze?: boolean
            include_assistant_messages?: boolean
            max_conversations?: number
            max_messages_per_conversation?: number
            max_candidates_per_conversation?: number
            max_new_memories?: number
            min_confidence?: number
            provider?: string
            model?: string
            api_base_url?: string
            api_key?: string
            concurrency?: number
        }) => {
            const res = await apiFetch(`${API_BASE}/conversations/mine-memories`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload || {}),
            })
            if (!res.ok) {
                let msg = 'Failed to mine memories from conversations'
                try {
                    const err = await res.json()
                    msg = err?.detail || err?.message || msg
                } catch (e) { }
                throw new Error(msg)
            }
            return res.json()
        },
        ingest: async (payload: {
            conversation_id: string
            title?: string
            source_llm?: string
            messages: Array<{
                id?: string
                role?: string
                content: string
                timestamp?: string | number | null
            }>
            tags?: string[]
            summary?: string
            started_at?: string | number | null
            ended_at?: string | number | null
            status?: string
        }) => {
            const res = await apiFetch(`${API_BASE}/conversations/ingest`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            })
            if (!res.ok) {
                let msg = 'Failed to ingest conversation'
                try {
                    const err = await res.json()
                    msg = err?.detail || err?.message || msg
                } catch (e) { }
                throw new Error(msg)
            }
            return res.json()
        }
    },
    search: {
        unified: async (params: {
            q?: string
            limit?: number
            include_memories?: boolean
            include_conversations?: boolean
            date_from?: string
            date_to?: string
            sources?: string[]
        }) => {
            const url = new URL(`${API_BASE}/search/`)
            if (params?.q) url.searchParams.append('q', params.q)
            if (params?.limit) url.searchParams.append('limit', String(params.limit))
            if (typeof params?.include_memories === 'boolean') url.searchParams.append('include_memories', String(params.include_memories))
            if (typeof params?.include_conversations === 'boolean') url.searchParams.append('include_conversations', String(params.include_conversations))
            if (params?.date_from) url.searchParams.append('date_from', params.date_from)
            if (params?.date_to) url.searchParams.append('date_to', params.date_to)
            if (params?.sources && params.sources.length > 0) {
                url.searchParams.append('sources', params.sources.join(','))
            }
            const res = await apiFetch(url.toString())
            if (!res.ok) {
                let msg = 'Failed to run unified search'
                try {
                    const err = await res.json()
                    msg = err?.detail || err?.message || msg
                } catch (e) { }
                throw new Error(msg)
            }
            return res.json()
        },
    },
    import: {
        upload: async (formData: FormData) => {
            const res = await apiFetch(`${API_BASE}/import/upload`, {
                method: 'POST',
                body: formData
            })
            if (!res.ok) {
                let msg = 'Upload failed'
                try {
                    const err = await res.json()
                    msg = err.detail || msg
                } catch (e) { }
                throw new Error(msg)
            }
            return res.json()
        },
        confirm: async (previewId: string) => {
            const res = await apiFetch(`${API_BASE}/import/confirm/${previewId}`, { method: 'POST' })
            if (!res.ok) throw new Error('Failed to confirm import')
            return res.json()
        },
        chatgptPreview: async (file: File) => {
            const formData = new FormData()
            formData.append('file', file)
            formData.append('confirm', 'false')
            const res = await apiFetch(`${API_BASE}/import/chatgpt`, {
                method: 'POST',
                body: formData,
            })
            if (!res.ok) throw new Error('ChatGPT import preview failed')
            return res.json()
        },
        chatgptConfirm: async (previewId: string) => {
            const formData = new FormData()
            formData.append('confirm', 'true')
            formData.append('preview_id', previewId)
            const res = await apiFetch(`${API_BASE}/import/chatgpt`, {
                method: 'POST',
                body: formData,
            })
            if (!res.ok) throw new Error('ChatGPT import confirmation failed')
            return res.json()
        },
        export: async () => {
            const res = await apiFetch(`${API_BASE}/import/export`)
            if (!res.ok) throw new Error('Export failed')
            return res.blob()
        },
        exportUrl: () => `${API_BASE}/import/export`
    },
    health: async () => {
        const res = await apiFetch(`${BASE_URL}/health`)
        if (!res.ok) throw new Error('Backend unhealthy')
        return res.json()
    },
    admin: {
        config: async () => {
            const res = await apiFetch(`${API_BASE}/admin/config`)
            if (!res.ok) throw new Error('Failed to fetch config')
            return res.json()
        },
        completeOnboarding: async () => {
            const res = await apiFetch(`${API_BASE}/admin/onboarding-complete`, { method: 'POST' })
            if (!res.ok) throw new Error('Failed to complete onboarding')
            return res.json()
        },
        rotateToken: async () => {
            const res = await apiFetch(`${API_BASE}/admin/snapshot-token/rotate`, { method: 'POST' })
            if (!res.ok) throw new Error('Failed to rotate token')
            return res.json()
        },
        syncStatus: async () => {
            const res = await apiFetch(`${API_BASE}/admin/sync/status`)
            if (!res.ok) {
                let msg = 'Failed to fetch sync status'
                try {
                    const err = await res.json()
                    msg = err?.detail || err?.message || msg
                } catch (e) { }
                throw new Error(msg)
            }
            return res.json()
        },
        updateSyncConfig: async (data: any) => {
            const res = await apiFetch(`${API_BASE}/admin/sync/config`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            })
            if (!res.ok) {
                let msg = 'Failed to update sync config'
                try {
                    const err = await res.json()
                    msg = err?.detail || err?.message || msg
                } catch (e) { }
                throw new Error(msg)
            }
            return res.json()
        },
        unlockSync: async (passphrase: string) => {
            const res = await apiFetch(`${API_BASE}/admin/sync/unlock`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ passphrase }),
            })
            if (!res.ok) {
                let msg = 'Failed to unlock sync key'
                try {
                    const err = await res.json()
                    msg = err?.detail || err?.message || msg
                } catch (e) { }
                throw new Error(msg)
            }
            return res.json()
        },
        lockSync: async () => {
            const res = await apiFetch(`${API_BASE}/admin/sync/lock`, { method: 'POST' })
            if (!res.ok) {
                let msg = 'Failed to lock sync key'
                try {
                    const err = await res.json()
                    msg = err?.detail || err?.message || msg
                } catch (e) { }
                throw new Error(msg)
            }
            return res.json()
        },
        runSync: async (passphrase?: string) => {
            const res = await apiFetch(`${API_BASE}/admin/sync/run`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ passphrase: passphrase || null, source: 'manual' }),
            })
            if (!res.ok) {
                let msg = 'Failed to run sync'
                try {
                    const err = await res.json()
                    msg = err?.detail || err?.message || msg
                } catch (e) { }
                throw new Error(msg)
            }
            return res.json()
        },
        syncTest: async (data: {
            provider: string
            endpoint_url?: string
            bucket?: string
            region?: string
            access_key_id?: string
            secret_access_key?: string
            webdav_url?: string
            webdav_username?: string
            webdav_password?: string
        }) => {
            const res = await apiFetch(`${API_BASE}/admin/sync/test`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            })
            if (!res.ok) {
                let msg = 'Connection test failed'
                try {
                    const err = await res.json()
                    msg = err?.detail || err?.message || msg
                } catch (e) { }
                throw new Error(msg)
            }
            return res.json()
        },
        insightsConfig: async () => {
            const res = await apiFetch(`${API_BASE}/admin/insights/config`)
            if (!res.ok) {
                let msg = 'Failed to fetch insights config'
                try {
                    const err = await res.json()
                    msg = err?.detail || err?.message || msg
                } catch (e) { }
                throw new Error(msg)
            }
            return res.json()
        },
        updateInsightsConfig: async (data: any) => {
            const res = await apiFetch(`${API_BASE}/admin/insights/config`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            })
            if (!res.ok) {
                let msg = 'Failed to update insights config'
                try {
                    const err = await res.json()
                    msg = err?.detail || err?.message || msg
                } catch (e) { }
                throw new Error(msg)
            }
            return res.json()
        },
        runMcpAutoconfig: async (payload?: { force?: boolean }) => {
            const res = await apiFetch(`${API_BASE}/admin/mcp/autoconfigure`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload || {}),
            })
            if (!res.ok) {
                let msg = 'Failed to auto-configure MCP clients'
                try {
                    const err = await res.json()
                    msg = err?.detail || err?.message || msg
                } catch (e) { }
                throw new Error(msg)
            }
            return res.json()
        },
        snapshotToken: async () => {
            const res = await apiFetch(`${API_BASE}/admin/snapshot-token`)
            if (!res.ok) throw new Error('Failed to fetch snapshot token')
            return res.json()
        },
        mcpAuthStatus: async () => {
            const res = await apiFetch(`${API_BASE}/admin/mcp/auth-status`)
            if (!res.ok) {
                let msg = 'Failed to fetch MCP auth status'
                try {
                    const err = await res.json()
                    msg = err?.detail || err?.message || msg
                } catch (e) { }
                throw new Error(msg)
            }
            return res.json()
        },
        insightsTest: async () => {
            const res = await apiFetch(`${API_BASE}/admin/insights/test`, { method: 'POST' })
            if (!res.ok) {
                let msg = 'LLM connection test failed'
                try {
                    const err = await res.json()
                    msg = err?.detail || err?.message || msg
                } catch (e) { }
                throw new Error(msg)
            }
            return res.json()
        },
        remoteAccessStatus: async () => {
            const res = await apiFetch(`${API_BASE}/admin/remote/status`)
            if (!res.ok) {
                let msg = 'Failed to fetch remote access status'
                try {
                    const err = await res.json()
                    msg = err?.detail || err?.message || msg
                } catch (e) { }
                throw new Error(msg)
            }
            return res.json()
        },
        updateRemoteAccessConfig: async (data: any) => {
            const res = await apiFetch(`${API_BASE}/admin/remote/config`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data || {}),
            })
            if (!res.ok) {
                let msg = 'Failed to update remote access config'
                try {
                    const err = await res.json()
                    msg = err?.detail || err?.message || msg
                } catch (e) { }
                throw new Error(msg)
            }
            return res.json()
        },
        pollRemoteAccessNow: async () => {
            const res = await apiFetch(`${API_BASE}/admin/remote/poll-now`, {
                method: 'POST',
            })
            if (!res.ok) {
                let msg = 'Failed to trigger remote poll'
                try {
                    const err = await res.json()
                    msg = err?.detail || err?.message || msg
                } catch (e) { }
                throw new Error(msg)
            }
            return res.json()
        },
        securityStatus: async () => {
            const res = await apiFetch(`${API_BASE}/admin/security/status`)
            if (!res.ok) {
                let msg = 'Failed to fetch security status'
                try {
                    const err = await res.json()
                    msg = err?.detail || err?.message || msg
                } catch (e) { }
                throw new Error(msg)
            }
            return res.json()
        },
        securityConfig: async () => {
            const res = await apiFetch(`${API_BASE}/admin/security/config`)
            if (!res.ok) {
                let msg = 'Failed to fetch security config'
                try {
                    const err = await res.json()
                    msg = err?.detail || err?.message || msg
                } catch (e) { }
                throw new Error(msg)
            }
            return res.json()
        },
        updateSecurityConfig: async (data: any) => {
            const res = await apiFetch(`${API_BASE}/admin/security/config`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data || {}),
            })
            if (!res.ok) {
                let msg = 'Failed to update security config'
                try {
                    const err = await res.json()
                    msg = err?.detail || err?.message || msg
                } catch (e) { }
                throw new Error(msg)
            }
            return res.json()
        },
        hardenSecurity: async (payload?: { force_disable_snapshot_mcp_fallback?: boolean }) => {
            const res = await apiFetch(`${API_BASE}/admin/security/harden`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload || {}),
            })
            if (!res.ok) {
                let msg = 'Failed to apply strict security preset'
                try {
                    const err = await res.json()
                    msg = err?.detail || err?.message || msg
                } catch (e) { }
                throw new Error(msg)
            }
            return res.json()
        },
        runSecurityAudit: async () => {
            const res = await apiFetch(`${API_BASE}/admin/security/audit/run`, {
                method: 'POST',
            })
            if (!res.ok) {
                let msg = 'Failed to run security audit'
                try {
                    const err = await res.json()
                    msg = err?.detail || err?.message || msg
                } catch (e) { }
                throw new Error(msg)
            }
            return res.json()
        },
        deduplicateConversations: async (payload: { dry_run?: boolean; include_messages?: boolean }) => {
            const res = await apiFetch(`${API_BASE}/admin/maintenance/conversations/deduplicate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            })
            if (!res.ok) {
                let msg = 'Failed to analyze/deduplicate conversations'
                try {
                    const err = await res.json()
                    msg = err?.detail || err?.message || msg
                } catch (e) { }
                throw new Error(msg)
            }
            return res.json()
        },
        purgeConversations: async (payload: { include_messages?: boolean }) => {
            const res = await apiFetch(`${API_BASE}/admin/maintenance/conversations/purge`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            })
            if (!res.ok) {
                let msg = 'Failed to purge conversations'
                try {
                    const err = await res.json()
                    msg = err?.detail || err?.message || msg
                } catch (e) { }
                throw new Error(msg)
            }
            return res.json()
        },
        deleteConversationsByIds: async (payload: { conversation_ids: string[]; include_messages?: boolean }) => {
            const res = await apiFetch(`${API_BASE}/admin/maintenance/conversations/delete-ids`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            })
            if (!res.ok) {
                let msg = 'Failed to delete selected conversations'
                try {
                    const err = await res.json()
                    msg = err?.detail || err?.message || msg
                } catch (e) { }
                throw new Error(msg)
            }
            return res.json()
        },
        backgroundStatus: async (params?: { includeHeavy?: boolean }) => {
            const url = new URL(`${API_BASE}/admin/background/status`)
            if (params?.includeHeavy) {
                url.searchParams.append('include_heavy', 'true')
            }
            const res = await apiFetch(url.toString())
            if (!res.ok) {
                let msg = 'Failed to fetch background status'
                try {
                    const err = await res.json()
                    msg = err?.detail || err?.message || msg
                } catch (e) { }
                throw new Error(msg)
            }
            return res.json()
        },
        runBackgroundAnalysis: async (payload?: {
            force_reanalyze?: boolean
            provider?: string
            conversation_ids?: string[]
            max_conversations?: number
            max_messages_per_conversation?: number
            max_candidates_per_conversation?: number
            max_new_memories?: number
            min_confidence?: number
            concurrency?: number
            wait_for_completion?: boolean
        }) => {
            const res = await apiFetch(`${API_BASE}/admin/background/analysis/run`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload || {}),
            })
            if (!res.ok) {
                let msg = 'Failed to run background analysis'
                try {
                    const err = await res.json()
                    msg = err?.detail || err?.message || msg
                } catch (e) { }
                throw new Error(msg)
            }
            return res.json()
        },
        listBackgroundAnalysisJobs: async (limit = 20) => {
            const url = new URL(`${API_BASE}/admin/background/analysis/jobs`)
            url.searchParams.append('limit', String(limit))
            const res = await apiFetch(url.toString())
            if (!res.ok) {
                let msg = 'Failed to list analysis jobs'
                try {
                    const err = await res.json()
                    msg = err?.detail || err?.message || msg
                } catch (e) { }
                throw new Error(msg)
            }
            return res.json()
        },
        cancelBackgroundAnalysisJob: async (jobId: string) => {
            const res = await apiFetch(`${API_BASE}/admin/background/analysis/jobs/${jobId}/cancel`, {
                method: 'POST',
            })
            if (!res.ok) {
                let msg = 'Failed to cancel analysis job'
                try {
                    const err = await res.json()
                    msg = err?.detail || err?.message || msg
                } catch (e) { }
                throw new Error(msg)
            }
            return res.json()
        }
    },
    dashboard: {
        stats: async () => {
            const res = await apiFetch(`${API_BASE}/memories/stats`)
            if (!res.ok) throw new Error('Failed to fetch stats')
            return res.json()
        },
        insights: async () => {
            const res = await apiFetch(`${API_BASE}/memories/insights`)
            if (!res.ok) throw new Error('Failed to fetch dashboard insights')
            return res.json()
        }
    },
    conflicts: {
        list: async () => {
            const res = await apiFetch(`${API_BASE}/conflicts/`)
            if (!res.ok) throw new Error('Failed to fetch conflicts')
            return res.json()
        },
        count: async () => {
            const res = await apiFetch(`${API_BASE}/conflicts/count`)
            if (!res.ok) throw new Error('Failed to fetch conflict count')
            return res.json()
        },
        resolve: async (id: string, resolution: string, mergedContent?: string) => {
            const res = await apiFetch(`${API_BASE}/conflicts/${id}/resolve`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ resolution, merged_content: mergedContent })
            })
            if (!res.ok) throw new Error('Failed to resolve conflict')
            return res.json()
        }
    }
}
