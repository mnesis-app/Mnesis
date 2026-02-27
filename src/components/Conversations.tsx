import { useConversations, useConversation, useDeleteConversation } from '../lib/queries'
import type { Conversation, ConversationMessage } from '../lib/types'
import { useEffect, useMemo, useState } from 'react'
import { Search, Calendar, Loader2, Trash, Eye, EyeOff, Terminal } from 'lucide-react'
import { ConfirmDialog } from './ui/ConfirmDialog'
import { useAppStore } from '../lib/store'
import { PalimpsestIcon } from './Logo'

// ─── Tokens ────────────────────────────────────────────────────────────────

const LABEL: React.CSSProperties = {
    fontSize: '9px',
    fontWeight: 800,
    letterSpacing: '0.25em',
    textTransform: 'uppercase',
    color: '#333',
}

const LLM_COLORS: Record<string, { color: string; border: string; bg: string }> = {
    claude: { color: '#d4a27a', border: '#3a2a1a', bg: '#120d08' },
    gpt: { color: '#7ac5a2', border: '#1a3a2a', bg: '#081208' },
    gemini: { color: '#7aacd4', border: '#1a2a3a', bg: '#080c12' },
    default: { color: '#888888', border: '#2a2a2a', bg: '#0d0d0d' },
}

function llmStyle(llm: string) {
    const key = Object.keys(LLM_COLORS).find(k => String(llm || '').toLowerCase().includes(k))
    return LLM_COLORS[key || 'default']
}

// ─── MCP Auto-Capture Helpers ───────────────────────────────────────────────

/** Returns true if a conversation was auto-captured from MCP tool activity (not a real conversation). */
function isMcpAutoCapture(conv: Conversation): boolean {
    return (conv.tags || []).some(t =>
        t === 'source:mcp:auto-capture:v1' ||
        t === 'source:mcp:auto-capture' ||
        t === 'source:mcp'
    )
}

interface ParsedToolCall {
    toolName: string
    args: Record<string, unknown>
}

/** Parse auto-captured tool call content: "tool:memory_read args={...}" */
function parseToolCallContent(content: string): ParsedToolCall | null {
    const m = content.match(/^tool:([^\s]+)\s+args=(\{[\s\S]*\})$/)
    if (!m) return null
    try {
        return { toolName: m[1], args: JSON.parse(m[2]) }
    } catch {
        return null
    }
}

