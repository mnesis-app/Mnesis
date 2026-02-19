import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import { useMemories, useBackendHealth, useConfig } from './lib/queries'
import { useAppStore } from './lib/store'
import {
    Search, LayoutDashboard, AlertTriangle, MessageSquare,
    Download, Plus, Settings, Database
} from 'lucide-react'
import { MemoryDetail } from './components/MemoryDetail'
import { Settings as SettingsView } from './components/Settings'
import { FirstSetup } from './components/FirstSetup'
import { Dashboard } from './components/Dashboard'
import { Conflicts } from './components/Conflicts'
import { Conversations } from './components/Conversations'
import { ImportExport } from './components/ImportExport'
import { AddMemory } from './components/AddMemory'
import { Onboarding } from './components/Onboarding'
import { MnesisLoader } from './components/ui/Loader'
import { PalimpsestIcon } from './components/Logo'

const queryClient = new QueryClient()

// ─────────────────────────────────────────────────────────────────
// Memory List
// ─────────────────────────────────────────────────────────────────
function MemoryList({ searchQuery }: { searchQuery: string }) {
    const { data: memories, isLoading } = useMemories({ query: searchQuery })
    const { setSelectedMemory } = useAppStore()

    if (isLoading) return (
        <div className="flex justify-center p-8">
            <MnesisLoader size="sm" />
        </div>
    )

    return (
        <div className="flex-1 overflow-auto p-3 space-y-1.5">
            {memories?.map((mem: any) => (
                <div
                    key={mem.id}
                    onClick={() => setSelectedMemory(mem.id)}
                    style={{
                        padding: '12px 14px',
                        background: 'transparent',
                        border: '1px solid #1e1e1e',
                        borderRadius: '4px',
                        cursor: 'pointer',
                        transition: 'border-color 150ms ease, background 150ms ease',
                    }}
                    onMouseEnter={e => {
                        (e.currentTarget as HTMLElement).style.borderColor = '#333'
                            ; (e.currentTarget as HTMLElement).style.background = '#0d0d0d'
                    }}
                    onMouseLeave={e => {
                        (e.currentTarget as HTMLElement).style.borderColor = '#1e1e1e'
                            ; (e.currentTarget as HTMLElement).style.background = 'transparent'
                    }}
                >
                    <p style={{ fontSize: '13px', color: '#d0d0d0', lineHeight: 1.5, margin: 0, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                        {mem.content}
                    </p>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '8px' }}>
                        <span style={{
                            fontSize: '9px', fontWeight: 600, letterSpacing: '0.12em',
                            textTransform: 'uppercase', color: '#555',
                            border: '1px solid #2a2a2a', borderRadius: '2px',
                            padding: '2px 6px',
                        }}>
                            {mem.category}
                        </span>
                        <span style={{ fontSize: '10px', color: '#444' }}>
                            {new Date(mem.created_at).toLocaleDateString()}
                        </span>
                    </div>
                </div>
            ))}
            {(!memories || memories.length === 0) && (
                <div style={{ textAlign: 'center', color: '#333', fontSize: '11px', padding: '40px 20px', fontWeight: 500, letterSpacing: '0.04em', textTransform: 'uppercase' }}>
                    {searchQuery ? 'No results' : 'No memories'}
                </div>
            )}
        </div>
    )
}

// ─────────────────────────────────────────────────────────────────
// Nav item definitions
// ─────────────────────────────────────────────────────────────────
const navItems = [
    { view: 'dashboard', icon: <LayoutDashboard size={18} strokeWidth={2} />, label: 'Overview' },
    { view: 'memories', icon: <Database size={18} strokeWidth={2} />, label: 'Memories' },
    { view: 'conversations', icon: <MessageSquare size={18} strokeWidth={2} />, label: 'History' },
    { view: 'import', icon: <Download size={18} strokeWidth={2} />, label: 'Import' },
    { view: 'conflicts', icon: <AlertTriangle size={18} strokeWidth={2} />, label: 'Conflicts' },
]
const navBottom = [
    { view: 'add_memory', icon: <Plus size={18} strokeWidth={2} />, label: 'Add' },
    { view: 'settings', icon: <Settings size={18} strokeWidth={2} />, label: 'Settings' },
]

