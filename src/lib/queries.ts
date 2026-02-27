import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api } from './api'

export const useMemories = (params?: { query?: string; limit?: number; offset?: number; status?: string }) =>
    useQuery({
        queryKey: ['memories', params],
        queryFn: () => api.memories.list(params),
        staleTime: 5 * 60 * 1000, // Cache for 5 minutes
    })

export const useMemory = (id: string | null) =>
    useQuery({
        queryKey: ['memory', id],
        queryFn: () => id ? api.memories.get(id) : null,
        enabled: !!id,
        staleTime: 5 * 60 * 1000,
    })

export const useMemoryHealth = (id: string | null) =>
    useQuery({
        queryKey: ['memory_health', id],
        queryFn: () => id ? api.memories.health(id) : null,
        enabled: !!id,
        staleTime: 60_000,
    })

// ...
export const useContextSnapshot = (context?: string) =>
    useQuery({
        queryKey: ['snapshot', context],
        queryFn: () => api.snapshot.get(context),
        staleTime: 30_000
    })

export const useCreateMemory = () => {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: api.memories.create,
        onSuccess: () => {
            toast.success('Memory created')
            qc.invalidateQueries({ queryKey: ['memories'] })
            qc.invalidateQueries({ queryKey: ['snapshot'] })
            qc.invalidateQueries({ queryKey: ['memory_graph'] })
            qc.invalidateQueries({ queryKey: ['memory_graph_overview'] })
            qc.invalidateQueries({ queryKey: ['dashboard_stats'] })
            qc.invalidateQueries({ queryKey: ['dashboard_insights'] })
            qc.invalidateQueries({ queryKey: ['conflicts'] })
            qc.invalidateQueries({ queryKey: ['conflict_count'] })
        },
        onError: () => toast.error('Failed to create memory'),
    })
}

export const useUpdateMemory = () => {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: ({ id, data }: { id: string; data: any }) => api.memories.update(id, data),
        onSuccess: () => {
            toast.success('Memory updated')
            qc.invalidateQueries({ queryKey: ['memories'] })
            qc.invalidateQueries({ queryKey: ['memory'] })
            qc.invalidateQueries({ queryKey: ['snapshot'] })
            qc.invalidateQueries({ queryKey: ['memory_graph'] })
            qc.invalidateQueries({ queryKey: ['memory_graph_overview'] })
            qc.invalidateQueries({ queryKey: ['dashboard_stats'] })
            qc.invalidateQueries({ queryKey: ['dashboard_insights'] })
        },
        onError: () => toast.error('Failed to update memory'),
    })
}

export const useDeleteMemory = () => {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: api.memories.delete,
        onSuccess: () => {
            toast.success('Memory deleted')
            qc.invalidateQueries({ queryKey: ['memories'] })
            qc.invalidateQueries({ queryKey: ['memory'] })
            qc.invalidateQueries({ queryKey: ['snapshot'] })
            qc.invalidateQueries({ queryKey: ['memory_graph'] })
            qc.invalidateQueries({ queryKey: ['memory_graph_overview'] })
            qc.invalidateQueries({ queryKey: ['dashboard_stats'] })
            qc.invalidateQueries({ queryKey: ['dashboard_insights'] })
            qc.invalidateQueries({ queryKey: ['conflicts'] })
            qc.invalidateQueries({ queryKey: ['conflict_count'] })
        },
        onError: () => toast.error('Failed to delete memory'),
    })
}

export const useSetMemoryStatus = () => {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: ({ id, status, source_llm, review_note }: { id: string; status: string; source_llm?: string; review_note?: string }) =>
            api.memories.setStatus(id, { status, source_llm, review_note }),
        onSuccess: (_data, variables) => {
            const label = variables.status === 'active' ? 'approved' : variables.status === 'rejected' ? 'rejected' : 'updated'
            toast.success(`Memory ${label}`)
            qc.invalidateQueries({ queryKey: ['memories'] })
            qc.invalidateQueries({ queryKey: ['memory'] })
            qc.invalidateQueries({ queryKey: ['snapshot'] })
            qc.invalidateQueries({ queryKey: ['memory_graph'] })
            qc.invalidateQueries({ queryKey: ['memory_graph_overview'] })
            qc.invalidateQueries({ queryKey: ['dashboard_stats'] })
            qc.invalidateQueries({ queryKey: ['dashboard_insights'] })
            qc.invalidateQueries({ queryKey: ['conflicts'] })
            qc.invalidateQueries({ queryKey: ['conflict_count'] })
        },
        onError: () => toast.error('Failed to update memory status'),
    })
}

