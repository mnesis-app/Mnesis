import { useState } from 'react'
import { api } from '../lib/api'
import { Plus, Loader2, Check } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'

const inputStyle: React.CSSProperties = {
    width: '100%', background: '#060606',
    border: '1px solid #1e1e1e', borderRadius: '4px',
    padding: '10px 12px', fontSize: '13px', color: '#d0d0d0',
    outline: 'none', fontFamily: 'inherit', boxSizing: 'border-box',
    transition: 'border-color 150ms ease',
}

export function AddMemory() {
    const [content, setContent] = useState('')
    const [category, setCategory] = useState('semantic')
    const [importing, setImporting] = useState(false)
    const [success, setSuccess] = useState(false)
    const queryClient = useQueryClient()

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!content.trim()) return
        setImporting(true); setSuccess(false)
        try {
            await api.memories.create({ content, category, level: category, source_llm: 'manual', confidence_score: 1.0 })
            setContent('')
            setSuccess(true)
            queryClient.invalidateQueries({ queryKey: ['memories'] })
            setTimeout(() => setSuccess(false), 3000)
        } catch (err) { console.error(err) }
        finally { setImporting(false) }
    }

    return (
        <div style={{ padding: '36px 40px', maxWidth: '640px' }}>
            <div style={{ marginBottom: '28px' }}>
                <h1 style={{ fontSize: '22px', fontWeight: 800, margin: '0 0 6px', letterSpacing: '-0.02em', color: '#f5f3ee' }}>
                    Add Memory
                </h1>
                <p style={{ fontSize: '12px', color: '#444', margin: 0 }}>
                    Manually insert a fact, preference, or project detail.
                </p>
            </div>

            <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                {/* Content */}
                <div>
                    <label style={{
                        fontSize: '9px', fontWeight: 800, letterSpacing: '0.25em',
                        textTransform: 'uppercase', color: '#333',
                        display: 'block', marginBottom: '8px',
                    }}>
                        Content
                        <span style={{ fontWeight: 400, marginLeft: '8px', letterSpacing: '0.1em', color: '#2a2a2a' }}>
                            (third-person format recommended)
                        </span>
                    </label>
                    <textarea
                        value={content}
                        onChange={e => setContent(e.target.value)}
                        placeholder="e.g. Thomas prefers concise answers without preamble."
                        autoFocus
                        style={{ ...inputStyle, height: '120px', resize: 'none', lineHeight: 1.6 } as React.CSSProperties}
                        onFocus={e => (e.target.style.borderColor = '#2a2a2a')}
                        onBlur={e => (e.target.style.borderColor = '#1e1e1e')}
                    />
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '6px' }}>
                        <span style={{ fontSize: '10px', color: '#2a2a2a' }}>{content.length} / 1000</span>
                        {content.length > 0 && content.length < 20 && (
                            <span style={{ fontSize: '10px', color: '#7c3a1f' }}>Too short (min 20)</span>
                        )}
                    </div>
                </div>

                {/* Category */}
                <div>
                    <label style={{
                        fontSize: '9px', fontWeight: 800, letterSpacing: '0.25em',
                        textTransform: 'uppercase', color: '#333', display: 'block', marginBottom: '8px',
                    }}>Category</label>
                    <select
                        value={category}
                        onChange={e => setCategory(e.target.value)}
                        style={{ ...inputStyle, cursor: 'pointer' }}
                    >
                        <option value="semantic">Semantic — General Knowledge</option>
                        <option value="episodic">Episodic — Events & Experiences</option>
                        <option value="working">Working — Temporary Context</option>
                    </select>
                </div>

                {/* Submit */}
                <button
                    type="submit"
                    disabled={importing || content.length < 20}
                    style={{
                        display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px',
                        padding: '12px 24px', borderRadius: '4px', border: 'none',
                        fontFamily: 'inherit', fontWeight: 800, fontSize: '10px',
                        letterSpacing: '0.2em', textTransform: 'uppercase', cursor: 'pointer',
                        transition: 'all 150ms ease',
                        background: (importing || content.length < 20) ? '#111' : (success ? '#10b981' : '#f5f3ee'),
                        color: (importing || content.length < 20) ? '#222' : '#0a0a0a',
                        marginTop: '8px',
                    }}
                >
                    {importing
                        ? <Loader2 size={15} style={{ animation: 'spin 1s linear infinite' }} />
                        : success
                            ? <Check size={15} />
                            : <Plus size={15} />
                    }
                    {success ? 'Saved!' : 'Save Memory'}
                </button>
            </form>
        </div>
    )
}
