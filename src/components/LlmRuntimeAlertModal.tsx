import { AlertTriangle, ExternalLink, X } from 'lucide-react'
import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import type { LlmRuntimeIssue } from '../lib/runtimeAlerts'

interface LlmRuntimeAlertModalProps {
    issue: LlmRuntimeIssue | null
    isOpen: boolean
    onOpenSettings: () => void
    onDismiss: () => void
}

function providerLabel(provider: string): string {
    const normalized = String(provider || '').trim().toLowerCase()
    if (normalized === 'ollama') return 'Ollama'
    if (normalized === 'openai') return 'OpenAI'
    if (normalized === 'anthropic') return 'Anthropic'
    return normalized ? normalized : 'LLM runtime'
}

export function LlmRuntimeAlertModal({
    issue,
    isOpen,
    onOpenSettings,
    onDismiss,
}: LlmRuntimeAlertModalProps) {
    useEffect(() => {
        if (!isOpen) return
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') onDismiss()
        }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
    }, [isOpen, onDismiss])

    if (!isOpen || !issue) return null

    const provider = providerLabel(issue.provider)
    const model = String(issue.model || '').trim()
    const baseUrl = String(issue.apiBaseUrl || '').trim()
    const looksLikeOllama = String(issue.provider || '').trim().toLowerCase() === 'ollama' || issue.message.toLowerCase().includes('ollama')

    return createPortal(
        <div
            onClick={(event) => {
                if (event.target === event.currentTarget) onDismiss()
            }}
            style={{
                position: 'fixed',
                inset: 0,
                background: 'rgba(0,0,0,0.62)',
                backdropFilter: 'blur(2px)',
                zIndex: 140,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                padding: '18px',
            }}
        >
            <div
                role="dialog"
                aria-modal="true"
                aria-label="LLM runtime unavailable"
                style={{
                    width: 'min(560px, 100%)',
                    border: '1px solid #2b2b2b',
                    borderRadius: '9px',
                    background: '#0b0b0b',
                    boxShadow: '0 20px 60px rgba(0,0,0,0.6)',
                    padding: '14px 14px 12px',
                }}
            >
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: '10px' }}>
                    <div
                        style={{
                            width: '28px',
                            height: '28px',
                            borderRadius: '6px',
                            border: '1px solid #3a2525',
                            background: '#180f0f',
                            color: '#fca5a5',
                            display: 'inline-flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            flexShrink: 0,
                        }}
                    >
                        <AlertTriangle size={15} />
                    </div>
                    <div style={{ minWidth: 0, flex: 1 }}>
                        <h3
                            style={{
                                margin: 0,
                                fontSize: '14px',
                                fontWeight: 700,
                                letterSpacing: '0.02em',
                                color: '#f3f3f0',
                            }}
                        >
                            LLM runtime unavailable
                        </h3>
                        <p style={{ margin: '4px 0 0', fontSize: '11px', color: '#9b9b9b', lineHeight: 1.5 }}>
                            Mnesis can still run locally, but AI insights and conversation memory mining will be degraded
                            until the runtime is available.
                        </p>
                    </div>
                    <button
                        onClick={onDismiss}
                        style={{
                            width: '24px',
                            height: '24px',
                            border: '1px solid #242424',
                            borderRadius: '4px',
                            background: '#101010',
                            color: '#8c8c8c',
                            cursor: 'pointer',
                            display: 'inline-flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            flexShrink: 0,
                        }}
                        aria-label="Dismiss runtime warning"
                        title="Dismiss"
                    >
                        <X size={12} />
                    </button>
                </div>

                <div
                    style={{
                        marginTop: '11px',
                        border: '1px solid #232323',
                        borderRadius: '7px',
                        background: '#0f0f0f',
                        padding: '9px 10px',
                    }}
                >
                    <div style={{ fontSize: '10px', color: '#6f6f6f', letterSpacing: '0.09em', textTransform: 'uppercase' }}>
                        Runtime
                    </div>
                    <div style={{ marginTop: '5px', fontSize: '12px', color: '#d4d4cf' }}>
                        {provider}
                        {model ? ` · ${model}` : ''}
                        {baseUrl ? ` · ${baseUrl}` : ''}
                    </div>
                    <div style={{ marginTop: '8px', fontSize: '11px', color: '#a9a9a4', lineHeight: 1.45 }}>
                        {issue.message}
                    </div>
                </div>

                {looksLikeOllama && (
                    <div
                        style={{
                            marginTop: '9px',
                            border: '1px solid #222a24',
                            borderRadius: '7px',
                            background: '#0d120f',
                            padding: '8px 10px',
                        }}
                    >
                        <div style={{ fontSize: '10px', color: '#82cbb3', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
                            Quick fix
                        </div>
                        <div style={{ marginTop: '6px', fontSize: '11px', color: '#b8c9c1', lineHeight: 1.5 }}>
                            Start Ollama (`ollama serve`) and ensure the model exists (`ollama pull {model || 'llama3.2:3b'}`).
                        </div>
                    </div>
                )}

                <div style={{ marginTop: '12px', display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                    <button
                        onClick={onDismiss}
                        style={{
                            height: '31px',
                            border: '1px solid #242424',
                            borderRadius: '6px',
                            background: '#101010',
                            color: '#9b9b9b',
                            padding: '0 11px',
                            fontSize: '10px',
                            fontWeight: 600,
                            letterSpacing: '0.09em',
                            textTransform: 'uppercase',
                            cursor: 'pointer',
                        }}
                    >
                        Dismiss
                    </button>
                    <button
                        onClick={onOpenSettings}
                        style={{
                            height: '31px',
                            border: '1px solid #1f3a2f',
                            borderRadius: '6px',
                            background: '#0d1713',
                            color: '#9de6cc',
                            padding: '0 11px',
                            fontSize: '10px',
                            fontWeight: 700,
                            letterSpacing: '0.09em',
                            textTransform: 'uppercase',
                            cursor: 'pointer',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '5px',
                        }}
                    >
                        Open settings
                        <ExternalLink size={11} />
                    </button>
                </div>
            </div>
        </div>,
        document.body
    )
}