export const useSetMemoryStatusBulk = () => {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: ({ ids, status, source_llm, review_note }: { ids: string[]; status: string; source_llm?: string; review_note?: string }) =>
            api.memories.setStatusBulk({ ids, status, source_llm, review_note }),
        onSuccess: (_data, variables) => {
            const label = variables.status === 'active' ? 'approved' : variables.status === 'rejected' ? 'rejected' : 'updated'
            toast.success(`${variables.ids.length} ${variables.ids.length === 1 ? 'memory' : 'memories'} ${label}`)
            qc.invalidateQueries({ queryKey: ['memories'] })
            qc.invalidateQueries({ queryKey: ['memory'] })
            qc.invalidateQueries({ queryKey: ['snapshot'] })
            qc.invalidateQueries({ queryKey: ['memory_graph'] })
            qc.invalidateQueries({ queryKey: ['memory_graph_overview'] })
            qc.invalidateQueries({ queryKey: ['dashboard_stats'] })
            qc.invalidateQueries({ queryKey: ['dashboard_insights'] })
            qc.invalidateQueries({ queryKey: ['conflicts'] })
            qc.invalidateQueries({ queryKey: ['conflict_count'] })
        },
        onError: () => toast.error('Failed to update memories'),
    })
}

export const useMemoryGraph = (id: string | null, depth = 2) =>
    useQuery({
        queryKey: ['memory_graph', id, depth],
        queryFn: () => id ? api.memories.graph(id, depth) : null,
        enabled: !!id,
        staleTime: 30_000
    })

export const useMemoryGraphOverview = (params?: {
    depth?: number
    centerMemoryId?: string
    category?: string
    edgeType?: string
    maxNodes?: number
    includeConversations?: boolean
}) =>
    useQuery({
        queryKey: ['memory_graph_overview', params],
        queryFn: () => api.memories.graphOverview(params),
        staleTime: 20_000
    })

export const useBackendHealth = () =>
    useQuery({
        queryKey: ['health'],
        queryFn: api.health,
        refetchInterval: 5000,
        retry: true
    })

export const useSnapshotToken = () =>
    useQuery({
        queryKey: ['snapshot_token'],
        queryFn: api.admin.snapshotToken,
        staleTime: Infinity,
        gcTime: Infinity,
        refetchOnMount: false,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
    })

export const useRotateToken = () => {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: api.admin.rotateToken,
        onSuccess: () => {
            toast.success('Token rotated — update your MCP clients')
            qc.invalidateQueries({ queryKey: ['config'] })
            qc.invalidateQueries({ queryKey: ['snapshot_token'] })
        },
        onError: () => toast.error('Failed to rotate token'),
    })
}

export const useDashboardStats = () =>
    useQuery({
        queryKey: ['dashboard_stats'],
        queryFn: api.dashboard.stats,
        refetchInterval: 10000
    })

export const useDashboardInsights = () =>
    useQuery({
        queryKey: ['dashboard_insights'],
        queryFn: api.dashboard.insights,
        staleTime: 60_000,
        refetchInterval: 5 * 60 * 1000,
    })

export const useConflicts = () =>
    useQuery({
        queryKey: ['conflicts'],
        queryFn: api.conflicts.list
    })

export const useConflictCount = () =>
    useQuery({
        queryKey: ['conflict_count'],
        queryFn: api.conflicts.count,
        refetchInterval: 15000
    })

export const useConfig = () =>
    useQuery({
        queryKey: ['config'],
        queryFn: api.admin.config,
        staleTime: Infinity,
        gcTime: Infinity,
        refetchOnMount: false,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false
    })

export const useSyncStatus = () =>
    useQuery({
        queryKey: ['sync_status'],
        queryFn: api.admin.syncStatus,
        refetchInterval: 15000,
        staleTime: 10_000,
    })

export const useUpdateSyncConfig = () => {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: api.admin.updateSyncConfig,
        onSuccess: () => {
            toast.success('Sync settings saved')
            qc.invalidateQueries({ queryKey: ['config'] })
            qc.invalidateQueries({ queryKey: ['sync_status'] })
        },
        onError: () => toast.error('Failed to save sync settings'),
    })
}

