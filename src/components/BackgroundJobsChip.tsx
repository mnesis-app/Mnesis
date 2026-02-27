import { AlertTriangle, CheckCircle2, Clock3, Loader2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useBackgroundStatus } from '../lib/queries'

type ChipState = 'running' | 'queued' | 'failed' | 'idle'

function toNumber(value: unknown, fallback = 0): number {
    const n = Number(value)
    return Number.isFinite(n) ? n : fallback
}

function clamp(value: number, min: number, max: number): number {
    return Math.max(min, Math.min(max, value))
}

function toLocalTime(value: unknown): string {
    const raw = String(value || '').trim()
    if (!raw) return 'never'
    const dt = new Date(raw)
    if (Number.isNaN(dt.getTime())) return 'never'
    return dt.toLocaleTimeString()
}

function toPercent(value: unknown): string {
    const n = clamp(toNumber(value, 0), 0, 1)
    return `${Math.round(n * 100)}%`
}

function elapsedSince(value: unknown): string {
    const raw = String(value || '').trim()
    if (!raw) return '0s'
    const started = new Date(raw)
    if (Number.isNaN(started.getTime())) return '0s'
    const sec = Math.max(0, Math.floor((Date.now() - started.getTime()) / 1000))
    if (sec < 60) return `${sec}s`
    const min = Math.floor(sec / 60)
    const rem = sec % 60
    if (min < 60) return `${min}m ${rem}s`
    const hours = Math.floor(min / 60)
    return `${hours}h ${min % 60}m`
}

function toDuration(value: unknown): string {
    const ms = toNumber(value, 0)
    if (ms <= 0) return '0s'
    if (ms < 1000) return `${ms}ms`
    return `${(ms / 1000).toFixed(ms >= 10000 ? 0 : 1)}s`
}

function shortenId(value: unknown): string {
    const raw = String(value || '').trim()
    if (!raw) return 'n/a'
    if (raw.length <= 12) return raw
    return `${raw.slice(0, 8)}…${raw.slice(-4)}`
}

function statePalette(state: ChipState) {
    if (state === 'running') {
        return {
            border: '#1f3531',
            background: '#0d1514',
            text: '#8fe3d1',
            track: '#18312d',
            fill: '#2ac6a3',
        }
    }
    if (state === 'queued') {
        return {
            border: '#2f2a1a',
            background: '#141108',
            text: '#e7c97a',
            track: '#2e2715',
            fill: '#d3a33c',
        }
    }
    if (state === 'failed') {
        return {
            border: '#382020',
            background: '#170d0d',
            text: '#ef9a9a',
            track: '#341f1f',
            fill: '#ef4444',
        }
    }
    return {
        border: '#202020',
        background: '#101010',
        text: '#8a8a8a',
        track: '#1e1e1e',
        fill: '#5b5b5b',
    }
}

