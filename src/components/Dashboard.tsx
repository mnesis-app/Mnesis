import { useDashboardInsights, useConflictCount } from '../lib/queries'
import { useAppStore } from '../lib/store'
import { ArrowRight, Loader2, TrendingUp, Sparkles, AlertTriangle, Inbox } from 'lucide-react'
import {
    ResponsiveContainer,
    AreaChart,
    Area,
    CartesianGrid,
    XAxis,
    YAxis,
    Tooltip,
    Legend,
    BarChart,
    Bar,
} from 'recharts'

// ─── Tokens ────────────────────────────────────────────────────────────────

const LABEL: React.CSSProperties = {
    fontSize: '9px',
    fontWeight: 700,
    letterSpacing: '0.18em',
    textTransform: 'uppercase',
    color: '#333',
}

const DIVIDER: React.CSSProperties = {
    border: 'none',
    borderTop: '1px solid #111',
    margin: '28px 0',
}

const CATEGORY_ORDER = ['identity', 'preferences', 'skills', 'relationships', 'projects', 'history', 'working']

const CATEGORY_COLORS: Record<string, string> = {
    identity: '#60a5fa',
    preferences: '#a78bfa',
    skills: '#10b981',
    relationships: '#f59e0b',
    projects: '#22d3ee',
    history: '#f97316',
    working: '#ef4444',
}

const FALLBACK_COLORS = ['#eab308', '#14b8a6', '#f43f5e', '#8b5cf6', '#38bdf8', '#fb7185']

function getCategoryKeys(rows: Array<Record<string, any>>): string[] {
    const seen = new Set<string>()
    for (const row of rows) {
        for (const key of Object.keys(row)) {
            if (key !== 'date' && key !== 'total') seen.add(key)
        }
    }
    return Array.from(seen).sort((a, b) => {
        const ia = CATEGORY_ORDER.indexOf(a)
        const ib = CATEGORY_ORDER.indexOf(b)
        if (ia === -1 && ib === -1) return a.localeCompare(b)
        if (ia === -1) return 1
        if (ib === -1) return -1
        return ia - ib
    })
}

function colorForCategory(key: string, index: number): string {
    return CATEGORY_COLORS[key] || FALLBACK_COLORS[index % FALLBACK_COLORS.length]
}

function dayLabel(value: string): string {
    if (typeof value !== 'string' || value.length < 10) return String(value || '')
    return value.slice(5)
}

// ─── KPI Card ──────────────────────────────────────────────────────────────

function KpiCard({
    label,
    value,
    sub,
    accent,
}: {
    label: string
    value: string | number
    sub?: string
    accent?: string
}) {
    return (
        <div
            style={{
                padding: '20px 24px 16px',
                borderRight: '1px solid #111',
                display: 'flex',
                flexDirection: 'column',
                gap: '10px',
                transition: 'background 150ms ease',
                cursor: 'default',
            }}
            onMouseEnter={e => (e.currentTarget.style.background = '#0d0d0d')}
            onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
        >
            <span style={LABEL}>{label}</span>
            <span
                style={{
                    fontSize: '32px',
                    fontWeight: 800,
                    lineHeight: 1,
                    letterSpacing: '-0.03em',
                    color: accent || '#f5f3ee',
                }}
            >
                {value}
            </span>
            {sub && <span style={{ fontSize: '11px', color: '#444', marginTop: '-4px' }}>{sub}</span>}
        </div>
    )
}

// ─── Chart Tooltip ─────────────────────────────────────────────────────────

