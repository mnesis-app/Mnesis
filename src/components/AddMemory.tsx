import { useState } from 'react'
import { api } from '../lib/api'
import { Loader2, Check, Brain } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'

// ─── Tokens ────────────────────────────────────────────────────────────────

const LABEL: React.CSSProperties = {
    fontSize: '9px',
    fontWeight: 800,
    letterSpacing: '0.25em',
    textTransform: 'uppercase',
    color: '#333',
    display: 'block',
    marginBottom: '8px',
}

// ─── Category Config ────────────────────────────────────────────────────────

const CATEGORIES = [
    {
        value: 'semantic',
        label: 'Semantic',
        sub: 'General facts & knowledge',
        color: '#60a5fa',
        bgTint: 'rgba(96, 165, 250, 0.04)',
    },
    {
        value: 'episodic',
        label: 'Episodic',
        sub: 'Events & experiences',
        color: '#a78bfa',
        bgTint: 'rgba(167, 139, 250, 0.04)',
    },
    {
        value: 'working',
        label: 'Working',
        sub: 'Temporary context',
        color: '#10b981',
        bgTint: 'rgba(16, 185, 129, 0.04)',
    },
]

const MAX_CHARS = 1000
const MIN_CHARS = 20

// ─── Category Tile ──────────────────────────────────────────────────────────

function CategoryTile({
    cat,
    selected,
    onSelect,
}: {
    cat: (typeof CATEGORIES)[0]
    selected: boolean
    onSelect: () => void
}) {
    return (
        <button
            type="button"
            onClick={onSelect}
            style={{
                flex: 1,
                display: 'flex',
                alignItems: 'flex-start',
                gap: '10px',
                padding: '11px 13px',
                border: `1px solid ${selected ? cat.color : '#1e1e1e'}`,
                borderRadius: '4px',
                background: selected ? cat.bgTint : '#050505',
                cursor: 'pointer',
                fontFamily: 'inherit',
                textAlign: 'left',
                transition: 'border-color 150ms ease, background 150ms ease',
            }}
            onMouseEnter={e => {
                if (!selected) (e.currentTarget as HTMLButtonElement).style.borderColor = '#2a2a2a'
            }}
            onMouseLeave={e => {
                if (!selected) (e.currentTarget as HTMLButtonElement).style.borderColor = '#1e1e1e'
            }}
        >
            {/* Color dot */}
            <div
                style={{
                    width: '6px',
                    height: '6px',
                    borderRadius: '50%',
                    background: selected ? cat.color : '#2a2a2a',
                    flexShrink: 0,
                    marginTop: '3px',
                    transition: 'background 150ms ease',
                }}
            />
            <div>
                <p
                    style={{
                        margin: 0,
                        fontSize: '11px',
                        fontWeight: 600,
                        color: selected ? cat.color : '#888',
                        letterSpacing: '0.02em',
                        transition: 'color 150ms ease',
                    }}
                >
                    {cat.label}
                </p>
                <p
                    style={{
                        margin: '2px 0 0',
                        fontSize: '10px',
                        color: selected ? '#555' : '#333',
                        lineHeight: 1.4,
                        transition: 'color 150ms ease',
                    }}
                >
                    {cat.sub}
                </p>
            </div>
        </button>
    )
}

// ─── AddMemory ──────────────────────────────────────────────────────────────

