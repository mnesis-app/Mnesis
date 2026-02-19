import { useState, useEffect } from 'react'
import { api } from '../lib/api'
import { Loader2, AlertCircle } from 'lucide-react'
import { MnesisWordmark } from './Logo'

export function FirstSetup({ onReady }: { onReady: () => void }) {
    const [status, setStatus] = useState<any>(null)
    const [retrying, setRetrying] = useState(false)

    useEffect(() => {
        const check = async () => {
            try {
                const res = await api.health()
                setStatus(res)
                if (res.model_ready) onReady()
            } catch {
                setRetrying(true)
            }
        }
        const interval = setInterval(check, 1000)
        check()
        return () => clearInterval(interval)
    }, [onReady])

    const statusText = status?.model_status?.toUpperCase() || (retrying ? 'CONNECTING' : 'CHECKING')

    return (
        <div style={{
            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
            height: '100vh', background: '#0a0a0a', color: '#f5f3ee', padding: '40px',
        }}>
            <div style={{ width: '100%', maxWidth: '400px', textAlign: 'center' }}>
                {/* Wordmark */}
                <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '32px' }}>
                    <MnesisWordmark color="#f5f3ee" iconSize={40} textSize={32} gap={14} />
                </div>

                <p style={{ fontSize: '12px', color: '#444', margin: '0 0 36px', fontWeight: 400 }}>
                    Setting up your local neural memory
                </p>

                {/* Status card */}
                <div style={{
                    background: '#080808', border: '1px solid #1a1a1a',
                    borderRadius: '4px', padding: '20px', marginBottom: '16px',
                }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                        <span style={{ fontSize: '11px', color: '#444' }}>System Status</span>
                        <span style={{
                            fontSize: '9px', fontWeight: 800, letterSpacing: '0.2em',
                            border: '1px solid #2a2a2a', borderRadius: '2px', padding: '2px 7px',
                            color: status?.model_status === 'error' ? '#ef4444' : '#888',
                        }}>
                            {statusText}
                        </span>
                    </div>

                    {status?.model_status === 'downloading' && (
                        <div style={{ marginBottom: '12px' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                                <span style={{ fontSize: '10px', color: '#444' }}>Downloading {status.download_file}...</span>
                                <span style={{ fontSize: '10px', color: '#555', fontFamily: 'monospace' }}>{status.download_percent}%</span>
                            </div>
                            <div style={{ height: '2px', background: '#1a1a1a', borderRadius: '1px', overflow: 'hidden' }}>
                                <div style={{
                                    height: '100%', background: '#f5f3ee',
                                    width: `${status.download_percent}%`,
                                    transition: 'width 300ms ease',
                                }} />
                            </div>
                        </div>
                    )}

                    {status?.model_status === 'loading' && (
                        <div style={{ height: '2px', background: '#1a1a1a', borderRadius: '1px', overflow: 'hidden', marginBottom: '12px' }}>
                            <div style={{
                                height: '100%', background: '#f5f3ee',
                                animation: 'loading-bar 2s ease-in-out infinite',
                                width: '40%',
                            }} />
                        </div>
                    )}

                    {!status && (
                        <div style={{ display: 'flex', justifyContent: 'center' }}>
                            <Loader2 size={16} style={{ animation: 'spin 1s linear infinite', color: '#2a2a2a' }} />
                        </div>
                    )}

                    <p style={{ fontSize: '11px', color: '#2a2a2a', margin: 0, lineHeight: 1.6 }}>
                        Downloading bge-small-en-v1.5 (once). Mnesis runs 100% offline.
                    </p>
                </div>

                {status?.model_status === 'error' && (
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', color: '#ef4444', fontSize: '11px' }}>
                        <AlertCircle size={14} /> Error loading model. Check logs.
                    </div>
                )}
            </div>
        </div>
    )
}