/** Render a tool call in a readable, structured way. */
function ToolCallMessage({ toolName, args }: ParsedToolCall) {
    const query = args.query as string | undefined
    const content = args.content as string | undefined
    const context = args.context as string | undefined
    const category = args.category as string | undefined
    const level = args.level as string | undefined
    const limit = args.limit as number | undefined

    return (
        <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                <Terminal size={11} style={{ color: '#4ade80', flexShrink: 0 }} />
                <span style={{ fontFamily: 'monospace', color: '#4ade80', fontSize: '11px', fontWeight: 700 }}>
                    {toolName}
                </span>
            </div>
            {query && (
                <div style={{ marginBottom: '4px' }}>
                    <span style={{ fontSize: '9px', color: '#444', textTransform: 'uppercase', letterSpacing: '0.1em' }}>query · </span>
                    <span style={{ fontSize: '12px', color: '#aaa', fontStyle: 'italic' }}>«{query}»</span>
                </div>
            )}
            {content && (
                <div style={{ marginBottom: '4px' }}>
                    <span style={{ fontSize: '9px', color: '#444', textTransform: 'uppercase', letterSpacing: '0.1em' }}>content · </span>
                    <span style={{ fontSize: '12px', color: '#aaa' }}>{content}</span>
                </div>
            )}
            {context && (
                <div style={{ marginBottom: '4px' }}>
                    <span style={{ fontSize: '9px', color: '#444', textTransform: 'uppercase', letterSpacing: '0.1em' }}>context · </span>
                    <span style={{ fontSize: '11px', color: '#666' }}>{context}</span>
                </div>
            )}
            {(category || level) && (
                <div style={{ display: 'flex', gap: '8px', marginBottom: '4px' }}>
                    {category && <span style={{ fontSize: '9px', color: '#555', border: '1px solid #2a2a2a', borderRadius: '2px', padding: '1px 5px' }}>{category}</span>}
                    {level && <span style={{ fontSize: '9px', color: '#555', border: '1px solid #2a2a2a', borderRadius: '2px', padding: '1px 5px' }}>{level}</span>}
                </div>
            )}
            {limit !== undefined && !query && !content && !context && (
                <span style={{ fontSize: '9px', color: '#444' }}>limit: {limit}</span>
            )}
            {/* Show raw JSON only when there's nothing more meaningful to show */}
            {!query && !content && !context && !category && !level && Object.keys(args).length > 0 && (
                <pre style={{ margin: 0, fontSize: '10px', color: '#555', fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>
                    {JSON.stringify(args, null, 2)}
                </pre>
            )}
        </div>
    )
}

// ─── Conversations ──────────────────────────────────────────────────────────

export function Conversations() {
    const { selectedConversationId, setSelectedConversation } = useAppStore()
    const [selectedId, setSelectedId] = useState<string | null>(selectedConversationId)
    const [search, setSearch] = useState('')
    const [showMcpTraces, setShowMcpTraces] = useState(false)
    const { data: conversations, isLoading } = useConversations(
        search,
        search.trim() ? 200 : 5000,
        0
    )
    const allRows = useMemo(() => (conversations || []) as Conversation[], [conversations])
    const rows = useMemo(
        () => showMcpTraces ? allRows : allRows.filter(c => !isMcpAutoCapture(c)),
        [allRows, showMcpTraces]
    )
    const mcpTraceCount = useMemo(() => allRows.filter(isMcpAutoCapture).length, [allRows])

    useEffect(() => {
        if (selectedConversationId !== selectedId) {
            setSelectedId(selectedConversationId)
        }
    }, [selectedConversationId])

    return (
        <div style={{ display: 'flex', height: '100%', background: '#0a0a0a' }}>

            {/* ── Left list ─────────────────────────────────────────────── */}
            <div
                style={{
                    width: '300px',
                    borderRight: '1px solid #1a1a1a',
                    display: 'flex',
                    flexDirection: 'column',
                    flexShrink: 0,
                }}
            >
                {/* Search header */}
                <div style={{ padding: '12px', borderBottom: '1px solid #1a1a1a' }}>
                    <div style={{ position: 'relative' }}>
                        <Search
                            size={13}
                            style={{
                                position: 'absolute',
                                left: '10px',
                                top: '50%',
                                transform: 'translateY(-50%)',
                                color: '#333',
                                pointerEvents: 'none',
                            }}
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
                                transition: 'border-color 150ms ease',
                            }}
                            placeholder="Search history..."
                            value={search}
                            onChange={e => setSearch(e.target.value)}
                            onFocus={e => (e.target.style.borderColor = '#2a2a2a')}
                            onBlur={e => (e.target.style.borderColor = '#1e1e1e')}
                        />
                    </div>
                    {/* MCP trace toggle */}
                    {mcpTraceCount > 0 && (
                        <button
                            onClick={() => setShowMcpTraces(v => !v)}
                            style={{
                                marginTop: '8px',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '5px',
                                background: 'transparent',
                                border: '1px solid #1e1e1e',
                                borderRadius: '4px',
                                padding: '4px 8px',
                                cursor: 'pointer',
                                width: '100%',
                                color: showMcpTraces ? '#4ade80' : '#444',
                                fontSize: '10px',
                                letterSpacing: '0.06em',
                                fontFamily: 'inherit',
                                transition: 'color 150ms ease, border-color 150ms ease',
                            }}
                            onMouseEnter={e => (e.currentTarget.style.borderColor = '#2a2a2a')}
                            onMouseLeave={e => (e.currentTarget.style.borderColor = '#1e1e1e')}
                        >
                            {showMcpTraces
                                ? <Eye size={10} />
                                : <EyeOff size={10} />
                            }
                            <span>{showMcpTraces ? 'Hiding' : 'Show'} {mcpTraceCount} MCP trace{mcpTraceCount !== 1 ? 's' : ''}</span>
                        </button>
                    )}
                </div>

                {/* List */}
                <div style={{ flex: 1, overflowY: 'auto', padding: '8px' }}>
                    {isLoading ? (
                        <div style={{ padding: '4px 0' }}>
                            {Array.from({ length: 8 }).map((_, i) => (
                                <div key={i} style={{ padding: '10px 12px', marginBottom: '2px', borderRadius: '4px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                    <div style={{ height: '10px', borderRadius: '3px', background: '#1a1a1a', width: `${55 + (i % 3) * 15}%`, animation: 'skeleton-pulse 1.4s ease-in-out infinite', animationDelay: `${i * 80}ms` }} />
                                    <div style={{ height: '8px', borderRadius: '3px', background: '#161616', width: `${35 + (i % 4) * 10}%`, animation: 'skeleton-pulse 1.4s ease-in-out infinite', animationDelay: `${i * 80 + 100}ms` }} />
                                </div>
                            ))}
                        </div>
                    ) : rows.length === 0 ? (
                        <div
                            style={{
                                textAlign: 'center',
                                color: '#333',
                                fontSize: '11px',
                                padding: '40px 20px',
                                fontWeight: 500,
                                letterSpacing: '0.04em',
                                textTransform: 'uppercase',
                            }}
                        >
                            {search ? 'No results' : allRows.length > 0 ? 'No full conversations yet' : 'No conversations'}
                        </div>
                    ) : (
                        rows.map((conv) => {
                            const active = selectedId === conv.id
                            const llm = llmStyle(conv.source_llm)
                            const isMcp = isMcpAutoCapture(conv)
                            return (
                                <div
                                    key={conv.id}
                                    onClick={() => {
                                        setSelectedId(conv.id)
                                        setSelectedConversation(conv.id)
                                    }}
                                    style={{
                                        padding: '12px 14px',
                                        borderRadius: '4px',
                                        cursor: 'pointer',
                                        background: active ? '#0d0d0d' : 'transparent',
                                        border: `1px solid ${active ? '#2a2a2a' : '#1e1e1e'}`,
                                        marginBottom: '4px',
                                        transition: 'border-color 150ms ease, background 150ms ease',
                                        opacity: isMcp ? 0.75 : 1,
                                    }}
                                    onMouseEnter={e => {
                                        if (!active) {
                                            const el = e.currentTarget as HTMLElement
                                            el.style.borderColor = '#333'
                                            el.style.background = '#0d0d0d'
                                        }
                                    }}
                                    onMouseLeave={e => {
                                        if (!active) {
                                            const el = e.currentTarget as HTMLElement
                                            el.style.borderColor = '#1e1e1e'
                                            el.style.background = 'transparent'
                                        }
                                    }}
                                >
                                    <p
                                        style={{
                                            fontSize: '12px',
                                            fontWeight: 600,
                                            color: active ? '#e8e8e8' : '#c8c8c8',
                                            margin: '0 0 8px',
                                            whiteSpace: 'nowrap',
                                            overflow: 'hidden',
                                            textOverflow: 'ellipsis',
                                            lineHeight: 1.3,
                                        }}
                                    >
                                        {conv.title}
                                    </p>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                        {/* MCP trace badge */}
                                        {isMcp ? (
                                            <span
                                                style={{
                                                    fontSize: '8px',
                                                    fontWeight: 700,
                                                    letterSpacing: '0.12em',
                                                    textTransform: 'uppercase',
                                                    color: '#4ade80',
                                                    border: '1px solid #1a3a1a',
                                                    borderRadius: '2px',
                                                    padding: '2px 5px',
                                                    background: '#081208',
                                                    display: 'flex',
                                                    alignItems: 'center',
                                                    gap: '3px',
                                                }}
                                            >
                                                <Terminal size={7} />
                                                MCP trace
                                            </span>
                                        ) : (
                                            /* LLM badge for real conversations */
                                            <span
                                                style={{
                                                    fontSize: '8px',
                                                    fontWeight: 700,
                                                    letterSpacing: '0.12em',
                                                    textTransform: 'uppercase',
                                                    color: llm.color,
                                                    border: `1px solid ${llm.border}`,
                                                    borderRadius: '2px',
                                                    padding: '2px 5px',
                                                    background: llm.bg,
                                                }}
                                            >
                                                {conv.source_llm}
                                            </span>
                                        )}
                                        {/* Date */}
                                        <span style={{ fontSize: '10px', color: '#444' }}>
                                            {new Date(conv.started_at).toLocaleDateString()}
                                        </span>
                                        {/* Message count */}
                                        {conv.message_count > 0 && (
                                            <span style={{ fontSize: '10px', color: '#2a2a2a', marginLeft: 'auto' }}>
                                                {conv.message_count}↑
                                            </span>
                                        )}
                                    </div>
                                </div>
                            )
                        })
                    )}
                </div>
            </div>

            {/* ── Right: viewer ─────────────────────────────────────────── */}
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', background: '#080808' }}>
                {selectedId ? (
                    <ConversationViewer
                        id={selectedId}
                        onDelete={() => { setSelectedId(null); setSelectedConversation(null) }}
                    />
                ) : (
                    <div
                        style={{
                            flex: 1,
                            display: 'flex',
                            flexDirection: 'column',
                            alignItems: 'center',
                            justifyContent: 'center',
                            gap: '16px',
                            padding: '40px',
                        }}
                    >
                        <PalimpsestIcon color="#1e1e1e" style={{ width: 40, height: 40 }} />
                        <p
                            style={{
                                fontSize: '10px',
                                fontWeight: 500,
                                letterSpacing: '0.1em',
                                textTransform: 'uppercase',
                                color: '#2a2a2a',
                                margin: 0,
                            }}
                        >
                            Select a conversation
                        </p>
                    </div>
                )}
            </div>
        </div>
    )
}

// ─── ConversationViewer ─────────────────────────────────────────────────────

function ConversationViewer({ id, onDelete }: { id: string; onDelete: () => void }) {
    const { data: conv, isLoading } = useConversation(id)
    const { mutate: deleteConversation, isPending: isDeleting } = useDeleteConversation()
    const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
    const conversation = conv as Conversation | null
    const messages = (conversation?.messages || []) as ConversationMessage[]

    const handleDelete = () => {
        deleteConversation(id, {
            onSuccess: () => { setShowDeleteConfirm(false); onDelete() }
        })
    }

    if (isLoading) return (
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Loader2 size={18} style={{ color: '#2a2a2a', animation: 'spin 1s linear infinite' }} />
        </div>
    )

    if (!conversation) return null

    const llm = llmStyle(conversation.source_llm)
    const isMcp = isMcpAutoCapture(conversation)

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

            {/* ── Viewer Header ──────────────────────────────────────────── */}
            <div
                style={{
                    padding: '20px 28px',
                    borderBottom: '1px solid #1a1a1a',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'flex-start',
                    gap: '12px',
                    background: '#080808',
                    flexShrink: 0,
                }}
            >
                <div style={{ minWidth: 0 }}>
                    <h1
                        style={{
                            fontSize: '16px',
                            fontWeight: 800,
                            color: '#f5f3ee',
                            margin: '0 0 10px',
                            letterSpacing: '-0.01em',
                            lineHeight: 1.2,
                        }}
                    >
                        {conversation.title}
                    </h1>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                        {/* MCP or LLM badge */}
                        {isMcp ? (
                            <span
                                style={{
                                    fontSize: '8px',
                                    fontWeight: 700,
                                    letterSpacing: '0.12em',
                                    textTransform: 'uppercase',
                                    color: '#4ade80',
                                    border: '1px solid #1a3a1a',
                                    borderRadius: '2px',
                                    padding: '2px 6px',
                                    background: '#081208',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '4px',
                                }}
                            >
                                <Terminal size={8} />
                                MCP activity trace
                            </span>
                        ) : (
                            <span
                                style={{
                                    fontSize: '8px',
                                    fontWeight: 700,
                                    letterSpacing: '0.12em',
                                    textTransform: 'uppercase',
                                    color: llm.color,
                                    border: `1px solid ${llm.border}`,
                                    borderRadius: '2px',
                                    padding: '2px 6px',
                                    background: llm.bg,
                                }}
                            >
                                {conversation.source_llm}
                            </span>
                        )}
                        {/* Date */}
                        <span style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '11px', color: '#444' }}>
                            <Calendar size={10} />
                            {new Date(conversation.started_at).toLocaleString()}
                        </span>
                        {/* Message count */}
                        <span
                            style={{
                                fontSize: '8px',
                                fontWeight: 700,
                                letterSpacing: '0.12em',
                                textTransform: 'uppercase',
                                color: '#555',
                                border: '1px solid #222',
                                borderRadius: '2px',
                                padding: '2px 5px',
                            }}
                        >
                            {conversation.message_count} msg
                        </span>
                        {/* Tags — skip the auto-capture tags since we already show the badge */}
                        {conversation.tags
                            ?.filter(tag => !tag.startsWith('source:mcp'))
                            .map((tag: string) => (
                                <span
                                    key={tag}
                                    style={{
                                        fontSize: '9px',
                                        border: '1px solid #222',
                                        borderRadius: '999px',
                                        padding: '2px 7px',
                                        color: '#555',
                                    }}
                                >
                                    #{tag}
                                </span>
                            ))}
                    </div>
                </div>

                {/* Delete */}
                <button
                    onClick={() => setShowDeleteConfirm(true)}
                    disabled={isDeleting}
                    style={{
                        width: '32px',
                        height: '32px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        background: 'transparent',
                        border: '1px solid transparent',
                        borderRadius: '4px',
                        cursor: 'pointer',
                        color: '#333',
                        flexShrink: 0,
                        transition: 'color 150ms ease, border-color 150ms ease',
                    }}
                    onMouseEnter={e => {
                        const el = e.currentTarget as HTMLButtonElement
                        el.style.color = '#ef4444'
                        el.style.borderColor = '#2a2a2a'
                    }}
                    onMouseLeave={e => {
                        const el = e.currentTarget as HTMLButtonElement
                        el.style.color = '#333'
                        el.style.borderColor = 'transparent'
                    }}
                >
                    {isDeleting
                        ? <Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} />
                        : <Trash size={16} />
                    }
                </button>
            </div>

            {/* ── MCP Trace Banner ───────────────────────────────────────── */}
            {isMcp && (
                <div
                    style={{
                        padding: '10px 28px',
                        background: '#040808',
                        borderBottom: '1px solid #0d1a0d',
                        display: 'flex',
                        alignItems: 'flex-start',
                        gap: '8px',
                    }}
                >
                    <Terminal size={12} style={{ color: '#2a6a2a', marginTop: '1px', flexShrink: 0 }} />
                    <p style={{ margin: 0, fontSize: '11px', color: '#2a6a2a', lineHeight: 1.5 }}>
                        This is an <strong>MCP activity trace</strong> — a log of the memory tool calls made during a session.
                        The original user/assistant messages were not sent to Mnesis and cannot be recorded here.
                        To capture full conversations, the assistant must call <code style={{ fontFamily: 'monospace', background: '#0a1a0a', padding: '1px 4px', borderRadius: '2px' }}>conversation_sync()</code> at the end of each session.
                    </p>
                </div>
            )}

            {/* ── Viewer Content ─────────────────────────────────────────── */}
            <div style={{ flex: 1, overflowY: 'auto', padding: '20px 28px' }}>

                {/* Summary panel */}
                {conversation.summary && (
                    <div
                        style={{
                            marginBottom: '16px',
                            padding: '12px 14px',
                            background: '#060606',
                            border: '1px solid #1a1a1a',
                            borderLeft: '2px solid #333',
                            borderRadius: '4px',
                        }}
                    >
                        <p style={{ ...LABEL, marginBottom: '8px', color: '#444' }}>Summary</p>
                        <p style={{ margin: 0, color: '#7a7a7a', fontSize: '12px', lineHeight: 1.65 }}>
                            {conversation.summary}
                        </p>
                    </div>
                )}

                {/* Messages */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {messages.map((msg) => {
                        const role = (msg.role || 'user').toLowerCase()
                        const isAssistant = role === 'assistant'
                        const parsedTool = parseToolCallContent(msg.content)
                        const isTool = parsedTool !== null

                        return (
                            <div
                                key={msg.id}
                                style={{
                                    padding: '10px 14px',
                                    background: isTool ? '#040a04' : '#060606',
                                    border: `1px solid ${isTool ? '#0d1a0d' : '#1a1a1a'}`,
                                    borderLeft: `2px solid ${isTool ? '#1a4a1a' : isAssistant ? '#22d3ee' : '#2a2a2a'}`,
                                    borderRadius: '4px',
                                    transition: 'border-color 150ms ease',
                                }}
                                onMouseEnter={e => {
                                    (e.currentTarget as HTMLElement).style.borderColor = isTool ? '#1a3a1a' : '#2a2a2a'
                                }}
                                onMouseLeave={e => {
                                    (e.currentTarget as HTMLElement).style.borderColor = isTool ? '#0d1a0d' : '#1a1a1a'
                                }}
                            >
                                <div
                                    style={{
                                        display: 'flex',
                                        alignItems: 'center',
                                        justifyContent: 'space-between',
                                        gap: '8px',
                                        marginBottom: '7px',
                                    }}
                                >
                                    <span
                                        style={{
                                            fontSize: '9px',
                                            fontWeight: 800,
                                            letterSpacing: '0.2em',
                                            textTransform: 'uppercase',
                                            color: isTool ? '#2a6a2a' : isAssistant ? '#22d3ee' : '#555',
                                        }}
                                    >
                                        {isTool ? 'tool call' : role}
                                    </span>
                                    <span style={{ fontSize: '10px', color: '#333' }}>
                                        {new Date(msg.timestamp).toLocaleString()}
                                    </span>
                                </div>
                                {isTool ? (
                                    <ToolCallMessage {...parsedTool} />
                                ) : (
                                    <p
                                        style={{
                                            margin: 0,
                                            whiteSpace: 'pre-wrap',
                                            color: isAssistant ? '#c0c0c0' : '#888',
                                            fontSize: '12px',
                                            lineHeight: 1.65,
                                        }}
                                    >
                                        {msg.content}
                                    </p>
                                )}
                            </div>
                        )
                    })}
                </div>

                {/* Empty messages */}
                {messages.length === 0 && (
                    <div
                        style={{
                            padding: '32px',
                            background: '#060606',
                            border: '1px solid #1a1a1a',
                            borderRadius: '4px',
                            fontSize: '11px',
                            color: '#333',
                            textAlign: 'center',
                        }}
                    >
                        No messages available for this conversation.
                    </div>
                )}

                {/* Linked Memories */}
                {conversation.memory_ids?.length > 0 && (
                    <div style={{ marginTop: '24px' }}>
                        <p style={{ ...LABEL, marginBottom: '10px', color: '#444' }}>
                            Linked Memories
                        </p>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                            {conversation.memory_ids.map((memId: string) => (
                                <div
                                    key={memId}
                                    style={{
                                        padding: '8px 12px',
                                        background: '#060606',
                                        border: '1px solid #1a1a1a',
                                        borderRadius: '4px',
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: '8px',
                                        fontSize: '11px',
                                        color: '#444',
                                        transition: 'border-color 150ms ease',
                                    }}
                                    onMouseEnter={e => ((e.currentTarget as HTMLElement).style.borderColor = '#2a2a2a')}
                                    onMouseLeave={e => ((e.currentTarget as HTMLElement).style.borderColor = '#1a1a1a')}
                                >
                                    <div
                                        style={{
                                            width: '4px',
                                            height: '4px',
                                            borderRadius: '50%',
                                            background: '#333',
                                            flexShrink: 0,
                                        }}
                                    />
                                    <span style={{ fontFamily: 'monospace', fontSize: '10px', color: '#393939' }}>
                                        {memId}
                                    </span>
                                </div>
                            ))}
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}