export const useUnlockSync = () => {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: api.admin.unlockSync,
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['sync_status'] })
        }
    })
}

export const useLockSync = () => {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: api.admin.lockSync,
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['sync_status'] })
        }
    })
}

export const useRunSync = () => {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: api.admin.runSync,
        onSuccess: () => {
            toast.success('Sync complete')
            qc.invalidateQueries({ queryKey: ['sync_status'] })
            qc.invalidateQueries({ queryKey: ['config'] })
            qc.invalidateQueries({ queryKey: ['memories'] })
            qc.invalidateQueries({ queryKey: ['memory'] })
            qc.invalidateQueries({ queryKey: ['conflicts'] })
            qc.invalidateQueries({ queryKey: ['conflict_count'] })
            qc.invalidateQueries({ queryKey: ['dashboard_stats'] })
            qc.invalidateQueries({ queryKey: ['dashboard_insights'] })
            qc.invalidateQueries({ queryKey: ['conversations'] })
        },
        onError: () => toast.error('Sync failed'),
    })
}

export const useInsightsConfig = () =>
    useQuery({
        queryKey: ['insights_config'],
        queryFn: api.admin.insightsConfig,
        staleTime: 60_000,
    })

export const useUpdateInsightsConfig = () => {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: api.admin.updateInsightsConfig,
        onSuccess: () => {
            toast.success('Insights settings saved')
            qc.invalidateQueries({ queryKey: ['insights_config'] })
            qc.invalidateQueries({ queryKey: ['dashboard_insights'] })
        },
        onError: () => toast.error('Failed to save insights settings'),
    })
}

export const useRemoteAccessStatus = () =>
    useQuery({
        queryKey: ['remote_access_status'],
        queryFn: api.admin.remoteAccessStatus,
        staleTime: 15_000,
        refetchInterval: 15_000,
    })

export const useUpdateRemoteAccessConfig = () => {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: api.admin.updateRemoteAccessConfig,
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['remote_access_status'] })
            qc.invalidateQueries({ queryKey: ['background_status'] })
            qc.invalidateQueries({ queryKey: ['config'] })
        },
    })
}

export const usePollRemoteAccessNow = () => {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: api.admin.pollRemoteAccessNow,
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['remote_access_status'] })
            qc.invalidateQueries({ queryKey: ['background_status'] })
        },
    })
}

export const useSecurityStatus = () =>
    useQuery({
        queryKey: ['security_status'],
        queryFn: api.admin.securityStatus,
        staleTime: 30_000,
        refetchInterval: 30_000,
    })

export const useSecurityConfig = () =>
    useQuery({
        queryKey: ['security_config'],
        queryFn: api.admin.securityConfig,
        staleTime: 30_000,
    })

export const useUpdateSecurityConfig = () => {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: api.admin.updateSecurityConfig,
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['security_config'] })
            qc.invalidateQueries({ queryKey: ['security_status'] })
            qc.invalidateQueries({ queryKey: ['background_status'] })
            qc.invalidateQueries({ queryKey: ['config'] })
        },
    })
}

export const useHardenSecurity = () => {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: api.admin.hardenSecurity,
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['security_config'] })
            qc.invalidateQueries({ queryKey: ['security_status'] })
            qc.invalidateQueries({ queryKey: ['background_status'] })
            qc.invalidateQueries({ queryKey: ['config'] })
        },
    })
}

export const useRunSecurityAudit = () => {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: api.admin.runSecurityAudit,
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['security_status'] })
            qc.invalidateQueries({ queryKey: ['background_status'] })
        },
    })
}

export const useDeduplicateConversations = () => {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (payload: { dry_run?: boolean; include_messages?: boolean }) =>
            api.admin.deduplicateConversations(payload),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['conversations'] })
            qc.invalidateQueries({ queryKey: ['conversation'] })
        },
    })
}

export const usePurgeConversations = () => {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (payload: { include_messages?: boolean }) => api.admin.purgeConversations(payload),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['conversations'] })
            qc.invalidateQueries({ queryKey: ['conversation'] })
            qc.invalidateQueries({ queryKey: ['dashboard_stats'] })
        },
    })
}

export const useDeleteConversationsByIds = () => {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (payload: { conversation_ids: string[]; include_messages?: boolean }) =>
            api.admin.deleteConversationsByIds(payload),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['conversations'] })
            qc.invalidateQueries({ queryKey: ['conversation'] })
            qc.invalidateQueries({ queryKey: ['dashboard_stats'] })
        },
    })
}

