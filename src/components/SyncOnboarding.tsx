import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { Loader2, Check, X } from 'lucide-react'

type Provider = 's3' | 'r2' | 'webdav'
type Step = 1 | 2 | 3

const PROVIDERS: { id: Provider; label: string; description: string }[] = [
    { id: 's3', label: 'Amazon S3', description: 'Any S3-compatible storage (AWS, MinIO…)' },
    { id: 'r2', label: 'Cloudflare R2', description: 'Zero egress fees, global edge' },
    { id: 'webdav', label: 'WebDAV', description: 'Nextcloud, ownCloud, generic WebDAV' },
]

const LABEL: React.CSSProperties = {
    fontSize: '9px', fontWeight: 800, letterSpacing: '0.22em',
    textTransform: 'uppercase', color: '#444', display: 'block', marginBottom: '6px',
}

const INPUT: React.CSSProperties = {
    width: '100%', background: '#080808', border: '1px solid #1a1a1a',
    borderRadius: '4px', padding: '8px 10px', fontSize: '12px',
    color: '#d0d0d0', outline: 'none', fontFamily: 'inherit',
    marginBottom: '10px', boxSizing: 'border-box',
}

const SECTION: React.CSSProperties = { marginBottom: '14px' }

function Field({ label, type = 'text', value, onChange, placeholder }: {
    label: string; type?: string; value: string;
    onChange: (v: string) => void; placeholder?: string;
}) {
    return (
        <div style={SECTION}>
            <label style={LABEL}>{label}</label>
            <input
                type={type}
                value={value}
                onChange={e => onChange(e.target.value)}
                placeholder={placeholder}
                autoComplete="off"
                style={INPUT}
            />
        </div>
    )
}

