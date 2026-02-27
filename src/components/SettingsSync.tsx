import { Cloud, Loader2, Lock, Unlock, Upload } from 'lucide-react'
import { useEffect, useState } from 'react'
import {
    useConfig,
    useLockSync,
    useRunSync,
    useSyncStatus,
    useUnlockSync,
    useUpdateSyncConfig,
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

const SYNC_PROVIDER_OPTIONS = [
    { value: 's3', label: 'AWS S3' },
    { value: 'r2', label: 'Cloudflare R2' },
    { value: 'minio', label: 'MinIO' },
    { value: 'custom', label: 'Custom S3-Compatible' },
    { value: 'webdav', label: 'WebDAV (Nextcloud/ownCloud)' },
]

function providerEndpointPlaceholder(provider: string): string {
    if (provider === 'r2') return 'https://<account-id>.r2.cloudflarestorage.com'
    if (provider === 'minio') return 'http://127.0.0.1:9000'
    if (provider === 'custom') return 'https://your-s3-compatible-endpoint'
    if (provider === 'webdav') return 'https://cloud.example.com/remote.php/dav/files/<user>'
    return 'Optional for AWS S3'
}

function providerHelpText(provider: string): string {
    if (provider === 's3') return 'AWS S3 native endpoint is used when endpoint URL is empty.'
    if (provider === 'r2') return 'R2 requires endpoint URL + access key + secret key.'
    if (provider === 'minio') return 'MinIO usually works best with path-style addressing.'
    if (provider === 'webdav') return 'WebDAV mode supports Nextcloud/ownCloud using app password credentials.'
    return 'Custom mode works with any S3-compatible storage.'
}

function syncResultTone(result: string): 'ok' | 'error' | 'idle' {
    if (result === 'ok') return 'ok'
    if (result === 'error') return 'error'
    return 'idle'
}

export function SettingsSync() {
    const { data: config } = useConfig()
    const { data: syncState, isLoading: syncLoading } = useSyncStatus()
    const updateSync = useUpdateSyncConfig()
    const unlockSync = useUnlockSync()
    const lockSync = useLockSync()
    const runSync = useRunSync()

    const [passphrase, setPassphrase] = useState('')
    const [syncMessage, setSyncMessage] = useState<string | null>(null)
    const [syncForm, setSyncForm] = useState({
        enabled: false,
        provider: 's3',
        endpoint_url: '',
        force_path_style: false,
        webdav_url: '',
        webdav_username: '',
        webdav_password: '',
        bucket: '',
        region: 'auto',
        access_key_id: '',
        secret_access_key: '',
        object_prefix: 'mnesis',
        device_id: '',
        auto_sync: false,
        auto_sync_interval_minutes: 60,
    })

    useEffect(() => {
        if (!config || !(config as any).sync) return
        const sync = (config as any).sync
        setSyncForm({
            enabled: !!sync.enabled,
            provider: sync.provider || 's3',
            endpoint_url: sync.endpoint_url || '',
            force_path_style: !!sync.force_path_style,
            webdav_url: sync.webdav_url || '',
            webdav_username: sync.webdav_username || '',
            webdav_password: sync.webdav_password || '',
            bucket: sync.bucket || '',
            region: sync.region || 'auto',
            access_key_id: sync.access_key_id || '',
            secret_access_key: sync.secret_access_key || '',
            object_prefix: sync.object_prefix || 'mnesis',
            device_id: sync.device_id || '',
            auto_sync: !!sync.auto_sync,
            auto_sync_interval_minutes: Number(sync.auto_sync_interval_minutes || 60),
        })
    }, [config])

    const isWebdavProvider = ['webdav', 'nextcloud', 'owncloud'].includes(syncForm.provider)
    const endpointRequired = !isWebdavProvider && ['r2', 'minio', 'custom'].includes(syncForm.provider)
    const syncResult = syncState?.sync_status?.last_sync_result || 'never'
    const syncResultClass = syncResultTone(syncResult)

    const handleSaveSync = async () => {
        setSyncMessage(null)
        if (isWebdavProvider) {
            if (!syncForm.webdav_url.trim() || !syncForm.webdav_username.trim() || !syncForm.webdav_password.trim()) {
                setSyncMessage('WebDAV URL, username, and password are required.')
                return
            }
        } else if (endpointRequired && !syncForm.endpoint_url.trim()) {
            setSyncMessage('Endpoint URL is required for this provider.')
            return
        }
        try {
            await updateSync.mutateAsync(syncForm)
            setSyncMessage('Sync settings saved.')
        } catch (e: any) {
            setSyncMessage(e?.message || 'Failed to save sync settings.')
        }
    }

    const handleUnlock = async () => {
        setSyncMessage(null)
        if (!passphrase || passphrase.length < 8) {
            setSyncMessage('Passphrase must be at least 8 characters.')
            return
        }
        try {
            await unlockSync.mutateAsync(passphrase)
            setSyncMessage('Sync key unlocked on this device.')
        } catch (e: any) {
            setSyncMessage(e?.message || 'Failed to unlock sync key.')
        }
    }

    const handleLock = async () => {
        setSyncMessage(null)
        try {
            await lockSync.mutateAsync()
            setSyncMessage('Sync key locked.')
        } catch (e: any) {
            setSyncMessage(e?.message || 'Failed to lock sync key.')
        }
    }

    const handleRunSync = async () => {
        setSyncMessage(null)
        try {
            await runSync.mutateAsync(passphrase || undefined)
            setSyncMessage('Sync completed.')
        } catch (e: any) {
            setSyncMessage(e?.message || 'Sync failed.')
        }
    }

    return (
        <SectionBlock
            title="Sync (E2E Encrypted)"
            description="Configure your storage provider, unlock your local encryption key, and run encrypted sync across devices."
        >
            <Panel>
                <div className="settings-status-head">
                    <div className="settings-status-title-wrap">
                        <Cloud size={14} />
                        <span>Sync status</span>
                    </div>
                    <span className={cx('settings-status-badge', `settings-status-badge--${syncResultClass}`)}>{syncResult}</span>
                </div>

                <div className="settings-stats-grid">
                    <StatCell
                        label="Last sync"
                        value={syncState?.sync_status?.last_sync_at ? new Date(syncState.sync_status.last_sync_at).toLocaleString() : 'Never'}
                    />
                    <StatCell
                        label="Last size"
                        value={`${Math.round((syncState?.sync_status?.last_sync_size_bytes || 0) / 1024)} KB`}
                    />
                    <StatCell label="Devices" value={`${(syncState?.sync_status?.devices || []).length}`} />
                </div>

                <div className="settings-key-row">
                    <span>Key state: {syncState?.unlocked ? 'Unlocked' : 'Locked'}</span>
                    {syncLoading && <Loader2 size={13} className="settings-spinner" />}
                </div>

                {syncState?.sync_status?.last_error && syncState.sync_status.last_sync_result === 'error' && (
                    <div className="settings-alert-error">{syncState.sync_status.last_error}</div>
                )}

                <div className="settings-fields-grid">
                    <Field label="Provider" helper={providerHelpText(syncForm.provider)} extra="OneDrive / iCloud require dedicated OAuth connectors.">
                        <select
                            value={syncForm.provider}
                            onChange={(e) => {
                                const provider = e.target.value
                                setSyncForm((s) => ({ ...s, provider, force_path_style: provider === 'minio' ? true : s.force_path_style }))
                            }}
                            className="settings-input"
                        >
                            {SYNC_PROVIDER_OPTIONS.map((opt) => (
                                <option key={opt.value} value={opt.value}>{opt.label}</option>
                            ))}
                        </select>
                    </Field>

                    {isWebdavProvider ? (
                        <>
                            <Field label="WebDAV URL *">
                                <input
                                    value={syncForm.webdav_url}
                                    onChange={(e) => setSyncForm((s) => ({ ...s, webdav_url: e.target.value }))}
                                    className="settings-input"
                                    placeholder={providerEndpointPlaceholder(syncForm.provider)}
                                />
                            </Field>
                            <Field label="WebDAV Username *">
                                <input
                                    value={syncForm.webdav_username}
                                    onChange={(e) => setSyncForm((s) => ({ ...s, webdav_username: e.target.value }))}
                                    className="settings-input"
                                    placeholder="your-username"
                                />
                            </Field>
                            <Field label="WebDAV Password / App Password *">
                                <input
                                    type="password"
                                    value={syncForm.webdav_password}
                                    onChange={(e) => setSyncForm((s) => ({ ...s, webdav_password: e.target.value }))}
                                    className="settings-input"
                                    placeholder="••••••••"
                                />
                            </Field>
                            <Field label="Object Prefix">
                                <input
                                    value={syncForm.object_prefix}
                                    onChange={(e) => setSyncForm((s) => ({ ...s, object_prefix: e.target.value }))}
                                    className="settings-input"
                                    placeholder="mnesis"
                                />
                            </Field>
                        </>
                    ) : (
                        <>
                            <Field label="Region">
                                <input
                                    value={syncForm.region}
                                    onChange={(e) => setSyncForm((s) => ({ ...s, region: e.target.value }))}
                                    className="settings-input"
                                    placeholder="auto"
                                />
                            </Field>
                            <Field label={`Endpoint URL${endpointRequired ? ' *' : ''}`}>
                                <input
                                    value={syncForm.endpoint_url}
                                    onChange={(e) => setSyncForm((s) => ({ ...s, endpoint_url: e.target.value }))}
                                    className="settings-input"
                                    placeholder={providerEndpointPlaceholder(syncForm.provider)}
                                />
                            </Field>
                            <Field label="Bucket">
                                <input
                                    value={syncForm.bucket}
                                    onChange={(e) => setSyncForm((s) => ({ ...s, bucket: e.target.value }))}
                                    className="settings-input"
                                    placeholder="my-mnesis-bucket"
                                />
                            </Field>
                            <Field label="Access Key ID">
                                <input
                                    value={syncForm.access_key_id}
                                    onChange={(e) => setSyncForm((s) => ({ ...s, access_key_id: e.target.value }))}
                                    className="settings-input"
                                    placeholder="AKIA..."
                                />
                            </Field>
                            <Field label="Secret Access Key">
                                <input
                                    type="password"
                                    value={syncForm.secret_access_key}
                                    onChange={(e) => setSyncForm((s) => ({ ...s, secret_access_key: e.target.value }))}
                                    className="settings-input"
                                    placeholder="••••••••"
                                />
                            </Field>
                            <Field label="Object Prefix">
                                <input
                                    value={syncForm.object_prefix}
                                    onChange={(e) => setSyncForm((s) => ({ ...s, object_prefix: e.target.value }))}
                                    className="settings-input"
                                    placeholder="mnesis"
                                />
                            </Field>
                        </>
                    )}

                    <Field label="Device ID">
                        <input
                            value={syncForm.device_id}
                            onChange={(e) => setSyncForm((s) => ({ ...s, device_id: e.target.value }))}
                            className="settings-input"
                            placeholder="Optional local device identifier"
                        />
                    </Field>
                </div>

                <div className="settings-toggle-row">
                    <CheckboxLabel checked={syncForm.enabled} onChange={(checked) => setSyncForm((s) => ({ ...s, enabled: checked }))}>
                        Enable sync
                    </CheckboxLabel>
                    <CheckboxLabel checked={syncForm.auto_sync} onChange={(checked) => setSyncForm((s) => ({ ...s, auto_sync: checked }))}>
                        Auto sync
                    </CheckboxLabel>
                    {!isWebdavProvider && (
                        <CheckboxLabel
                            checked={syncForm.force_path_style}
                            onChange={(checked) => setSyncForm((s) => ({ ...s, force_path_style: checked }))}
                        >
                            Force path-style
                        </CheckboxLabel>
                    )}
                    <label className="settings-inline-number">
                        Interval (min)
                        <input
                            type="number"
                            min={5}
                            max={1440}
                            value={syncForm.auto_sync_interval_minutes}
                            onChange={(e) => setSyncForm((s) => ({ ...s, auto_sync_interval_minutes: Number(e.target.value || 60) }))}
                            className="settings-input settings-input--compact"
                        />
                    </label>
                </div>

                <Field label="Passphrase (local only)">
                    <input
                        type="password"
                        value={passphrase}
                        onChange={(e) => setPassphrase(e.target.value)}
                        className="settings-input"
                        placeholder="At least 8 characters"
                    />
                </Field>

                <div className="settings-actions-row">
                    <ActionButton onClick={handleSaveSync} busy={updateSync.isPending} icon={<Cloud size={14} />}>
                        Save sync settings
                    </ActionButton>
                    <ActionButton onClick={handleUnlock} busy={unlockSync.isPending} icon={<Unlock size={14} />}>
                        Unlock key
                    </ActionButton>
                    <ActionButton onClick={handleLock} busy={lockSync.isPending} icon={<Lock size={14} />}>
                        Lock key
                    </ActionButton>
                    <ActionButton onClick={handleRunSync} busy={runSync.isPending} icon={<Upload size={14} />}>
                        Sync now
                    </ActionButton>
                </div>

                {syncMessage && <InlineMessage danger={isDangerMessage(syncMessage)}>{syncMessage}</InlineMessage>}
            </Panel>
        </SectionBlock>
    )
}
