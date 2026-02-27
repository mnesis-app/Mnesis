import { Check, Copy, RefreshCw, Shield } from 'lucide-react'
import { useState } from 'react'
import { api } from '../lib/api'
import { useConfig, useSnapshotToken } from '../lib/queries'
import {
    ActionButton,
    InlineMessage,
    Panel,
    SectionBlock,
    cx,
    isDangerMessage,
} from './SettingsShared'

export function SettingsMcp() {
    const { data: config, refetch: refetchConfig } = useConfig()
    const { data: snapshotTokenData } = useSnapshotToken()

    const [mcpAutoconfigMessage, setMcpAutoconfigMessage] = useState<string | null>(null)
    const [mcpAutoconfigBusy, setMcpAutoconfigBusy] = useState(false)
    const [mcpCopiedKind, setMcpCopiedKind] = useState<'none' | 'sse' | 'bridge' | 'tunnel'>('none')
    const [mcpCopyMessage, setMcpCopyMessage] = useState<string | null>(null)
    const [mcpAuthStatusResult, setMcpAuthStatusResult] = useState<string | null>(null)
    const [mcpAuthStatusBusy, setMcpAuthStatusBusy] = useState(false)

    const mcpAutoconfigState = (config as any)?.mcp_autoconfig || {}
    const mcpDetectedClients: string[] = Array.isArray(mcpAutoconfigState?.detected_clients) ? mcpAutoconfigState.detected_clients : []
    const mcpConfiguredClients: string[] = Array.isArray(mcpAutoconfigState?.configured_clients) ? mcpAutoconfigState.configured_clients : []
    const detectedClientsCount = mcpDetectedClients.length
    const configuredClientsCount = mcpConfiguredClients.length
    const mcpAllDetectedConfigured = detectedClientsCount > 0 && configuredClientsCount >= detectedClientsCount

    const restPort = (typeof window !== 'undefined' && (window as any)?.electronAPI?.getRestPort)
        ? Number((window as any).electronAPI.getRestPort() || 7860)
        : 7860
    const mcpBaseUrl = `http://127.0.0.1:${restPort}`
    const mcpSseUrl = `${mcpBaseUrl}/mcp/sse`
    const mcpBridgeApiKey = String(snapshotTokenData?.token || (config as any)?.snapshot_read_token || '').trim() || '<YOUR_MCP_KEY>'
    const mcpBridgeSnippet = `{
  "mcpServers": {
    "mnesis": {
      "command": "/Applications/Mnesis.app/Contents/Resources/backend/mcp-stdio-bridge",
      "env": {
        "MNESIS_MCP_URL": "${mcpBaseUrl}",
        "MNESIS_API_KEY": "${mcpBridgeApiKey}"
      }
    }
  }
}`
    const mcpTunnelSnippet = `# Example (advanced, unsupported)
ngrok http ${restPort}
# Then use https://<your-subdomain>.ngrok.app/mcp/sse`

    const handleRunMcpAutoconfig = async () => {
        setMcpAutoconfigMessage(null)
        setMcpAutoconfigBusy(true)
        try {
            const res = await api.admin.runMcpAutoconfig({ force: true })
            const result = (res as any)?.result || {}
            const detected = Array.isArray(result?.detected_clients) ? result.detected_clients.length : 0
            const configured = Array.isArray(result?.configured_clients) ? result.configured_clients.length : 0
            const errors = Number(result?.error_count || 0)
            setMcpAutoconfigMessage(
                errors > 0
                    ? `Auto-config finished with ${errors} issue(s). Detected ${detected}, configured ${configured}.`
                    : `Auto-config successful. Detected ${detected}, configured ${configured}.`
            )
            await refetchConfig()
        } catch (e: any) {
            setMcpAutoconfigMessage(e?.message || 'Auto-config failed.')
        } finally {
            setMcpAutoconfigBusy(false)
        }
    }

    const handleCopyMcpValue = async (
        kind: 'sse' | 'bridge' | 'tunnel',
        label: string,
        value: string
    ) => {
        try {
            await navigator.clipboard.writeText(value)
            setMcpCopiedKind(kind)
            setMcpCopyMessage(`${label} copied.`)
            window.setTimeout(() => setMcpCopiedKind('none'), 1800)
        } catch {
            setMcpCopyMessage(`Failed to copy ${label.toLowerCase()}.`)
        }
    }

    const handleCheckMcpAuthStatus = async () => {
        setMcpAuthStatusResult(null)
        setMcpAuthStatusBusy(true)
        try {
            const res = await api.admin.mcpAuthStatus()
            const mode = res.auth_mode === 'dedicated_keys'
                ? `Dedicated keys (${res.client_keys_count})`
                : 'Snapshot token'
            setMcpAuthStatusResult(`Auth mode: ${mode}${res.allow_snapshot_fallback ? ' · fallback enabled' : ''}`)
        } catch (e: any) {
            setMcpAuthStatusResult(e?.message || 'Failed to check auth status.')
        } finally {
            setMcpAuthStatusBusy(false)
        }
    }

    return (
        <SectionBlock title="MCP Configuration" description="Single setup for all MCP-compatible clients (Claude, Cursor, ChatGPT, etc.).">
            <Panel>
                <div className="settings-integrations-grid">
                    <div className="settings-integration-card">
                        <p className="settings-integration-title">Universal MCP Setup</p>
                        <p className="settings-card-copy">
                            One setup for all compatible clients. Same endpoint, same API key.
                        </p>
                        <div className="settings-mcp-summary">
                            <span className={cx('settings-status-badge', `settings-status-badge--${mcpAllDetectedConfigured ? 'ok' : 'idle'}`)}>
                                {configuredClientsCount}/{detectedClientsCount || 0} configured
                            </span>
                            <span className="settings-status-badge settings-status-badge--idle">
                                endpoint: {mcpSseUrl}
                            </span>
                        </div>
                        <p className="settings-helper-text">
                            First launch auto-config: <strong>{mcpAutoconfigState?.first_launch_done ? 'enabled' : 'pending'}</strong>
                            {mcpAutoconfigState?.last_run_at ? ` · last run ${new Date(mcpAutoconfigState.last_run_at).toLocaleString()}` : ''}
                        </p>
                        <p className="settings-helper-text">
                            Detected clients: {mcpDetectedClients.length > 0 ? mcpDetectedClients.join(', ') : 'none'}
                        </p>
                        <p className="settings-helper-text">
                            Configured clients: {mcpConfiguredClients.length > 0 ? mcpConfiguredClients.join(', ') : 'none'}
                        </p>
                        <div className="settings-actions-row settings-actions-row--tight">
                            <ActionButton
                                onClick={handleRunMcpAutoconfig}
                                busy={mcpAutoconfigBusy}
                                icon={<RefreshCw size={14} />}
                            >
                                Auto-config now
                            </ActionButton>
                            <ActionButton
                                onClick={handleCheckMcpAuthStatus}
                                busy={mcpAuthStatusBusy}
                                icon={<Shield size={14} />}
                            >
                                Check auth status
                            </ActionButton>
                            <ActionButton
                                onClick={() => { void handleCopyMcpValue('sse', 'SSE URL', mcpSseUrl) }}
                                busy={false}
                                icon={mcpCopiedKind === 'sse' ? <Check size={14} /> : <Copy size={14} />}
                            >
                                Copy SSE URL
                            </ActionButton>
                            <ActionButton
                                onClick={() => { void handleCopyMcpValue('bridge', 'Bridge config', mcpBridgeSnippet) }}
                                busy={false}
                                icon={mcpCopiedKind === 'bridge' ? <Check size={14} /> : <Copy size={14} />}
                            >
                                Copy bridge config
                            </ActionButton>
                        </div>
                        <pre className="settings-code-block">{mcpBridgeSnippet}</pre>
                        <p className="settings-config-path">
                            SSE endpoint: <code>{mcpSseUrl}</code>
                        </p>
                        {mcpAutoconfigMessage && (
                            <InlineMessage danger={isDangerMessage(mcpAutoconfigMessage)}>
                                {mcpAutoconfigMessage}
                            </InlineMessage>
                        )}
                        {mcpAuthStatusResult && (
                            <InlineMessage danger={isDangerMessage(mcpAuthStatusResult)}>
                                {mcpAuthStatusResult}
                            </InlineMessage>
                        )}
                        {mcpCopyMessage && (
                            <InlineMessage danger={isDangerMessage(mcpCopyMessage)}>
                                {mcpCopyMessage}
                            </InlineMessage>
                        )}
                        {detectedClientsCount > 0 && (
                            <div className="settings-mcp-chip-row">
                                {mcpDetectedClients.map((client) => {
                                    const configured = mcpConfiguredClients.includes(client)
                                    return (
                                        <span
                                            key={client}
                                            className={cx(
                                                'settings-mcp-chip',
                                                configured && 'settings-mcp-chip--ok'
                                            )}
                                        >
                                            {client} {configured ? 'configured' : 'detected'}
                                        </span>
                                    )
                                })}
                            </div>
                        )}
                        <p className="settings-helper-text settings-helper-text--top-space">
                            Philosophy: <strong>local-first</strong>. No managed relay is enabled by default.
                        </p>
                        <details className="settings-mcp-details">
                            <summary>BYO tunnel (advanced)</summary>
                            <p className="settings-helper-text settings-helper-text--top-space">
                                Expose your own local endpoint temporarily with ngrok/cloudflared.
                            </p>
                            <ol className="settings-steps-list">
                                <li>Create a dedicated MCP key in config (scopes: read/write/sync).</li>
                                <li>Keep snapshot query token disabled and snapshot fallback for MCP disabled.</li>
                                <li>Use short-lived tunnel sessions and rotate keys regularly.</li>
                            </ol>
                            <div className="settings-actions-row settings-actions-row--tight">
                                <ActionButton
                                    onClick={() => { void handleCopyMcpValue('tunnel', 'BYO tunnel snippet', mcpTunnelSnippet) }}
                                    busy={false}
                                    icon={mcpCopiedKind === 'tunnel' ? <Check size={14} /> : <Copy size={14} />}
                                >
                                    Copy tunnel snippet
                                </ActionButton>
                            </div>
                            <pre className="settings-code-block">{mcpTunnelSnippet}</pre>
                            <p className="settings-helper-text settings-helper-text--top-space">
                                Full guide: <code>BYO_TUNNEL.md</code>
                            </p>
                        </details>
                    </div>
                </div>
            </Panel>
        </SectionBlock>
    )
}