export function SyncOnboarding({ onClose }: { onClose: () => void }) {
    const qc = useQueryClient()
    const [step, setStep] = useState<Step>(1)
    const [provider, setProvider] = useState<Provider | null>(null)
    const [testError, setTestError] = useState<string | null>(null)
    const [testOk, setTestOk] = useState(false)

    // S3/R2 fields
    const [endpoint, setEndpoint] = useState('')
    const [bucket, setBucket] = useState('')
    const [region, setRegion] = useState('')
    const [accessKey, setAccessKey] = useState('')
    const [secretKey, setSecretKey] = useState('')

    // WebDAV fields
    const [webdavUrl, setWebdavUrl] = useState('')
    const [webdavUser, setWebdavUser] = useState('')
    const [webdavPass, setWebdavPass] = useState('')

    const testMutation = useMutation({
        mutationFn: () => api.admin.syncTest(
            provider === 'webdav'
                ? { provider: 'webdav', webdav_url: webdavUrl, webdav_username: webdavUser || undefined, webdav_password: webdavPass || undefined }
                : {
                    provider: provider!,
                    endpoint_url: endpoint || undefined,
                    bucket: bucket || undefined,
                    region: region || undefined,
                    access_key_id: accessKey || undefined,
                    secret_access_key: secretKey || undefined,
                }
        ),
        onSuccess: () => { setTestOk(true); setTestError(null) },
        onError: (e: Error) => { setTestError(e.message); setTestOk(false) },
    })

    const saveMutation = useMutation({
        mutationFn: () => api.admin.updateSyncConfig(
            provider === 'webdav'
                ? { enabled: true, provider: 'webdav', webdav_url: webdavUrl, webdav_username: webdavUser || undefined, webdav_password: webdavPass || undefined }
                : {
                    enabled: true,
                    provider: provider!,
                    endpoint_url: endpoint || undefined,
                    bucket: bucket || undefined,
                    region: region || 'us-east-1',
                    access_key_id: accessKey || undefined,
                    secret_access_key: secretKey || undefined,
                }
        ),
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['sync_status_banner'] })
            qc.invalidateQueries({ queryKey: ['config'] })
            onClose()
        },
    })

    const canAdvanceStep2 = provider === 'webdav' ? !!webdavUrl : !!bucket

    return (
        /* Backdrop */
        <div
            style={{
                position: 'fixed', inset: 0, zIndex: 1000,
                background: 'rgba(0,0,0,0.7)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
            onClick={e => { if (e.target === e.currentTarget) onClose() }}
        >
            <div style={{
                width: '480px', background: '#080808',
                border: '1px solid #1f1f1f', borderRadius: '8px',
                padding: '28px 28px 24px',
                animation: 'sync-modal-in 220ms ease',
            }}>
                <style>{`
                    @keyframes sync-modal-in {
                        from { opacity: 0; transform: translateY(8px); }
                        to   { opacity: 1; transform: translateY(0); }
                    }
                `}</style>

                {/* Header */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '24px' }}>
                    <div>
                        <p style={{ fontSize: '9px', fontWeight: 800, letterSpacing: '0.2em', textTransform: 'uppercase', color: '#444', margin: 0, marginBottom: '4px' }}>
                            Step {step} / 3
                        </p>
                        <h2 style={{ fontSize: '18px', fontWeight: 800, color: '#f5f3ee', letterSpacing: '-0.02em', margin: 0 }}>
                            {step === 1 && 'Choose a provider'}
                            {step === 2 && 'Configure credentials'}
                            {step === 3 && 'Test & activate'}
                        </h2>
                    </div>
                    <button
                        onClick={onClose}
                        style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#333', display: 'flex', padding: '4px' }}
                        onMouseEnter={e => (e.currentTarget.style.color = '#888')}
                        onMouseLeave={e => (e.currentTarget.style.color = '#333')}
                    >
                        <X size={16} />
                    </button>
                </div>

                {/* Step 1 — Pick provider */}
                {step === 1 && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                        {PROVIDERS.map(p => (
                            <button
                                key={p.id}
                                onClick={() => setProvider(p.id)}
                                style={{
                                    display: 'flex', flexDirection: 'column', alignItems: 'flex-start',
                                    padding: '14px 16px', background: provider === p.id ? '#111' : '#090909',
                                    border: `1px solid ${provider === p.id ? '#2f2f2f' : '#1a1a1a'}`,
                                    borderRadius: '4px', cursor: 'pointer', fontFamily: 'inherit',
                                    textAlign: 'left', transition: 'all 150ms ease',
                                }}
                                onMouseEnter={e => { if (provider !== p.id) e.currentTarget.style.borderColor = '#252525' }}
                                onMouseLeave={e => { if (provider !== p.id) e.currentTarget.style.borderColor = '#1a1a1a' }}
                            >
                                <span style={{ fontSize: '12px', fontWeight: 700, color: '#d0d0d0', marginBottom: '3px' }}>{p.label}</span>
                                <span style={{ fontSize: '11px', color: '#555' }}>{p.description}</span>
                            </button>
                        ))}
                        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '8px' }}>
                            <PrimaryButton onClick={() => provider && setStep(2)} disabled={!provider}>
                                Continue →
                            </PrimaryButton>
                        </div>
                    </div>
                )}

                {/* Step 2 — Configure */}
                {step === 2 && (
                    <div>
                        {(provider === 's3' || provider === 'r2') && (
                            <>
                                {provider === 'r2' && (
                                    <Field label="Endpoint URL (account.r2.cloudflarestorage.com)" value={endpoint} onChange={setEndpoint} placeholder="https://…r2.cloudflarestorage.com" />
                                )}
                                {provider === 's3' && (
                                    <Field label="Region" value={region} onChange={setRegion} placeholder="us-east-1" />
                                )}
                                <Field label="Bucket" value={bucket} onChange={setBucket} placeholder="my-mnesis-backup" />
                                <Field label="Access Key ID" value={accessKey} onChange={setAccessKey} />
                                <Field label="Secret Access Key" type="password" value={secretKey} onChange={setSecretKey} />
                            </>
                        )}
                        {provider === 'webdav' && (
                            <>
                                <Field label="WebDAV URL" value={webdavUrl} onChange={setWebdavUrl} placeholder="https://cloud.example.com/remote.php/dav/files/user" />
                                <Field label="Username" value={webdavUser} onChange={setWebdavUser} />
                                <Field label="Password" type="password" value={webdavPass} onChange={setWebdavPass} />
                            </>
                        )}
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '4px' }}>
                            <GhostButton onClick={() => setStep(1)}>← Back</GhostButton>
                            <PrimaryButton onClick={() => setStep(3)} disabled={!canAdvanceStep2}>
                                Continue →
                            </PrimaryButton>
                        </div>
                    </div>
                )}

                {/* Step 3 — Test + activate */}
                {step === 3 && (
                    <div>
                        <p style={{ fontSize: '12px', color: '#666', marginBottom: '20px', lineHeight: 1.6 }}>
                            Credentials are not saved until activation. Click Test to verify the connection first.
                        </p>

                        {testError && (
                            <div style={{
                                padding: '10px 12px', background: '#140909', border: '1px solid #3a1515',
                                borderRadius: '4px', marginBottom: '14px',
                                fontSize: '12px', color: '#f87171', lineHeight: 1.5,
                            }}>
                                {testError}
                            </div>
                        )}

                        {testOk && (
                            <div style={{
                                display: 'flex', alignItems: 'center', gap: '8px',
                                padding: '10px 12px', background: '#0a1f16', border: '1px solid #1f3a2f',
                                borderRadius: '4px', marginBottom: '14px',
                                fontSize: '12px', color: '#34d399',
                            }}>
                                <Check size={13} /> Connection successful
                            </div>
                        )}

                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px' }}>
                            <GhostButton onClick={() => setStep(2)}>← Back</GhostButton>
                            <div style={{ display: 'flex', gap: '8px' }}>
                                <GhostButton
                                    onClick={() => testMutation.mutate()}
                                    disabled={testMutation.isPending}
                                >
                                    {testMutation.isPending ? <Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} /> : null}
                                    Test connection
                                </GhostButton>
                                <PrimaryButton
                                    onClick={() => saveMutation.mutate()}
                                    disabled={saveMutation.isPending || !testOk}
                                >
                                    {saveMutation.isPending ? <Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} /> : null}
                                    Enable sync ✓
                                </PrimaryButton>
                            </div>
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}

