import React, { useState, useMemo, useEffect } from 'react'
import { Loader2, Check, X } from 'lucide-react'
import { useMemories, useSetMemoryStatus, useSetMemoryStatusBulk } from '../lib/queries'
import { useAppStore } from '../lib/store'
import { MnesisLoader } from './ui/Loader'

function relativeTime(dateStr: string | null | undefined): string {
    if (!dateStr) return ''
    const d = new Date(dateStr)
    if (isNaN(d.getTime())) return ''
    const diff = Date.now() - d.getTime()
    const mins = Math.floor(diff / 60000)
    if (mins < 1) return 'just now'
    if (mins < 60) return `${mins}m ago`
    const hrs = Math.floor(mins / 60)
    if (hrs < 24) return `${hrs}h ago`
    const days = Math.floor(hrs / 24)
    if (days < 7) return `${days}d ago`
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function MemoryList({ searchQuery, mode }: { searchQuery: string; mode: 'all' | 'inbox' }) {
    const { data: memories, isLoading } = useMemories({
        query: mode === 'all' ? searchQuery : undefined,
        status: mode === 'inbox' ? 'pending_review' : undefined,
        limit: mode === 'inbox' ? 360 : 120,
    })
    const setMemoryStatus = useSetMemoryStatus()
    const setMemoryStatusBulk = useSetMemoryStatusBulk()
    const { setSelectedMemory, selectedMemoryId } = useAppStore()
    const [actioning, setActioning] = useState<{ id: string; action: 'approve' | 'reject' } | null>(null)
    const [selectedPendingIds, setSelectedPendingIds] = useState<string[]>([])
    const [smartQueueEnabled, setSmartQueueEnabled] = useState(true)
    const [inboxLimit] = useState(30)
    const [reviewMode, setReviewMode] = useState(false)
    const [reviewCursor, setReviewCursor] = useState(0)

    const allRows = useMemo(() => (Array.isArray(memories) ? memories : []), [memories])

    const inboxPrepared = useMemo(() => {
        const source = Array.isArray(memories) ? memories.filter((m: any) => m?.status === 'pending_review') : []
        const q = searchQuery.trim().toLowerCase()
        const filtered = source.filter((mem: any) => {
            if (!q) return true
            const content = String(mem?.content || '').toLowerCase()
            const category = String(mem?.category || '').toLowerCase()
            const level = String(mem?.level || '').toLowerCase()
            const reason = String(mem?.suggestion_reason || '').toLowerCase()
            return content.includes(q) || category.includes(q) || level.includes(q) || reason.includes(q)
        })

        const toTimestamp = (raw: any) => {
            const ts = Date.parse(String(raw || ''))
            return Number.isFinite(ts) ? ts : 0
        }

        const score = (mem: any) => {
            const confidence = Number(mem?.confidence_score || 0)
            const importance = Number(mem?.importance_score || 0.5)
            const createdAt = toTimestamp(mem?.created_at)
            const ageHours = Math.max(0, (Date.now() - createdAt) / 3_600_000)
            const recency = Math.exp(-ageHours / 120)
            const category = String(mem?.category || '').toLowerCase()
            const level = String(mem?.level || '').toLowerCase()
            const levelBonus = level === 'semantic' ? 0.08 : level === 'episodic' ? 0.05 : 0.02
            const categoryBonus = (category === 'identity' || category === 'preferences' || category === 'skills')
                ? 0.06
                : category === 'projects'
                    ? 0.04
                    : 0.02
            return (confidence * 0.55) + (importance * 0.25) + (recency * 0.2) + levelBonus + categoryBonus
        }

        const sorted = [...filtered].sort((a: any, b: any) => {
            const diff = score(b) - score(a)
            if (Math.abs(diff) > 0.0001) return diff
            return toTimestamp(b?.created_at) - toTimestamp(a?.created_at)
        })

        const toConversationKey = (mem: any) => {
            const raw = String(mem?.source_conversation_id || '').trim()
            return raw || `single:${String(mem?.id || '')}`
        }

        let rows: any[] = []
        if (!smartQueueEnabled) {
            rows = sorted.slice(0, inboxLimit)
        } else {
            const buckets = new Map<string, any[]>()
            for (const mem of sorted) {
                const key = toConversationKey(mem)
                if (!buckets.has(key)) buckets.set(key, [])
                buckets.get(key)!.push(mem)
            }

            const queue: any[] = []
            while (queue.length < inboxLimit) {
                let progressed = false
                for (const bucket of buckets.values()) {
                    if (!bucket.length) continue
                    const picked = bucket.shift()
                    if (!picked) continue
                    queue.push(picked)
                    progressed = true
                    if (queue.length >= inboxLimit) break
                }
                if (!progressed) break
            }
            rows = queue
        }

        const conversationSpread = new Set(
            filtered.map((mem: any) => String(mem?.source_conversation_id || '').trim()).filter(Boolean)
        ).size

        return {
            rows,
            filteredCount: filtered.length,
            hiddenCount: Math.max(0, filtered.length - rows.length),
            conversationSpread,
        }
    }, [memories, searchQuery, smartQueueEnabled, inboxLimit])

    const rows = mode === 'inbox' ? inboxPrepared.rows : allRows

    const currentReviewMemory = useMemo(() => {
        if (mode !== 'inbox' || !reviewMode || rows.length === 0) return null
        const safeIndex = Math.min(Math.max(0, reviewCursor), rows.length - 1)
        return rows[safeIndex]
    }, [mode, reviewMode, rows, reviewCursor])

    const displayRows = mode === 'inbox' && reviewMode
        ? (currentReviewMemory ? [currentReviewMemory] : [])
        : rows

    const visiblePendingIds = useMemo(
        () => displayRows.filter((mem: any) => mem?.status === 'pending_review').map((mem: any) => String(mem.id)),
        [displayRows]
    )

    const selectedVisibleIds = useMemo(() => {
        const visible = new Set(visiblePendingIds)
        return selectedPendingIds.filter((id) => visible.has(id))
    }, [selectedPendingIds, visiblePendingIds])

    const allVisibleSelected = visiblePendingIds.length > 0 && selectedVisibleIds.length === visiblePendingIds.length
    const bulkBusy = setMemoryStatusBulk.isPending

    useEffect(() => {
        const allowed = new Set(rows.map((mem: any) => String(mem.id)))
        setSelectedPendingIds((prev) => {
            const next = prev.filter((id) => allowed.has(id))
            return next.length === prev.length ? prev : next
        })
    }, [rows])

    useEffect(() => {
        if (mode !== 'inbox') return
        setReviewCursor((prev) => {
            if (rows.length === 0) return 0
            return Math.min(prev, rows.length - 1)
        })
    }, [mode, rows.length])

    useEffect(() => {
        if (mode !== 'inbox' || !reviewMode) return
        if (!currentReviewMemory) {
            if (selectedMemoryId) setSelectedMemory(null)
            return
        }
        if (selectedMemoryId !== currentReviewMemory.id) {
            setSelectedMemory(currentReviewMemory.id)
        }
    }, [mode, reviewMode, currentReviewMemory, selectedMemoryId, setSelectedMemory])

    const togglePendingSelection = (memoryId: string, checked: boolean) => {
        setSelectedPendingIds((prev) => {
            const set = new Set(prev)
            if (checked) set.add(memoryId)
            else set.delete(memoryId)
            return Array.from(set)
        })
    }

    const toggleSelectAllVisible = (checked: boolean) => {
        setSelectedPendingIds((prev) => {
            const set = new Set(prev)
            if (checked) {
                for (const id of visiblePendingIds) set.add(id)
            } else {
                for (const id of visiblePendingIds) set.delete(id)
            }
            return Array.from(set)
        })
    }

    const moveReview = (delta: number) => {
        setReviewCursor((prev) => {
            if (rows.length === 0) return 0
            const next = prev + delta
            if (next < 0) return 0
            if (next >= rows.length) return rows.length - 1
            return next
        })
    }

    const applyStatus = async (
        memoryId: string,
        status: 'active' | 'rejected',
        action: 'approve' | 'reject',
        options?: { advanceReview?: boolean }
    ) => {
        try {
            setActioning({ id: memoryId, action })
            await setMemoryStatus.mutateAsync({
                id: memoryId,
                status,
                source_llm: 'review',
                review_note: status === 'active' ? 'Approved from inbox (single)' : 'Rejected from inbox (single)',
            })
            if (mode === 'inbox' && (selectedMemoryId === memoryId || reviewMode)) {
                setSelectedMemory(null)
            }
            setSelectedPendingIds((prev) => prev.filter((id) => id !== memoryId))
            if (options?.advanceReview && mode === 'inbox') {
                moveReview(1)
            }
        } finally {
            setActioning(null)
        }
    }

    const applyBulkStatus = async (status: 'active' | 'rejected') => {
        const ids = selectedVisibleIds
        if (ids.length === 0) return
        await setMemoryStatusBulk.mutateAsync({
            ids,
            status,
            source_llm: 'review',
            review_note: status === 'active' ? 'Approved from inbox (bulk)' : 'Rejected from inbox (bulk)',
        })
        if (selectedMemoryId && ids.includes(selectedMemoryId)) {
            setSelectedMemory(null)
        }
        setSelectedPendingIds((prev) => prev.filter((id) => !ids.includes(id)))
    }

    useEffect(() => {
        if (mode !== 'inbox' || !reviewMode) return

        const onKeyDown = (event: KeyboardEvent) => {
            const target = event.target as HTMLElement | null
            const tagName = target?.tagName?.toLowerCase()
            if (tagName === 'input' || tagName === 'textarea' || target?.isContentEditable) return

            const key = event.key.toLowerCase()
            if ((key === 'j' || key === 'arrowdown') && rows.length > 1) {
                event.preventDefault()
                moveReview(1)
                return
            }
            if ((key === 'k' || key === 'arrowup') && rows.length > 1) {
                event.preventDefault()
                moveReview(-1)
                return
            }
            if (!currentReviewMemory || actioning || setMemoryStatus.isPending) return
            if (key === 'a') {
                event.preventDefault()
                void applyStatus(String(currentReviewMemory.id), 'active', 'approve', { advanceReview: true })
            } else if (key === 'r') {
                event.preventDefault()
                void applyStatus(String(currentReviewMemory.id), 'rejected', 'reject', { advanceReview: true })
            }
        }

        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
    }, [mode, reviewMode, rows.length, currentReviewMemory, actioning, setMemoryStatus.isPending])

    if (isLoading) return (
        <div className="flex justify-center p-8">
            <MnesisLoader size="sm" />
        </div>
    )

    const queueSummary = `${rows.length}/${inboxPrepared.filteredCount}`
        + (inboxPrepared.hiddenCount > 0 ? ` • ${inboxPrepared.hiddenCount} hidden` : '')
        + (smartQueueEnabled && inboxPrepared.conversationSpread > 0 ? ` • ${inboxPrepared.conversationSpread} conv` : '')

    // ── shared micro-button base ──────────────────────────────────
    const ctrlBtn: React.CSSProperties = {
        display: 'inline-flex', alignItems: 'center', gap: '4px',
        height: '24px', padding: '0 8px',
        border: '1px solid #1f1f1f', borderRadius: '3px',
        background: 'transparent', cursor: 'pointer',
        fontSize: '9px', fontWeight: 700, letterSpacing: '0.1em',
        textTransform: 'uppercase', color: '#555',
        whiteSpace: 'nowrap', fontFamily: 'inherit',
        transition: 'color 120ms ease, border-color 120ms ease',
    }

    const actionBtn: React.CSSProperties = {
        display: 'inline-flex', alignItems: 'center', gap: '4px',
        height: '22px', padding: '0 8px', borderRadius: '3px',
        fontSize: '9px', fontWeight: 700, letterSpacing: '0.1em',
        textTransform: 'uppercase', cursor: 'pointer',
        whiteSpace: 'nowrap', fontFamily: 'inherit',
    }

    return (
        <div style={{ flex: 1, overflowY: 'auto', padding: '0' }}>
            {mode === 'inbox' && (
                <div style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    gap: '6px', padding: '8px 12px',
                    background: '#070707', position: 'sticky', top: 0, zIndex: 3,
                    borderBottom: '1px solid #151515',
                }}>
                    {/* Left controls */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                        {reviewMode ? (
                            <>
                                <button onClick={() => moveReview(-1)}
                                    disabled={reviewCursor <= 0}
                                    style={{ ...ctrlBtn, opacity: reviewCursor <= 0 ? 0.35 : 1 }}>
                                    ← Prev
                                </button>
                                <span style={{ fontSize: '9px', color: '#404040', letterSpacing: '0.06em' }}>
                                    {Math.min(reviewCursor + 1, rows.length)}/{rows.length}
                                </span>
                                <button onClick={() => moveReview(1)}
                                    disabled={reviewCursor >= rows.length - 1}
                                    style={{ ...ctrlBtn, opacity: reviewCursor >= rows.length - 1 ? 0.35 : 1 }}>
                                    Next →
                                </button>
                            </>
                        ) : (
                            <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}
                                onClick={e => e.stopPropagation()}>
                                <input type="checkbox" checked={allVisibleSelected}
                                    onChange={e => toggleSelectAllVisible(e.target.checked)}
                                    style={{ accentColor: '#f5f3ee', width: '12px', height: '12px' }} />
                                <span style={{ fontSize: '9px', color: '#404040', letterSpacing: '0.06em', userSelect: 'none' }}>
                                    {selectedVisibleIds.length}/{visiblePendingIds.length}
                                </span>
                            </label>
                        )}

                        <button onClick={() => { setReviewMode(p => !p); setReviewCursor(0); setSelectedPendingIds([]) }}
                            style={{ ...ctrlBtn, borderColor: reviewMode ? '#1a3328' : '#1f1f1f', color: reviewMode ? '#4ade80' : '#555' }}>
                            Review {reviewMode ? 'on' : 'off'}
                        </button>
                        <button onClick={() => setSmartQueueEnabled(p => !p)}
                            style={{ ...ctrlBtn, borderColor: smartQueueEnabled ? '#1a3328' : '#1f1f1f', color: smartQueueEnabled ? '#4ade80' : '#555' }}>
                            {smartQueueEnabled ? 'Smart' : 'Chrono'}
                        </button>
                    </div>

                    {/* Right: bulk actions + summary */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                        {!reviewMode && (
                            <>
                                <button disabled={selectedVisibleIds.length === 0 || bulkBusy}
                                    onClick={() => void applyBulkStatus('active')}
                                    style={{
                                        ...actionBtn, border: '1px solid #1a3328', background: '#08110e',
                                        color: selectedVisibleIds.length === 0 ? '#2a4a3a' : '#4ade80',
                                        cursor: selectedVisibleIds.length === 0 || bulkBusy ? 'not-allowed' : 'pointer',
                                    }}>
                                    {bulkBusy ? <Loader2 size={9} style={{ animation: 'spin 1s linear infinite' }} /> : <Check size={9} />}
                                    Approve
                                </button>
                                <button disabled={selectedVisibleIds.length === 0 || bulkBusy}
                                    onClick={() => void applyBulkStatus('rejected')}
                                    style={{
                                        ...actionBtn, border: '1px solid #3a1515', background: '#110808',
                                        color: selectedVisibleIds.length === 0 ? '#4a2525' : '#f87171',
                                        cursor: selectedVisibleIds.length === 0 || bulkBusy ? 'not-allowed' : 'pointer',
                                    }}>
                                    {bulkBusy ? <Loader2 size={9} style={{ animation: 'spin 1s linear infinite' }} /> : <X size={9} />}
                                    Reject
                                </button>
                            </>
                        )}
                        <span style={{ fontSize: '9px', color: '#333', letterSpacing: '0.04em' }}>
                            {queueSummary}
                        </span>
                    </div>
                </div>
            )}

            {displayRows?.map((mem: any) => {
                const isPending = mem.status === 'pending_review'
                const isActioning = actioning?.id === mem.id
                const isChecked = selectedVisibleIds.includes(String(mem.id))
                const isReviewCard = reviewMode && mode === 'inbox'
                const confidencePct = Math.round(Number(mem.confidence_score || 0) * 100)
                const timeLabel = relativeTime(mem?.created_at)
                const isSelected = selectedMemoryId === mem.id

                return (
                    <div
                        key={mem.id}
                        onClick={() => setSelectedMemory(mem.id)}
                        style={{
                            position: 'relative',
                            padding: '11px 12px',
                            borderBottom: '1px solid #121212',
                            background: isSelected ? '#0d0d0d' : 'transparent',
                            borderLeft: isSelected ? '2px solid #333' : '2px solid transparent',
                            cursor: 'pointer',
                            transition: 'background 130ms ease, border-color 130ms ease',
                        }}
                        onMouseEnter={e => { if (!isSelected) (e.currentTarget as HTMLElement).style.background = '#0a0a0a' }}
                        onMouseLeave={e => { if (!isSelected) (e.currentTarget as HTMLElement).style.background = 'transparent' }}
                    >
                        {/* Top meta row */}
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '7px', minWidth: 0 }}>
                                {/* Checkbox (inbox, no-review only) */}
                                {mode === 'inbox' && isPending && !reviewMode && (
                                    <label onClick={e => e.stopPropagation()} style={{ display: 'flex', alignItems: 'center', flexShrink: 0 }}>
                                        <input type="checkbox" checked={isChecked}
                                            onChange={e => togglePendingSelection(String(mem.id), e.target.checked)}
                                            onClick={e => e.stopPropagation()}
                                            style={{ accentColor: '#f5f3ee', width: '11px', height: '11px', cursor: 'pointer' }} />
                                    </label>
                                )}
                                {/* Category */}
                                <span style={{
                                    fontSize: '9px', fontWeight: 700, letterSpacing: '0.12em',
                                    textTransform: 'uppercase', color: '#404040',
                                }}>
                                    {mem.category}
                                </span>
                                {/* Review card position */}
                                {isReviewCard && (
                                    <span style={{ fontSize: '9px', color: '#353535' }}>
                                        {Math.min(reviewCursor + 1, rows.length)}/{rows.length}
                                    </span>
                                )}
                            </div>

                            {/* Right meta */}
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
                                {confidencePct > 0 && (
                                    <span style={{ fontSize: '9px', color: '#333', letterSpacing: '0.04em' }}>
                                        {confidencePct}%
                                    </span>
                                )}
                                <span style={{ fontSize: '9px', color: '#2e2e2e', letterSpacing: '0.02em' }}>
                                    {timeLabel}
                                </span>
                            </div>
                        </div>

                        {/* Content */}
                        <p style={{
                            fontSize: '13px', color: '#c8c8c8', lineHeight: 1.52,
                            margin: 0, marginBottom: mode === 'inbox' && isPending ? '9px' : 0,
                            display: '-webkit-box', WebkitLineClamp: 2,
                            WebkitBoxOrient: 'vertical', overflow: 'hidden',
                        }}>
                            {mem.content}
                        </p>

                        {/* Suggestion reason (selected only) */}
                        {mode === 'inbox' && isPending && mem.suggestion_reason && isSelected && (
                            <p style={{
                                margin: '4px 0 8px', fontSize: '10px', color: '#383838',
                                display: '-webkit-box', WebkitLineClamp: 1,
                                WebkitBoxOrient: 'vertical', overflow: 'hidden',
                            }}>
                                {mem.suggestion_reason}
                            </p>
                        )}

                        {/* Approve / Reject row */}
                        {mode === 'inbox' && isPending && (
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                <button
                                    onClick={e => { e.stopPropagation(); if (!isActioning) void applyStatus(String(mem.id), 'active', 'approve', { advanceReview: reviewMode }) }}
                                    disabled={isActioning}
                                    style={{
                                        ...actionBtn, border: '1px solid #1a3328', background: '#08110e',
                                        color: '#4ade80', cursor: isActioning ? 'wait' : 'pointer',
                                        opacity: isActioning ? 0.6 : 1,
                                    }}>
                                    {isActioning && actioning?.action === 'approve'
                                        ? <Loader2 size={9} style={{ animation: 'spin 1s linear infinite' }} />
                                        : <Check size={9} />}
                                    Approve
                                </button>
                                <button
                                    onClick={e => { e.stopPropagation(); if (!isActioning) void applyStatus(String(mem.id), 'rejected', 'reject', { advanceReview: reviewMode }) }}
                                    disabled={isActioning}
                                    style={{
                                        ...actionBtn, border: '1px solid #3a1515', background: '#110808',
                                        color: '#f87171', cursor: isActioning ? 'wait' : 'pointer',
                                        opacity: isActioning ? 0.6 : 1,
                                    }}>
                                    {isActioning && actioning?.action === 'reject'
                                        ? <Loader2 size={9} style={{ animation: 'spin 1s linear infinite' }} />
                                        : <X size={9} />}
                                    Reject
                                </button>
                            </div>
                        )}
                    </div>
                )
            })}

            {(!displayRows || displayRows.length === 0) && (
                <div style={{ textAlign: 'center', color: '#2a2a2a', fontSize: '10px', padding: '48px 20px', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase' }}>
                    {searchQuery ? 'No results' : mode === 'inbox' ? 'Inbox clear ✓' : 'No memories'}
                </div>
            )}
        </div>
    )
}
