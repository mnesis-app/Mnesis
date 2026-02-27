import { useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import { MnesisWordmark } from './Logo'
import './FirstSetup.css'

type SetupHealth = {
    model_ready?: boolean
    model_status?: string
    download_percent?: number
    download_file?: string
}

type StepState = 'idle' | 'active' | 'done' | 'error'

export function FirstSetup({ onReady }: { onReady: () => void }) {
    const [status, setStatus] = useState<SetupHealth | null>(null)
    const [retrying, setRetrying] = useState(false)

    useEffect(() => {
        const check = async () => {
            try {
                const res = await api.health()
                setStatus(res)
                setRetrying(false)
                if (res.model_ready) onReady()
            } catch {
                setRetrying(true)
            }
        }
        const interval = setInterval(check, 1200)
        check()
        return () => clearInterval(interval)
    }, [onReady])

    const modelStatus = String(status?.model_status || (retrying ? 'connecting' : 'checking')).toLowerCase()
    const downloadPercentRaw = Number(status?.download_percent)
    const hasProgress = Number.isFinite(downloadPercentRaw)
    const progress = hasProgress ? Math.max(0, Math.min(100, Math.round(downloadPercentRaw))) : null

    const downloadFile = (() => {
        const raw = String(status?.download_file || '').trim()
        if (!raw) return ''
        const slash = raw.lastIndexOf('/')
        const backslash = raw.lastIndexOf('\\')
        const idx = Math.max(slash, backslash)
        return idx >= 0 ? raw.slice(idx + 1) : raw
    })()

    const messageLine = (() => {
        if (modelStatus === 'downloading') return 'Downloading embedded model...'
        if (modelStatus === 'loading') return 'Loading model into memory...'
        if (modelStatus === 'ready') return 'Ready.'
        if (modelStatus === 'error') return 'Model setup failed.'
        if (retrying || modelStatus === 'connecting') return 'Connecting to backend...'
        return 'Preparing local memory...'
    })()

    const detailLine = (() => {
        if (modelStatus === 'downloading') {
            if (downloadFile) {
                return progress !== null ? `${downloadFile} — ${progress}%` : downloadFile
            }
            return progress !== null ? `${progress}%` : 'Preparing model files...'
        }
        if (modelStatus === 'loading') return 'Building inference runtime'
        if (modelStatus === 'ready') return 'Mnesis runs fully offline.'
        if (modelStatus === 'error') return 'Check backend logs for details.'
        if (retrying || modelStatus === 'connecting') return 'Retrying local backend connection...'
        return 'First run: downloading bge-small-en-v1.5'
    })()

    const connectState: StepState = retrying || modelStatus === 'connecting'
        ? 'active'
        : (status ? 'done' : 'active')
    const downloadState: StepState = modelStatus === 'error'
        ? 'error'
        : modelStatus === 'downloading'
            ? 'active'
            : (modelStatus === 'loading' || modelStatus === 'ready')
                ? 'done'
                : 'idle'
    const loadState: StepState = modelStatus === 'error'
        ? 'error'
        : modelStatus === 'loading'
            ? 'active'
            : modelStatus === 'ready'
                ? 'done'
                : 'idle'

    const dots = useMemo(
        () => [
            { id: 'connect',  label: 'Service', state: connectState },
            { id: 'download', label: modelStatus === 'downloading' && progress !== null ? `${progress}%` : 'Model', state: downloadState },
            { id: 'load',     label: 'Runtime', state: loadState },
        ],
        [connectState, downloadState, loadState, modelStatus, progress]
    )

    const stateClass = (() => {
        if (modelStatus === 'error') return 'first-setup-state-error'
        if (modelStatus === 'ready') return 'first-setup-state-ready'
        return ''
    })()

    return (
        <div className={`first-setup-shell ${stateClass}`}>
            <div className="first-setup-center">
                <div className="first-setup-wordmark">
                    <MnesisWordmark color="#f5f3ee" iconSize={48} textSize={52} gap={14} />
                </div>

                <p className="first-setup-message">{messageLine}</p>
                <p className="first-setup-detail">{detailLine}</p>

                <div className="first-setup-dots">
                    {dots.map((dot) => (
                        <div key={dot.id} className={`first-setup-dot-item first-setup-dot-item--${dot.state}`}>
                            <div className="first-setup-dot" />
                            <span className="first-setup-dot-label">{dot.label}</span>
                        </div>
                    ))}
                </div>
            </div>

            <div className="first-setup-progress-bar">
                {progress !== null ? (
                    <div className="first-setup-progress-fill" style={{ width: `${Math.max(progress, 2)}%` }} />
                ) : (
                    <div className="first-setup-progress-fill first-setup-progress-indeterminate" />
                )}
            </div>
        </div>
    )
}
