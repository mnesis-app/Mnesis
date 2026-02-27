import { useEffect, useMemo, useState } from 'react'
import { Loader2, Network, Filter, Maximize2 } from 'lucide-react'
import { useMemoryGraphOverview } from '../lib/queries'
import { useAppStore } from '../lib/store'

const EDGE_TYPES = [
    'ALL',
    'BELONGS_TO',
    'CONTRADICTS',
    'REINFORCES',
    'PRECEDES',
    'DEPENDS_ON',
    'INVOLVES_PERSON',
] as const

const CATEGORIES = ['ALL', 'identity', 'preferences', 'skills', 'relationships', 'projects', 'history', 'working'] as const

function edgeColorByType(type: string): string {
    if (type === 'CONTRADICTS') return '#ef4444'
    if (type === 'REINFORCES') return '#10b981'
    if (type === 'DEPENDS_ON') return '#f59e0b'
    if (type === 'PRECEDES') return '#38bdf8'
    if (type === 'INVOLVES_PERSON') return '#f97316'
    if (type === 'CONVERSATION_CONTEXT') return '#22d3ee'
    return '#71717a'
}

export function GraphView() {
    const { selectedMemoryId, setSelectedMemory, setSelectedConversation, setCurrentView } = useAppStore()
    const [depth, setDepth] = useState(2)
    const [edgeType, setEdgeType] = useState<typeof EDGE_TYPES[number]>('ALL')
    const [category, setCategory] = useState<typeof CATEGORIES[number]>('ALL')
    const [focusSelected, setFocusSelected] = useState(false)
    const [includeConversations, setIncludeConversations] = useState(false)
    const [maxNodes, setMaxNodes] = useState(220)
    const [GraphComponent, setGraphComponent] = useState<any>(null)
    const [graphLibError, setGraphLibError] = useState<string | null>(null)
    const [viewport, setViewport] = useState({ width: 1100, height: 600 })

    const { data, isLoading } = useMemoryGraphOverview({
        depth,
        centerMemoryId: focusSelected ? (selectedMemoryId || undefined) : undefined,
        edgeType: edgeType === 'ALL' ? undefined : edgeType,
        category: category === 'ALL' ? undefined : category,
        maxNodes,
        includeConversations,
    })

    useEffect(() => {
        let isMounted = true
            ; (async () => {
                try {
                    const mod: any = await import('react-force-graph-2d')
                    const component = mod?.default ?? mod
                    if (isMounted) {
                        setGraphComponent(() => component)
                        setGraphLibError(null)
                    }
                } catch (e) {
                    if (isMounted) setGraphLibError('react-force-graph-2d is not installed. Showing list fallback.')
                }
            })()
        return () => { isMounted = false }
    }, [])

    useEffect(() => {
        const compute = () => {
            const width = Math.max(760, window.innerWidth - 200)
            const height = Math.max(480, window.innerHeight - 180)
            setViewport({ width, height })
        }
        compute()
        window.addEventListener('resize', compute)
        return () => window.removeEventListener('resize', compute)
    }, [])

    const graphData = useMemo(() => {
        const nodes = (data?.nodes || []).map((n: any) => ({ ...n, id: n.id }))
        const links = (data?.edges || []).map((e: any) => ({
            ...e,
            source: e.source,
            target: e.target,
        }))
        return { nodes, links }
    }, [data])

    return (
        <div style={{ height: '100%', width: '100%', overflow: 'hidden', padding: '20px 24px', background: '#080808' }}>
            <div style={{
                border: '1px solid #1a1a1a',
                borderRadius: '4px',
                background: '#0a0a0a',
                height: '100%',
                display: 'flex',
                flexDirection: 'column',
                overflow: 'hidden',
            }}>
                <div style={{
                    borderBottom: '1px solid #1a1a1a',
                    padding: '10px 12px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '10px',
                    flexWrap: 'wrap',
                }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginRight: '6px' }}>
                        <Network size={14} color="#a1a1aa" />
                        <span style={{
                            fontSize: '10px',
                            fontWeight: 700,
                            letterSpacing: '0.15em',
                            textTransform: 'uppercase',
                            color: '#71717a',
                        }}>
                            Global Graph
                        </span>
                    </div>

                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', color: '#71717a' }}>
                        <Filter size={12} />
                        Edge
                        <select
                            value={edgeType}
                            onChange={(e) => setEdgeType(e.target.value as any)}
                            style={{
                                background: '#09090b',
                                border: '1px solid #27272a',
                                color: '#a1a1aa',
                                borderRadius: '4px',
                                padding: '4px 6px',
                            }}
                        >
                            {EDGE_TYPES.map((t) => (
                                <option key={t} value={t}>{t}</option>
                            ))}
                        </select>
                    </label>

                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', color: '#71717a' }}>
                        Category
                        <select
                            value={category}
                            onChange={(e) => setCategory(e.target.value as any)}
                            style={{
                                background: '#09090b',
                                border: '1px solid #27272a',
                                color: '#a1a1aa',
                                borderRadius: '4px',
                                padding: '4px 6px',
                            }}
                        >
                            {CATEGORIES.map((c) => (
                                <option key={c} value={c}>{c}</option>
                            ))}
                        </select>
                    </label>

                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', color: '#71717a' }}>
                        Depth
                        <select
                            value={depth}
                            onChange={(e) => setDepth(Number(e.target.value))}
                            style={{
                                background: '#09090b',
                                border: '1px solid #27272a',
                                color: '#a1a1aa',
                                borderRadius: '4px',
                                padding: '4px 6px',
                            }}
                        >
                            <option value={1}>1</option>
                            <option value={2}>2</option>
                            <option value={3}>3</option>
                            <option value={4}>4</option>
                        </select>
                    </label>

                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', color: '#71717a' }}>
                        Max nodes
                        <select
                            value={maxNodes}
                            onChange={(e) => setMaxNodes(Number(e.target.value))}
                            style={{
                                background: '#09090b',
                                border: '1px solid #27272a',
                                color: '#a1a1aa',
                                borderRadius: '4px',
                                padding: '4px 6px',
                            }}
                        >
                            <option value={120}>120</option>
                            <option value={220}>220</option>
                            <option value={320}>320</option>
                            <option value={500}>500</option>
                        </select>
                    </label>

                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', color: '#71717a' }}>
                        <input
                            type="checkbox"
                            checked={focusSelected}
                            onChange={(e) => setFocusSelected(e.target.checked)}
                        />
                        Focus selected memory
                    </label>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', color: '#71717a' }}>
                        <input
                            type="checkbox"
                            checked={includeConversations}
                            onChange={(e) => setIncludeConversations(e.target.checked)}
                        />
                        Show conversation links
                    </label>

                    <span style={{ marginLeft: 'auto', fontSize: '11px', color: '#52525b', display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <Maximize2 size={12} />
                        {data?.nodes?.length ?? 0} nodes · {data?.edges?.length ?? 0} edges
                        {includeConversations ? ` · ${Number(data?.conversation_links?.length || 0)} links` : ''}
                    </span>
                </div>

                <div style={{ flex: 1, overflow: 'hidden', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#060606' }}>
                    {isLoading && (
                        <Loader2 size={18} style={{ animation: 'spin 1s linear infinite', color: '#3f3f46' }} />
                    )}

                    {!isLoading && (!data || data.nodes?.length === 0) && (
                        <div style={{ color: '#52525b', fontSize: '11px', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
                            Graph is empty for current filters
                        </div>
                    )}

                    {!isLoading && data && data.nodes?.length > 0 && GraphComponent && (
                        <GraphComponent
                            width={viewport.width}
                            height={viewport.height}
                            graphData={graphData}
                            nodeLabel={(n: any) => `${n.node_type || 'memory'} · ${n.category || 'memory'}: ${n.content_preview || n.id}`}
                            nodeColor={(n: any) => {
                                if (n.id === selectedMemoryId) return '#f5f3ee'
                                if (String(n.node_type || '').toLowerCase() === 'conversation') return '#38bdf8'
                                return '#a1a1aa'
                            }}
                            linkColor={(l: any) => edgeColorByType(l.type)}
                            linkDirectionalArrowLength={4}
                            linkDirectionalArrowRelPos={1}
                            nodeRelSize={4}
                            cooldownTicks={80}
                            onNodeClick={(node: any) => {
                                if (!node?.id) return
                                if (String(node?.node_type || '').toLowerCase() === 'conversation') {
                                    const raw = String(node.id || '')
                                    const conversationId = raw.startsWith('conversation:') ? raw.slice('conversation:'.length) : raw
                                    if (conversationId) {
                                        setSelectedConversation(conversationId)
                                        setCurrentView('conversations')
                                    }
                                    return
                                }
                                setSelectedMemory(node.id)
                            }}
                        />
                    )}

                    {!isLoading && data && data.nodes?.length > 0 && !GraphComponent && (
                        <div style={{ width: '100%', height: '100%', padding: '12px', overflowY: 'auto' }}>
                            {graphLibError && (
                                <p style={{ margin: '0 0 10px', color: '#71717a', fontSize: '11px' }}>
                                    {graphLibError}
                                </p>
                            )}
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                {data.edges.slice(0, 80).map((edge: any) => (
                                    <button
                                        key={edge.id}
                                        onClick={() => setSelectedMemory(edge.source)}
                                        style={{
                                            textAlign: 'left',
                                            background: '#09090b',
                                            border: '1px solid #1f1f23',
                                            borderRadius: '4px',
                                            padding: '6px 8px',
                                            cursor: 'pointer',
                                            color: '#a1a1aa',
                                            fontSize: '11px',
                                        }}
                                    >
                                        <span style={{ color: edgeColorByType(edge.type), fontWeight: 700 }}>{edge.type}</span>
                                        {' '}
                                        {edge.source.slice(0, 8)} → {edge.target.slice(0, 8)}
                                        {' '}
                                        <span style={{ color: '#52525b' }}>
                                            ({Math.round((edge.score || 0) * 100)}%)
                                        </span>
                                    </button>
                                ))}
                            </div>
                        </div>
                    )}
                </div>

                {(Array.isArray(data?.topic_clusters) && data.topic_clusters.length > 0) || (Array.isArray(data?.timeline) && data.timeline.length > 0) ? (
                    <div
                        style={{
                            borderTop: '1px solid #1a1a1a',
                            padding: '10px 12px',
                            display: 'grid',
                            gridTemplateColumns: '1fr 1fr',
                            gap: '10px',
                            background: '#070707',
                        }}
                    >
                        <div>
                            <p style={{ margin: '0 0 8px', fontSize: '10px', letterSpacing: '0.1em', textTransform: 'uppercase', color: '#666' }}>
                                Topic Clusters
                            </p>
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                                {(data?.topic_clusters || []).slice(0, 8).map((c: any) => (
                                    <span
                                        key={c.topic}
                                        style={{
                                            border: '1px solid #1f1f1f',
                                            borderRadius: '999px',
                                            padding: '3px 8px',
                                            fontSize: '10px',
                                            color: '#8a8a8a',
                                        }}
                                    >
                                        {c.topic} <span style={{ color: '#4f4f4f' }}>{c.count}</span>
                                    </span>
                                ))}
                            </div>
                        </div>
                        <div>
                            <p style={{ margin: '0 0 8px', fontSize: '10px', letterSpacing: '0.1em', textTransform: 'uppercase', color: '#666' }}>
                                Timeline
                            </p>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', maxHeight: '96px', overflowY: 'auto' }}>
                                {(data?.timeline || []).slice(-8).map((row: any) => (
                                    <div key={row.date} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: '#7d7d7d' }}>
                                        <span>{row.date}</span>
                                        <span style={{ color: '#5f5f5f' }}>
                                            M {Number(row.memories || 0)} · C {Number(row.conversations || 0)} · L {Number(row.links || 0)}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>
                ) : null}

                {selectedMemoryId && (
                    <div style={{
                        borderTop: '1px solid #1a1a1a',
                        padding: '8px 10px',
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        color: '#71717a',
                        fontSize: '11px',
                    }}>
                        <span>Selected: {selectedMemoryId}</span>
                        <button
                            onClick={() => setCurrentView('memories')}
                            style={{
                                border: '1px solid #27272a',
                                background: '#09090b',
                                color: '#a1a1aa',
                                borderRadius: '4px',
                                padding: '4px 8px',
                                fontSize: '10px',
                                textTransform: 'uppercase',
                                letterSpacing: '0.08em',
                                cursor: 'pointer',
                            }}
                        >
                            Open In Memories
                        </button>
                    </div>
                )}
            </div>
        </div>
    )
}