function ChartTooltip({ active, payload, label }: any) {
    if (!active || !payload || payload.length === 0) return null
    return (
        <div
            style={{
                background: '#0b0b0b',
                border: '1px solid #27272a',
                borderRadius: '4px',
                padding: '8px 10px',
                minWidth: '140px',
            }}
        >
            <p style={{ margin: '0 0 6px', color: '#d4d4d8', fontSize: '10px', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
                {label}
            </p>
            {payload.map((entry: any, idx: number) => (
                <p key={`${entry.name}-${idx}`} style={{ margin: '0 0 3px', color: entry.color || '#a1a1aa', fontSize: '11px' }}>
                    {entry.name}: {entry.value}
                </p>
            ))}
        </div>
    )
}

// ─── Memory Layers Bar ─────────────────────────────────────────────────────

function MemoryLayersBar({ levels }: { levels: Record<string, number> }) {
    const semantic = Number(levels.semantic || 0)
    const episodic = Number(levels.episodic || 0)
    const working = Number(levels.working || 0)
    const total = semantic + episodic + working || 1

    const segments = [
        { key: 'semantic', label: 'Semantic', value: semantic, color: '#60a5fa' },
        { key: 'episodic', label: 'Episodic', value: episodic, color: '#a78bfa' },
        { key: 'working', label: 'Working', value: working, color: '#10b981' },
    ]

    return (
        <div>
            <p style={{ ...LABEL, marginBottom: '14px' }}>Memory Layers</p>
            {/* Bar */}
            <div
                style={{
                    height: '5px',
                    borderRadius: '3px',
                    overflow: 'hidden',
                    display: 'flex',
                    background: '#111',
                    marginBottom: '10px',
                }}
            >
                {segments.map(s => (
                    <div
                        key={s.key}
                        style={{
                            width: `${(s.value / total) * 100}%`,
                            background: s.color,
                            transition: 'width 400ms ease',
                        }}
                    />
                ))}
            </div>
            {/* Labels */}
            <div style={{ display: 'flex', gap: '24px' }}>
                {segments.map(s => (
                    <div key={s.key} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <div style={{ width: '6px', height: '6px', borderRadius: '50%', background: s.color, flexShrink: 0 }} />
                        <span style={{ fontSize: '10px', color: '#555', textTransform: 'uppercase', letterSpacing: '0.1em' }}>
                            {s.label}
                        </span>
                        <span style={{ fontSize: '13px', fontWeight: 700, color: s.color }}>{s.value}</span>
                        <span style={{ fontSize: '10px', color: '#333' }}>
                            {((s.value / total) * 100).toFixed(0)}%
                        </span>
                    </div>
                ))}
            </div>
        </div>
    )
}

// ─── Action Banner ─────────────────────────────────────────────────────────

function ActionBanner({
    icon,
    accentColor,
    title,
    description,
    ctaLabel,
    onClick,
}: {
    icon: React.ReactNode
    accentColor: string
    title: string
    description: string
    ctaLabel: string
    onClick: () => void
}) {
    return (
        <div
            style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: '16px',
                padding: '12px 16px',
                border: '1px solid #1e1e1e',
                borderLeft: `2px solid ${accentColor}`,
                borderRadius: '4px',
                background: '#080808',
            }}
        >
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', minWidth: 0 }}>
                <span style={{ color: accentColor, flexShrink: 0 }}>{icon}</span>
                <div style={{ minWidth: 0 }}>
                    <p style={{ fontSize: '12px', fontWeight: 600, color: '#e8e6e1', margin: 0 }}>{title}</p>
                    <p style={{ fontSize: '10px', color: '#444', margin: '2px 0 0', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {description}
                    </p>
                </div>
            </div>
            <button
                onClick={onClick}
                style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '5px',
                    flexShrink: 0,
                    border: '1px solid #2a2a2a',
                    background: 'transparent',
                    color: '#d0d0d0',
                    borderRadius: '4px',
                    padding: '6px 12px',
                    cursor: 'pointer',
                    fontSize: '9px',
                    fontWeight: 700,
                    letterSpacing: '0.12em',
                    textTransform: 'uppercase',
                    fontFamily: 'inherit',
                    transition: 'border-color 150ms, color 150ms',
                }}
                onMouseEnter={e => {
                    const el = e.currentTarget as HTMLButtonElement
                    el.style.borderColor = accentColor
                    el.style.color = '#f5f3ee'
                }}
                onMouseLeave={e => {
                    const el = e.currentTarget as HTMLButtonElement
                    el.style.borderColor = '#2a2a2a'
                    el.style.color = '#d0d0d0'
                }}
            >
                {ctaLabel} <ArrowRight size={10} />
            </button>
        </div>
    )
}

