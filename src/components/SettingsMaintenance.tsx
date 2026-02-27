import { Check, Play, RefreshCw, Shield, Trash2 } from 'lucide-react'
import { useState } from 'react'
import {
    useBackgroundStatus,
    useDeduplicateConversations,
    useDeleteConversationsByIds,
    usePurgeConversations,
    useRunBackgroundAnalysis,
} from '../lib/queries'
import {
    ActionButton,
    CheckboxLabel,
    Field,
    InlineMessage,
    Panel,
    SectionBlock,
    StatCell,
    cx,
    isDangerMessage,
} from './SettingsShared'

type ConversationsMaintenanceReport = {
    status: string
    dry_run?: boolean
    conversations_total?: number
    conversations_kept?: number
    conversations_duplicates?: number
    messages_total?: number
    messages_kept?: number
    messages_duplicates?: number
    conversation_duplicate_ids_preview?: string[]
    message_duplicate_ids_preview?: string[]
    conversations_deleted?: number
    messages_deleted?: number
}

/**
 * Renders Client Readiness + Conversation Maintenance + Background Jobs panels.
 * Only mounted when the user is in Advanced + Diagnostics mode, so
 * useBackgroundStatus always runs with includeHeavy: true here.
 */
export function SettingsMaintenance() {
    const {
        data: backgroundStatus,
        isLoading: backgroundLoading,
        refetch: refetchBackgroundStatus,
    } = useBackgroundStatus({ includeHeavy: true })
    const runBackgroundAnalysis = useRunBackgroundAnalysis()
    const deduplicateConversations = useDeduplicateConversations()
    const deleteConversationsByIds = useDeleteConversationsByIds()
    const purgeConversations = usePurgeConversations()

    const [maintenanceMessage, setMaintenanceMessage] = useState<string | null>(null)
    const [maintenanceReport, setMaintenanceReport] = useState<ConversationsMaintenanceReport | null>(null)
    const [maintenanceIncludeMessages, setMaintenanceIncludeMessages] = useState(true)
    const [maintenanceDeleteIdsInput, setMaintenanceDeleteIdsInput] = useState('')
    const [maintenanceAction, setMaintenanceAction] = useState<'analyze' | 'deduplicate' | 'purge' | null>(null)
    const [backgroundMessage, setBackgroundMessage] = useState<string | null>(null)
    const [forceBackgroundReanalyze, setForceBackgroundReanalyze] = useState(false)
    const [targetConversationIdsInput, setTargetConversationIdsInput] = useState('')

    // ── Derived background status values ──────────────────────────────────
    const scheduler = backgroundStatus?.scheduler || {}
    const analysisStats = scheduler?.last_analysis_stats || scheduler?.last_auto_conversation_analysis_stats || {}
    const lastAnalysisAt = scheduler?.last_analysis || scheduler?.last_auto_conversation_analysis
    const lastAnalysisSource = String(scheduler?.last_analysis_source || 'auto')
    const backgroundCounts = backgroundStatus?.counts || {}
    const memoryCounts = backgroundCounts?.memories || {}
    const conversationCounts = backgroundCounts?.conversations || {}
    const embeddingStatus = backgroundStatus?.model?.embedding_status || 'unknown'
    const schemaInfo = backgroundStatus?.schema || {}
    const missingTemporalFields = Array.isArray(schemaInfo?.memories_missing_temporal_fields)
        ? schemaInfo.memories_missing_temporal_fields
        : []
    const memoryLegacyWriteGuard = String(backgroundStatus?.runtime?.memory_legacy_write_guard || 'unknown')
    const analysisRuntime = backgroundStatus?.runtime?.analysis || {}
    const analysisGate = analysisRuntime?.llm_gate || {}
    const analysisGateBlocked = analysisGate?.analysis_allowed === false
    const analysisGateReason = typeof analysisGate?.reason === 'string' ? analysisGate.reason : ''
    const analysisRunning = !!analysisRuntime?.running
    const analysisWorker = backgroundStatus?.runtime?.analysis_worker || {}
    const jobsInfo = backgroundStatus?.jobs || {}
    const jobCounts = jobsInfo?.counts || {}
    const analysisGenericRate = Number(analysisStats?.generic_rate || 0)
    const analysisDuplicateRate = Number(analysisStats?.duplicate_rate || 0)
    const analysisAcceptedRate = Number(analysisStats?.accepted_rate || 0)
    const analysisContextCoverageRate = Number(analysisStats?.context_coverage_rate || 0)
    const clientObservability = backgroundStatus?.clients || {}
    const clientObservabilitySummary = clientObservability?.summary || {}
    const clientObservabilityHistory = clientObservability?.history || {}
    const clientRows = Array.isArray(clientObservability?.clients) ? clientObservability.clients : []
    const clientHistoryRows = Array.isArray(clientObservabilityHistory?.recent) ? clientObservabilityHistory.recent : []
    const releaseGates = backgroundStatus?.release_gates || {}
    const releaseGateRows = Array.isArray(releaseGates?.gates) ? releaseGates.gates : []
    const gateC = releaseGateRows.find((gate: any) => String(gate?.id || '').toUpperCase() === 'C') || null
    const gateCReady = !!gateC?.pass
    const runtimeRequests24hTotal = Number(clientObservabilitySummary?.runtime_requests_24h_total || 0)
    const runtimeErrors24hTotal = Number(clientObservabilitySummary?.runtime_errors_24h_total || 0)
    const runtimeErrorRate24h = Number(clientObservabilitySummary?.runtime_error_rate_24h || 0)
    const lastClientMetricsFlushAt = scheduler?.last_client_metrics_flush
    const lastClientMetricsFlushResult = scheduler?.last_client_metrics_flush_result || {}
    const clientRowsActive = clientRows.filter((client: any) =>
        Number(client?.sessions_total || 0) > 0 ||
        Number(client?.runtime_total_requests || 0) > 0 ||
        Number(client?.runtime_requests_24h || 0) > 0
    )

    // ── Helpers ───────────────────────────────────────────────────────────

    const parseConversationIds = (raw: string): string[] => {
        const seen = new Set<string>()
        const out: string[] = []
        for (const token of raw.split(/[\n,\s]+/g)) {
            const value = String(token || '').trim()
            if (!value || seen.has(value)) continue
            seen.add(value)
            out.push(value)
        }
        return out
    }

    // ── Handlers ──────────────────────────────────────────────────────────

    const handleAnalyzeConversations = async () => {
        setMaintenanceMessage(null)
        setMaintenanceAction('analyze')
        try {
            const res = await deduplicateConversations.mutateAsync({
                dry_run: true,
                include_messages: maintenanceIncludeMessages,
            })
            setMaintenanceReport(res)
            if (Array.isArray(res?.conversation_duplicate_ids_preview) && res.conversation_duplicate_ids_preview.length > 0) {
                setMaintenanceDeleteIdsInput(res.conversation_duplicate_ids_preview.join('\n'))
            }
            const duplicates = Number(res?.conversations_duplicates || 0) + Number(res?.messages_duplicates || 0)
            setMaintenanceMessage(duplicates > 0 ? 'Duplicates detected. You can run deduplication safely.' : 'No duplicates detected.')
        } catch (e: any) {
            setMaintenanceMessage(e?.message || 'Failed to analyze conversations.')
        } finally {
            setMaintenanceAction(null)
        }
    }

    const handleDeduplicateConversations = async () => {
        setMaintenanceMessage(null)
        if (!window.confirm('Deduplicate conversations now? Older duplicates will be removed and the newest versions kept.')) {
            return
        }
        setMaintenanceAction('deduplicate')
        try {
            const res = await deduplicateConversations.mutateAsync({
                dry_run: false,
                include_messages: maintenanceIncludeMessages,
            })
            setMaintenanceReport(res)
            const convDup = Number(res?.conversations_duplicates || 0)
            const msgDup = Number(res?.messages_duplicates || 0)
            setMaintenanceMessage(`Deduplication completed. Removed ${convDup} duplicated conversations and ${msgDup} duplicated messages.`)
        } catch (e: any) {
            setMaintenanceMessage(e?.message || 'Failed to deduplicate conversations.')
        } finally {
            setMaintenanceAction(null)
        }
    }

    const handlePurgeConversations = async () => {
        setMaintenanceMessage(null)
        if (!window.confirm('Delete all conversations now? This cannot be undone.')) {
            return
        }
        setMaintenanceAction('purge')
        try {
            const res = await purgeConversations.mutateAsync({
                include_messages: maintenanceIncludeMessages,
            })
            setMaintenanceReport(res)
            const deletedConversations = Number(res?.conversations_deleted || 0)
            const deletedMessages = Number(res?.messages_deleted || 0)
            setMaintenanceMessage(`Purge completed. Deleted ${deletedConversations} conversations and ${deletedMessages} messages.`)
        } catch (e: any) {
            setMaintenanceMessage(e?.message || 'Failed to purge conversations.')
        } finally {
            setMaintenanceAction(null)
        }
    }

    const handleDeleteSelectedConversations = async () => {
        setMaintenanceMessage(null)
        const ids = parseConversationIds(maintenanceDeleteIdsInput)
        if (ids.length === 0) {
            setMaintenanceMessage('Provide at least one conversation ID to delete.')
            return
        }
        if (!window.confirm(`Delete ${ids.length} selected conversation(s)?`)) {
            return
        }
        setMaintenanceAction('deduplicate')
        try {
            const res = await deleteConversationsByIds.mutateAsync({
                conversation_ids: ids,
                include_messages: maintenanceIncludeMessages,
            })
            setMaintenanceMessage(
                `Deleted ${Number(res?.updated || 0)} conversation(s). Messages deleted: ${Number(res?.messages_deleted || 0)}.`
            )
        } catch (e: any) {
            setMaintenanceMessage(e?.message || 'Failed to delete selected conversations.')
        } finally {
            setMaintenanceAction(null)
        }
    }

    const handleRunBackgroundAnalysis = async () => {
        setBackgroundMessage(null)
        try {
            const targetIds = parseConversationIds(targetConversationIdsInput)
            const res = await runBackgroundAnalysis.mutateAsync({
                force_reanalyze: forceBackgroundReanalyze,
                conversation_ids: targetIds.length > 0 ? targetIds : undefined,
                wait_for_completion: false,
            })
            if (res?.status === 'accepted') {
                const jobId = res?.job?.id ? ` Job: ${res.job.id}` : ''
                setBackgroundMessage(`Background analysis queued.${jobId}`)
            } else if (res?.status === 'busy') {
                setBackgroundMessage('An analysis is already running. Wait for completion before launching another one.')
            } else {
                const result = res?.result || {}
                const stats = result?.write_stats || {}
                setBackgroundMessage(
                    `Run complete: selected ${Number(result?.conversations_selected || 0)}, candidates ${Number(result?.candidates_total || 0)}, created ${Number(stats?.created || 0)}, rejected ${Number(stats?.rejected || 0)}.`
                )
            }
            await refetchBackgroundStatus()
        } catch (e: any) {
            setBackgroundMessage(e?.message || 'Failed to run background analysis.')
        }
    }

    return (
        <>
            {/* ── Client Readiness ─────────────────────────────────────────────── */}
            <SectionBlock
                title="Client Readiness"
                description="Track whether each MCP client actually reads memory before writing, with live runtime health and 24h history."
            >
                <Panel>
                    <div className="settings-status-head">
                        <div className="settings-status-title-wrap">
                            <Shield size={14} />
                            <span>Cross-LLM memory usage</span>
                        </div>
                        <span className={cx('settings-status-badge', `settings-status-badge--${gateCReady ? 'ok' : 'error'}`)}>
                            Gate C: {gateCReady ? 'pass' : gateC ? 'fail' : 'no-data'}
                        </span>
                    </div>

                    <div className="settings-stats-grid">
                        <StatCell label="Clients total" value={`${Number(clientObservabilitySummary?.total_clients || 0)}`} />
                        <StatCell label="Configured" value={`${Number(clientObservabilitySummary?.configured_clients || 0)}`} />
                        <StatCell label="Active clients" value={`${Number(clientObservabilitySummary?.active_clients || 0)}`} />
                        <StatCell label="Read reliability" value={`${Math.round(Number(clientObservabilitySummary?.cross_llm_read_reliability || 0) * 100)}%`} />
                        <StatCell label="Requests (24h)" value={`${runtimeRequests24hTotal}`} />
                        <StatCell label="Error rate (24h)" value={`${Math.round(runtimeErrorRate24h * 100)}%`} />
                        <StatCell label="Metrics rows (24h)" value={`${Number(clientObservabilitySummary?.runtime_rows_24h || 0)}`} />
                        <StatCell label="Last metrics flush" value={lastClientMetricsFlushAt ? new Date(lastClientMetricsFlushAt).toLocaleString() : 'Never'} />
                        <StatCell label="Flush status" value={String(lastClientMetricsFlushResult?.status || 'n/a')} />
                        <StatCell label="Rows written" value={`${Number(lastClientMetricsFlushResult?.rows_written || 0)}`} />
                    </div>

                    {clientRowsActive.length === 0 ? (
                        <p className="settings-helper-text">No active client usage yet. Connect at least one MCP client and perform a memory read/write cycle.</p>
                    ) : (
                        <div className="settings-client-readiness-list">
                            {clientRowsActive.slice(0, 12).map((client: any) => {
                                const readGate = String(client?.reads_before_response || 'no-data')
                                const readGateTone = readGate === 'yes' ? 'ok' : readGate === 'no' ? 'error' : 'idle'
                                return (
                                    <div key={String(client?.name || 'unknown')} className="settings-client-readiness-item">
                                        <div className="settings-client-readiness-item-head">
                                            <p className="settings-helper-text">
                                                <strong>{String(client?.name || 'unknown')}</strong>
                                                {client?.configured ? ' · configured' : ' · discovered'}
                                                {Array.isArray(client?.scopes) && client.scopes.length > 0 ? ` · scopes: ${client.scopes.join(',')}` : ''}
                                            </p>
                                            <span className={cx('settings-status-badge', `settings-status-badge--${readGateTone}`)}>
                                                reads-before-response: {readGate}
                                            </span>
                                        </div>
                                        <div className="settings-stats-grid">
                                            <StatCell label="Sessions" value={`${Number(client?.sessions_total || 0)}`} />
                                            <StatCell label="Reads" value={`${Number(client?.memory_reads_total || 0)}`} />
                                            <StatCell label="Writes" value={`${Number(client?.memory_writes_total || 0)}`} />
                                            <StatCell label="Requests (24h)" value={`${Number(client?.runtime_requests_24h || 0)}`} />
                                            <StatCell label="Errors (24h)" value={`${Number(client?.runtime_errors_24h || 0)}`} />
                                            <StatCell label="Avg latency (24h)" value={`${Math.round(Number(client?.runtime_avg_latency_24h_ms || 0))}ms`} />
                                            <StatCell label="P95 latency (24h)" value={`${Math.round(Number(client?.runtime_p95_latency_24h_ms || 0))}ms`} />
                                            <StatCell label="Last write" value={client?.last_write_at ? new Date(client.last_write_at).toLocaleString() : 'Never'} />
                                        </div>
                                    </div>
                                )
                            })}
                        </div>
                    )}

                    {clientHistoryRows.length > 0 && (
                        <div className="settings-maintenance-preview">
                            <p className="settings-helper-text">
                                Recent runtime windows ({Number(clientObservabilityHistory?.period_hours || 24)}h):
                            </p>
                            {clientHistoryRows.slice(0, 6).map((row: any, idx: number) => (
                                <p key={`${row?.client || 'unknown'}-${row?.captured_at || idx}`} className="settings-helper-text settings-helper-text--top-space">
                                    {String(row?.client || 'unknown')} · {row?.captured_at ? new Date(row.captured_at).toLocaleString() : 'n/a'} · +{Number(row?.delta_requests || 0)} req · +{Number(row?.delta_errors || 0)} err · {Math.round(Number(row?.avg_latency_ms || 0))}ms avg
                                </p>
                            ))}
                        </div>
                    )}
                </Panel>
            </SectionBlock>

            {/* ── Conversation Maintenance ──────────────────────────────────────── */}
            <SectionBlock
                title="Conversation Maintenance"
                description="Audit duplicates from imports, remove duplicated rows automatically, or reset all imported conversations."
            >
                <Panel>
                    <div className="settings-toggle-row settings-toggle-row--tight">
                        <CheckboxLabel checked={maintenanceIncludeMessages} onChange={setMaintenanceIncludeMessages}>
                            Include messages
                        </CheckboxLabel>
                    </div>

                    <div className="settings-actions-row settings-actions-row--tight">
                        <ActionButton
                            onClick={handleAnalyzeConversations}
                            busy={maintenanceAction === 'analyze'}
                            icon={<RefreshCw size={14} />}
                            disabled={maintenanceAction !== null}
                        >
                            Analyze duplicates
                        </ActionButton>
                        <ActionButton
                            onClick={handleDeduplicateConversations}
                            busy={maintenanceAction === 'deduplicate'}
                            icon={<Check size={14} />}
                            disabled={maintenanceAction !== null}
                        >
                            Remove duplicates
                        </ActionButton>
                        <ActionButton
                            onClick={handlePurgeConversations}
                            busy={maintenanceAction === 'purge'}
                            icon={<Trash2 size={14} />}
                            disabled={maintenanceAction !== null}
                        >
                            Purge all conversations
                        </ActionButton>
                    </div>

                    <Field
                        label="Delete specific conversation IDs"
                        helper="Paste IDs separated by new lines, commas, or spaces. Useful to remove only detected duplicates."
                    >
                        <textarea
                            value={maintenanceDeleteIdsInput}
                            onChange={(e) => setMaintenanceDeleteIdsInput(e.target.value)}
                            className="settings-input"
                            rows={4}
                            placeholder="6993683f-853c-838f-9e41-79c451f37ae7"
                        />
                    </Field>

                    <div className="settings-actions-row settings-actions-row--tight">
                        <ActionButton
                            onClick={handleDeleteSelectedConversations}
                            busy={maintenanceAction === 'deduplicate' || deleteConversationsByIds.isPending}
                            icon={<Trash2 size={14} />}
                            disabled={maintenanceAction !== null}
                        >
                            Delete selected IDs
                        </ActionButton>
                    </div>

                    {maintenanceReport && (
                        <div className="settings-maintenance-report">
                            {'conversations_total' in maintenanceReport && (
                                <div className="settings-stats-grid">
                                    <StatCell label="Conversations total" value={`${maintenanceReport.conversations_total ?? 0}`} />
                                    <StatCell label="Conversations kept" value={`${maintenanceReport.conversations_kept ?? 0}`} />
                                    <StatCell label="Conversations duplicates" value={`${maintenanceReport.conversations_duplicates ?? 0}`} />
                                    <StatCell label="Messages total" value={`${maintenanceReport.messages_total ?? 0}`} />
                                    <StatCell label="Messages kept" value={`${maintenanceReport.messages_kept ?? 0}`} />
                                    <StatCell label="Messages duplicates" value={`${maintenanceReport.messages_duplicates ?? 0}`} />
                                </div>
                            )}
                            {'conversations_deleted' in maintenanceReport && (
                                <div className="settings-stats-grid">
                                    <StatCell label="Conversations deleted" value={`${maintenanceReport.conversations_deleted ?? 0}`} />
                                    <StatCell label="Messages deleted" value={`${maintenanceReport.messages_deleted ?? 0}`} />
                                </div>
                            )}
                            {maintenanceReport?.conversation_duplicate_ids_preview && maintenanceReport.conversation_duplicate_ids_preview.length > 0 && (
                                <div className="settings-maintenance-preview">
                                    <p className="settings-helper-text">
                                        Duplicate conversation IDs (preview): {maintenanceReport.conversation_duplicate_ids_preview.join(', ')}
                                    </p>
                                </div>
                            )}
                            {maintenanceReport?.message_duplicate_ids_preview && maintenanceReport.message_duplicate_ids_preview.length > 0 && (
                                <div className="settings-maintenance-preview">
                                    <p className="settings-helper-text">
                                        Duplicate message IDs (preview): {maintenanceReport.message_duplicate_ids_preview.join(', ')}
                                    </p>
                                </div>
                            )}
                        </div>
                    )}

                    {maintenanceMessage && <InlineMessage danger={isDangerMessage(maintenanceMessage)}>{maintenanceMessage}</InlineMessage>}
                </Panel>
            </SectionBlock>

            {/* ── Background Jobs (Debug) ───────────────────────────────────────── */}
            <SectionBlock
                title="Background Jobs (Debug)"
                description="Live visibility for scheduler tasks, auto conversation analysis, and why memory suggestions may be empty."
            >
                <Panel>
                    <div className="settings-status-head">
                        <div className="settings-status-title-wrap">
                            <RefreshCw size={14} />
                            <span>Scheduler state</span>
                        </div>
                        <span className={cx('settings-status-badge', `settings-status-badge--${embeddingStatus === 'ready' ? 'ok' : 'error'}`)}>
                            model: {embeddingStatus}{analysisRunning ? ' · analysis running' : ''}
                        </span>
                    </div>

                    <div className="settings-stats-grid">
                        <StatCell
                            label="Last analysis"
                            value={lastAnalysisAt ? `${new Date(lastAnalysisAt).toLocaleString()} (${lastAnalysisSource})` : 'Never'}
                        />
                        <StatCell label="Selected (last run)" value={`${Number(analysisStats?.conversations_selected || 0)}`} />
                        <StatCell label="Candidates (last run)" value={`${Number(analysisStats?.candidates_total || 0)}`} />
                        <StatCell label="Created (last run)" value={`${Number(analysisStats?.created || 0)}`} />
                        <StatCell label="Rejected (last run)" value={`${Number(analysisStats?.rejected || 0)}`} />
                        <StatCell label="Accepted rate" value={`${Math.round(analysisAcceptedRate * 100)}%`} />
                        <StatCell label="Duplicate rate" value={`${Math.round(analysisDuplicateRate * 100)}%`} />
                        <StatCell label="Generic rate" value={`${Math.round(analysisGenericRate * 100)}%`} />
                        <StatCell label="Context coverage" value={`${Math.round(analysisContextCoverageRate * 100)}%`} />
                        <StatCell label="Duration (last run)" value={`${Math.round(Number(analysisStats?.duration_ms || 0) / 1000)}s`} />
                        <StatCell label="Auto pending now" value={`${Number(memoryCounts?.auto_pending_review || 0)}`} />
                        <StatCell label="Auto non-archived now" value={`${Number(memoryCounts?.auto_nonarchived || 0)}`} />
                        <StatCell label="Conversations tagged" value={`${Number(conversationCounts?.tagged_analysis || 0)} / ${Number(conversationCounts?.active || 0)}`} />
                        <StatCell label="Schema missing fields" value={`${missingTemporalFields.length}`} />
                        <StatCell label="Write guard" value={memoryLegacyWriteGuard} />
                        <StatCell label="LLM gate" value={analysisGateBlocked ? 'blocked' : 'open'} />
                        <StatCell label="Analysis running" value={analysisRunning ? 'yes' : 'no'} />
                        <StatCell label="Queue pending" value={`${Number(jobCounts?.pending || 0)}`} />
                        <StatCell label="Queue running" value={`${Number(jobCounts?.running || 0)}`} />
                        <StatCell label="Queue failed" value={`${Number(jobCounts?.failed || 0)}`} />
                        <StatCell label="Worker alive" value={analysisWorker?.task_alive ? 'yes' : 'no'} />
                        <StatCell label="Client reliability" value={`${Math.round(Number(clientObservabilitySummary?.cross_llm_read_reliability || 0) * 100)}%`} />
                        <StatCell label="Last decay run" value={scheduler?.last_decay ? new Date(scheduler.last_decay).toLocaleString() : 'Never'} />
                        <StatCell label="Last hourly checks" value={scheduler?.last_hourly_checks ? new Date(scheduler.last_hourly_checks).toLocaleString() : 'Never'} />
                    </div>

                    <div className="settings-maintenance-preview">
                        <p className="settings-helper-text">
                            Release gates: {releaseGates?.ready_for_v1 ? 'ready for v1' : `blocked (${(releaseGates?.blockers || []).join(', ') || 'unknown'})`}
                        </p>
                        {releaseGateRows.map((gate: any) => (
                            <p key={String(gate?.id || gate?.name)} className="settings-helper-text settings-helper-text--top-space">
                                [{gate?.id}] {gate?.name}: {gate?.pass ? 'PASS' : 'FAIL'}
                            </p>
                        ))}
                    </div>

                    {clientRows.length > 0 && (
                        <div className="settings-maintenance-preview">
                            <p className="settings-helper-text">Client observability:</p>
                            <div className="settings-stats-grid">
                                <StatCell label="Clients total" value={`${Number(clientObservabilitySummary?.total_clients || 0)}`} />
                                <StatCell label="Configured" value={`${Number(clientObservabilitySummary?.configured_clients || 0)}`} />
                                <StatCell label="Active clients" value={`${Number(clientObservabilitySummary?.active_clients || 0)}`} />
                                <StatCell label="Write sessions" value={`${Number(clientObservabilitySummary?.write_sessions_total || 0)}`} />
                                <StatCell label="Requests (24h)" value={`${runtimeRequests24hTotal}`} />
                                <StatCell label="Errors (24h)" value={`${runtimeErrors24hTotal}`} />
                            </div>
                            <p className="settings-helper-text settings-helper-text--top-space">
                                Detailed client-by-client view is available in <strong>Client Readiness</strong>.
                            </p>
                        </div>
                    )}

                    {Array.isArray(analysisStats?.sample_errors) && analysisStats.sample_errors.length > 0 && (
                        <div className="settings-maintenance-preview">
                            <p className="settings-helper-text">Recent analysis errors:</p>
                            {analysisStats.sample_errors.map((err: string, idx: number) => (
                                <p key={`${idx}-${err}`} className="settings-helper-text settings-helper-text--top-space">
                                    {err}
                                </p>
                            ))}
                        </div>
                    )}
                    {analysisGateBlocked && analysisGateReason && (
                        <div className="settings-maintenance-preview">
                            <p className="settings-helper-text">
                                Analysis blocked: {analysisGateReason}
                            </p>
                        </div>
                    )}
                    {missingTemporalFields.length > 0 && (
                        <div className="settings-maintenance-preview">
                            <p className="settings-helper-text">
                                Legacy schema detected on memories table. Missing fields: {missingTemporalFields.join(', ')}
                            </p>
                        </div>
                    )}

                    <p className="settings-helper-text">
                        Config file: <code>{backgroundStatus?.config?.config_path || 'n/a'}</code>
                    </p>

                    <div className="settings-toggle-row settings-toggle-row--tight">
                        <CheckboxLabel checked={forceBackgroundReanalyze} onChange={setForceBackgroundReanalyze}>
                            Force reanalyze
                        </CheckboxLabel>
                    </div>

                    <Field
                        label="Target conversation IDs (optional)"
                        helper="When provided, analysis runs only on these conversations. Leave empty for normal auto selection."
                    >
                        <textarea
                            value={targetConversationIdsInput}
                            onChange={(e) => setTargetConversationIdsInput(e.target.value)}
                            className="settings-input"
                            rows={3}
                            placeholder="id1,id2,id3"
                        />
                    </Field>

                    <div className="settings-actions-row settings-actions-row--tight">
                        <ActionButton
                            onClick={() => { void refetchBackgroundStatus() }}
                            busy={backgroundLoading}
                            icon={<RefreshCw size={14} />}
                        >
                            Refresh status
                        </ActionButton>
                        <ActionButton
                            onClick={handleRunBackgroundAnalysis}
                            busy={runBackgroundAnalysis.isPending}
                            disabled={analysisRunning || analysisGateBlocked}
                            icon={<Play size={14} />}
                        >
                            Run analysis now
                        </ActionButton>
                    </div>

                    {backgroundMessage && <InlineMessage danger={isDangerMessage(backgroundMessage)}>{backgroundMessage}</InlineMessage>}
                </Panel>
            </SectionBlock>
        </>
    )
}
