import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from './api'

export const useMemories = (params?: { query?: string; limit?: number }) =>
    useQuery({
        queryKey: ['memories', params],
        queryFn: () => api.memories.list(params),
        staleTime: 5 * 60 * 1000, // Cache for 5 minutes
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
            qc.invalidateQueries({ queryKey: ['memories'] })
            qc.invalidateQueries({ queryKey: ['snapshot'] })
        }
    })
}

export const useUpdateMemory = () => {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: ({ id, data }: { id: string; data: any }) => api.memories.update(id, data),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['memories'] })
            qc.invalidateQueries({ queryKey: ['snapshot'] })
        }
    })
}

export const useDeleteMemory = () => {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: api.memories.delete,
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['memories'] })
            qc.invalidateQueries({ queryKey: ['snapshot'] })
        }
    })
}

export const useBackendHealth = () =>
    useQuery({
        queryKey: ['health'],
        queryFn: api.health,
        refetchInterval: 5000,
        retry: true
    })

export const useRotateToken = () => {
    const qc = useQueryClient()
    return useMutation({
        mutationFn: api.admin.rotateToken,
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['config'] })
        }
    })
}

export const useDashboardStats = () =>
    useQuery({
        queryKey: ['dashboard_stats'],
        queryFn: api.dashboard.stats,
        refetchInterval: 10000
    })

export const useConflicts = () =>
    useQuery({
        queryKey: ['conflicts'],
        queryFn: api.conflicts.list
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

// ...

// Conversation Hooks
export const useConversations = (search?: string) =>
    useQuery({
        queryKey: ['conversations', search],
        queryFn: () => api.conversations.list({ search }),
        staleTime: 5 * 60 * 1000 // Cache for 5 minutes
    })

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
            qc.invalidateQueries({ queryKey: ['conversations'] })
        }
    })
}

export const useResolveConflict = () => {
    // ... same as before
    const qc = useQueryClient()
    return useMutation({
        mutationFn: ({ id, resolution, mergedContent }: { id: string; resolution: string; mergedContent?: string }) =>
            api.conflicts.resolve(id, resolution, mergedContent),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['conflicts'] })
            qc.invalidateQueries({ queryKey: ['memories'] })
            qc.invalidateQueries({ queryKey: ['dashboard_stats'] })
        }
    })
}