// ─── Suggestion Card ───────────────────────────────────────────────────────

function SuggestionCard({ item }: { item: any }) {
    const conf = Number(item.confidence_score || 0)
    const confColor = conf >= 0.8 ? '#10b981' : conf >= 0.6 ? '#f59e0b' : '#666'
    const content = String(item.content || item.content_preview || '')
    const { setCurrentView, setMemoriesMode } = useAppStore()

    return (
        <div
            onClick={() => { setMemoriesMode('inbox'); setCurrentView('memories') }}
            style={{
                minWidth: '240px',
                maxWidth: '240px',
                border: '1px solid #1a1a1a',
                borderRadius: '4px',
                padding: '12px 14px',
                background: '#080808',
                display: 'flex',
                flexDirection: 'column',
                gap: '8px',
                flexShrink: 0,
                transition: 'border-color 150ms',
                cursor: 'pointer',
            }}
            onMouseEnter={e => (e.currentTarget.style.borderColor = '#2a2a2a')}
            onMouseLeave={e => (e.currentTarget.style.borderColor = '#1a1a1a')}
            title={content}
        >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '8px' }}>
                <p style={{ margin: 0, fontSize: '12px', color: '#c8c8c8', lineHeight: 1.45, display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                    {content}
                </p>
                <span style={{ fontSize: '10px', fontWeight: 700, color: confColor, flexShrink: 0 }}>
                    {(conf * 100).toFixed(0)}%
                </span>
            </div>
            <div style={{ display: 'flex', gap: '6px', alignItems: 'center', marginTop: 'auto' }}>
                <span style={{
                    fontSize: '8px', fontWeight: 700, letterSpacing: '0.12em',
                    textTransform: 'uppercase', color: '#555',
                    border: '1px solid #222', borderRadius: '2px',
                    padding: '2px 5px',
                }}>
                    {item.category}
                </span>
                <span style={{
                    fontSize: '8px', fontWeight: 700, letterSpacing: '0.12em',
                    textTransform: 'uppercase', color: '#444',
                }}>
                    {item.level}
                </span>
            </div>
        </div>
    )
}

// ─── Dashboard ─────────────────────────────────────────────────────────────

