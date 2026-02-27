import { useEffect, useMemo, useRef, useState } from 'react'
import { CalendarDays, CornerDownLeft, Database, Loader2, MessageSquare, Search } from 'lucide-react'
import { useUnifiedSearch } from '../lib/queries'
import { useAppStore } from '../lib/store'

type SearchCommandDialogProps = {
    open: boolean
    onOpenChange: (next: boolean) => void
}

type TimeRange = 'all' | '7d' | '30d' | '90d'
const DEFAULT_PROVIDER_FILTERS = ['chatgpt', 'claude', 'gemini', 'openai', 'anthropic', 'ollama', 'manual', 'imported']

function formatDate(value: any): string {
    if (!value) return ''
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return ''
    return date.toLocaleString()
}

function normalizeProvider(value: any): string {
    const raw = String(value || '').trim().toLowerCase()
    if (!raw) return 'unknown'
    if (raw.includes('chatgpt') || raw === 'gpt') return 'chatgpt'
    if (raw.includes('openai')) return 'openai'
    if (raw.includes('claude')) return 'claude'
    if (raw.includes('anthropic')) return 'anthropic'
    if (raw.includes('gemini')) return 'gemini'
    if (raw.includes('ollama')) return 'ollama'
    if (raw.includes('manual')) return 'manual'
    if (raw.includes('import')) return 'imported'
    const tokens = raw.split(/[^a-z0-9]+/).filter(Boolean)
    return tokens[tokens.length - 1] || 'unknown'
}

