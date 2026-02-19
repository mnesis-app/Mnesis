import { useState, useEffect } from 'react'
import { useAppStore } from '../lib/store'
import { useMemories, useUpdateMemory, useDeleteMemory } from '../lib/queries'
import { Loader2, Save, Trash2, X } from 'lucide-react'
import { ConfirmDialog } from './ui/ConfirmDialog'

const metaLabel: React.CSSProperties = {
    fontSize: '9px', fontWeight: 800, letterSpacing: '0.25em',
    textTransform: 'uppercase' as const, color: '#333', display: 'block', marginBottom: '6px',
}

export function MemoryDetail() {
    const { selectedMemoryId, setSelectedMemory } = useAppStore()
    const { data: memories } = useMemories()
    const updateMemory = useUpdateMemory()
    const deleteMemory = useDeleteMemory()

    const [editContent, setEditContent] = useState('')
    const [isEditing, setIsEditing] = useState(false)
    const [showArchiveConfirm, setShowArchiveConfirm] = useState(false)

    const memory = memories?.find((m: any) => m.id === selectedMemoryId)

    useEffect(() => {
        if (memory) { setEditContent(memory.content); setIsEditing(false) }
    }, [memory])

    if (!selectedMemoryId) return null
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
        </div>
    )
}
