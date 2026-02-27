import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useMemoryHealth } from '../lib/queries'
import { api } from '../lib/api'
import { Loader2 } from 'lucide-react'

type HealthGrade = 'A' | 'B' | 'C' | 'D' | 'F'

const GRADE_COLOR: Record<HealthGrade, string> = {
    A: '#10b981',
    B: '#34d399',
    C: '#f59e0b',
    D: '#f97316',
    F: '#ef4444',
}

const GRADE_BG: Record<HealthGrade, string> = {
    A: '#0a1f16',
    B: '#0d2118',
    C: '#1c1505',
    D: '#1c0e05',
    F: '#1c0505',
}

function ScoreBar({ value, label }: { value: number; label: string }) {
    const pct = Math.round(value * 100)
    return (
        <div style={{ marginBottom: '10px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                <span style={{ fontSize: '9px', letterSpacing: '0.12em', textTransform: 'uppercase', color: '#555' }}>
                    {label}
                </span>
                <span style={{ fontSize: '11px', fontWeight: 700, color: '#c0c0c0', letterSpacing: '-0.01em' }}>
                    {pct}%
                </span>
            </div>
            <div style={{
                height: '2px', background: '#1a1a1a', borderRadius: '999px', overflow: 'hidden',
            }}>
                <div style={{
                    height: '100%', width: `${pct}%`,
                    background: pct >= 70 ? '#10b981' : pct >= 40 ? '#f59e0b' : '#ef4444',
                    borderRadius: '999px',
                    transition: 'width 400ms ease',
                }} />
            </div>
        </div>
    )
}

function TimelineEntry({ label, value }: { label: string; value: string | null | undefined }) {
    if (!value) return null
    const d = new Date(value)
    const isValid = !isNaN(d.getTime())
    return (
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', marginBottom: '6px' }}>
            <span style={{ fontSize: '9px', letterSpacing: '0.1em', textTransform: 'uppercase', color: '#444', flexShrink: 0 }}>
                {label}
            </span>
            <span style={{ fontSize: '10px', color: '#666', textAlign: 'right' }}>
                {isValid ? d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : value}
            </span>
        </div>
    )
}

export function MemoryHealthPanel({ memoryId }: { memoryId: string }) {
    const qc = useQueryClient()
    const { data: health, isLoading } = useMemoryHealth(memoryId)
    const boostMutation = useMutation({
        mutationFn: (scores: { importance_score?: number; confidence_score?: number }) =>
            api.memories.updateScores(memoryId, scores),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['memory_health', memoryId] })
            qc.invalidateQueries({ queryKey: ['memory', memoryId] })
        },
    })

    if (isLoading) {
        return (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}>
                <Loader2 size={14} style={{ animation: 'spin 1s linear infinite', color: '#333' }} />
            </div>
        )
    }

    if (!health) return null

    const grade = (health.grade || 'C') as HealthGrade
    const gradeColor = GRADE_COLOR[grade] ?? '#888'
    const gradeBg = GRADE_BG[grade] ?? '#111'

    const handleBoost = async () => {
        const newScore = Math.min(1.0, (health.importance_score ?? 0.5) + 0.2)
        await boostMutation.mutateAsync({ importance_score: newScore })
    }

    return (
        <div style={{ marginTop: '12px' }}>
            {/* Grade header */}
            <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                background: gradeBg,
                border: `1px solid ${gradeColor}22`,
                borderRadius: '4px',
                padding: '12px 14px',
                marginBottom: '8px',
            }}>
                <div>
                    <span style={{
                        fontSize: '9px', fontWeight: 800, letterSpacing: '0.25em',
                        textTransform: 'uppercase', color: '#444', display: 'block', marginBottom: '4px',
                    }}>
                        Health
                    </span>
                    <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
                        <span style={{ fontSize: '32px', fontWeight: 800, color: gradeColor, letterSpacing: '-0.03em', lineHeight: 1 }}>
                            {grade}
                        </span>
                        {health.needs_review && (
                            <span style={{
                                fontSize: '9px', fontWeight: 700, letterSpacing: '0.12em',
                                textTransform: 'uppercase', color: '#f97316',
                                border: '1px solid #3a1a05', borderRadius: '2px', padding: '2px 6px',
                            }}>
                                Review needed
                            </span>
                        )}
                        {health.days_until_expiry !== null && health.days_until_expiry !== undefined && (
                            <span style={{
                                fontSize: '9px', letterSpacing: '0.08em', textTransform: 'uppercase',
                                color: health.days_until_expiry < 7 ? '#ef4444' : '#555',
                            }}>
                                {health.days_until_expiry === 0 ? 'Expired' : `Expires in ${health.days_until_expiry}d`}
                            </span>
                        )}
                    </div>
                </div>
                <button
                    onClick={handleBoost}
                    disabled={boostMutation.isPending || (health.importance_score ?? 0) >= 1.0}
                    title="Boost importance score by 0.2"
                    style={{
                        fontSize: '9px', fontWeight: 700, letterSpacing: '0.12em',
                        textTransform: 'uppercase',
                        padding: '6px 12px',
                        background: 'transparent',
                        border: '1px solid #2a2a2a',
                        borderRadius: '4px',
                        color: '#666',
                        cursor: boostMutation.isPending ? 'wait' : 'pointer',
                        fontFamily: 'inherit',
                        transition: 'all 150ms ease',
                    }}
                    onMouseEnter={e => { (e.currentTarget.style.color = '#f5f3ee'); (e.currentTarget.style.borderColor = '#444') }}
                    onMouseLeave={e => { (e.currentTarget.style.color = '#666'); (e.currentTarget.style.borderColor = '#2a2a2a') }}
                >
                    {boostMutation.isPending ? <Loader2 size={10} style={{ animation: 'spin 1s linear infinite' }} /> : '↑ Boost'}
                </button>
            </div>

            {/* Score bars */}
            <div style={{ background: '#080808', border: '1px solid #1a1a1a', borderRadius: '4px', padding: '14px 14px 10px' }}>
                <ScoreBar value={health.importance_score ?? 0.5} label="Importance" />
                <ScoreBar value={health.confidence_score ?? 0.5} label="Confidence" />

                {/* Decay profile */}
                {health.decay_profile && health.decay_profile !== 'stable' && (
                    <div style={{ marginTop: '8px', paddingTop: '8px', borderTop: '1px solid #161616' }}>
                        <span style={{ fontSize: '9px', letterSpacing: '0.1em', textTransform: 'uppercase', color: '#444' }}>
                            Decay
                        </span>
                        <span style={{ fontSize: '11px', color: '#f59e0b', marginLeft: '8px', fontWeight: 600 }}>
                            {health.decay_profile}
                        </span>
                    </div>
                )}
            </div>

            {/* Timeline */}
            <div style={{ background: '#080808', border: '1px solid #1a1a1a', borderRadius: '4px', padding: '12px 14px', marginTop: '4px' }}>
                <span style={{
                    fontSize: '9px', fontWeight: 800, letterSpacing: '0.25em',
                    textTransform: 'uppercase', color: '#333', display: 'block', marginBottom: '8px',
                }}>
                    Timeline
                </span>
                <TimelineEntry label="Created" value={health.created_at} />
                <TimelineEntry label="Updated" value={health.updated_at} />
                {health.event_date && <TimelineEntry label="Event" value={health.event_date} />}
                {health.expires_at && <TimelineEntry label="Expires" value={health.expires_at} />}
                {health.review_due_at && <TimelineEntry label="Review due" value={health.review_due_at} />}
            </div>
        </div>
    )
}
