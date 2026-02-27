import { create } from 'zustand'

interface AppStore {
    selectedMemoryId: string | null
    selectedConversationId: string | null
    conflictCount: number
    pendingCount: number
    backendStatus: 'starting' | 'ready' | 'error'
    activeContext: string | null
    currentView: 'dashboard' | 'memories' | 'graph' | 'conflicts' | 'settings' | 'conversations' | 'import' | 'add_memory' | 'ask'
    memoriesMode: 'all' | 'inbox'
    setSelectedMemory: (id: string | null) => void
    setSelectedConversation: (id: string | null) => void
    setConflictCount: (n: number) => void
    setPendingCount: (n: number) => void
    setBackendStatus: (s: AppStore['backendStatus']) => void
    setActiveContext: (c: string | null) => void
    setCurrentView: (v: 'dashboard' | 'memories' | 'graph' | 'conflicts' | 'settings' | 'conversations' | 'import' | 'add_memory' | 'ask') => void
    setMemoriesMode: (mode: 'all' | 'inbox') => void
}

export const useAppStore = create<AppStore>((set) => ({
    selectedMemoryId: null,
    selectedConversationId: null,
    conflictCount: 0,
    pendingCount: 0,
    backendStatus: 'starting',
    activeContext: null,
    currentView: 'dashboard',
    memoriesMode: 'all',
    setSelectedMemory: (id) => set({ selectedMemoryId: id }),
    setSelectedConversation: (id) => set({ selectedConversationId: id }),
    setConflictCount: (n) => set({ conflictCount: n }),
    setPendingCount: (n) => set({ pendingCount: n }),
    setBackendStatus: (s) => set({ backendStatus: s }),
    setActiveContext: (c) => set({ activeContext: c }),
    setCurrentView: (v) => set({ currentView: v }),
    setMemoriesMode: (mode) => set({ memoriesMode: mode }),
}))
