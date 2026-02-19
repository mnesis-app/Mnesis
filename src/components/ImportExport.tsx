import { useState, useRef } from 'react'
import { api } from '../lib/api'
import { Upload, Check, AlertCircle, Loader2, FileText, Download } from 'lucide-react'

export function ImportExport() {
    const [preview, setPreview] = useState<any>(null)
    const [uploading, setUploading] = useState(false)
    const [importing, setImporting] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [status, setStatus] = useState<string | null>(null)
    const fileInputRef = useRef<HTMLInputElement>(null)
    const [source, setSource] = useState('claude')

    const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0]
        if (!file) return

        setUploading(true)
        setError(null)
        setPreview(null)

        const formData = new FormData()
        formData.append('file', file)
        formData.append('source', source)

        try {
            const res = await api.import.upload(formData)
            setPreview(res)
        } catch (err: any) {
            setError(err.response?.data?.detail || "Upload failed")
        } finally {
            setUploading(false)
        }
    }

    const handleConfirm = async () => {
        if (!preview?.preview_id) return
        setImporting(true)
        try {
            const res = await api.import.confirm(preview.preview_id)
            setStatus(`Import started for ${res.count} memories.`)
            setPreview(null)
        } catch (err: any) {
            setError("Import confirmation failed")
        } finally {
            setImporting(false)
        }
    }

    return (
        <div className="flex-1 p-8 bg-[#09090b] text-zinc-100 overflow-auto">
            <h1 className="text-2xl font-bold mb-6">Import & Export</h1>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                {/* Import Section */}
                <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl p-6">
                    <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                        <Upload size={20} className="text-zinc-100" />
                        Import Data
                    </h2>

                    <div className="space-y-4">
                        <div>
                            <label className="block text-sm text-zinc-400 mb-2">Source</label>
                            <select
                                value={source}
                                onChange={(e) => setSource(e.target.value)}
                                className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-sm focus:outline-none focus:border-zinc-700"
                            >
                                <option value="claude">Claude Export (JSON)</option>
                                <option value="chatgpt">ChatGPT Export (JSON)</option>
                                <option value="gemini">Gemini Export (ZIP)</option>
                                <option value="mnesis-backup">Mnesis Backup (JSON)</option>
                            </select>
                        </div>

                        <div
                            className="border-2 border-dashed border-zinc-800 hover:border-zinc-600 rounded-xl p-8 flex flex-col items-center justify-center cursor-pointer transition-colors bg-zinc-950/30"
                            onClick={() => fileInputRef.current?.click()}
                        >
                            <input
                                type="file"
                                ref={fileInputRef}
                                className="hidden"
                                accept={source === 'gemini' ? '.zip' : '.json'}
                                onChange={handleFileChange}
                            />
                            {uploading ? (
                                <Loader2 className="animate-spin text-zinc-500" size={32} />
                            ) : (
                                <Upload className="text-zinc-500 mb-2" size={32} />
                            )}
                            <p className="text-sm text-zinc-400 text-center">
                                {uploading ? "Analyzing..." : "Click to select file"}
                            </p>
                            <p className="text-xs text-zinc-600 mt-1">
                                {source === 'gemini' ? 'ZIP archives only' : 'JSON files (conversations or memories)'}
                            </p>
                        </div>

                        {error && (
                            <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-lg flex items-center gap-2 text-sm text-red-400">
                                <AlertCircle size={16} />
                                {error}
                            </div>
                        )}

                        {status && (
                            <div className="p-3 bg-emerald-500/10 border border-emerald-500/20 rounded-lg flex items-center gap-2 text-sm text-emerald-400">
                                <Check size={16} />
                                {status}
                            </div>
                        )}

                        {preview && (
                            <div className="mt-4 space-y-4 animate-in fade-in slide-in-from-top-4">
                                <div className="p-4 bg-zinc-950 rounded-lg border border-zinc-800">
                                    <h3 className="text-sm font-medium mb-2 text-zinc-300">Preview Analysis</h3>
                                    <div className="grid grid-cols-2 gap-4 text-xs">
                                        <div>
                                            <span className="text-zinc-500">Memories:</span>
                                            <span className="ml-2 text-zinc-200">{preview.total_memories || preview.total_found || 0}</span>
                                        </div>
                                        <div>
                                            <span className="text-zinc-500">Conversations:</span>
                                            <span className="ml-2 text-zinc-200">{preview.total_conversations || 0}</span>
                                        </div>
                                        <div>
                                            <span className="text-zinc-500">Categories:</span>
                                            <span className="ml-2 text-zinc-200">{Object.keys(preview.categories || {}).length}</span>
                                        </div>
                                    </div>

                                    <div className="mt-4 space-y-2">
                                        <p className="text-xs text-zinc-500 uppercase tracking-wider font-semibold">Samples</p>
                                        {preview.samples.map((s: any, i: number) => (
                                            <div key={i} className="text-xs text-zinc-400 truncate bg-zinc-900 p-1.5 rounded border border-zinc-800/50">
                                                {s.content}
                                            </div>
                                        ))}
                                    </div>
                                </div>

                                <button
                                    onClick={handleConfirm}
                                    disabled={importing}
                                    className="w-full py-2.5 bg-zinc-100 hover:bg-white text-zinc-950 rounded-lg text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 shadow-lg shadow-zinc-950/20"
                                >
                                    {importing && <Loader2 className="animate-spin" size={16} />}
                                    Confirm Import
                                </button>
                            </div>
                        )}
                    </div>
                </div>

                {/* Export Section */}
                <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl p-6">
                    <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                        <Download size={20} className="text-emerald-400" />
                        Export Data
                    </h2>
                    <p className="text-sm text-zinc-400 mb-6">
                        Download a full copy of your memory database in JSON format.
                        Includes all memories, conversations, and metadata.
                    </p>
                    <button
                        className="w-full py-2.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-100 rounded-lg text-sm font-medium transition-colors border border-zinc-700 flex items-center justify-center gap-2"
                        onClick={() => window.location.href = 'http://localhost:7860/api/v1/import/export'}
                    >
                        <FileText size={16} />
                        Download Full Backup (JSON)
                    </button>
                    {/* TODO: Implement GET /api/v1/export endpoint */}
                </div>
            </div>
        </div>
    )
}