export function Dashboard() {
    const { data: insightsData, isLoading } = useDashboardInsights()
    const { data: conflictCountData } = useConflictCount()
    const { setCurrentView, setMemoriesMode } = useAppStore()

    if (isLoading) {
        return (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '60vh' }}>
                <Loader2 size={18} style={{ animation: 'spin 1s linear infinite', color: '#3f3f46' }} />
            </div>
        )
    }

    const summary = insightsData?.analytics?.summary
    const pendingConflicts = Number(conflictCountData?.pending || 0)
    const categorySeries = (insightsData?.analytics?.category_evolution || []) as Array<Record<string, any>>
    const domainSeries = insightsData?.analytics?.domain_activity || []
    const recurrentTopics = insightsData?.analytics?.recurrent_topics || []
    const autoSuggestions = insightsData?.analytics?.auto_memory_suggestions || []
    const autoSuggestionsPending = Number(summary?.auto_suggestions_pending || autoSuggestions.length || 0)
    const conflictResolutionRate = summary?.conflict_resolution_rate ?? 0

    const recentCategoryRows = categorySeries.slice(-14)
    const categoryKeys = getCategoryKeys(recentCategoryRows)
    const categoryLegendCount = Math.min(6, categoryKeys.length)

    const recentDomainRows = domainSeries.slice(-14).map((row: any) => ({
        ...row,
        label: dayLabel(row.date),
    }))

    const hasActions = pendingConflicts > 0 || autoSuggestionsPending > 0

    return (
        <div style={{ padding: '32px 40px 48px', width: '100%' }}>

            {/* ── KPI Row ───────────────────────────────────────────────── */}
            <div
                style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(5, 1fr)',
                    border: '1px solid #1a1a1a',
                    borderRadius: '4px',
                    overflow: 'hidden',
                    marginBottom: '24px',
                }}
            >
                <KpiCard label="Total Memories" value={summary?.total_memories ?? '—'} />
                <KpiCard
                    label="Conflict Resolution"
                    value={`${(conflictResolutionRate || 0).toFixed(1)}%`}
                    sub={`${summary?.conflicts_resolved ?? 0} of ${summary?.conflicts_total ?? 0} resolved`}
                />
                <KpiCard
                    label="Top Writer"
                    value={summary?.most_active_llm?.name ?? '—'}
                    sub={`${summary?.most_active_llm?.writes ?? 0} writes`}
                />
                <KpiCard
                    label="Pending Conflicts"
                    value={pendingConflicts}
                    accent={pendingConflicts > 0 ? '#ef4444' : undefined}
                />
                <div
                    style={{
                        padding: '20px 24px 16px',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '10px',
                        transition: 'background 150ms ease',
                        cursor: 'default',
                        borderRight: 'none',
                    }}
                    onMouseEnter={e => (e.currentTarget.style.background = '#0d0d0d')}
                    onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                >
                    <span style={LABEL}>Auto Suggestions</span>
                    <span
                        style={{
                            fontSize: '32px',
                            fontWeight: 800,
                            lineHeight: 1,
                            letterSpacing: '-0.03em',
                            color: autoSuggestionsPending > 0 ? '#22d3ee' : '#f5f3ee',
                        }}
                    >
                        {autoSuggestionsPending}
                    </span>
                    <span style={{ fontSize: '11px', color: '#444', marginTop: '-4px' }}>Pending review</span>
                </div>
            </div>

            {/* ── Memory Layers ─────────────────────────────────────────── */}
            <div
                style={{
                    border: '1px solid #1a1a1a',
                    borderRadius: '4px',
                    padding: '20px 24px',
                    marginBottom: '24px',
                    background: '#080808',
                }}
            >
                <MemoryLayersBar levels={summary?.levels || {}} />
            </div>

            {/* ── Action Banners ────────────────────────────────────────── */}
            {hasActions && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '24px' }}>
                    {pendingConflicts > 0 && (
                        <ActionBanner
                            icon={<AlertTriangle size={14} />}
                            accentColor="#ef4444"
                            title={`${pendingConflicts} unresolved conflict${pendingConflicts !== 1 ? 's' : ''}`}
                            description="Resolve contradictions to improve retrieval quality"
                            ctaLabel="Resolve"
                            onClick={() => setCurrentView('conflicts')}
                        />
                    )}
                    {autoSuggestionsPending > 0 && (
                        <ActionBanner
                            icon={<Inbox size={14} />}
                            accentColor="#22d3ee"
                            title={`${autoSuggestionsPending} auto-suggested memor${autoSuggestionsPending !== 1 ? 'ies' : 'y'} pending review`}
                            description="Conversation signals analyzed in background — validate to enrich your memory graph"
                            ctaLabel="Review"
                            onClick={() => {
                                setMemoriesMode('inbox')
                                setCurrentView('memories')
                            }}
                        />
                    )}
                </div>
            )}

            {/* ── Charts ────────────────────────────────────────────────── */}
            <hr style={DIVIDER} />
            <div
                style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr 1fr',
                    gap: '16px',
                    marginBottom: '24px',
                }}
            >
                <div
                    style={{
                        background: '#080808',
                        border: '1px solid #1a1a1a',
                        borderRadius: '4px',
                        padding: '18px',
                    }}
                >
                    <p style={{ ...LABEL, marginBottom: '16px' }}>Category Evolution  ·  Last 14 days</p>
                    <div style={{ height: 220 }}>
                        <ResponsiveContainer width="100%" height="100%">
                            <AreaChart data={recentCategoryRows} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                                <CartesianGrid stroke="#131313" vertical={false} />
                                <XAxis dataKey="date" tickFormatter={dayLabel} tick={{ fill: '#444', fontSize: 10 }} stroke="#1a1a1a" />
                                <YAxis tick={{ fill: '#444', fontSize: 10 }} stroke="#1a1a1a" width={28} />
                                <Tooltip content={<ChartTooltip />} />
                                <Legend wrapperStyle={{ fontSize: 10, color: '#555', paddingTop: '8px' }} />
                                {categoryKeys.slice(0, categoryLegendCount).map((key, idx) => (
                                    <Area
                                        key={key}
                                        type="monotone"
                                        dataKey={key}
                                        stackId="cats"
                                        stroke={colorForCategory(key, idx)}
                                        fill={colorForCategory(key, idx)}
                                        fillOpacity={0.2}
                                        strokeWidth={1.5}
                                        name={key}
                                    />
                                ))}
                            </AreaChart>
                        </ResponsiveContainer>
                    </div>
                </div>

                <div
                    style={{
                        background: '#080808',
                        border: '1px solid #1a1a1a',
                        borderRadius: '4px',
                        padding: '18px',
                    }}
                >
                    <p style={{ ...LABEL, marginBottom: '16px' }}>Domain Activity  ·  Last 14 days</p>
                    <div style={{ height: 220 }}>
                        <ResponsiveContainer width="100%" height="100%">
                            <BarChart data={recentDomainRows} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                                <CartesianGrid stroke="#131313" vertical={false} />
                                <XAxis dataKey="label" tick={{ fill: '#444', fontSize: 10 }} stroke="#1a1a1a" />
                                <YAxis tick={{ fill: '#444', fontSize: 10 }} stroke="#1a1a1a" width={28} />
                                <Tooltip content={<ChartTooltip />} />
                                <Legend wrapperStyle={{ fontSize: 10, color: '#555', paddingTop: '8px' }} />
                                <Bar dataKey="code" stackId="d" fill="#10b981" radius={[2, 2, 0, 0]} />
                                <Bar dataKey="business" stackId="d" fill="#0ea5e9" radius={[2, 2, 0, 0]} />
                                <Bar dataKey="personal" stackId="d" fill="#a78bfa" radius={[2, 2, 0, 0]} />
                                <Bar dataKey="casual" stackId="d" fill="#f59e0b" radius={[2, 2, 0, 0]} />
                            </BarChart>
                        </ResponsiveContainer>
                    </div>
                </div>
            </div>

            {/* ── Intel Row ─────────────────────────────────────────────── */}
            <hr style={DIVIDER} />
            <div
                style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr 1fr',
                    gap: '16px',
                    marginBottom: '24px',
                }}
            >
                {/* AI Insights */}
                <div
                    style={{
                        background: '#080808',
                        border: '1px solid #1a1a1a',
                        borderRadius: '4px',
                        padding: '18px',
                    }}
                >
                    <p style={{ ...LABEL, marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <Sparkles size={10} /> AI Insights
                    </p>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                        {(insightsData?.insights || []).map((insight: any, idx: number) => {
                            const accentColors = ['#22d3ee', '#10b981', '#a78bfa', '#f59e0b']
                            const ac = accentColors[idx % accentColors.length]
                            return (
                                <div
                                    key={`${insight.title}-${idx}`}
                                    style={{
                                        borderLeft: `2px solid ${ac}`,
                                        paddingLeft: '12px',
                                        paddingTop: '8px',
                                        paddingBottom: '8px',
                                        paddingRight: '8px',
                                    }}
                                >
                                    <p style={{ margin: '0 0 3px', color: '#d4d4d8', fontSize: '12px', fontWeight: 600 }}>{insight.title}</p>
                                    <p style={{ margin: 0, color: '#555', fontSize: '11px', lineHeight: 1.5 }}>{insight.detail}</p>
                                </div>
                            )
                        })}
                        {(!insightsData?.insights || insightsData.insights.length === 0) && (
                            <p style={{ margin: 0, fontSize: '11px', color: '#333' }}>No insights generated yet.</p>
                        )}
                    </div>
                    {insightsData?.generated_at && (
                        <p style={{ margin: '14px 0 0', fontSize: '10px', color: '#2a2a2a' }}>
                            {insightsData?.source} · {new Date(insightsData.generated_at).toLocaleString()}
                        </p>
                    )}
                </div>

                {/* Recurrent Topics + Most Referenced */}
                <div
                    style={{
                        background: '#080808',
                        border: '1px solid #1a1a1a',
                        borderRadius: '4px',
                        padding: '18px',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '0',
                    }}
                >
                    <p style={{ ...LABEL, marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <TrendingUp size={10} /> Recurrent Topics
                    </p>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '5px', marginBottom: '20px' }}>
                        {recurrentTopics.map((topic: any) => (
                            <span
                                key={topic.topic}
                                style={{
                                    border: '1px solid #222',
                                    borderRadius: '999px',
                                    padding: '3px 8px',
                                    fontSize: '10px',
                                    color: '#777',
                                    transition: 'border-color 150ms, color 150ms',
                                    cursor: 'default',
                                }}
                                onMouseEnter={e => {
                                    const el = e.currentTarget as HTMLSpanElement
                                    el.style.borderColor = '#444'
                                    el.style.color = '#aaa'
                                }}
                                onMouseLeave={e => {
                                    const el = e.currentTarget as HTMLSpanElement
                                    el.style.borderColor = '#222'
                                    el.style.color = '#777'
                                }}
                            >
                                {topic.topic} <span style={{ color: '#444', fontSize: '9px' }}>{topic.count}</span>
                            </span>
                        ))}
                        {recurrentTopics.length === 0 && (
                            <span style={{ fontSize: '11px', color: '#333' }}>No recurrent topic detected.</span>
                        )}
                    </div>

                    <p style={{ ...LABEL, marginBottom: '10px' }}>Most Referenced</p>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '1px' }}>
                        {(summary?.top_referenced_memories || []).slice(0, 3).map((row: any, idx: number) => (
                            <div
                                key={row.id}
                                style={{
                                    padding: '9px 0',
                                    borderBottom: idx < 2 ? '1px solid #0f0f0f' : 'none',
                                }}
                            >
                                <p style={{ margin: '0 0 3px', color: '#888', fontSize: '11px', lineHeight: 1.4 }}>
                                    {row.content_preview}
                                </p>
                                <p style={{ margin: 0, color: '#2e2e2e', fontSize: '10px' }}>
                                    {row.reference_count} refs · {row.category}
                                </p>
                            </div>
                        ))}
                        {(!summary?.top_referenced_memories || summary.top_referenced_memories.length === 0) && (
                            <p style={{ margin: 0, fontSize: '11px', color: '#333' }}>No references yet.</p>
                        )}
                    </div>
                </div>
            </div>

            {/* ── Auto Suggestions Carousel ─────────────────────────────── */}
            {autoSuggestions.length > 0 && (
                <>
                    <hr style={DIVIDER} />
                    <p style={{ ...LABEL, marginBottom: '14px' }}>Auto Suggestions</p>
                    <div
                        style={{
                            display: 'flex',
                            gap: '10px',
                            overflowX: 'auto',
                            paddingBottom: '4px',
                            scrollbarWidth: 'none',
                        }}
                    >
                        {autoSuggestions.slice(0, 8).map((item: any) => (
                            <SuggestionCard key={item.id} item={item} />
                        ))}
                    </div>
                </>
            )}

            {/* ── Error Banner ──────────────────────────────────────────── */}
            {insightsData?.cache?.last_error && (
                <div
                    style={{
                        marginTop: '24px',
                        border: '1px solid #3f1d1d',
                        background: '#100606',
                        color: '#f87171',
                        borderRadius: '4px',
                        padding: '10px 14px',
                        fontSize: '11px',
                    }}
                >
                    Insight generation warning: {insightsData.cache.last_error}
                </div>
            )}
        </div>
    )
}
