import { useState, useRef } from 'react'
import { api } from '../lib/api'
import { Upload, Check, AlertCircle, Loader2, FileText, Download } from 'lucide-react'
import './ImportExport.css'

type ImportPreview = {
    preview_id: string
    total_memories?: number
    total_conversations?: number
    categories?: Record<string, number>
    samples?: Array<{
        content?: string
        source?: string
        original_category?: string
        original_level?: string
        category?: string
        level?: string
    }>
    status: string
    detected_memories?: number
    ignored?: number
}

type ImportReport = {
    imported: number
    deduplicated: number
    ignored: number
    detected_conversations?: number
    detected_messages?: number
    imported_conversations?: number
    imported_messages?: number
    deduplicated_conversations?: number
    deduplicated_messages?: number
    skipped_conversations?: number
    skipped_messages?: number
}

export function ImportExport() {
    const [preview, setPreview] = useState<ImportPreview | null>(null)
    const [uploading, setUploading] = useState(false)
    const [importing, setImporting] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [status, setStatus] = useState<string | null>(null)
    const [report, setReport] = useState<ImportReport | null>(null)
    const [dragActive, setDragActive] = useState(false)
    const [source, setSource] = useState('chatgpt')
    const fileInputRef = useRef<HTMLInputElement>(null)

    const runPreview = async (file: File) => {
        setUploading(true)
        setError(null)
        setStatus(null)
        setPreview(null)
        setReport(null)

        try {
            if (source === 'chatgpt') {
                const res = await api.import.chatgptPreview(file)
                setPreview(res)
            } else {
                const formData = new FormData()
                formData.append('file', file)
                formData.append('source', source)
                const res = await api.import.upload(formData)
                setPreview(res)
            }
        } catch (err: any) {
            setError(err?.message || 'Upload failed')
        } finally {
            setUploading(false)
        }
    }

    const onDropFile = async (e: React.DragEvent<HTMLDivElement>) => {
        e.preventDefault()
        setDragActive(false)
        const file = e.dataTransfer.files?.[0]
        if (!file) return
        await runPreview(file)
    }

    const onInputChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0]
        if (!file) return
        await runPreview(file)
    }

    const handleConfirm = async () => {
        if (!preview?.preview_id) return
        setImporting(true)
        setError(null)
        try {
            if (source === 'chatgpt') {
                const res = await api.import.chatgptConfirm(preview.preview_id)
                setReport({
                    imported: res.imported ?? 0,
                    deduplicated: res.deduplicated ?? 0,
                    ignored: res.ignored ?? 0,
                    detected_conversations: res.detected_conversations ?? 0,
                    detected_messages: res.detected_messages ?? 0,
                    imported_conversations: res.imported_conversations ?? 0,
                    imported_messages: res.imported_messages ?? 0,
                    deduplicated_conversations: res.deduplicated_conversations ?? 0,
                    deduplicated_messages: res.deduplicated_messages ?? 0,
                    skipped_conversations: res.skipped_conversations ?? 0,
                    skipped_messages: res.skipped_messages ?? 0,
                })
                setStatus('Import completed.')
            } else {
                const res = await api.import.confirm(preview.preview_id)
                setStatus(`Import started for ${res.count} items.`)
            }
            setPreview(null)
        } catch (err: any) {
            setError(err?.message || 'Import confirmation failed')
        } finally {
            setImporting(false)
        }
    }

    const memoryCount = preview?.detected_memories ?? preview?.total_memories ?? 0
    const conversationsCount = preview?.total_conversations ?? 0

    return (
        <div className="ie-page">

            {/* ──── IMPORT SECTION ──── */}
            <section className="ie-section">
                <div className="ie-section-head">
                    <h2>Import</h2>
                    <p>Select a source, drop your export file, and review before confirming.</p>
                    <div className="ie-source-tags">
                        {['ChatGPT', 'Claude', 'Gemini', 'Mnesis Backup'].map((s) => (
                            <span key={s} className="ie-source-tag">{s}</span>
                        ))}
                    </div>
                </div>

                <div className="ie-panel">
                    {/* Source */}
                    <div className="ie-source-row">
                        <span className="ie-field-label">Source</span>
                        <select
                            className="ie-select"
                            value={source}
                            onChange={(e) => {
                                setSource(e.target.value)
                                setPreview(null)
                                setStatus(null)
                                setReport(null)
                                setError(null)
                            }}
                        >
                            <option value="chatgpt">ChatGPT Export (Memories + Conversations)</option>
                            <option value="claude">Claude Export (JSON)</option>
                            <option value="gemini">Gemini Export (ZIP)</option>
                            <option value="mnesis-backup">Mnesis Backup (JSON)</option>
                        </select>
                    </div>

                    {/* Drop zone */}
                    <div
                        className={`ie-dropzone${dragActive ? ' ie-dropzone--active' : ''}`}
                        onClick={() => fileInputRef.current?.click()}
                        onDragOver={(e) => { e.preventDefault(); setDragActive(true) }}
                        onDragLeave={() => setDragActive(false)}
                        onDrop={onDropFile}
                    >
                        <input
                            type="file"
                            ref={fileInputRef}
                            style={{ display: 'none' }}
                            accept={source === 'gemini' ? '.zip' : '.json'}
                            onChange={onInputChange}
                        />
                        {uploading
                            ? <Loader2 size={20} className="ie-spinner ie-dropzone-icon" />
                            : <Upload size={20} className="ie-dropzone-icon" />
                        }
                        <p className="ie-dropzone-label">
                            {uploading ? 'Analyzing…' : 'Drop file here or click to select'}
                        </p>
                        <p className="ie-dropzone-hint">
                            {source === 'gemini' ? 'ZIP archives only' : 'JSON files'}
                        </p>
                    </div>

                    {/* Error */}
                    {error && (
                        <div className="ie-message ie-message--error">
                            <AlertCircle size={14} style={{ flexShrink: 0, marginTop: 1 }} />
                            {error}
                        </div>
                    )}

                    {/* Success */}
                    {status && (
                        <div className="ie-message ie-message--success">
                            <Check size={14} style={{ flexShrink: 0, marginTop: 1 }} />
                            {status}
                        </div>
                    )}

                    {/* Import report */}
                    {report && (
                        <>
                            <div className="ie-stat-label" style={{ marginBottom: 8 }}>Import report</div>
                            <div className="ie-stats-grid" style={{ marginBottom: 0 }}>
                                <div className="ie-stat-cell">
                                    <div className="ie-stat-label">Memories</div>
                                    <div className="ie-stat-value">{report.imported}</div>
                                </div>
                                <div className="ie-stat-cell">
                                    <div className="ie-stat-label">Deduplicated</div>
                                    <div className="ie-stat-value">{report.deduplicated}</div>
                                </div>
                                <div className="ie-stat-cell">
                                    <div className="ie-stat-label">Ignored</div>
                                    <div className="ie-stat-value">{report.ignored}</div>
                                </div>
                                {typeof report.imported_conversations === 'number' && (
                                    <div className="ie-stat-cell">
                                        <div className="ie-stat-label">Imported convos</div>
                                        <div className="ie-stat-value">{report.imported_conversations}</div>
                                    </div>
                                )}
                                {typeof report.imported_messages === 'number' && (
                                    <div className="ie-stat-cell">
                                        <div className="ie-stat-label">Imported msgs</div>
                                        <div className="ie-stat-value">{report.imported_messages}</div>
                                    </div>
                                )}
                                {typeof report.detected_conversations === 'number' && (
                                    <div className="ie-stat-cell">
                                        <div className="ie-stat-label">Detected convos</div>
                                        <div className="ie-stat-value">{report.detected_conversations}</div>
                                    </div>
                                )}
                                {typeof report.detected_messages === 'number' && (
                                    <div className="ie-stat-cell">
                                        <div className="ie-stat-label">Detected msgs</div>
                                        <div className="ie-stat-value">{report.detected_messages}</div>
                                    </div>
                                )}
                                {typeof report.deduplicated_conversations === 'number' && (
                                    <div className="ie-stat-cell">
                                        <div className="ie-stat-label">Dedup. convos</div>
                                        <div className="ie-stat-value">{report.deduplicated_conversations}</div>
                                    </div>
                                )}
                                {typeof report.deduplicated_messages === 'number' && (
                                    <div className="ie-stat-cell">
                                        <div className="ie-stat-label">Dedup. msgs</div>
                                        <div className="ie-stat-value">{report.deduplicated_messages}</div>
                                    </div>
                                )}
                                {typeof report.skipped_conversations === 'number' && (
                                    <div className="ie-stat-cell">
                                        <div className="ie-stat-label">Skipped convos</div>
                                        <div className="ie-stat-value">{report.skipped_conversations}</div>
                                    </div>
                                )}
                                {typeof report.skipped_messages === 'number' && (
                                    <div className="ie-stat-cell">
                                        <div className="ie-stat-label">Skipped msgs</div>
                                        <div className="ie-stat-value">{report.skipped_messages}</div>
                                    </div>
                                )}
                            </div>
                        </>
                    )}

                    {/* Preview */}
                    {preview && (
                        <>
                            {/* Stats */}
                            <div className="ie-stats-grid">
                                <div className="ie-stat-cell">
                                    <div className="ie-stat-label">Memories</div>
                                    <div className="ie-stat-value">{memoryCount}</div>
                                </div>
                                <div className="ie-stat-cell">
                                    <div className="ie-stat-label">Conversations</div>
                                    <div className="ie-stat-value">{conversationsCount}</div>
                                </div>
                                <div className="ie-stat-cell">
                                    <div className="ie-stat-label">Ignored</div>
                                    <div className="ie-stat-value">{preview.ignored ?? 0}</div>
                                </div>
                                <div className="ie-stat-cell">
                                    <div className="ie-stat-label">Categories</div>
                                    <div className="ie-stat-value">{Object.keys(preview.categories || {}).length}</div>
                                </div>
                            </div>

                            {/* Samples */}
                            {(preview.samples || []).length > 0 && (
                                <>
                                    <p className="ie-samples-label">Samples</p>
                                    <div className="ie-samples-list">
                                        {(preview.samples || []).slice(0, 5).map((s, i) => (
                                            <div key={i} className="ie-sample-card">
                                                <p className="ie-sample-content">
                                                    {s.content || 'No content preview'}
                                                </p>
                                                <div className="ie-sample-tags">
                                                    <span>{s.source || source}</span>
                                                    <span>{s.category || s.original_category || 'unknown'}</span>
                                                    <span>{s.level || s.original_level || 'semantic'}</span>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </>
                            )}

                            {/* Confirm */}
                            <div className="ie-action-row">
                                <button
                                    className="ie-btn"
                                    onClick={handleConfirm}
                                    disabled={importing}
                                >
                                    {importing
                                        ? <Loader2 size={13} className="ie-spinner" />
                                        : <Check size={13} />
                                    }
                                    Confirm Import
                                </button>
                            </div>
                        </>
                    )}
                </div>
            </section>

            {/* ──── EXPORT SECTION ──── */}
            <section className="ie-section">
                <div className="ie-section-head">
                    <h2>Export</h2>
                    <p>Download a full JSON backup of your memory graph.</p>
                </div>

                <div className="ie-panel">
                    <div className="ie-export-row">
                        <FileText size={16} className="ie-export-icon" />
                        <div className="ie-export-info">
                            <p className="ie-export-title">Download Full Backup (JSON)</p>
                            <p className="ie-export-desc">Includes all memories, conversations, and metadata.</p>
                        </div>
                        <button
                            className="ie-btn"
                            onClick={() => { window.location.href = api.import.exportUrl() }}
                        >
                            <Download size={13} />
                            Download
                        </button>
                    </div>
                </div>
            </section>
        </div>
    )
}
