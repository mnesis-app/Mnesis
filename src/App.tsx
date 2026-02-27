import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React, { useState, lazy, Suspense, useEffect, useRef } from 'react'
import { Toaster } from 'sonner'
import { useBackendHealth, useConfig, useConflictCount, useBackgroundStatus } from './lib/queries'
import { MemoryList } from './components/MemoryList'
import { useAppStore } from './lib/store'
import {
    Search, LayoutDashboard, AlertTriangle, MessageSquare,
    Download, Plus, Settings, Database, Network, PanelLeft, Sparkles
} from 'lucide-react'
import { MemoryDetail } from './components/MemoryDetail'
import { Settings as SettingsView } from './components/Settings'
import { FirstSetup } from './components/FirstSetup'
import { Conflicts } from './components/Conflicts'
import { Conversations } from './components/Conversations'
import { ImportExport } from './components/ImportExport'
import { AddMemory } from './components/AddMemory'
import { Ask } from './components/Ask'
import { Onboarding } from './components/Onboarding'
import { MnesisLoader } from './components/ui/Loader'
import { MnesisWordmark, PalimpsestIcon } from './components/Logo'
import { SearchCommandDialog } from './components/SearchCommandDialog'
import { BackgroundJobsChip } from './components/BackgroundJobsChip'
import { LlmRuntimeAlertModal } from './components/LlmRuntimeAlertModal'
import { SyncBanner } from './components/SyncBanner'
import { confirmIssueStillActive, detectLlmRuntimeIssue, issueFingerprint, type LlmRuntimeIssue } from './lib/runtimeAlerts'

const queryClient = new QueryClient()
const DashboardView = lazy(() => import('./components/Dashboard').then((m) => ({ default: m.Dashboard })))
const GraphViewLazy = lazy(() => import('./components/GraphView').then((m) => ({ default: m.GraphView })))

// ─────────────────────────────────────────────────────────────────
// Error Boundary
// ─────────────────────────────────────────────────────────────────
class ErrorBoundary extends React.Component<
    { children: React.ReactNode },
    { hasError: boolean }
> {
    constructor(props: any) { super(props); this.state = { hasError: false } }
    static getDerivedStateFromError() { return { hasError: true } }
    componentDidCatch(e: Error, i: React.ErrorInfo) { console.error('[Mnesis ErrorBoundary]', e, i) }
    render() {
        if (this.state.hasError) return (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: '12px' }}>
                <p style={{ color: '#555', fontSize: '11px', letterSpacing: '0.1em', textTransform: 'uppercase', fontWeight: 700, margin: 0 }}>Something went wrong</p>
                <button onClick={() => this.setState({ hasError: false })}
                    style={{ fontSize: '10px', color: '#888', background: 'none', border: '1px solid #2a2a2a', borderRadius: '3px', padding: '5px 12px', cursor: 'pointer', fontFamily: 'inherit' }}>
                    Try again
                </button>
            </div>
        )
        return this.props.children
    }
}


