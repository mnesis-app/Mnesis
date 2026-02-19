import { useConfig, useRotateToken } from '../lib/queries'
import { Loader2, RefreshCw, Copy, Check } from 'lucide-react'
import { useState } from 'react'

const sectionLabel: React.CSSProperties = {
    fontSize: '9px', fontWeight: 800, letterSpacing: '0.3em',
    textTransform: 'uppercase' as const, color: '#333', marginBottom: '12px', display: 'block',
}

const card: React.CSSProperties = {
    background: '#080808',
    border: '1px solid #1a1a1a',
    borderRadius: '4px',
    padding: '20px',
    transition: 'border-color 150ms ease',
}

export function Settings() {
    const { data: config, isLoading, isError } = useConfig()
    const rotateToken = useRotateToken()
    const [copied, setCopied] = useState(false)

    if (isLoading) return (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flex: 1, padding: '80px' }}>
            <Loader2 size={18} style={{ animation: 'spin 1s linear infinite', color: '#2a2a2a' }} />
        </div>
    )
    if (isError || !config) return (
        <div style={{ padding: '80px', color: '#ef4444', fontSize: '12px' }}>Failed to load configuration.</div>
    )

    const handleCopy = () => {
        if (config?.snapshot_read_token) {
            navigator.clipboard.writeText(config.snapshot_read_token)
            setCopied(true)
            setTimeout(() => setCopied(false), 2000)
        }
    }

    const iconBtn: React.CSSProperties = {
        padding: '7px', background: 'transparent',
        border: '1px solid #1e1e1e', borderRadius: '4px',
        cursor: 'pointer', color: '#444',
        transition: 'all 150ms ease', display: 'flex', alignItems: 'center',
    }

    return (
        <div style={{ padding: '36px 40px', maxWidth: '740px' }}>

            {/* ── Snapshot Access ── */}
            <section style={{ marginBottom: '36px' }}>
                <span style={sectionLabel}>Snapshot Access</span>
                <p style={{ fontSize: '12px', color: '#444', margin: '0 0 16px', lineHeight: 1.6 }}>
                    Use this token to allow external tools (like ChatGPT) to read your memory snapshot. Keep it secret.
                </p>
                <div style={card}>
                    <span style={{ ...sectionLabel, marginBottom: '10px' }}>Snapshot Read Token</span>
                    <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                        <code style={{
                            flex: 1, background: '#050505',
                            border: '1px solid #1a1a1a', borderRadius: '4px',
                            padding: '8px 12px', fontSize: '11px',
                            fontFamily: 'monospace', color: '#555',
                            wordBreak: 'break-all',
                        }}>
                            {config?.snapshot_read_token ?? 'Token not available'}
                        </code>
                        <button onClick={handleCopy} style={iconBtn} title="Copy">
                            {copied ? <Check size={15} style={{ color: '#10b981' }} /> : <Copy size={15} />}
                        </button>
                        <button
                            onClick={() => rotateToken.mutate()}
                            disabled={rotateToken.isPending}
                            style={iconBtn} title="Rotate"
                        >
                            {rotateToken.isPending
                                ? <Loader2 size={15} style={{ animation: 'spin 1s linear infinite' }} />
                                : <RefreshCw size={15} />}
                        </button>
                    </div>
                    <p style={{ fontSize: '10px', color: '#2a2a2a', margin: '8px 0 0' }}>
                        Rotating the token will immediately invalidate the old one.
                    </p>
                </div>
            </section>

            {/* ── Integrations ── */}
            <section style={{ marginBottom: '36px' }}>
                <span style={sectionLabel}>Integrations</span>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>

                    {/* ChatGPT */}
                    <IntegrationCard title="ChatGPT">
                        <p style={{ fontSize: '12px', color: '#444', lineHeight: 1.6, margin: '0 0 12px' }}>
                            Create a custom GPT with an Action to talk to Mnesis.
                        </p>
                        <ol style={{ margin: 0, padding: '0 0 0 16px', listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                            {[
                                'Create new GPT → Add Action',
                                'Import from URL: http://127.0.0.1:7860/openapi.json',
                                'Auth Type: API Key (Bearer). Paste Snapshot Token.',
                            ].map((s, i) => (
                                <li key={i} style={{ fontSize: '11px', color: '#444', display: 'flex', gap: '8px' }}>
                                    <span style={{ color: '#2a2a2a', flexShrink: 0 }}>{i + 1}.</span>
                                    <span>{s}</span>
                                </li>
                            ))}
                        </ol>
                    </IntegrationCard>

                    {/* Claude Desktop */}
                    <IntegrationCard title="Claude Desktop">
                        <p style={{ fontSize: '12px', color: '#444', lineHeight: 1.6, margin: '0 0 12px' }}>
                            Add Mnesis to your Claude Desktop config file.
                        </p>
                        <pre style={{
                            background: '#050505', border: '1px solid #1a1a1a',
                            borderRadius: '4px', padding: '12px', fontSize: '10px',
                            fontFamily: 'monospace', color: '#444',
                            overflowX: 'auto', margin: '0 0 8px',
                        }}>
                            {`"mcpServers": {\n  "mnesis": {\n    "command": "{app_path}/Contents/Resources/extraResources/mcp-stdio-bridge",\n    "env": {\n      "MNESIS_MCP_URL": "http://127.0.0.1:7861",\n      "MNESIS_API_KEY": "${config.snapshot_read_token}"\n    }\n  }\n}`}
                        </pre>
                        <p style={{ fontSize: '10px', color: '#2a2a2a', margin: 0 }}>
                            Config: <code style={{ fontFamily: 'monospace', color: '#333' }}>~/Library/Application Support/Claude/claude_desktop_config.json</code>
                        </p>
                    </IntegrationCard>

                    {/* Cursor */}
                    <IntegrationCard title="Cursor">
                        <p style={{ fontSize: '12px', color: '#444', lineHeight: 1.6, margin: '0 0 12px' }}>
                            Add Mnesis-MCP to your Cursor features.
                        </p>
                        <ol style={{ margin: 0, padding: '0 0 0 16px', listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                            <li style={{ fontSize: '11px', color: '#444', display: 'flex', gap: '8px' }}>
                                <span style={{ color: '#2a2a2a' }}>1.</span>
                                <span>Go to <strong style={{ color: '#888' }}>Cursor Settings → Features → MCP</strong></span>
                            </li>
                            <li style={{ fontSize: '11px', color: '#444', display: 'flex', gap: '8px' }}>
                                <span style={{ color: '#2a2a2a' }}>2.</span>
                                <span>
                                    Add MCP Server · Type: <code style={{ fontFamily: 'monospace', color: '#555' }}>SSE</code> ·
                                    URL: <code style={{ fontFamily: 'monospace', color: '#555' }}>http://127.0.0.1:7860/mcp/sse</code>
                                </span>
                            </li>
                        </ol>
                    </IntegrationCard>
                </div>
            </section>

            {/* ── Memory Decay ── */}
            <section>
                <span style={sectionLabel}>Memory Decay</span>
                <p style={{ fontSize: '12px', color: '#444', margin: '0 0 16px', lineHeight: 1.6 }}>
                    Rate at which memories lose importance over time without retrieval.
                </p>
                <div style={card}>
                    {[
                        { label: 'Semantic', value: config?.decay_rates?.semantic ?? '0.001' },
                        { label: 'Episodic', value: config?.decay_rates?.episodic ?? '0.05' },
                        { label: 'Working', value: config?.decay_rates?.working ?? '0.3' },
                    ].map(({ label: l, value }, i, arr) => (
                        <div
                            key={l}
                            style={{
                                display: 'flex',
                                justifyContent: 'space-between',
                                alignItems: 'center',
                                padding: '10px 0',
                                borderBottom: i < arr.length - 1 ? '1px solid #1a1a1a' : 'none',
                            }}
                        >
                            <span style={{ fontSize: '12px', color: '#888' }}>{l}</span>
                            <span style={{ fontFamily: 'monospace', fontSize: '11px', color: '#444' }}>{value}</span>
                        </div>
                    ))}
                </div>
            </section>
        </div>
    )
}

function IntegrationCard({ title, children }: { title: string; children: React.ReactNode }) {
    return (
        <div
            style={{
                background: '#080808',
                border: '1px solid #1a1a1a',
                borderRadius: '4px',
                padding: '20px',
                transition: 'border-color 150ms ease',
            }}
            onMouseEnter={e => (e.currentTarget.style.borderColor = '#2a2a2a')}
            onMouseLeave={e => (e.currentTarget.style.borderColor = '#1a1a1a')}
        >
            <p style={{
                fontSize: '11px', fontWeight: 800, letterSpacing: '0.15em',
                textTransform: 'uppercase', color: '#f5f3ee', margin: '0 0 12px',
            }}>
                {title}
            </p>
            {children}
        </div>
    )
}
