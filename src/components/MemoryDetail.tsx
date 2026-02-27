import { useState, useEffect } from 'react'
import { useAppStore } from '../lib/store'
import { useMemory, useUpdateMemory, useDeleteMemory, useSetMemoryStatus } from '../lib/queries'
import { Loader2, Save, Trash2, X, Network, Check, Activity } from 'lucide-react'
import { ConfirmDialog } from './ui/ConfirmDialog'
import { MemoryGraph } from './MemoryGraph'
import { MemoryHealthPanel } from './MemoryHealthPanel'

const metaLabel: React.CSSProperties = {
    fontSize: '9px', fontWeight: 800, letterSpacing: '0.25em',
    textTransform: 'uppercase' as const, color: '#333', display: 'block', marginBottom: '6px',
}

export function MemoryDetail() {
    const { selectedMemoryId, setSelectedMemory, setCurrentView } = useAppStore()
    const { data: memory, isLoading } = useMemory(selectedMemoryId)
    const updateMemory = useUpdateMemory()
    const deleteMemory = useDeleteMemory()
    const setMemoryStatus = useSetMemoryStatus()

    const [editContent, setEditContent] = useState('')
    const [isEditing, setIsEditing] = useState(false)
    const [showArchiveConfirm, setShowArchiveConfirm] = useState(false)
    const [showGraph, setShowGraph] = useState(true)
    const [showHealth, setShowHealth] = useState(false)

    useEffect(() => {
        if (memory) { setEditContent(memory.content); setIsEditing(false) }
    }, [memory?.id, memory?.content])

    if (!selectedMemoryId) return null
    if (isLoading) return (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flex: 1 }}>
            <Loader2 size={18} style={{ animation: 'spin 1s linear infinite', color: '#333' }} />
        </div>
    )
    if (!memory) return (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flex: 1, color: '#333', fontSize: '12px' }}>
            Memory not found
        </div>
    )

    const handleSave = async () => {
        if (!editContent.trim()) return
        await updateMemory.mutateAsync({ id: memory.id, data: { content: editContent, source_llm: 'manual' } })
        setIsEditing(false)
    }

    const handleDelete = async () => {
        await deleteMemory.mutateAsync(memory.id)
        setSelectedMemory(null)
        setShowArchiveConfirm(false)
    }

    const handleApprove = async () => {
        await setMemoryStatus.mutateAsync({
            id: memory.id,
            status: 'active',
            source_llm: 'review',
            review_note: 'Approved from memory detail',
        })
    }

    const handleReject = async () => {
        await setMemoryStatus.mutateAsync({
            id: memory.id,
            status: 'rejected',
            source_llm: 'review',
            review_note: 'Rejected from memory detail',
        })
    }

    return (
        <div style={{ width: '100%', maxWidth: '680px', height: '100%', display: 'flex', flexDirection: 'column', padding: '28px 32px' }}>
            <ConfirmDialog
                isOpen={showArchiveConfirm}
                title="Archive Memory"
                description="Are you sure you want to archive this memory?"
                confirmText="Archive"
                variant="danger"
                onConfirm={handleDelete}
                onCancel={() => setShowArchiveConfirm(false)}
            />

            {/* Header */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <span style={{
                        fontSize: '9px', fontWeight: 800, letterSpacing: '0.2em',
                        textTransform: 'uppercase', color: '#f5f3ee',
                        border: '1px solid #2a2a2a', borderRadius: '2px', padding: '3px 8px',
                    }}>
                        {memory.category}
                    </span>
                    <span style={{ fontSize: '10px', color: '#333' }}>
                        {new Date(memory.created_at).toLocaleString()}
                    </span>
                </div>
                <div style={{ display: 'flex', gap: '4px' }}>
                    {memory.status === 'pending_review' && (
                        <>
                            <button
                                onClick={handleApprove}
                                title="Approve"
                                disabled={setMemoryStatus.isPending}
                                style={{
                                    padding: '6px',
                                    background: '#0d1411',
                                    border: '1px solid #1f3a2f',
                                    borderRadius: '4px',
                                    cursor: setMemoryStatus.isPending ? 'wait' : 'pointer',
                                    color: '#9de6cc',
                                    transition: 'all 150ms ease',
                                }}
                            >
                                {setMemoryStatus.isPending ? <Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} /> : <Check size={16} />}
                            </button>
                            <button
                                onClick={handleReject}
                                title="Reject"
                                disabled={setMemoryStatus.isPending}
                                style={{
                                    padding: '6px',
                                    background: '#150c0c',
                                    border: '1px solid #3a1f1f',
                                    borderRadius: '4px',
                                    cursor: setMemoryStatus.isPending ? 'wait' : 'pointer',
                                    color: '#fca5a5',
                                    transition: 'all 150ms ease',
                                }}
                            >
                                <X size={16} />
                            </button>
                        </>
                    )}
                    <button
                        onClick={() => setShowArchiveConfirm(true)}
                        title="Archive"
                        style={{
                            padding: '6px', background: 'transparent',
                            border: '1px solid transparent', borderRadius: '4px',
                            cursor: 'pointer', color: '#333', transition: 'all 150ms ease',
                        }}
                        onMouseEnter={e => { (e.currentTarget.style.color = '#ef4444'); (e.currentTarget.style.borderColor = '#2a2a2a') }}
                        onMouseLeave={e => { (e.currentTarget.style.color = '#333'); (e.currentTarget.style.borderColor = 'transparent') }}
                    >
                        <Trash2 size={16} />
                    </button>
                    <button
                        onClick={() => setSelectedMemory(null)}
                        style={{
                            padding: '6px', background: 'transparent',
                            border: '1px solid transparent', borderRadius: '4px',
                            cursor: 'pointer', color: '#333', transition: 'all 150ms ease',
                        }}
                        onMouseEnter={e => (e.currentTarget.style.color = '#888')}
                        onMouseLeave={e => (e.currentTarget.style.color = '#333')}
                    >
                        <X size={16} />
                    </button>
                </div>
            </div>

            {/* Editor */}
            <div style={{
                flex: 1, display: 'flex', flexDirection: 'column',
                background: '#080808', border: '1px solid #1a1a1a', borderRadius: '4px',
                overflow: 'hidden',
            }}>
                <textarea
                    value={editContent}
                    onChange={e => { setEditContent(e.target.value); setIsEditing(true) }}
                    style={{
                        flex: 1, background: 'transparent', border: 'none', outline: 'none',
                        padding: '20px', resize: 'none', fontSize: '14px',
                        color: '#d0d0d0', lineHeight: 1.75, fontFamily: 'inherit',
                    }}
                    placeholder="Memory content..."
                />
                <div style={{
                    padding: '10px 16px', borderTop: '1px solid #1a1a1a',
                    display: 'flex', justifyContent: 'flex-end', gap: '8px', background: '#060606',
                }}>
                    {isEditing && (
                        <button
                            onClick={() => { setEditContent(memory.content); setIsEditing(false) }}
                            style={{
                                padding: '6px 14px', background: 'transparent',
                                border: 'none', fontSize: '11px', cursor: 'pointer',
                                color: '#444', fontFamily: 'inherit',
                            }}
                        >
                            Cancel
                        </button>
                    )}
                    <button
                        onClick={handleSave}
                        disabled={!isEditing || updateMemory.isPending}
                        style={{
                            display: 'flex', alignItems: 'center', gap: '6px',
                            padding: '6px 16px', borderRadius: '4px', border: 'none',
                            fontSize: '10px', fontWeight: 800, letterSpacing: '0.15em',
                            textTransform: 'uppercase', cursor: isEditing ? 'pointer' : 'not-allowed',
                            fontFamily: 'inherit',
                            background: isEditing ? '#f5f3ee' : '#111',
                            color: isEditing ? '#0a0a0a' : '#222',
                            transition: 'all 150ms ease',
                        }}
                    >
                        {updateMemory.isPending ? <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> : <Save size={13} />}
                        Save
                    </button>
                </div>
            </div>

            {/* Meta */}
            {memory.suggestion_reason && (
                <div style={{
                    marginTop: '12px',
                    background: '#080808',
                    border: '1px solid #1a1a1a',
                    borderRadius: '4px',
                    padding: '12px 14px',
                }}>
                    <span style={metaLabel}>Suggestion Reason</span>
                    <p style={{ margin: 0, color: '#8b8b8b', fontSize: '12px', lineHeight: 1.55 }}>
                        {memory.suggestion_reason}
                    </p>
                </div>
            )}
            {memory.review_note && (
                <div style={{
                    marginTop: '8px',
                    background: '#080808',
                    border: '1px solid #1a1a1a',
                    borderRadius: '4px',
                    padding: '12px 14px',
                }}>
                    <span style={metaLabel}>Review Note</span>
                    <p style={{ margin: 0, color: '#8b8b8b', fontSize: '12px', lineHeight: 1.55 }}>
                        {memory.review_note}
                    </p>
                </div>
            )}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2px', marginTop: '12px' }}>
                <div style={{ background: '#080808', border: '1px solid #1a1a1a', borderRadius: '4px', padding: '14px 16px' }}>
                    <span style={metaLabel}>Confidence</span>
                    <span style={{ fontSize: '24px', fontWeight: 800, color: '#f5f3ee', letterSpacing: '-0.02em' }}>
                        {(memory.confidence_score * 100).toFixed(0)}%
                    </span>
                </div>
                <div style={{ background: '#080808', border: '1px solid #1a1a1a', borderRadius: '4px', padding: '14px 16px' }}>
                    <span style={metaLabel}>Level</span>
                    <span style={{ fontSize: '24px', fontWeight: 800, color: '#f5f3ee', letterSpacing: '-0.02em', textTransform: 'capitalize' }}>
                        {memory.level}
                    </span>
                </div>
            </div>

            {/* Health Panel */}
            <div style={{ marginTop: '12px' }}>
                <button
                    onClick={() => setShowHealth(v => !v)}
                    style={{
                        width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                        border: '1px solid #1a1a1a', background: '#080808', color: '#a1a1aa',
                        borderRadius: '4px', padding: '10px 12px', fontSize: '10px', fontWeight: 700,
                        letterSpacing: '0.14em', textTransform: 'uppercase', cursor: 'pointer', fontFamily: 'inherit',
                        transition: 'border-color 150ms ease',
                    }}
                    onMouseEnter={e => (e.currentTarget.style.borderColor = '#2a2a2a')}
                    onMouseLeave={e => (e.currentTarget.style.borderColor = '#1a1a1a')}
                >
                    <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <Activity size={14} />
                        Memory Health
                    </span>
                    <span style={{ fontSize: '9px', opacity: 0.5 }}>{showHealth ? '▲' : '▼'}</span>
                </button>
                {showHealth && <MemoryHealthPanel memoryId={memory.id} />}
            </div>

            {/* Graph Panel */}
            <div style={{ marginTop: '12px' }}>
                <div style={{
                    width: '100%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    border: '1px solid #1a1a1a',
                    background: '#080808',
                    color: '#a1a1aa',
                    borderRadius: '4px',
                    padding: '10px 12px',
                    fontSize: '10px',
                    fontWeight: 700,
                    letterSpacing: '0.14em',
                    textTransform: 'uppercase',
                }}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <Network size={14} />
                        Memory Graph
                    </span>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <button
                            onClick={(e) => { e.stopPropagation(); setCurrentView('graph') }}
                            style={{
                                border: '1px solid #27272a',
                                background: '#09090b',
                                color: '#a1a1aa',
                                borderRadius: '4px',
                                padding: '4px 8px',
                                fontSize: '9px',
                                textTransform: 'uppercase',
                                letterSpacing: '0.08em',
                                cursor: 'pointer',
                            }}
                        >
                            Open Graph
                        </button>
                        <button
                            onClick={() => setShowGraph((v) => !v)}
                            style={{
                                border: '1px solid #27272a',
                                background: '#09090b',
                                color: '#a1a1aa',
                                borderRadius: '4px',
                                padding: '4px 8px',
                                fontSize: '9px',
                                textTransform: 'uppercase',
                                letterSpacing: '0.08em',
                                cursor: 'pointer',
                            }}
                        >
                            {showGraph ? 'Hide' : 'Show'}
                        </button>
                    </span>
                </div>

                {showGraph && (
                    <div style={{ marginTop: '8px' }}>
                        <MemoryGraph memoryId={memory.id} />
                    </div>
                )}
            </div>
        </div>
    )
}
