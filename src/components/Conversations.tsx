import { useConversations, useConversation, useDeleteConversation } from '../lib/queries'
import { useState } from 'react'
import { Search, Calendar, Loader2, Trash, MessageSquare } from 'lucide-react'
import { ConfirmDialog } from './ui/ConfirmDialog'

const label: React.CSSProperties = {
    fontSize: '9px', fontWeight: 800, letterSpacing: '0.25em',
    textTransform: 'uppercase' as const, color: '#333',
}

export function Conversations() {
    const [selectedId, setSelectedId] = useState<string | null>(null)
    const [search, setSearch] = useState('')
    const { data: conversations, isLoading } = useConversations(search)

    return (
        <div style={{ display: 'flex', height: '100%', background: '#0a0a0a' }}>
            {/* Left list */}
            <div style={{ width: '300px', borderRight: '1px solid #1a1a1a', display: 'flex', flexDirection: 'column', flexShrink: 0 }}>
                {/* Header */}
                <div style={{ padding: '16px 14px 12px', borderBottom: '1px solid #1a1a1a' }}>
                    <div style={{ position: 'relative' }}>
                        <Search size={13} style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: '#333' }} />
                        <input
                            style={{
                                width: '100%', background: '#080808',
                                border: '1px solid #1e1e1e', borderRadius: '4px',
                                padding: '7px 10px 7px 28px',
                                fontSize: '12px', color: '#888',
                                outline: 'none', fontFamily: 'inherit', boxSizing: 'border-box',
                            }}
                            placeholder="Search history..."
                            value={search}
                            onChange={e => setSearch(e.target.value)}
                        />
                    </div>
                </div>

                {/* List */}
                <div style={{ flex: 1, overflowY: 'auto', padding: '8px' }}>
                    {isLoading ? (
                        <div style={{ display: 'flex', justifyContent: 'center', padding: '24px' }}>
                            <Loader2 size={16} style={{ animation: 'spin 1s linear infinite', color: '#2a2a2a' }} />
                        </div>
                    ) : conversations?.map((conv: any) => {
                        const active = selectedId === conv.id
                        return (
                            <div
                                key={conv.id}
                                onClick={() => setSelectedId(conv.id)}
                                style={{
                                    padding: '10px 12px',
                                    borderRadius: '4px',
                                    cursor: 'pointer',
                                    background: active ? '#0d0d0d' : 'transparent',
                                    border: `1px solid ${active ? '#2a2a2a' : 'transparent'}`,
                                    marginBottom: '2px',
                                    transition: 'all 100ms ease',
                                }}
                                onMouseEnter={e => { if (!active) (e.currentTarget.style.background = '#0d0d0d') }}
                                onMouseLeave={e => { if (!active) (e.currentTarget.style.background = 'transparent') }}
                            >
                                <p style={{ fontSize: '12px', fontWeight: 700, color: '#d0d0d0', margin: '0 0 6px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                    {conv.title}
                                </p>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                    <span style={{ ...label, color: conv.source_llm === 'claude' ? '#7c4f27' : '#3d7c4f' }}>
                                        {conv.source_llm}
                                    </span>
                                    <span style={{ fontSize: '10px', color: '#333' }}>
                                        {new Date(conv.started_at).toLocaleDateString()}
                                    </span>
                                </div>
                            </div>
                        )
                    })}
                </div>
            </div>

            {/* Right: viewer */}
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
                {selectedId ? (
                    <ConversationViewer id={selectedId} onDelete={() => setSelectedId(null)} />
                ) : (
                    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '12px' }}>
                        <MessageSquare size={32} style={{ color: '#1e1e1e' }} />
                        <p style={{ ...label, color: '#222' }}>Select a conversation</p>
                    </div>
                )}
            </div>
        </div>
    )
}