export function AddMemory() {
    const [content, setContent] = useState('')
    const [category, setCategory] = useState('semantic')
    const [importing, setImporting] = useState(false)
    const [success, setSuccess] = useState(false)
    const queryClient = useQueryClient()

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!content.trim() || content.length < MIN_CHARS) return
        setImporting(true)
        setSuccess(false)
        try {
            await api.memories.create({
                content,
                category,
                level: category,
                source_llm: 'manual',
                confidence_score: 1.0,
            })
            setContent('')
            setSuccess(true)
            queryClient.invalidateQueries({ queryKey: ['memories'] })
            setTimeout(() => setSuccess(false), 3000)
        } catch (err) {
            console.error(err)
        } finally {
            setImporting(false)
        }
    }

    const selectedCat = CATEGORIES.find(c => c.value === category) || CATEGORIES[0]
    const charPct = Math.min((content.length / MAX_CHARS) * 100, 100)
    const tooShort = content.length > 0 && content.length < MIN_CHARS
    const canSubmit = content.length >= MIN_CHARS && !importing

    return (
        <div style={{ padding: '32px 40px', maxWidth: '640px' }}>

            {/* ── Page Header ───────────────────────────────────────────── */}
            <div style={{ marginBottom: '24px', display: 'flex', alignItems: 'flex-start', gap: '12px' }}>
                <div
                    style={{
                        width: '32px',
                        height: '32px',
                        border: '1px solid #1e1e1e',
                        borderRadius: '4px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: '#444',
                        flexShrink: 0,
                        marginTop: '1px',
                    }}
                >
                    <Brain size={14} />
                </div>
                <div>
                    <h1
                        style={{
                            fontSize: '22px',
                            fontWeight: 800,
                            margin: '0 0 5px',
                            letterSpacing: '-0.02em',
                            color: '#f5f3ee',
                            lineHeight: 1.1,
                        }}
                    >
                        Add Memory
                    </h1>
                    <p style={{ fontSize: '12px', color: '#444', margin: 0, lineHeight: 1.5 }}>
                        Manually insert a fact, preference, or project detail.
                    </p>
                </div>
            </div>

            {/* ── Form Panel ────────────────────────────────────────────── */}
            <div
                style={{
                    border: '1px solid #1a1a1a',
                    borderRadius: '4px',
                    background: '#080808',
                    padding: '20px',
                }}
            >
                <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>

                    {/* Content */}
                    <div>
                        <label style={LABEL}>
                            Content
                            <span
                                style={{
                                    fontWeight: 400,
                                    marginLeft: '8px',
                                    letterSpacing: '0.1em',
                                    color: '#2a2a2a',
                                }}
                            >
                                third-person recommended
                            </span>
                        </label>
                        <textarea
                            value={content}
                            onChange={e => setContent(e.target.value)}
                            placeholder="e.g. Thomas prefers concise answers without preamble."
                            autoFocus
                            maxLength={MAX_CHARS}
                            style={{
                                width: '100%',
                                height: '140px',
                                background: '#050505',
                                border: '1px solid #1e1e1e',
                                borderRadius: '4px',
                                padding: '10px 12px',
                                fontSize: '12px',
                                color: '#c0c0c0',
                                outline: 'none',
                                fontFamily: 'inherit',
                                boxSizing: 'border-box',
                                resize: 'none',
                                lineHeight: 1.6,
                                transition: 'border-color 150ms ease',
                            }}
                            onFocus={e => (e.target.style.borderColor = '#333')}
                            onBlur={e => (e.target.style.borderColor = '#1e1e1e')}
                        />

                        {/* Char progress bar */}
                        <div
                            style={{
                                height: '2px',
                                background: '#111',
                                borderRadius: '1px',
                                marginTop: '6px',
                                overflow: 'hidden',
                            }}
                        >
                            <div
                                style={{
                                    height: '100%',
                                    width: `${charPct}%`,
                                    background: charPct > 90 ? '#f59e0b' : '#22d3ee',
                                    borderRadius: '1px',
                                    transition: 'width 100ms ease, background 150ms ease',
                                }}
                            />
                        </div>

                        {/* Counter row */}
                        <div
                            style={{
                                display: 'flex',
                                justifyContent: 'space-between',
                                marginTop: '5px',
                            }}
                        >
                            <span style={{ fontSize: '10px', color: '#444' }}>
                                {content.length} / {MAX_CHARS}
                            </span>
                            {tooShort && (
                                <span style={{ fontSize: '10px', color: '#fca5a5' }}>
                                    Min {MIN_CHARS} characters
                                </span>
                            )}
                        </div>
                    </div>

                    {/* Divider */}
                    <div style={{ borderTop: '1px solid #111', margin: '0 0 0' }} />

                    {/* Category */}
                    <div>
                        <span style={LABEL}>Category</span>
                        <div style={{ display: 'flex', gap: '8px' }}>
                            {CATEGORIES.map(cat => (
                                <CategoryTile
                                    key={cat.value}
                                    cat={cat}
                                    selected={category === cat.value}
                                    onSelect={() => setCategory(cat.value)}
                                />
                            ))}
                        </div>
                    </div>

                    {/* Submit */}
                    <button
                        type="submit"
                        disabled={!canSubmit}
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            gap: '8px',
                            height: '38px',
                            padding: '0 24px',
                            borderRadius: '4px',
                            border: canSubmit ? 'none' : '1px solid #1a1a1a',
                            fontFamily: 'inherit',
                            fontWeight: 800,
                            fontSize: '10px',
                            letterSpacing: '0.2em',
                            textTransform: 'uppercase',
                            cursor: canSubmit ? 'pointer' : 'default',
                            transition: 'background 150ms ease, color 150ms ease',
                            background: !canSubmit
                                ? '#0d0d0d'
                                : success
                                    ? '#10b981'
                                    : '#f5f3ee',
                            color: !canSubmit
                                ? '#2a2a2a'
                                : '#0a0a0a',
                        }}
                    >
                        {importing ? (
                            <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />
                        ) : success ? (
                            <Check size={14} />
                        ) : (
                            <div
                                style={{
                                    width: '4px',
                                    height: '4px',
                                    borderRadius: '50%',
                                    background: canSubmit ? selectedCat.color : '#2a2a2a',
                                    transition: 'background 150ms ease',
                                }}
                            />
                        )}
                        {success ? 'Memory Saved' : 'Save Memory'}
                    </button>
                </form>
            </div>
        </div>
    )
}