export function SearchCommandDialog({ open, onOpenChange }: SearchCommandDialogProps) {
    const { setCurrentView, setSelectedMemory, setSelectedConversation, setMemoriesMode } = useAppStore()
    const [query, setQuery] = useState('')
    const [includeMemories, setIncludeMemories] = useState(true)
    const [includeConversations, setIncludeConversations] = useState(true)
    const [timeRange, setTimeRange] = useState<TimeRange>('all')
    const [selectedProviders, setSelectedProviders] = useState<string[]>([])
    const [selectedIndex, setSelectedIndex] = useState(0)
    const inputRef = useRef<HTMLInputElement | null>(null)

    const isTypeFilterActive = includeMemories || includeConversations
    const trimmedQuery = query.trim()
    const dateFrom = useMemo(() => {
        if (timeRange === 'all') return undefined
        const now = new Date()
        const from = new Date(now)
        const days = timeRange === '7d' ? 7 : timeRange === '30d' ? 30 : 90
        from.setDate(now.getDate() - days)
        return from.toISOString()
    }, [timeRange])
    const dateTo = useMemo(() => {
        if (timeRange === 'all') return undefined
        return new Date().toISOString()
    }, [timeRange])

    const params = useMemo(
        () => ({
            q: trimmedQuery,
            limit: 24,
            include_memories: includeMemories,
            include_conversations: includeConversations,
            date_from: dateFrom,
            date_to: dateTo,
            sources: selectedProviders.length > 0 ? selectedProviders : undefined,
        }),
        [trimmedQuery, includeMemories, includeConversations, dateFrom, dateTo, selectedProviders]
    )
    const { data, isLoading, error } = useUnifiedSearch(params, {
        enabled: open && trimmedQuery.length > 0 && isTypeFilterActive,
    })
    const rows = Array.isArray(data?.items) ? data.items : []
    const discoveredProviders = useMemo(() => {
        const out = new Set<string>()
        for (const item of rows) {
            const provider = normalizeProvider(item?.source_llm)
            if (provider && provider !== 'unknown') out.add(provider)
        }
        return Array.from(out).sort()
    }, [rows])
    const providerOptions = useMemo(() => {
        const out = new Set<string>(DEFAULT_PROVIDER_FILTERS)
        for (const provider of discoveredProviders) out.add(provider)
        return Array.from(out)
    }, [discoveredProviders])
    const isMac = typeof navigator !== 'undefined' && /mac/i.test(navigator.platform)
    const shortcutLabel = isMac ? '⌘K' : 'Ctrl+K'

    const openResult = (item: any) => {
        if (!item) return
        if (item?.type === 'memory') {
            setMemoriesMode('all')
            setSelectedMemory(String(item.id))
            setCurrentView('memories')
            onOpenChange(false)
            return
        }
        if (item?.type === 'conversation') {
            setSelectedConversation(String(item.id))
            setCurrentView('conversations')
            onOpenChange(false)
        }
    }

    useEffect(() => {
        if (!open) {
            setQuery('')
            setIncludeMemories(true)
            setIncludeConversations(true)
            setTimeRange('all')
            setSelectedProviders([])
            setSelectedIndex(0)
            return
        }
        const timer = window.setTimeout(() => inputRef.current?.focus(), 20)
        return () => window.clearTimeout(timer)
    }, [open])

    useEffect(() => {
        if (!open) return
        if (rows.length === 0) {
            setSelectedIndex(0)
            return
        }
        setSelectedIndex((prev) => Math.max(0, Math.min(prev, rows.length - 1)))
    }, [open, rows])

    useEffect(() => {
        if (!open) return
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                event.preventDefault()
                onOpenChange(false)
                return
            }
            if (event.key === 'ArrowDown') {
                event.preventDefault()
                if (!rows.length) return
                setSelectedIndex((prev) => (prev + 1) % rows.length)
                return
            }
            if (event.key === 'ArrowUp') {
                event.preventDefault()
                if (!rows.length) return
                setSelectedIndex((prev) => (prev - 1 + rows.length) % rows.length)
                return
            }
            if (event.key === 'Enter') {
                const item = rows[selectedIndex]
                if (!item) return
                event.preventDefault()
                openResult(item)
            }
        }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
    }, [open, onOpenChange, rows, selectedIndex])

    if (!open) return null

    return (
        <div
            className="titlebar-no-drag"
            onMouseDown={(e) => {
                if (e.currentTarget === e.target) onOpenChange(false)
            }}
            style={{
                position: 'fixed',
                inset: 0,
                background: 'rgba(4, 4, 4, 0.72)',
                backdropFilter: 'blur(7px)',
                zIndex: 1200,
                display: 'flex',
                justifyContent: 'center',
                alignItems: 'flex-start',
                padding: '72px 24px 24px',
            }}
        >
            <div
                style={{
                    width: 'min(760px, 100%)',
                    border: '1px solid #222',
                    borderRadius: '10px',
                    background: '#0b0b0b',
                    boxShadow: '0 20px 60px rgba(0,0,0,0.55)',
                    overflow: 'hidden',
                }}
            >
                <div
                    style={{
                        display: 'grid',
                        gap: '10px',
                        borderBottom: '1px solid #181818',
                        padding: '12px 14px',
                        background: '#0d0d0d',
                    }}
                >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                        <Search size={14} color="#7a7a7a" />
                        <input
                            ref={inputRef}
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            placeholder="Search memories and conversations..."
                            style={{
                                border: 'none',
                                outline: 'none',
                                background: 'transparent',
                                color: '#e5e5e5',
                                width: '100%',
                                fontSize: '13px',
                                fontFamily: 'inherit',
                            }}
                        />
                        <span
                            style={{
                                border: '1px solid #2a2a2a',
                                borderRadius: '4px',
                                padding: '2px 6px',
                                fontSize: '10px',
                                color: '#7b7b7b',
                                letterSpacing: '0.08em',
                                textTransform: 'uppercase',
                            }}
                        >
                            {shortcutLabel}
                        </span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                        <button
                            onClick={() => setIncludeMemories((prev) => !prev)}
                            style={{
                                border: `1px solid ${includeMemories ? '#27405a' : '#262626'}`,
                                background: includeMemories ? '#0e1822' : '#101010',
                                color: includeMemories ? '#9cc8f7' : '#7a7a7a',
                                borderRadius: '999px',
                                padding: '4px 10px',
                                fontSize: '10px',
                                letterSpacing: '0.08em',
                                textTransform: 'uppercase',
                                cursor: 'pointer',
                            }}
                        >
                            Memories
                        </button>
                        <button
                            onClick={() => setIncludeConversations((prev) => !prev)}
                            style={{
                                border: `1px solid ${includeConversations ? '#1f4f41' : '#262626'}`,
                                background: includeConversations ? '#0d1c18' : '#101010',
                                color: includeConversations ? '#8ee3c7' : '#7a7a7a',
                                borderRadius: '999px',
                                padding: '4px 10px',
                                fontSize: '10px',
                                letterSpacing: '0.08em',
                                textTransform: 'uppercase',
                                cursor: 'pointer',
                            }}
                        >
                            Conversations
                        </button>
                        <span style={{ width: 1, height: 14, background: '#1d1d1d', margin: '0 2px' }} />
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '5px', color: '#686868', fontSize: '10px', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
                            <CalendarDays size={11} />
                            Range
                        </span>
                        {([
                            ['all', 'All'],
                            ['7d', '7d'],
                            ['30d', '30d'],
                            ['90d', '90d'],
                        ] as const).map(([value, label]) => {
                            const active = timeRange === value
                            return (
                                <button
                                    key={value}
                                    onClick={() => setTimeRange(value)}
                                    style={{
                                        border: `1px solid ${active ? '#2f2f2f' : '#242424'}`,
                                        background: active ? '#161616' : '#101010',
                                        color: active ? '#d0d0d0' : '#7a7a7a',
                                        borderRadius: '999px',
                                        padding: '4px 10px',
                                        fontSize: '10px',
                                        letterSpacing: '0.08em',
                                        textTransform: 'uppercase',
                                        cursor: 'pointer',
                                    }}
                                >
                                    {label}
                                </button>
                            )
                        })}
                        <span style={{ width: 1, height: 14, background: '#1d1d1d', margin: '0 2px' }} />
                        <span style={{ color: '#686868', fontSize: '10px', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
                            Source
                        </span>
                        {providerOptions.map((provider) => {
                            const active = selectedProviders.includes(provider)
                            return (
                                <button
                                    key={provider}
                                    onClick={() => {
                                        setSelectedProviders((prev) =>
                                            prev.includes(provider) ? prev.filter((p) => p !== provider) : [...prev, provider]
                                        )
                                    }}
                                    style={{
                                        border: `1px solid ${active ? '#2f2f2f' : '#242424'}`,
                                        background: active ? '#1a1a1a' : '#101010',
                                        color: active ? '#d0d0d0' : '#7a7a7a',
                                        borderRadius: '999px',
                                        padding: '4px 10px',
                                        fontSize: '10px',
                                        letterSpacing: '0.08em',
                                        textTransform: 'uppercase',
                                        cursor: 'pointer',
                                    }}
                                >
                                    {provider}
                                </button>
                            )
                        })}
                    </div>
                </div>

                <div style={{ maxHeight: '420px', overflowY: 'auto', background: '#090909' }}>
                    {!isTypeFilterActive && (
                        <div style={{ padding: '20px 16px', color: '#fca5a5', fontSize: '11px', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
                            Enable at least one filter: memories or conversations
                        </div>
                    )}
                    {!trimmedQuery && (
                        <div style={{ padding: '20px 16px', color: '#6a6a6a', fontSize: '11px', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
                            Start typing to search across memories and conversations
                        </div>
                    )}
                    {trimmedQuery && isLoading && (
                        <div style={{ display: 'flex', justifyContent: 'center', padding: '24px' }}>
                            <Loader2 size={16} style={{ animation: 'spin 1s linear infinite', color: '#666' }} />
                        </div>
                    )}
                    {trimmedQuery && !isLoading && error && (
                        <div style={{ padding: '16px', color: '#fca5a5', fontSize: '12px' }}>
                            {(error as Error)?.message || 'Search failed'}
                        </div>
                    )}
                    {trimmedQuery && !isLoading && !error && rows.length === 0 && (
                        <div style={{ padding: '20px 16px', color: '#6a6a6a', fontSize: '11px', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
                            No results
                        </div>
                    )}
                    {trimmedQuery && !isLoading && !error && rows.map((item: any, index: number) => {
                        const selected = index === selectedIndex
                        return (
                            <button
                                key={`${item.type}:${item.id}:${index}`}
                                onClick={() => openResult(item)}
                                onMouseEnter={() => setSelectedIndex(index)}
                                style={{
                                    width: '100%',
                                    border: 'none',
                                    borderBottom: '1px solid #141414',
                                    background: selected ? '#121212' : 'transparent',
                                    textAlign: 'left',
                                    padding: '11px 13px',
                                    color: '#d9d9d9',
                                    cursor: 'pointer',
                                }}
                            >
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
                                    {item.type === 'memory' ? <Database size={12} color="#60a5fa" /> : <MessageSquare size={12} color="#34d399" />}
                                    <span style={{ fontSize: '10px', color: '#7a7a7a', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
                                        {item.type}
                                    </span>
                                    <span
                                        style={{
                                            fontSize: '9px',
                                            color: '#6f6f6f',
                                            border: '1px solid #252525',
                                            borderRadius: '999px',
                                            padding: '1px 6px',
                                            letterSpacing: '0.08em',
                                            textTransform: 'uppercase',
                                        }}
                                    >
                                        {normalizeProvider(item.source_llm)}
                                    </span>
                                    <span style={{ fontSize: '10px', color: '#525252' }}>{formatDate(item.date)}</span>
                                    <span style={{ marginLeft: 'auto', fontSize: '10px', color: '#5c5c5c' }}>
                                        {(Number(item.score || 0) * 100).toFixed(0)}%
                                    </span>
                                </div>
                                <div style={{ fontSize: '12px', color: '#ececec', lineHeight: 1.45 }}>
                                    {item.title}
                                </div>
                                {item.excerpt && (
                                    <div style={{ marginTop: '5px', fontSize: '11px', color: '#7a7a7a', lineHeight: 1.45 }}>
                                        {item.excerpt}
                                    </div>
                                )}
                            </button>
                        )
                    })}
                </div>

                <div
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        borderTop: '1px solid #181818',
                        padding: '8px 12px',
                        color: '#636363',
                        fontSize: '10px',
                        letterSpacing: '0.08em',
                        textTransform: 'uppercase',
                        background: '#0d0d0d',
                    }}
                >
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
                        <CornerDownLeft size={11} />
                        Open result
                    </span>
                    <span>↑ ↓ Navigate · Esc close</span>
                </div>
            </div>
        </div>
    )
}