// ─────────────────────────────────────────────────────────────────
// Nav item definitions
// ─────────────────────────────────────────────────────────────────
const navItems = [
    { view: 'dashboard', icon: <LayoutDashboard size={18} strokeWidth={2} />, label: 'Overview' },
    { view: 'memories', icon: <Database size={18} strokeWidth={2} />, label: 'Memories' },
    { view: 'ask', icon: <Sparkles size={18} strokeWidth={2} />, label: 'Ask' },
    { view: 'graph', icon: <Network size={18} strokeWidth={2} />, label: 'Graph' },
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
function Sidebar({ expanded }: { expanded: boolean }) {
    const { currentView, setCurrentView } = useAppStore()
    const { data: conflictCountData } = useConflictCount()
    const conflictCount = conflictCountData?.pending ?? 0

    const NavBtn = ({ view, icon, label }: { view: string; icon: React.ReactNode; label: string }) => {
        const active = currentView === view
        const showConflictBadge = view === 'conflicts' && conflictCount > 0
        return (
            <button
                onClick={() => setCurrentView(view as any)}
                title={label}
                style={{
                    width: '100%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: expanded ? 'flex-start' : 'center',
                    gap: expanded ? '10px' : 0,
                    position: 'relative',
                    padding: expanded ? '10px 10px' : '11px 6px',
                    border: active ? '1px solid #2c2c2c' : '1px solid transparent',
                    borderRadius: '4px',
                    cursor: 'pointer',
                    transition: 'all 160ms ease',
                    background: active ? '#121212' : 'transparent',
                    color: active ? '#e8e6e1' : '#444',
                    boxShadow: active ? 'inset 0 0 0 1px rgba(245,243,238,0.06), 0 0 10px rgba(0,0,0,0.28)' : 'none',
                    marginBottom: '2px',
                }}
                onMouseEnter={e => {
                    if (!active) {
                        const el = e.currentTarget as HTMLElement
                        el.style.color = '#a3a3a3'
                        el.style.background = '#0f0f0f'
                        el.style.borderColor = '#1f1f1f'
                    }
                }}
                onMouseLeave={e => {
                    if (!active) {
                        const el = e.currentTarget as HTMLElement
                        el.style.color = '#444'
                        el.style.background = 'transparent'
                        el.style.borderColor = 'transparent'
                    }
                }}
            >
                {icon}
                {expanded && (
                    <span
                        style={{
                            fontSize: '11px',
                            letterSpacing: '0.06em',
                            textTransform: 'uppercase',
                            color: active ? '#e8e6e1' : '#858585',
                            fontWeight: active ? 700 : 600,
                        }}
                    >
                        {label}
                    </span>
                )}
                {showConflictBadge && (
                    <span
                        style={{
                            position: 'absolute',
                            right: '8px',
                            top: '8px',
                            minWidth: '16px',
                            height: '16px',
                            borderRadius: '999px',
                            background: '#dc2626',
                            color: '#fff',
                            fontSize: '9px',
                            lineHeight: '16px',
                            fontWeight: 700,
                            textAlign: 'center',
                            padding: '0 4px',
                        }}
                    >
                        {conflictCount > 99 ? '99+' : conflictCount}
                    </span>
                )}
            </button>
        )
    }

    return (
        <div style={{
            width: expanded ? '228px' : '80px',
            height: '100%',
            background: '#0a0a0a',
            borderRight: '1px solid #1a1a1a',
            display: 'flex',
            flexDirection: 'column',
            alignItems: expanded ? 'stretch' : 'center',
            padding: `0 ${expanded ? '12px' : '8px'}`,
            zIndex: 20,
            flexShrink: 0,
            transition: 'width 200ms ease, padding 200ms ease',
        }}>
            {/* Traffic light spacer */}
            <div className="titlebar-drag" style={{ width: '100%', height: '40px', flexShrink: 0 }} />

            {/* Brand */}
            <div style={{ width: '100%', marginBottom: '16px' }}>
                <button
                    onClick={() => setCurrentView('dashboard')}
                    title="Mnesis"
                    style={{
                        width: '100%',
                        display: 'inline-flex',
                        alignItems: 'center',
                        justifyContent: expanded ? 'flex-start' : 'center',
                        gap: '8px',
                        padding: expanded ? '6px 8px' : '6px',
                        border: '1px solid transparent',
                        borderRadius: '6px',
                        background: 'transparent',
                        color: '#f5f3ee',
                        cursor: 'pointer',
                        minHeight: '40px',
                    }}
                >
                    {expanded ? (
                        <MnesisWordmark color="#f5f3ee" iconSize={24} textSize={18} gap={8} />
                    ) : (
                        <PalimpsestIcon color="#f5f3ee" style={{ width: 24, height: 24 }} />
                    )}
                </button>
            </div>

            {/* Top nav */}
            <div style={{ width: '100%', display: 'flex', flexDirection: 'column' }}>
                {expanded && (
                    <span
                        style={{
                            fontSize: '9px',
                            fontWeight: 600,
                            letterSpacing: '0.16em',
                            textTransform: 'uppercase',
                            color: '#565656',
                            marginBottom: '6px',
                            paddingLeft: '4px',
                        }}
                    >
                        Navigation
                    </span>
                )}
                {navItems.map(n => (
                    <NavBtn key={n.view} {...n} />
                ))}
            </div>

            <div style={{ flex: 1 }} />

            {/* Bottom nav */}
            <div style={{ width: '100%', display: 'flex', flexDirection: 'column', paddingBottom: '12px' }}>
                {expanded && (
                    <span
                        style={{
                            fontSize: '9px',
                            fontWeight: 600,
                            letterSpacing: '0.16em',
                            textTransform: 'uppercase',
                            color: '#565656',
                            marginBottom: '6px',
                            paddingLeft: '4px',
                        }}
                    >
                        Actions
                    </span>
                )}
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

const ViewLoading = () => (
    <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <MnesisLoader size="sm" />
    </div>
)

const DraggableFullscreen = ({ children }: { children: React.ReactNode }) => (
    <div style={{ height: '100vh', background: '#0a0a0a', display: 'flex', flexDirection: 'column' }}>
        <div className="titlebar-drag" style={{ width: '100%', height: '40px', flexShrink: 0 }} />
        <div className="titlebar-no-drag" style={{ flex: 1, minHeight: 0 }}>
            {children}
        </div>
    </div>
)

// ─────────────────────────────────────────────────────────────────
// Main Layout
// ─────────────────────────────────────────────────────────────────
function MainLayout() {
    const { data: health, isLoading: healthLoading } = useBackendHealth()
    const { data: config, isLoading: configLoading } = useConfig()
    const { data: backgroundStatus } = useBackgroundStatus({ includeHeavy: false, refetchIntervalMs: 3000, staleTimeMs: 1200 })
    const { selectedMemoryId, currentView, memoriesMode, setMemoriesMode, setCurrentView } = useAppStore()
    const isHealthy = health?.status === 'ok'
    const [searchQuery, setSearchQuery] = useState('')
    const [searchDialogOpen, setSearchDialogOpen] = useState(false)
    const [onboardingCompletedLocally, setOnboardingCompletedLocally] = useState(false)
    const [llmRuntimeIssue, setLlmRuntimeIssue] = useState<LlmRuntimeIssue | null>(null)
    const dismissedIssueFingerprintsRef = useRef<Set<string>>(new Set())
    const [sidebarExpanded, setSidebarExpanded] = useState<boolean>(() => {
        if (typeof window === 'undefined') return false
        const saved = window.localStorage.getItem('mnesis.sidebar.expanded')
        return saved === '1'
    })
    const shortcutLabel = (typeof navigator !== 'undefined' && /mac/i.test(navigator.platform)) ? '⌘K' : 'Ctrl+K'

    useEffect(() => {
        if (typeof window === 'undefined') return
        window.localStorage.setItem('mnesis.sidebar.expanded', sidebarExpanded ? '1' : '0')
    }, [sidebarExpanded])

    useEffect(() => {
        let cancelled = false
        const issue = detectLlmRuntimeIssue(backgroundStatus)
        if (!issue) {
            setLlmRuntimeIssue(null)
            return () => {
                cancelled = true
            }
        }
        const fingerprint = issueFingerprint(issue)
        if (dismissedIssueFingerprintsRef.current.has(fingerprint)) {
            return () => {
                cancelled = true
            }
        }

        void (async () => {
            const stillActive = await confirmIssueStillActive(issue)
            if (cancelled || !stillActive) {
                if (!cancelled) setLlmRuntimeIssue(null)
                return
            }
            setLlmRuntimeIssue(issue)
        })()

        return () => {
            cancelled = true
        }
    }, [backgroundStatus])

    const dismissLlmRuntimeIssue = () => {
        if (llmRuntimeIssue) {
            dismissedIssueFingerprintsRef.current.add(issueFingerprint(llmRuntimeIssue))
        }
        setLlmRuntimeIssue(null)
    }

    const openSettingsFromRuntimeIssue = () => {
        if (llmRuntimeIssue) {
            dismissedIssueFingerprintsRef.current.add(issueFingerprint(llmRuntimeIssue))
        }
        setLlmRuntimeIssue(null)
        setCurrentView('settings')
    }

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key.toLowerCase() !== 'k') return
            if (!event.metaKey && !event.ctrlKey) return
            event.preventDefault()
            setSearchDialogOpen((prev) => !prev)
        }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
    }, [])

    if (healthLoading) {
        return (
            <DraggableFullscreen>
                <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <MnesisLoader size="lg" detail="Connecting to backend..." />
                </div>
            </DraggableFullscreen>
        )
    }

    if (configLoading && isHealthy) {
        return (
            <DraggableFullscreen>
                <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <MnesisLoader size="lg" detail="Loading configuration..." />
                </div>
            </DraggableFullscreen>
        )
    }

    if (health && !health.model_ready) {
        return (
            <DraggableFullscreen>
                <FirstSetup onReady={() => window.location.reload()} />
            </DraggableFullscreen>
        )
    }

    if (config && (config as any).onboarding_completed === false && !onboardingCompletedLocally) {
        return (
            <DraggableFullscreen>
                <Onboarding onComplete={() => setOnboardingCompletedLocally(true)} />
            </DraggableFullscreen>
        )
    }

    // View label map
    const viewLabels: Record<string, string> = {
        dashboard: 'Overview', memories: 'Memories', graph: 'Graph', conversations: 'History',
        import: 'Import / Export', conflicts: 'Conflicts', add_memory: 'Add Memory',
        settings: 'Settings', ask: 'Ask',
    }

    return (
        <div style={{ display: 'flex', height: '100vh', background: '#0a0a0a', color: '#f5f3ee', overflow: 'hidden' }}>
            <Sidebar expanded={sidebarExpanded} />

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
                        <div className="titlebar-no-drag" style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                            <button
                                onClick={() => setSidebarExpanded((prev) => !prev)}
                                title={sidebarExpanded ? 'Collapse sidebar' : 'Expand sidebar'}
                                style={{
                                    width: '26px',
                                    height: '26px',
                                    border: '1px solid #202020',
                                    borderRadius: '4px',
                                    background: '#101010',
                                    color: '#8a8a8a',
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    cursor: 'pointer',
                                    flexShrink: 0,
                                }}
                            >
                                <PanelLeft size={14} />
                            </button>
                            <div style={{ width: '1px', height: '14px', background: '#202020', flexShrink: 0 }} />
                            <span
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
                        </div>
                        <div className="titlebar-no-drag" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <BackgroundJobsChip />
                            <button
                                onClick={() => setSearchDialogOpen(true)}
                                style={{
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: '6px',
                                    border: '1px solid #202020',
                                    background: '#101010',
                                    color: '#8a8a8a',
                                    borderRadius: '4px',
                                    padding: '4px 8px',
                                    fontSize: '10px',
                                    letterSpacing: '0.08em',
                                    textTransform: 'uppercase',
                                    cursor: 'pointer',
                                }}
                            >
                                <Search size={11} />
                                Search
                                <span style={{ color: '#5c5c5c' }}>{shortcutLabel}</span>
                            </button>
                            <div style={{
                                width: '6px', height: '6px', borderRadius: '50%',
                                background: isHealthy ? '#10b981' : '#ef4444',
                            boxShadow: isHealthy ? '0 0 8px rgba(16,185,129,0.5)' : 'none',
                        }} />
                    </div>
                </div>

                {/* Sync banner — shown when sync is not configured */}
                <SyncBanner />

                {/* Main content */}
                <div style={{ flex: 1, overflow: 'hidden', position: 'relative' }}>
                    {currentView === 'dashboard' && (
                        <ScrollableContent>
                            <ErrorBoundary>
                                <Suspense fallback={<ViewLoading />}>
                                    <DashboardView />
                                </Suspense>
                            </ErrorBoundary>
                        </ScrollableContent>
                    )}
                    {currentView === 'settings' && <ScrollableContent><SettingsView /></ScrollableContent>}
                    {currentView === 'conflicts' && <ScrollableContent><Conflicts /></ScrollableContent>}
                    {currentView === 'graph' && (
                        <ErrorBoundary>
                            <Suspense fallback={<ViewLoading />}>
                                <GraphViewLazy />
                            </Suspense>
                        </ErrorBoundary>
                    )}
                    {currentView === 'conversations' && <Conversations />}
                    {currentView === 'import' && <ScrollableContent><ImportExport /></ScrollableContent>}
                    {currentView === 'add_memory' && <ScrollableContent><AddMemory /></ScrollableContent>}
                    {currentView === 'ask' && <Ask />}

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
                                {/* Tab bar + search */}
                                <div style={{ borderBottom: '1px solid #141414' }}>
                                    {/* Flat underline tabs */}
                                    <div style={{ display: 'flex', alignItems: 'stretch', padding: '0 12px', gap: '0' }}>
                                        {(['all', 'inbox'] as const).map(m => (
                                            <button
                                                key={m}
                                                onClick={() => { setMemoriesMode(m); setSearchQuery('') }}
                                                style={{
                                                    border: 'none',
                                                    borderBottom: `2px solid ${memoriesMode === m ? '#f5f3ee' : 'transparent'}`,
                                                    background: 'none',
                                                    cursor: 'pointer',
                                                    padding: '10px 0',
                                                    marginRight: '18px',
                                                    fontSize: '9px',
                                                    fontWeight: 800,
                                                    letterSpacing: '0.14em',
                                                    textTransform: 'uppercase',
                                                    color: memoriesMode === m ? '#c0c0c0' : '#383838',
                                                    fontFamily: 'inherit',
                                                    transition: 'color 150ms ease, border-color 150ms ease',
                                                }}
                                                onMouseEnter={e => { if (memoriesMode !== m) e.currentTarget.style.color = '#777' }}
                                                onMouseLeave={e => { if (memoriesMode !== m) e.currentTarget.style.color = '#383838' }}
                                            >
                                                {m === 'all' ? 'All' : 'Inbox'}
                                            </button>
                                        ))}
                                    </div>
                                    {/* Search */}
                                    <div style={{ position: 'relative', padding: '8px 12px' }}>
                                        <Search
                                            size={12}
                                            style={{ position: 'absolute', left: '22px', top: '50%', transform: 'translateY(-50%)', color: '#2e2e2e', pointerEvents: 'none' }}
                                        />
                                        <input
                                            style={{
                                                width: '100%',
                                                background: 'transparent',
                                                border: '1px solid #1a1a1a',
                                                borderRadius: '3px',
                                                padding: '6px 10px 6px 28px',
                                                fontSize: '11px',
                                                color: '#888',
                                                outline: 'none',
                                                fontFamily: 'inherit',
                                                boxSizing: 'border-box',
                                                transition: 'border-color 150ms ease',
                                            }}
                                            placeholder={memoriesMode === 'inbox' ? 'Filter inbox…' : 'Search memories…'}
                                            value={searchQuery}
                                            onChange={e => setSearchQuery(e.target.value)}
                                            onFocus={e => (e.target.style.borderColor = '#2a2a2a')}
                                            onBlur={e => (e.target.style.borderColor = '#1a1a1a')}
                                        />
                                    </div>
                                </div>
                                <MemoryList searchQuery={searchQuery} mode={memoriesMode} />
                            </div>

                            {/* Right: detail */}
                            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', background: '#080808' }}>
                                {selectedMemoryId ? (
                                    <ErrorBoundary>
                                        <MemoryDetail />
                                    </ErrorBoundary>
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
            <SearchCommandDialog open={searchDialogOpen} onOpenChange={setSearchDialogOpen} />
            <LlmRuntimeAlertModal
                issue={llmRuntimeIssue}
                isOpen={!!llmRuntimeIssue}
                onDismiss={dismissLlmRuntimeIssue}
                onOpenSettings={openSettingsFromRuntimeIssue}
            />
        </div>
    )
}

function App() {
    return (
        <QueryClientProvider client={queryClient}>
            <MainLayout />
            <Toaster
                position="bottom-right"
                theme="dark"
                toastOptions={{
                    style: {
                        background: '#111',
                        border: '1px solid #222',
                        color: '#e8e6e1',
                        fontSize: '12px',
                        fontFamily: 'inherit',
                    },
                }}
            />
        </QueryClientProvider>
    )
}

export default App