export const useBackgroundStatus = (params?: { includeHeavy?: boolean; refetchIntervalMs?: number; staleTimeMs?: number }) =>
    useQuery({
        queryKey: ['background_status', !!params?.includeHeavy],
        queryFn: () => api.admin.backgroundStatus(params),
        refetchInterval: params?.refetchIntervalMs ?? (params?.includeHeavy ? 10000 : 30000),
        staleTime: params?.staleTimeMs ?? (params?.includeHeavy ? 5000 : 15000),
    })

export const useRunBackgroundAnalysis = () => {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (payload?: {
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
        }) =>
            api.admin.runBackgroundAnalysis(payload),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['background_status'] })
            qc.invalidateQueries({ queryKey: ['memories'] })
            qc.invalidateQueries({ queryKey: ['memory'] })
            qc.invalidateQueries({ queryKey: ['dashboard_stats'] })
            qc.invalidateQueries({ queryKey: ['dashboard_insights'] })
            qc.invalidateQueries({ queryKey: ['conversations'] })
            qc.invalidateQueries({ queryKey: ['conversation'] })
            qc.invalidateQueries({ queryKey: ['conflicts'] })
            qc.invalidateQueries({ queryKey: ['conflict_count'] })
        },
    })
}

// ...

// Conversation Hooks
export const useConversations = (search?: string, limit?: number, offset?: number) =>
    useQuery({
        queryKey: ['conversations', search, limit, offset],
        queryFn: () => api.conversations.list({ search, limit, offset }),
        staleTime: 5 * 60 * 1000 // Cache for 5 minutes
    })

export const useUnifiedSearch = (params: {
    q?: string
    limit?: number
    include_memories?: boolean
    include_conversations?: boolean
    date_from?: string
    date_to?: string
    sources?: string[]
}, options?: { enabled?: boolean }) =>
    useQuery({
        queryKey: ['unified_search', params],
        queryFn: () => api.search.unified(params),
        staleTime: 20_000,
        enabled: options?.enabled ?? true,
    })

export const useMineConversationMemories = () => {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: (payload: {
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
        }) => api.conversations.mineMemories(payload),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['memories'] })
            qc.invalidateQueries({ queryKey: ['memory'] })
            qc.invalidateQueries({ queryKey: ['snapshot'] })
            qc.invalidateQueries({ queryKey: ['dashboard_stats'] })
            qc.invalidateQueries({ queryKey: ['dashboard_insights'] })
            qc.invalidateQueries({ queryKey: ['conversations'] })
            qc.invalidateQueries({ queryKey: ['conversation'] })
            qc.invalidateQueries({ queryKey: ['conflicts'] })
            qc.invalidateQueries({ queryKey: ['conflict_count'] })
        },
    })
}

export const useConversation = (id: string | null) =>
    useQuery({
        queryKey: ['conversation', id],
        queryFn: () => id ? api.conversations.get(id) : null,
        enabled: !!id,
        staleTime: 5 * 60 * 1000 // Cache for 5 minutes
    })

export const useDeleteConversation = () => {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: api.conversations.delete,
        onSuccess: () => {
            toast.success('Conversation deleted')
            qc.invalidateQueries({ queryKey: ['conversations'] })
            qc.invalidateQueries({ queryKey: ['conversation'] })
        },
        onError: () => toast.error('Failed to delete conversation'),
    })
}

export const useResolveConflict = () => {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: ({ id, resolution, mergedContent }: { id: string; resolution: string; mergedContent?: string }) =>
            api.conflicts.resolve(id, resolution, mergedContent),
        onSuccess: () => {
            toast.success('Conflict resolved')
            qc.invalidateQueries({ queryKey: ['conflicts'] })
            qc.invalidateQueries({ queryKey: ['conflict_count'] })
            qc.invalidateQueries({ queryKey: ['memories'] })
            qc.invalidateQueries({ queryKey: ['memory'] })
            qc.invalidateQueries({ queryKey: ['dashboard_stats'] })
            qc.invalidateQueries({ queryKey: ['dashboard_insights'] })
            qc.invalidateQueries({ queryKey: ['memory_graph'] })
            qc.invalidateQueries({ queryKey: ['memory_graph_overview'] })
        },
        onError: () => toast.error('Failed to resolve conflict'),
    })
}
