import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { SyncOnboarding } from './SyncOnboarding'
import { CloudUpload, X } from 'lucide-react'

export function SyncBanner() {
    const [dismissed, setDismissed] = useState(false)
    const [open, setOpen] = useState(false)

    const { data: syncStatus } = useQuery({
        queryKey: ['sync_status_banner'],
        queryFn: api.admin.syncStatus,
        staleTime: 60_000,
        retry: false,
    })

    // Show banner only when sync is explicitly disabled (not loading, not configured)
    const syncEnabled = syncStatus?.enabled === true
    if (syncEnabled || dismissed) return null

    return (
        <>
            <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '8px 16px',
                background: '#0a0a0a',
                borderBottom: '1px solid #191919',
                gap: '10px',
                flexShrink: 0,
            }}>
                <button
                    onClick={() => setOpen(true)}
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px',
                        background: 'none',
                        border: 'none',
                        cursor: 'pointer',
                        padding: 0,
                        fontFamily: 'inherit',
                        color: '#666',
                        transition: 'color 150ms ease',
                    }}
                    onMouseEnter={e => (e.currentTarget.style.color = '#c0c0c0')}
                    onMouseLeave={e => (e.currentTarget.style.color = '#666')}
                >
                    <CloudUpload size={12} />
                    <span style={{ fontSize: '11px', letterSpacing: '0.02em' }}>
                        Back up &amp; sync your memories across devices
                    </span>
                    <span style={{
                        fontSize: '10px', fontWeight: 700, letterSpacing: '0.1em',
                        textTransform: 'uppercase', color: '#444',
                        border: '1px solid #2a2a2a', borderRadius: '2px', padding: '2px 6px',
                        marginLeft: '2px',
                    }}>
                        Set up →
                    </span>
                </button>
                <button
                    onClick={() => setDismissed(true)}
                    title="Dismiss"
                    style={{
                        background: 'none', border: 'none', cursor: 'pointer',
                        color: '#333', padding: '2px', display: 'flex',
                        transition: 'color 150ms ease',
                    }}
                    onMouseEnter={e => (e.currentTarget.style.color = '#888')}
                    onMouseLeave={e => (e.currentTarget.style.color = '#333')}
                >
                    <X size={12} />
                </button>
            </div>

            {open && (
                <SyncOnboarding onClose={() => setOpen(false)} />
            )}
        </>
    )
}