export function BackgroundJobsChip() {
    const [open, setOpen] = useState(false)
    const rootRef = useRef<HTMLDivElement | null>(null)
    const { data, isLoading } = useBackgroundStatus({
        includeHeavy: false,
        refetchIntervalMs: 2500,
        staleTimeMs: 1200,
    })

    const view = useMemo(() => {
        const counts = (data as any)?.jobs?.counts || {}
        const scheduler = (data as any)?.scheduler || {}
        const worker = (data as any)?.runtime?.analysis_worker || {}
        const analysisRuntime = (data as any)?.runtime?.analysis || {}
        const recentJobs = Array.isArray((data as any)?.jobs?.recent) ? (data as any).jobs.recent : []

        const queuePending = toNumber(counts?.pending, 0)
        const queueRunning = toNumber(counts?.running, 0)
        const queueFailed = toNumber(counts?.failed, 0)
        const running = Boolean(worker?.running) || queueRunning > 0

        const runtimeStepTotal = toNumber(analysisRuntime?.phase_total_steps, 0)
        const runtimeStepIndex = toNumber(analysisRuntime?.phase_step, 0)
        const runtimeStepLabel = String(analysisRuntime?.phase_label || '').trim()
        const runtimeStepDetail = String(analysisRuntime?.phase_detail || '').trim()
        const runtimeStepProgress = clamp(toNumber(analysisRuntime?.phase_progress, 0), 0, 1)
        const runtimeItemsDone = Math.max(0, toNumber(analysisRuntime?.phase_items_done, 0))
        const runtimeItemsTotal = Math.max(0, toNumber(analysisRuntime?.phase_items_total, 0))
        const runtimeItemsUnit = String(analysisRuntime?.phase_items_unit || '').trim().toLowerCase()
        const runtimeItemsSummary =
            runtimeItemsTotal > 0 ? `${runtimeItemsDone}/${runtimeItemsTotal} ${runtimeItemsUnit || 'items'}` : ''
        const workerStepStartedAt = String(worker?.current_step_started_at || '').trim()
        const workerJobStartedAt = String(worker?.current_job_started_at || '').trim()

        const stepTotalRaw = runtimeStepTotal > 0 ? runtimeStepTotal : toNumber(worker?.current_step_total, 0)
        const stepIndexRaw = runtimeStepIndex > 0 ? runtimeStepIndex : toNumber(worker?.current_step_index, 0)
        const stepTotal = stepTotalRaw > 0 ? stepTotalRaw : 5
        let stepIndex = stepIndexRaw
        if (running && stepIndex <= 0) stepIndex = 2
        if (!running && queuePending > 0) stepIndex = 1
        if (!running && queuePending === 0 && queueFailed === 0) stepIndex = stepTotal
        stepIndex = clamp(stepIndex, 0, stepTotal)

        let stepLabel = runtimeStepLabel || String(worker?.current_step_label || '').trim()
        if (!stepLabel && running) stepLabel = 'Analyzing conversation contexts'
        if (!stepLabel && !running && queuePending > 0) stepLabel = 'Queued'
        if (!stepLabel && queueFailed > 0) stepLabel = 'Last run failed'
        if (!stepLabel) stepLabel = 'Idle'

        let stepDetail = runtimeStepDetail
        if (!stepDetail && running && runtimeItemsSummary) stepDetail = runtimeItemsSummary
        if (!stepDetail && running) {
            const elapsedSource = workerStepStartedAt || workerJobStartedAt
            if (elapsedSource) {
                stepDetail = `Running for ${elapsedSince(elapsedSource)}`
            } else {
                stepDetail = 'Processing in background'
            }
        }

        const state: ChipState = running
            ? 'running'
            : queuePending > 0
                ? 'queued'
                : queueFailed > 0
                    ? 'failed'
                    : 'idle'

        const progress = running
            ? runtimeStepProgress > 0
                ? clamp(runtimeStepProgress, 0.06, 0.98)
                : clamp(stepIndex / stepTotal, 0.06, 0.96)
            : queuePending > 0
                ? 0.08
                : queueFailed > 0
                    ? 0
                    : 1

        const compactSummary = running
            ? `${stepIndex}/${stepTotal}`
            : queuePending > 0
                ? `${queuePending}q`
                : queueFailed > 0
                    ? `${queueFailed}e`
                    : 'idle'

        const lastStats = (scheduler?.last_analysis_stats || {}) as any
        const recent = recentJobs[0] || null
        const sampleError = Array.isArray(lastStats?.sample_errors) && lastStats.sample_errors.length
            ? String(lastStats.sample_errors[0] || '')
            : ''

        const title = [
            `Background jobs: ${compactSummary}`,
            `Step: ${stepLabel}`,
            stepDetail ? `Detail: ${stepDetail}` : '',
            `Queue: pending ${queuePending} · running ${queueRunning} · failed ${queueFailed}`,
            `Last analysis: ${toLocalTime(scheduler?.last_analysis)}`,
        ].filter(Boolean).join('\n')

        return {
            state,
            progress,
            compactSummary,
            stepLabel,
            stepDetail,
            stepIndex,
            stepTotal,
            queuePending,
            queueRunning,
            queueFailed,
            workerAlive: Boolean(worker?.task_alive),
            currentJobId: shortenId(worker?.current_job_id),
            currentJobTrigger: String(worker?.current_job_trigger || '').trim() || 'manual',
            lastAnalysisTime: toLocalTime(scheduler?.last_analysis),
            lastAnalysisSource: String(scheduler?.last_analysis_source || '').trim(),
            lastStats,
            recent,
            sampleError,
            title,
            phaseUpdatedAt: toLocalTime(analysisRuntime?.phase_updated_at || workerStepStartedAt || workerJobStartedAt),
        }
    }, [data])

    const palette = statePalette(view.state)

    useEffect(() => {
        const onPointerDown = (event: MouseEvent) => {
            if (!open || !rootRef.current) return
            if (!rootRef.current.contains(event.target as Node)) {
                setOpen(false)
            }
        }
        const onKeyDown = (event: KeyboardEvent) => {
            if (!open) return
            if (event.key === 'Escape') {
                setOpen(false)
            }
        }
        window.addEventListener('mousedown', onPointerDown)
        window.addEventListener('keydown', onKeyDown)
        return () => {
            window.removeEventListener('mousedown', onPointerDown)
            window.removeEventListener('keydown', onKeyDown)
        }
    }, [open])

    return (
        <div ref={rootRef} style={{ position: 'relative' }}>
            <button
                type="button"
                onClick={() => setOpen((prev) => !prev)}
                title={view.title}
                style={{
                    width: '108px',
                    height: '26px',
                    border: `1px solid ${open ? '#2f2f2f' : palette.border}`,
                    borderRadius: '4px',
                    background: palette.background,
                    color: palette.text,
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '6px',
                    padding: '0 8px',
                    fontSize: '9px',
                    letterSpacing: '0.08em',
                    textTransform: 'uppercase',
                    cursor: 'pointer',
                    position: 'relative',
                    overflow: 'hidden',
                    opacity: isLoading ? 0.8 : 1,
                }}
                aria-label={`Background jobs ${view.compactSummary}. ${view.stepLabel}`}
                aria-expanded={open}
                aria-haspopup="dialog"
            >
                {view.state === 'running' ? (
                    <Loader2 size={11} className="animate-spin" style={{ flexShrink: 0 }} />
                ) : view.state === 'queued' ? (
                    <Clock3 size={11} style={{ flexShrink: 0 }} />
                ) : view.state === 'failed' ? (
                    <AlertTriangle size={11} style={{ flexShrink: 0 }} />
                ) : (
                    <CheckCircle2 size={11} style={{ flexShrink: 0 }} />
                )}
                <span style={{ fontWeight: 700 }}>Jobs</span>
                <span style={{ opacity: 0.9, marginLeft: 'auto', fontWeight: 700 }}>{view.compactSummary}</span>
                <span
                    style={{
                        position: 'absolute',
                        left: 0,
                        right: 0,
                        bottom: 0,
                        height: '2px',
                        background: palette.track,
                    }}
                />
                <span
                    style={{
                        position: 'absolute',
                        left: 0,
                        bottom: 0,
                        height: '2px',
                        width: `${Math.round(view.progress * 100)}%`,
                        background: palette.fill,
                        transition: 'width 220ms ease',
                    }}
                />
            </button>

            {open && (
                <div
                    role="dialog"
                    aria-label="Background jobs status"
                    style={{
                        position: 'absolute',
                        top: '32px',
                        right: 0,
                        width: '300px',
                        border: '1px solid #252525',
                        borderRadius: '8px',
                        background: '#0d0d0d',
                        boxShadow: '0 16px 34px rgba(0,0,0,0.55)',
                        zIndex: 90,
                        padding: '10px 11px',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '9px',
                    }}
                >
                    <div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <span style={{ fontSize: '10px', color: '#676767', letterSpacing: '0.08em', textTransform: 'uppercase' }}>Step</span>
                            <span style={{ marginLeft: 'auto', fontSize: '10px', color: '#8a8a8a' }}>
                                {view.stepIndex}/{view.stepTotal}
                            </span>
                        </div>
                        <p style={{ margin: '4px 0 0', fontSize: '12px', color: '#c8c8c8', lineHeight: 1.32 }}>{view.stepLabel}</p>
                        {view.stepDetail ? (
                            <p style={{ margin: '4px 0 0', fontSize: '10px', color: '#8e8e8e', lineHeight: 1.3 }}>
                                {view.stepDetail}
                            </p>
                        ) : null}
                        <div style={{ marginTop: '7px', height: '4px', background: '#1a1a1a', borderRadius: '999px', overflow: 'hidden' }}>
                            <div style={{ height: '100%', width: `${Math.round(view.progress * 100)}%`, background: palette.fill, transition: 'width 220ms ease' }} />
                        </div>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: '6px' }}>
                        <div>
                            <p style={{ margin: 0, fontSize: '9px', color: '#666', textTransform: 'uppercase' }}>P</p>
                            <p style={{ margin: '2px 0 0', fontSize: '12px', color: '#d1d1d1', fontWeight: 700 }}>{view.queuePending}</p>
                        </div>
                        <div>
                            <p style={{ margin: 0, fontSize: '9px', color: '#666', textTransform: 'uppercase' }}>R</p>
                            <p style={{ margin: '2px 0 0', fontSize: '12px', color: '#d1d1d1', fontWeight: 700 }}>{view.queueRunning}</p>
                        </div>
                        <div>
                            <p style={{ margin: 0, fontSize: '9px', color: '#666', textTransform: 'uppercase' }}>F</p>
                            <p style={{ margin: '2px 0 0', fontSize: '12px', color: '#d1d1d1', fontWeight: 700 }}>{view.queueFailed}</p>
                        </div>
                        <div>
                            <p style={{ margin: 0, fontSize: '9px', color: '#666', textTransform: 'uppercase' }}>Worker</p>
                            <p style={{ margin: '2px 0 0', fontSize: '12px', color: view.workerAlive ? '#8fe3d1' : '#ef9a9a', fontWeight: 700 }}>
                                {view.workerAlive ? 'on' : 'off'}
                            </p>
                        </div>
                    </div>

                    <div style={{ borderTop: '1px solid #1c1c1c', paddingTop: '8px' }}>
                        <p style={{ margin: 0, fontSize: '11px', color: '#c5c5c5' }}>
                            Last: {view.lastAnalysisTime}{view.lastAnalysisSource ? ` (${view.lastAnalysisSource})` : ''}
                        </p>
                        <p style={{ margin: '4px 0 0', fontSize: '10px', color: '#888' }}>
                            created {toNumber(view.lastStats?.created, 0)} · candidates {toNumber(view.lastStats?.candidates_total, 0)} · {toDuration(view.lastStats?.duration_ms)}
                        </p>
                        <p style={{ margin: '2px 0 0', fontSize: '10px', color: '#888' }}>
                            accepted {toPercent(view.lastStats?.accepted_rate)} · generic {toPercent(view.lastStats?.generic_rate)}
                        </p>
                    </div>

                    <div style={{ borderTop: '1px solid #1c1c1c', paddingTop: '8px' }}>
                        <p style={{ margin: 0, fontSize: '10px', color: '#7a7a7a', textTransform: 'uppercase' }}>
                            Current
                        </p>
                        <p style={{ margin: '3px 0 0', fontSize: '11px', color: '#b9b9b9' }}>
                            {view.currentJobId} · {view.currentJobTrigger}
                        </p>
                        <p style={{ margin: '2px 0 0', fontSize: '10px', color: '#7f7f7f' }}>
                            Update: {view.phaseUpdatedAt}
                        </p>
                        {view.recent ? (
                            <p style={{ margin: '3px 0 0', fontSize: '10px', color: '#8a8a8a' }}>
                                Recent: {String(view.recent?.status || 'unknown')} · {toDuration(view.recent?.result_summary?.duration_ms)}
                            </p>
                        ) : null}
                        {view.sampleError ? (
                            <p style={{ margin: '4px 0 0', fontSize: '10px', color: '#b48f8f', lineHeight: 1.3 }}>
                                {view.sampleError.length > 120 ? `${view.sampleError.slice(0, 120)}…` : view.sampleError}
                            </p>
                        ) : null}
                    </div>
                </div>
            )}
        </div>
    )
}
