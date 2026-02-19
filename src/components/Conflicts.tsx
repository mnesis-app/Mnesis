import { useConflicts, useResolveConflict } from '../lib/queries'
import { Loader2, Check, Merge, Split } from 'lucide-react'
import { useState } from 'react'

const lbl: React.CSSProperties = {
    fontSize: '9px', fontWeight: 800, letterSpacing: '0.25em',
    textTransform: 'uppercase' as const, color: '#333', marginBottom: '8px', display: 'block',
}

export function Conflicts() {
    const { data: conflicts, isLoading } = useConflicts()

    if (isLoading) return (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flex: 1, padding: '80px' }}>
            <Loader2 size={18} style={{ animation: 'spin 1s linear infinite', color: '#2a2a2a' }} />
        </div>
    )

    if (!conflicts || conflicts.length === 0) return (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', flex: 1, gap: '12px', padding: '80px' }}>
            <Check size={28} style={{ color: '#10b981' }} />
            <p style={{ fontSize: '10px', fontWeight: 800, letterSpacing: '0.25em', textTransform: 'uppercase', color: '#2a2a2a', margin: 0 }}>
                Memory is consistent
            </p>
        </div>
    )

    return (
        <div style={{ padding: '36px 40px', maxWidth: '840px' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                {conflicts.map((conflict: any) => (
                    <ConflictCard key={conflict.id} conflict={conflict} />
                ))}
            </div>
        </div>
    )
}

function ConflictCard({ conflict }: { conflict: any }) {
    const resolve = useResolveConflict()
    const [mergedContent, setMergedContent] = useState(conflict.memory_a?.content || '')
    const [merging, setMerging] = useState(false)

    const handleResolve = (resolution: string) => {
        resolve.mutate({ id: conflict.id, resolution, mergedContent: resolution === 'merged' ? mergedContent : undefined })
    }

    if (!conflict.memory_a || !conflict.memory_b) return null

    const actionBtn = (primary = false): React.CSSProperties => ({
        padding: '8px 16px', borderRadius: '4px', border: `1px solid ${primary ? 'transparent' : '#1e1e1e'}`,
        background: primary ? '#f5f3ee' : 'transparent',
        color: primary ? '#0a0a0a' : '#444',
        fontSize: '10px', fontWeight: 800, letterSpacing: '0.15em', textTransform: 'uppercase',
        cursor: 'pointer', fontFamily: 'inherit', transition: 'all 150ms ease',
    })

    return (
        <div style={{
            background: '#080808', border: '1px solid #1a1a1a',
            borderLeft: '3px solid #7c3a1f', borderRadius: '4px', overflow: 'hidden',
        }}>
            {/* Header */}
            <div style={{ padding: '12px 20px', borderBottom: '1px solid #1a1a1a', display: 'flex', alignItems: 'center', gap: '10px' }}>
                <span style={{
                    fontSize: '9px', fontWeight: 800, letterSpacing: '0.2em',
                    textTransform: 'uppercase', color: '#7c3a1f',
                    border: '1px solid #3a1a0a', borderRadius: '2px', padding: '2px 6px',
                }}>
                    {(conflict.similarity_score * 100).toFixed(0)}% similar
                </span>
                <span style={{ fontSize: '10px', color: '#333' }}>
                    Detected {new Date(conflict.detected_at).toLocaleDateString()}
                </span>
            </div>

            {/* Two columns */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 24px 1fr', gap: 0 }}>
                <div style={{ padding: '20px' }}>
                    <span style={lbl}>Existing</span>
                    <p style={{ fontSize: '13px', color: '#888', lineHeight: 1.65, margin: '0 0 16px', minHeight: '80px' }}>
                        {conflict.memory_a.content}
                    </p>
                    <button
                        onClick={() => handleResolve('kept_a')}
                        disabled={resolve.isPending}
                        style={actionBtn()}
                    >
                        Keep Existing
                    </button>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', borderLeft: '1px solid #1a1a1a', borderRight: '1px solid #1a1a1a' }}>
                    <Split size={12} style={{ color: '#2a2a2a' }} />
                </div>

                <div style={{ padding: '20px' }}>
                    <span style={lbl}>New Input</span>
                    <p style={{ fontSize: '13px', color: '#888', lineHeight: 1.65, margin: '0 0 16px', minHeight: '80px' }}>
                        {conflict.memory_b.content}
                    </p>
                    <button
                        onClick={() => handleResolve('kept_b')}
                        disabled={resolve.isPending}
                        style={actionBtn(true)}
                    >
                        Use New
                    </button>
                </div>
            </div>

            {/* Footer actions */}
            <div style={{ padding: '12px 20px', borderTop: '1px solid #1a1a1a', display: 'flex', gap: '16px', alignItems: 'center' }}>
                <button
                    onClick={() => setMerging(!merging)}
                    style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#444', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '5px', fontFamily: 'inherit', fontWeight: 800, letterSpacing: '0.1em', textTransform: 'uppercase', padding: 0 }}
                >
                    <Merge size={12} /> {merging ? 'Cancel' : 'Merge'}
                </button>
                <button
                    onClick={() => handleResolve('both_valid')}
                    disabled={resolve.isPending}
                    style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#444', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '5px', fontFamily: 'inherit', fontWeight: 800, letterSpacing: '0.1em', textTransform: 'uppercase', padding: 0 }}
                >
                    <Check size={12} /> Keep Both
                </button>
            </div>

            {merging && (
                <div style={{ padding: '16px 20px', borderTop: '1px solid #1a1a1a', background: '#060606' }}>
                    <textarea
                        style={{
                            width: '100%', background: '#040404',
                            border: '1px solid #1e1e1e', borderRadius: '4px',
                            padding: '10px 12px', fontSize: '13px', color: '#888',
                            outline: 'none', fontFamily: 'inherit', resize: 'vertical',
                            boxSizing: 'border-box', minHeight: '80px',
                        }}
                        rows={3}
                        value={mergedContent}
                        onChange={e => setMergedContent(e.target.value)}
                    />
                    <button
                        onClick={() => handleResolve('merged')}
                        disabled={resolve.isPending}
                        style={{
                            marginTop: '10px', width: '100%', padding: '9px',
                            background: '#f5f3ee', color: '#0a0a0a', border: 'none',
                            borderRadius: '4px', fontSize: '10px', fontWeight: 800,
                            letterSpacing: '0.15em', textTransform: 'uppercase',
                            cursor: 'pointer', fontFamily: 'inherit',
                        }}
                    >
                        Save Merged Memory
                    </button>
                </div>
            )}
        </div>
    )
}
