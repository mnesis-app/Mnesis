// Resolve the API base URL dynamically:
// - In Electron (production): use the dynamically-selected port via contextBridge
// - In browser dev (Vite only): fall back to 7860
function getBaseUrl(): string {
    if (typeof window !== 'undefined' && (window as any).electronAPI?.getRestPort) {
        const port = (window as any).electronAPI.getRestPort()
        return `http://127.0.0.1:${port}`
    }
    return 'http://127.0.0.1:7860'
}

const BASE_URL = getBaseUrl()
const API_BASE = `${BASE_URL}/api/v1`

export const api = {
    memories: {
        list: async (params?: { query?: string; limit?: number }) => {
            const url = new URL(`${API_BASE}/memories/`)
            if (params?.query) url.searchParams.append('query', params.query)
            if (params?.limit) url.searchParams.append('limit', params.limit.toString())

            const res = await fetch(url.toString())
            if (!res.ok) throw new Error('Failed to fetch memories')
            return res.json()
        },
        create: async (data: any) => {
            const res = await fetch(`${API_BASE}/memories/`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            })
            if (!res.ok) throw new Error('Failed to create memory')
            return res.json()
        },
        update: async (id: string, data: any) => {
            const res = await fetch(`${API_BASE}/memories/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            })
            if (!res.ok) throw new Error('Failed to update memory')
            return res.json()
        },
        delete: async (id: string) => {
            const res = await fetch(`${API_BASE}/memories/${id}`, {
                method: 'DELETE',
            })
            if (!res.ok) throw new Error('Failed to delete memory')
            return res.json()
        }
    },
    snapshot: {
        get: async (context?: string) => {
            const url = new URL(`${API_BASE}/memories/snapshot`)
            if (context) url.searchParams.append('context', context)
            const res = await fetch(url.toString())
            if (!res.ok) throw new Error('Failed to fetch snapshot')
            return res.json()
        },
        getText: async (token: string) => {
            const url = new URL(`${API_BASE}/snapshot/text`)
            url.searchParams.append('token', token)
            const res = await fetch(url.toString())
            if (!res.ok) throw new Error('Failed to fetch plain-text snapshot')
            return res.text()
        }
    },
    conversations: {
        list: async (params?: { search?: string }) => {
            if (params?.search) {
                const searchUrl = new URL(`${API_BASE}/conversations/search`)
                searchUrl.searchParams.append('query', params.search)
                const res = await fetch(searchUrl.toString())
                if (!res.ok) throw new Error('Failed to search conversations')
                return res.json()
            }
            const res = await fetch(`${API_BASE}/conversations/`)
            if (!res.ok) throw new Error('Failed to list conversations')
            return res.json()
        },
        get: async (id: string) => {
            const res = await fetch(`${API_BASE}/conversations/${id}`)
            if (!res.ok) throw new Error('Failed to get conversation')
            return res.json()
        },
        delete: async (id: string) => {
            const res = await fetch(`${API_BASE}/conversations/${id}`, { method: 'DELETE' })
            if (!res.ok) throw new Error('Failed to delete conversation')
            return res.json()
        }
    },
    import: {
        upload: async (formData: FormData) => {
            const res = await fetch(`${API_BASE}/import/upload`, {
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
            const res = await fetch(`${API_BASE}/import/confirm/${previewId}`, { method: 'POST' })
            if (!res.ok) throw new Error('Failed to confirm import')
            return res.json()
        },
        export: async () => {
            const res = await fetch(`${API_BASE}/import/export`)
            if (!res.ok) throw new Error('Export failed')
            return res.blob()
        }
    },
    health: async () => {
        const res = await fetch(`${BASE_URL}/health`)
        if (!res.ok) throw new Error('Backend unhealthy')
        return res.json()
    },
    admin: {
        config: async () => {
            const res = await fetch(`${API_BASE}/admin/config`)
            if (!res.ok) throw new Error('Failed to fetch config')
            return res.json()
        },
        completeOnboarding: async () => {
            const res = await fetch(`${API_BASE}/admin/onboarding-complete`, { method: 'POST' })
            if (!res.ok) throw new Error('Failed to complete onboarding')
            return res.json()
        },
        rotateToken: async () => {
            const res = await fetch(`${API_BASE}/admin/snapshot-token/rotate`, { method: 'POST' })
            if (!res.ok) throw new Error('Failed to rotate token')
            return res.json()
        }
    },
    dashboard: {
        stats: async () => {
            const res = await fetch(`${API_BASE}/memories/stats`)
            if (!res.ok) throw new Error('Failed to fetch stats')
            return res.json()
        }
    },
    conflicts: {
        list: async () => {
            const res = await fetch(`${API_BASE}/conflicts/`)
            if (!res.ok) throw new Error('Failed to fetch conflicts')
            return res.json()
        },
        resolve: async (id: string, resolution: string, mergedContent?: string) => {
            const res = await fetch(`${API_BASE}/conflicts/${id}/resolve`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ resolution, merged_content: mergedContent })
            })
            if (!res.ok) throw new Error('Failed to resolve conflict')
            return res.json()
        }
    }
}