// ─────────────────────────────────────────────────────────────────
// Sidebar
// ─────────────────────────────────────────────────────────────────
function Sidebar() {
    const { currentView, setCurrentView } = useAppStore()

    const NavBtn = ({ view, icon, label }: { view: string; icon: React.ReactNode; label: string }) => {
        const active = currentView === view
        return (
            <button
                onClick={() => setCurrentView(view as any)}
                title={label}
                style={{
                    width: '100%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    padding: '11px 6px',
                    border: 'none',
                    borderRadius: '4px',
                    cursor: 'pointer',
                    transition: 'all 150ms ease',
                    background: active ? '#f5f3ee' : 'transparent',
                    color: active ? '#0a0a0a' : '#444',
                    marginBottom: '2px',
                }}
                onMouseEnter={e => {
                    if (!active) (e.currentTarget as HTMLElement).style.color = '#888'
                }}
                onMouseLeave={e => {
                    if (!active) (e.currentTarget as HTMLElement).style.color = '#444'
                }}
            >
                {icon}
            </button>
        )
    }

    return (
        <div style={{
            width: '80px',
            height: '100%',
            background: '#0a0a0a',
            borderRight: '1px solid #1a1a1a',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            padding: '0 8px',
            zIndex: 20,
            flexShrink: 0,
        }}>
            {/* Traffic light spacer */}
            <div className="titlebar-drag" style={{ width: '100%', height: '40px', flexShrink: 0 }} />


            {/* Logo */}
            <div style={{ marginBottom: '20px', display: 'flex', justifyContent: 'center' }}>
                <PalimpsestIcon color="#f5f3ee" style={{ width: 28, height: 28 }} />
            </div>

            {/* Top nav */}
            <div style={{ width: '100%', display: 'flex', flexDirection: 'column' }}>
                {navItems.map(n => (
                    <NavBtn key={n.view} {...n} />
                ))}
            </div>

            <div style={{ flex: 1 }} />

            {/* Bottom nav */}
            <div style={{ width: '100%', display: 'flex', flexDirection: 'column', paddingBottom: '12px' }}>
                {navBottom.map(n => (
                    <NavBtn key={n.view} {...n} />
                ))}
            </div>
        </div>
    )
}

// Helper scrollable wrapper
const ScrollableContent = ({ children }: { children: React.ReactNode }) => (
    <div style={{ width: '100%', height: '100%', overflowY: 'auto' }}>
        {children}
    </div>
)

