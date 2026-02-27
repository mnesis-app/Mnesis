import { useRef, useState } from 'react'
import { ArrowUp, Loader2, MemoryStick, Sparkles } from 'lucide-react'
import { getBaseUrl } from '../lib/api'

// ── Types ─────────────────────────────────────────────────────────────────────

interface Citation {
    id: string
    content: string
    category: string
    source_llm: string
    created_at: string
    score: number
}

interface Turn {
    query: string
    answer: string
    citations: Citation[]
    streaming: boolean
}

async function streamChat(
    query: string,
    onCitations: (c: Citation[]) => void,
    onToken: (t: string) => void,
    onDone: () => void,
    signal: AbortSignal,
) {
    const url = `${getBaseUrl()}/api/v1/chat`
    const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Mnesis-Client': 'mnesis-desktop' },
        body: JSON.stringify({ query, limit: 12 }),
        signal,
    })
    if (!res.ok || !res.body) {
        if (res.status === 404) throw new Error('Backend not running or needs restart — start with `npm run dev` (404)')
        if (res.status === 403) throw new Error('Request blocked by security middleware — check origin/client header (403)')
        throw new Error(`HTTP ${res.status}`)
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        let currentEvent = ''
        for (const line of lines) {
            if (line.startsWith('event: ')) {
                currentEvent = line.slice(7).trim()
            } else if (line.startsWith('data: ')) {
                const data = line.slice(6)
                if (currentEvent === 'citations') {
                    try { onCitations(JSON.parse(data)) } catch { /* ignore */ }
                } else if (currentEvent === 'delta') {
                    onToken(data.replace(/\\n/g, '\n'))
                } else if (currentEvent === 'done') {
                    onDone()
                }
            }
        }
    }
    onDone()
}

// ── Styles ────────────────────────────────────────────────────────────────────

const S = {
    page: {
        display: 'flex',
        flexDirection: 'column' as const,
        height: '100%',
        background: '#0d0d0d',
        overflow: 'hidden',
    },
    header: {
        padding: '24px 28px 16px',
        borderBottom: '1px solid #1a1a1a',
        flexShrink: 0,
    },
    headerTitle: {
        fontSize: '13px',
        fontWeight: 700,
        color: '#e8e6e1',
        letterSpacing: '0.04em',
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        marginBottom: '2px',
    },
    headerSub: {
        fontSize: '11px',
        color: '#444',
    },
    turns: {
        flex: 1,
        overflowY: 'auto' as const,
        padding: '20px 28px',
        display: 'flex',
        flexDirection: 'column' as const,
        gap: '28px',
    },
    emptyState: {
        flex: 1,
        display: 'flex',
        flexDirection: 'column' as const,
        alignItems: 'center',
        justifyContent: 'center',
        gap: '12px',
        color: '#333',
    },
    emptyIcon: {
        width: '40px',
        height: '40px',
        borderRadius: '12px',
        background: '#141414',
        border: '1px solid #1f1f1f',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
    },
    emptyTitle: {
        fontSize: '13px',
        fontWeight: 600,
        color: '#555',
    },
    emptySub: {
        fontSize: '11px',
        color: '#333',
        textAlign: 'center' as const,
        maxWidth: '260px',
        lineHeight: 1.5,
    },
    turn: {
        display: 'flex',
        flexDirection: 'column' as const,
        gap: '12px',
    },
    queryBubble: {
        alignSelf: 'flex-end' as const,
        background: '#1a1a1a',
        border: '1px solid #272727',
        borderRadius: '12px 12px 3px 12px',
        padding: '10px 14px',
        maxWidth: '80%',
        fontSize: '13px',
        color: '#e8e6e1',
        lineHeight: 1.5,
    },
    answerBlock: {
        display: 'flex',
        flexDirection: 'column' as const,
        gap: '10px',
    },
    answerText: {
        fontSize: '13px',
        color: '#c8c5bf',
        lineHeight: 1.7,
        whiteSpace: 'pre-wrap' as const,
    },
    cursor: {
        display: 'inline-block',
        width: '2px',
        height: '13px',
        background: '#60a5fa',
        animation: 'blink 1s step-end infinite',
        verticalAlign: 'text-bottom',
        marginLeft: '2px',
    },
    citationsRow: {
        display: 'flex',
        flexWrap: 'wrap' as const,
        gap: '6px',
    },
    citationChip: {
        fontSize: '10px',
        color: '#555',
        background: '#111',
        border: '1px solid #1f1f1f',
        borderRadius: '6px',
        padding: '4px 8px',
        maxWidth: '260px',
        overflow: 'hidden' as const,
        textOverflow: 'ellipsis' as const,
        whiteSpace: 'nowrap' as const,
        cursor: 'default',
    },
    inputArea: {
        padding: '16px 28px 20px',
        borderTop: '1px solid #1a1a1a',
        flexShrink: 0,
    },
    inputRow: {
        display: 'flex',
        gap: '8px',
        alignItems: 'flex-end',
    },
    textarea: {
        flex: 1,
        background: '#111',
        border: '1px solid #222',
        borderRadius: '10px',
        padding: '10px 14px',
        fontSize: '13px',
        color: '#e8e6e1',
        resize: 'none' as const,
        outline: 'none',
        fontFamily: 'inherit',
        lineHeight: 1.5,
        minHeight: '42px',
        maxHeight: '120px',
        transition: 'border-color 0.15s',
    },
    sendBtn: {
        width: '38px',
        height: '38px',
        borderRadius: '10px',
        background: '#60a5fa',
        border: 'none',
        cursor: 'pointer',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
        transition: 'background 0.15s',
    },
    sendBtnDisabled: {
        background: '#1a1a1a',
        cursor: 'not-allowed',
    },
}

