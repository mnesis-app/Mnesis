import { useEffect, useMemo, useState } from 'react'
import { useMemoryGraph } from '../lib/queries'
import { Loader2, Network } from 'lucide-react'

function edgeColorByType(type: string): string {
    if (type === 'CONTRADICTS') return '#ef4444'
    if (type === 'REINFORCES') return '#10b981'
    if (type === 'DEPENDS_ON') return '#f59e0b'
    if (type === 'PRECEDES') return '#38bdf8'
    if (type === 'INVOLVES_PERSON') return '#f97316'
    return '#71717a'
}

export function MemoryGraph({ memoryId }: { memoryId: string }) {
    const { data, isLoading } = useMemoryGraph(memoryId, 2)
    const [GraphComponent, setGraphComponent] = useState<any>(null)
    const [graphLibError, setGraphLibError] = useState<string | null>(null)

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

    const graphData = useMemo(() => {
        const nodes = (data?.nodes || []).map((n: any) => ({ ...n, id: n.id }))
        const links = (data?.edges || []).map((e: any) => ({
            ...e,
            source: e.source,
            target: e.target,
        }))
        return { nodes, links }
    }, [data])

    if (isLoading) {
        return (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 220 }}>
                <Loader2 size={16} style={{ animation: 'spin 1s linear infinite', color: '#3f3f46' }} />
            </div>
        )
    }

    if (!data || data.nodes?.length === 0) {
        return (
            <div style={{
                border: '1px solid #1a1a1a',
                borderRadius: '4px',
                background: '#080808',
                padding: '18px',
                color: '#3f3f46',
                fontSize: '11px',
                textTransform: 'uppercase',
                letterSpacing: '0.1em'
            }}>
                No graph relationships available
            </div>
        )
    }

    return (
        <div style={{
            border: '1px solid #1a1a1a',
            borderRadius: '4px',
            background: '#080808',
            overflow: 'hidden',
        }}>
            <div style={{
                borderBottom: '1px solid #1a1a1a',
                padding: '10px 12px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Network size={14} color="#a1a1aa" />
                    <span style={{
                        fontSize: '10px',
                        fontWeight: 700,
                        letterSpacing: '0.15em',
                        textTransform: 'uppercase',
                        color: '#71717a',
                    }}>
                        Knowledge Graph
                    </span>
                </div>
                <span style={{ fontSize: '10px', color: '#52525b' }}>
                    {data.nodes.length} nodes · {data.edges.length} edges
                </span>
            </div>

            {GraphComponent ? (
                <GraphComponent
                    width={640}
                    height={250}
                    graphData={graphData}
                    nodeLabel={(n: any) => `${n.category || 'memory'}: ${n.content_preview || n.id}`}
                    nodeColor={(n: any) => n.id === data.start_memory_id ? '#f5f3ee' : '#a1a1aa'}
                    linkColor={(l: any) => edgeColorByType(l.type)}
                    linkDirectionalArrowLength={4}
                    linkDirectionalArrowRelPos={1}
                    nodeRelSize={4}
                    cooldownTicks={90}
                />
            ) : (
                <div style={{ padding: '14px 16px' }}>
                    {graphLibError && (
                        <p style={{ margin: '0 0 10px', color: '#71717a', fontSize: '11px' }}>
                            {graphLibError}
                        </p>
                    )}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', maxHeight: 180, overflowY: 'auto' }}>
                        {data.edges.slice(0, 20).map((edge: any) => (
                            <div
                                key={edge.id}
                                style={{
                                    fontSize: '11px',
                                    color: '#a1a1aa',
                                    border: '1px solid #1f1f23',
                                    borderRadius: '4px',
                                    padding: '6px 8px',
                                }}
                            >
                                <span style={{ color: edgeColorByType(edge.type), fontWeight: 700 }}>{edge.type}</span>
                                {' '}
                                {edge.source.slice(0, 8)} → {edge.target.slice(0, 8)}
                                {' '}
                                <span style={{ color: '#52525b' }}>
                                    ({Math.round((edge.score || 0) * 100)}%)
                                </span>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    )
}