function ConversationViewer({ id, onDelete }: { id: string; onDelete: () => void }) {
    const { data: conv, isLoading } = useConversation(id)
    const { mutate: deleteConversation, isPending: isDeleting } = useDeleteConversation()
    const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)

    const handleDelete = () => {
        deleteConversation(id, {
            onSuccess: () => { setShowDeleteConfirm(false); onDelete() }
        })
    }

    if (isLoading) return (
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Loader2 size={20} style={{ color: '#2a2a2a', animation: 'spin 1s linear infinite' }} />
        </div>
    )
    if (!conv) return null

    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
            <ConfirmDialog
                isOpen={showDeleteConfirm}
                title="Delete Conversation"
                description="Are you sure you want to delete this conversation? This action cannot be undone."
                confirmText="Delete"
                variant="danger"
                onConfirm={handleDelete}
                onCancel={() => setShowDeleteConfirm(false)}
            />

            {/* Header */}
            <div style={{
                padding: '24px 28px',
                borderBottom: '1px solid #1a1a1a',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'flex-start',
                background: '#080808',
            }}>
                <div>
                    <h1 style={{ fontSize: '18px', fontWeight: 800, color: '#f5f3ee', margin: '0 0 10px', letterSpacing: '-0.01em' }}>
                        {conv.title}
                    </h1>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <span style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '11px', color: '#444' }}>
                            <Calendar size={11} /> {new Date(conv.started_at).toLocaleString()}
                        </span>
                        <span style={{
                            fontSize: '9px', fontWeight: 800, letterSpacing: '0.2em',
                            textTransform: 'uppercase', color: '#333',
                            border: '1px solid #2a2a2a', borderRadius: '2px', padding: '2px 6px',
                        }}>
                            {conv.message_count} msg
                        </span>
                        {conv.tags?.map((tag: string) => (
                            <span key={tag} style={{ fontSize: '10px', color: '#333' }}>#{tag}</span>
                        ))}
                    </div>
                </div>
                <button
                    onClick={() => setShowDeleteConfirm(true)}
                    disabled={isDeleting}
                    style={{
                        padding: '6px', background: 'transparent', border: '1px solid transparent',
                        borderRadius: '4px', cursor: 'pointer', color: '#333',
                        transition: 'all 150ms ease',
                    }}
                    onMouseEnter={e => { (e.currentTarget.style.color = '#ef4444'); (e.currentTarget.style.borderColor = '#2a2a2a') }}
                    onMouseLeave={e => { (e.currentTarget.style.color = '#333'); (e.currentTarget.style.borderColor = 'transparent') }}
                >
                    {isDeleting ? <Loader2 size={18} style={{ animation: 'spin 1s linear infinite' }} /> : <Trash size={18} />}
                </button>
            </div>

            {/* Content */}
            <div style={{ flex: 1, overflowY: 'auto', padding: '24px 28px' }}>
                <div style={{
                    padding: '24px', background: '#080808',
                    border: '1px solid #1a1a1a', borderRadius: '4px',
                    fontSize: '12px', color: '#2a2a2a', fontStyle: 'italic', textAlign: 'center',
                }}>
                    Message history content...
                    <br /><span style={{ fontSize: '10px', color: '#1e1e1e' }}>(Requires message retrieval implementation)</span>
                </div>

                {conv.memory_ids?.length > 0 && (
                    <div style={{ marginTop: '24px' }}>
                        <p style={{ fontSize: '9px', fontWeight: 800, letterSpacing: '0.25em', textTransform: 'uppercase', color: '#333', marginBottom: '12px' }}>
                            Linked Memories
                        </p>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                            {conv.memory_ids.map((memId: string) => (
                                <div key={memId} style={{
                                    padding: '10px 14px',
                                    background: '#080808', border: '1px solid #1a1a1a', borderRadius: '4px',
                                    display: 'flex', alignItems: 'center', gap: '8px',
                                    fontSize: '11px', color: '#444',
                                }}>
                                    <div style={{ width: '4px', height: '4px', borderRadius: '50%', background: '#2a2a2a' }} />
                                    {memId}
                                </div>
                            ))}
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}
