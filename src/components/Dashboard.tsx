import { useDashboardStats, useConflicts } from '../lib/queries'
import { useAppStore } from '../lib/store'
import { ArrowRight } from 'lucide-react'

const sectionLabel: React.CSSProperties = {
    fontSize: '9px',
    fontWeight: 600,
    letterSpacing: '0.18em',
    textTransform: 'uppercase' as const,
    color: '#333',
    marginBottom: '16px',
}

function StatCard({ title, value }: { title: string; value: string | number }) {
    return (
        <div style={{
            background: '#080808',
            border: '1px solid #1a1a1a',
            borderRadius: '4px',
            padding: '20px 20px 16px',
            display: 'flex',
            flexDirection: 'column',
            gap: '12px',
            transition: 'border-color 150ms ease',
        }}
            onMouseEnter={e => (e.currentTarget.style.borderColor = '#2a2a2a')}
            onMouseLeave={e => (e.currentTarget.style.borderColor = '#1a1a1a')}
        >
            <p style={{ ...sectionLabel, marginBottom: 0 }}>{title}</p>
            <div style={{
                fontSize: '40px',
                fontFamily: "'Syne', sans-serif",
                fontWeight: 800,
                lineHeight: 1,
                color: '#f5f3ee',
                letterSpacing: '-0.03em',
            }}>
                {value}
            </div>
        </div>
    )
}

export function Dashboard() {
    const { data: stats } = useDashboardStats()
    const { data: conflicts } = useConflicts()
    const { setCurrentView } = useAppStore()

    return (
        <div style={{ padding: '36px 40px', maxWidth: '900px' }}>

            {/* Stat grid */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '2px', marginBottom: '32px' }}>
                <StatCard title="Total Memories" value={stats?.total_memories ?? '—'} />
                <StatCard title="Active Context" value={stats?.active ?? '—'} />
                <StatCard title="Conflicts" value={conflicts?.length ?? '—'} />
            </div>

            {/* Conflicts banner */}
            {conflicts?.length > 0 && (
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '16px 20px',
                    borderLeft: '3px solid #ef4444',
                    background: '#080808',
                    border: '1px solid #1e1e1e',
                    borderLeftColor: '#ef4444',
                    borderRadius: '4px',
                    marginBottom: '32px',
                }}>
                    <div>
                        <p style={{ fontSize: '13px', fontWeight: 500, color: '#f5f3ee', margin: '0 0 4px' }}>
                            {conflicts.length} unresolved conflict{conflicts.length !== 1 ? 's' : ''}
                        </p>
                        <p style={{ fontSize: '11px', color: '#444', margin: 0 }}>
                            Review information that contradicts existing memories.
                        </p>
                    </div>
                    <button
                        onClick={() => setCurrentView('conflicts')}
                        style={{
                            display: 'flex', alignItems: 'center', gap: '6px',
                            background: '#f5f3ee', color: '#0a0a0a',
                            border: 'none', borderRadius: '4px',
                            padding: '8px 14px', cursor: 'pointer',
                            fontSize: '11px', fontWeight: 600,
                            letterSpacing: '0.08em', textTransform: 'uppercase',
                            fontFamily: 'inherit',
                        }}
                    >
                        Review <ArrowRight size={12} />
                    </button>
                </div>
            )}

            {/* Info grid */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2px' }}>
                <div style={{ background: '#080808', border: '1px solid #1a1a1a', borderRadius: '4px', padding: '20px' }}>
                    <p style={sectionLabel}>Recent Activity</p>
                    <p style={{ fontSize: '12px', color: '#2a2a2a', fontStyle: 'italic', margin: 0 }}>No recent activity recorded.</p>
                </div>
                <div style={{ background: '#080808', border: '1px solid #1a1a1a', borderRadius: '4px', padding: '20px' }}>
                    <p style={sectionLabel}>System Health</p>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <div style={{ width: '6px', height: '6px', background: '#10b981', borderRadius: '50%', boxShadow: '0 0 8px rgba(16,185,129,0.5)' }} />
                        <span style={{ fontSize: '12px', color: '#888' }}>Operational</span>
                    </div>
                </div>
            </div>
        </div>
    )
}
