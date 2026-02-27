import { Check, Copy, Eye, EyeOff, Loader2, RefreshCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useConfig, useRotateToken, useSnapshotToken } from '../lib/queries'
import { ActionButton, IconButton, InlineMessage, Panel, SectionBlock, cx, isDangerMessage } from './SettingsShared'
import { SettingsInsights } from './SettingsInsights'
import { SettingsMaintenance } from './SettingsMaintenance'
import { SettingsMcp } from './SettingsMcp'
import { SettingsSync } from './SettingsSync'
import './Settings.css'

type Tab = 'mcp' | 'insights' | 'sync' | 'dev'

const TABS: { id: Tab; label: string }[] = [
    { id: 'mcp', label: 'MCP' },
    { id: 'insights', label: 'Insights' },
    { id: 'sync', label: 'Sync' },
    { id: 'dev', label: 'Dev' },
]

export function Settings() {
    const { isLoading, isError } = useConfig()
    const rotateToken = useRotateToken()
    const { data: snapshotTokenData } = useSnapshotToken()

    const [activeTab, setActiveTab] = useState<Tab>('mcp')
    const [copied, setCopied] = useState(false)
    const [tokenVisible, setTokenVisible] = useState(false)
    const [appVersion, setAppVersion] = useState<string>('')
    const [updateBusy, setUpdateBusy] = useState(false)
    const [updateMessage, setUpdateMessage] = useState<string | null>(null)

    const isElectron = typeof window !== 'undefined' && !!(window as any).electronAPI

    useEffect(() => {
        if (!isElectron) return
        ;(window as any).electronAPI.getAppVersion?.()
            .then((v: string) => setAppVersion(v || ''))
            .catch(() => {})
    }, [isElectron])

    if (isLoading) {
        return (
            <div className="settings-loading">
                <Loader2 size={20} className="settings-spinner" />
            </div>
        )
    }

    if (isError) {
        return <div className="settings-error">Failed to load configuration.</div>
    }

    const handleCopy = async () => {
        const token = snapshotTokenData?.token
        if (!token) return
        try {
            await navigator.clipboard.writeText(token)
            setCopied(true)
            setTimeout(() => setCopied(false), 1800)
        } catch {
            setCopied(false)
        }
    }

    return (
        <div className="settings-page">
            {/* ── Snapshot Access ───────────────────────────────────────────────── */}
            <SectionBlock
                title="Snapshot Access"
                description="Use this token to allow external tools (like ChatGPT) to read your memory snapshot. Keep it secret."
            >
                <Panel>
                    <div className="settings-token-row">
                        <code className="settings-token-value">
                            {tokenVisible
                                ? (snapshotTokenData?.token ?? 'Token not available')
                                : '••••••••••••••••••••••••'}
                        </code>
                        <IconButton onClick={() => setTokenVisible((v) => !v)} title={tokenVisible ? 'Hide token' : 'Reveal token'}>
                            {tokenVisible ? <EyeOff size={15} /> : <Eye size={15} />}
                        </IconButton>
                        <IconButton onClick={handleCopy} title="Copy">
                            {copied ? <Check size={15} className="settings-icon-success" /> : <Copy size={15} />}
                        </IconButton>
                        <IconButton onClick={() => rotateToken.mutate()} title="Rotate" disabled={rotateToken.isPending}>
                            {rotateToken.isPending ? <Loader2 size={15} className="settings-spinner" /> : <RefreshCw size={15} />}
                        </IconButton>
                    </div>
                    <p className="settings-helper-text">Rotating the token immediately invalidates the previous one.</p>
                </Panel>
            </SectionBlock>

            {/* ── Tab navigation ────────────────────────────────────────────────── */}
            <div className="settings-tabs-nav" role="tablist" aria-label="Settings sections">
                {TABS.map(({ id, label }) => (
                    <button
                        key={id}
                        type="button"
                        role="tab"
                        aria-selected={activeTab === id}
                        className={cx('settings-tab', activeTab === id && 'settings-tab--active')}
                        onClick={() => setActiveTab(id)}
                    >
                        {label}
                    </button>
                ))}
            </div>

            {/* ── Tab content ───────────────────────────────────────────────────── */}
            {activeTab === 'mcp' && <SettingsMcp />}
            {activeTab === 'insights' && <SettingsInsights />}
            {activeTab === 'sync' && <SettingsSync />}
            {activeTab === 'dev' && <SettingsMaintenance />}

            {/* ── About & Updates ───────────────────────────────────────────────── */}
            <SectionBlock
                title="About & Updates"
                description="Check for new versions of Mnesis. Updates are downloaded in the background and installed on next restart."
            >
                <Panel>
                    <p className="settings-helper-text">
                        Version: <strong>{appVersion || '—'}</strong>
                        {!isElectron && <span> · running in browser / dev mode</span>}
                    </p>
                    {isElectron && (
                        <>
                            <div className="settings-actions-row settings-actions-row--tight">
                                <ActionButton
                                    onClick={async () => {
                                        setUpdateMessage(null)
                                        setUpdateBusy(true)
                                        try {
                                            const res = await (window as any).electronAPI.checkForUpdates()
                                            if (!res.success) {
                                                setUpdateMessage(res.error || 'Update check failed.')
                                            } else if (res.updateInfo) {
                                                setUpdateMessage(`Update available: v${res.updateInfo.version}. Downloading in background…`)
                                            } else {
                                                setUpdateMessage('Mnesis is up to date.')
                                            }
                                        } catch (e: any) {
                                            setUpdateMessage(e?.message || 'Update check failed.')
                                        } finally {
                                            setUpdateBusy(false)
                                        }
                                    }}
                                    busy={updateBusy}
                                    icon={<RefreshCw size={14} />}
                                >
                                    Check for updates
                                </ActionButton>
                            </div>
                            {updateMessage && (
                                <InlineMessage danger={isDangerMessage(updateMessage)}>
                                    {updateMessage}
                                </InlineMessage>
                            )}
                        </>
                    )}
                    <p className="settings-helper-text settings-helper-text--top-space">
                        <a
                            href="https://github.com/mnesis-app/Mnesis/releases"
                            onClick={(e) => {
                                e.preventDefault()
                                if (isElectron) (window as any).electronAPI.openExternal('https://github.com/mnesis-app/Mnesis/releases')
                                else window.open('https://github.com/mnesis-app/Mnesis/releases', '_blank')
                            }}
                            className="settings-link"
                        >
                            View releases on GitHub
                        </a>
                    </p>
                </Panel>
            </SectionBlock>
        </div>
    )
}
