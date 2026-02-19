import { create } from 'zustand'

interface AppStore {
    selectedMemoryId: string | null
    conflictCount: number
    pendingCount: number
    backendStatus: 'starting' | 'ready' | 'error'
    activeContext: string | null
    currentView: 'dashboard' | 'memories' | 'conflicts' | 'settings' | 'conversations' | 'import' | 'add_memory'
    setSelectedMemory: (id: string | null) => void
    setConflictCount: (n: number) => void
    setPendingCount: (n: number) => void
    setBackendStatus: (s: AppStore['backendStatus']) => void
    setActiveContext: (c: string | null) => void
    setCurrentView: (v: 'dashboard' | 'memories' | 'conflicts' | 'settings' | 'conversations' | 'import' | 'add_memory') => void
}

export const useAppStore = create<AppStore>((set) => ({
    selectedMemoryId: null,
    conflictCount: 0,
    pendingCount: 0,
    backendStatus: 'starting',
    activeContext: null,
    currentView: 'dashboard',
    setSelectedMemory: (id) => set({ selectedMemoryId: id }),
    setConflictCount: (n) => set({ conflictCount: n }),
    setPendingCount: (n) => set({ pendingCount: n }),
    setBackendStatus: (s) => set({ backendStatus: s }),
    setActiveContext: (c) => set({ activeContext: c }),
    setCurrentView: (v) => set({ currentView: v }),
}))