function PrimaryButton({ onClick, disabled, children }: {
    onClick: () => void; disabled?: boolean; children: React.ReactNode;
}) {
    return (
        <button
            onClick={onClick}
            disabled={disabled}
            style={{
                display: 'inline-flex', alignItems: 'center', gap: '6px',
                padding: '8px 18px', background: disabled ? '#111' : '#f5f3ee',
                border: 'none', borderRadius: '4px', cursor: disabled ? 'not-allowed' : 'pointer',
                fontSize: '10px', fontWeight: 800, letterSpacing: '0.12em',
                textTransform: 'uppercase', color: disabled ? '#333' : '#0a0a0a',
                fontFamily: 'inherit', transition: 'all 150ms ease',
            }}
        >
            {children}
        </button>
    )
}

function GhostButton({ onClick, disabled, children }: {
    onClick: () => void; disabled?: boolean; children: React.ReactNode;
}) {
    return (
        <button
            onClick={onClick}
            disabled={disabled}
            style={{
                display: 'inline-flex', alignItems: 'center', gap: '6px',
                padding: '8px 14px', background: 'transparent',
                border: '1px solid #1f1f1f', borderRadius: '4px',
                cursor: disabled ? 'not-allowed' : 'pointer',
                fontSize: '10px', fontWeight: 600, letterSpacing: '0.08em',
                textTransform: 'uppercase', color: '#555', fontFamily: 'inherit',
                transition: 'all 150ms ease',
            }}
            onMouseEnter={e => { if (!disabled) e.currentTarget.style.color = '#d0d0d0' }}
            onMouseLeave={e => { if (!disabled) e.currentTarget.style.color = '#555' }}
        >
            {children}
        </button>
    )
}