// ─────────────────────────────────────────────────────────────────
// Main Layout
// ─────────────────────────────────────────────────────────────────
function MainLayout() {
    const { data: health, isLoading: healthLoading } = useBackendHealth()
    const { data: config, isLoading: configLoading } = useConfig()
    const { selectedMemoryId, currentView } = useAppStore()
    const isHealthy = health?.status === 'ok'
    const [searchQuery, setSearchQuery] = useState('')

    if (healthLoading) {
        return (
            <div style={{ height: '100vh', background: '#0a0a0a', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <MnesisLoader size="lg" detail="Connecting to backend..." />
            </div>
        )
    }

    if (configLoading && isHealthy) {
        return (
            <div style={{ height: '100vh', background: '#0a0a0a', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <MnesisLoader size="lg" detail="Loading configuration..." />
            </div>
        )
    }

    if (health && !health.model_ready) {
        return <FirstSetup onReady={() => window.location.reload()} />
    }

    if (config && (config as any).onboarding_completed === false) {
        return <Onboarding onComplete={() => window.location.reload()} />
    }

    // View label map
    const viewLabels: Record<string, string> = {
        dashboard: 'Overview', memories: 'Memories', conversations: 'History',
        import: 'Import / Export', conflicts: 'Conflicts', add_memory: 'Add Memory',
        settings: 'Settings',
    }

    return (
        <div style={{ display: 'flex', height: '100vh', background: '#0a0a0a', color: '#f5f3ee', overflow: 'hidden' }}>
            <Sidebar />

            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                {/* Top bar */}
                <div
                    className="titlebar-drag"
                    style={{
                        height: '40px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        padding: '0 20px',
                        borderBottom: '1px solid #1a1a1a',
                        flexShrink: 0,
                        background: '#0a0a0a',
                    }}
                >
                    <span
                        className="titlebar-no-drag"
                        style={{
                            fontWeight: 600,
                            fontSize: '10px',
                            letterSpacing: '0.2em',
                            textTransform: 'uppercase',
                            color: '#333',
                        }}
                    >
                        {viewLabels[currentView] ?? currentView}
                    </span>
                    <div className="titlebar-no-drag" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <div style={{
                            width: '6px', height: '6px', borderRadius: '50%',
                            background: isHealthy ? '#10b981' : '#ef4444',
                            boxShadow: isHealthy ? '0 0 8px rgba(16,185,129,0.5)' : 'none',
                        }} />
                    </div>
                </div>

                {/* Main content */}
                <div style={{ flex: 1, overflow: 'hidden', position: 'relative' }}>
                    {currentView === 'dashboard' && <ScrollableContent><Dashboard /></ScrollableContent>}
                    {currentView === 'settings' && <ScrollableContent><SettingsView /></ScrollableContent>}
                    {currentView === 'conflicts' && <ScrollableContent><Conflicts /></ScrollableContent>}
                    {currentView === 'conversations' && <Conversations />}
                    {currentView === 'import' && <ScrollableContent><ImportExport /></ScrollableContent>}
                    {currentView === 'add_memory' && <ScrollableContent><AddMemory /></ScrollableContent>}

                    {currentView === 'memories' && (
                        <div style={{ display: 'flex', height: '100%' }}>
                            {/* Left column: list */}
                            <div style={{
                                width: '300px',
                                borderRight: '1px solid #1a1a1a',
                                display: 'flex',
                                flexDirection: 'column',
                                flexShrink: 0,
                            }}>
                                {/* Search */}
                                <div style={{ padding: '12px', borderBottom: '1px solid #1a1a1a' }}>
                                    <div style={{ position: 'relative' }}>
                                        <Search
                                            size={14}
                                            style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: '#333' }}
                                        />
                                        <input
                                            style={{
                                                width: '100%',
                                                background: '#080808',
                                                border: '1px solid #1e1e1e',
                                                borderRadius: '4px',
                                                padding: '7px 10px 7px 30px',
                                                fontSize: '12px',
                                                color: '#888',
                                                outline: 'none',
                                                fontFamily: 'inherit',
                                                boxSizing: 'border-box',
                                            }}
                                            placeholder="Search memories..."
                                            value={searchQuery}
                                            onChange={e => setSearchQuery(e.target.value)}
                                            onFocus={e => (e.target.style.borderColor = '#2a2a2a')}
                                            onBlur={e => (e.target.style.borderColor = '#1e1e1e')}
                                        />
                                    </div>
                                </div>
                                <MemoryList searchQuery={searchQuery} />
                            </div>

                            {/* Right: detail */}
                            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', background: '#080808' }}>
                                {selectedMemoryId ? (
                                    <MemoryDetail />
                                ) : (
                                    <div style={{ textAlign: 'center', maxWidth: '320px', padding: '40px' }}>
                                        <PalimpsestIcon color="#1e1e1e" style={{ width: 48, height: 48, margin: '0 auto 20px' }} />
                                        <p style={{ fontSize: '10px', fontWeight: 500, letterSpacing: '0.1em', textTransform: 'uppercase', color: '#2a2a2a', margin: 0 }}>
                                            Select a memory
                                        </p>
                                    </div>
                                )}
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}

function App() {
    return (
        <QueryClientProvider client={queryClient}>
            <MainLayout />
        </QueryClientProvider>
    )
}

export default App