// ── Component ─────────────────────────────────────────────────────────────────

export function Ask() {
    const [turns, setTurns] = useState<Turn[]>([])
    const [input, setInput] = useState('')
    const [loading, setLoading] = useState(false)
    const abortRef = useRef<AbortController | null>(null)
    const bottomRef = useRef<HTMLDivElement>(null)
    const textareaRef = useRef<HTMLTextAreaElement>(null)

    const scrollToBottom = () => {
        setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }), 50)
    }

    const submit = async () => {
        const query = input.trim()
        if (!query || loading) return

        setInput('')
        setLoading(true)

        const turnIndex = turns.length
        setTurns(prev => [...prev, { query, answer: '', citations: [], streaming: true }])
        scrollToBottom()

        abortRef.current = new AbortController()

        try {
            await streamChat(
                query,
                (citations) => {
                    setTurns(prev => prev.map((t, i) => i === turnIndex ? { ...t, citations } : t))
                },
                (token) => {
                    setTurns(prev => prev.map((t, i) =>
                        i === turnIndex ? { ...t, answer: t.answer + token } : t
                    ))
                    scrollToBottom()
                },
                () => {
                    setTurns(prev => prev.map((t, i) => i === turnIndex ? { ...t, streaming: false } : t))
                    setLoading(false)
                },
                abortRef.current.signal,
            )
        } catch (e: any) {
            if (e?.name !== 'AbortError') {
                const raw = e?.message || 'unknown error'
                const isNetwork = raw.toLowerCase().includes('fetch') || raw.toLowerCase().includes('failed to fetch') || raw.toLowerCase().includes('networkerror')
                const display = isNetwork
                    ? 'Cannot reach the backend. Make sure Mnesis is running (`npm run dev`).'
                    : raw
                setTurns(prev => prev.map((t, i) =>
                    i === turnIndex ? { ...t, answer: display, streaming: false } : t
                ))
            }
            setLoading(false)
        }
    }

    const handleKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            submit()
        }
    }

    return (
        <div style={S.page}>
            <style>{`
                @keyframes blink { 0%, 100% { opacity: 1 } 50% { opacity: 0 } }
                .ask-textarea:focus { border-color: #333 !important; }
                .ask-send:hover:not(:disabled) { background: #93c5fd !important; }
                .citation-chip:hover { border-color: #333 !important; color: #888 !important; }
            `}</style>

            <div style={S.header}>
                <div style={S.headerTitle}>
                    <Sparkles size={14} style={{ color: '#a78bfa' }} />
                    Ask your memories
                </div>
                <div style={S.headerSub}>Natural language search with AI synthesis</div>
            </div>

            <div style={S.turns}>
                {turns.length === 0 && (
                    <div style={S.emptyState}>
                        <div style={S.emptyIcon}>
                            <MemoryStick size={18} style={{ color: '#333' }} />
                        </div>
                        <div style={S.emptyTitle}>Ask anything</div>
                        <div style={S.emptySub}>
                            Query your memory base in plain language.
                            Relevant memories are retrieved and synthesized into an answer.
                        </div>
                    </div>
                )}

                {turns.map((turn, i) => (
                    <div key={i} style={S.turn}>
                        <div style={S.queryBubble}>{turn.query}</div>

                        {(turn.answer || turn.streaming) && (
                            <div style={S.answerBlock}>
                                <div style={S.answerText}>
                                    {turn.answer || ''}
                                    {turn.streaming && <span style={S.cursor} />}
                                </div>

                                {!turn.streaming && turn.citations.length > 0 && (
                                    <div style={S.citationsRow}>
                                        {turn.citations.slice(0, 8).map((c, ci) => (
                                            <div
                                                key={c.id || ci}
                                                className="citation-chip"
                                                style={S.citationChip}
                                                title={c.content}
                                            >
                                                [{ci + 1}] {c.content.slice(0, 60)}{c.content.length > 60 ? '…' : ''}
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                ))}

                <div ref={bottomRef} />
            </div>

            <div style={S.inputArea}>
                <div style={S.inputRow}>
                    <textarea
                        ref={textareaRef}
                        className="ask-textarea"
                        style={S.textarea}
                        placeholder="What do you know about…"
                        value={input}
                        onChange={e => setInput(e.target.value)}
                        onKeyDown={handleKey}
                        rows={1}
                        disabled={loading}
                    />
                    <button
                        className="ask-send"
                        style={{ ...S.sendBtn, ...((!input.trim() || loading) ? S.sendBtnDisabled : {}) }}
                        onClick={submit}
                        disabled={!input.trim() || loading}
                        title="Send (Enter)"
                    >
                        {loading
                            ? <Loader2 size={16} style={{ color: '#555', animation: 'spin 1s linear infinite' }} />
                            : <ArrowUp size={16} style={{ color: loading || !input.trim() ? '#333' : '#0a0a0a' }} />
                        }
                    </button>
                </div>
            </div>
        </div>
    )
}
