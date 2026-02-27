export interface LlmRuntimeIssue {
    message: string
    provider: string
    model: string
    apiBaseUrl: string
    source: 'gate' | 'sample_error' | 'runtime_error'
}

function text(value: unknown): string {
    return String(value || '').trim()
}

const CONNECTIVITY_FAILURE_PATTERN =
    /(preflight failed|all connection attempts failed|connection refused|connect timeout|timed out|network is unreachable|failed to establish|service unavailable)/i

function toModelNames(payload: unknown): Set<string> {
    const out = new Set<string>()
    if (!payload || typeof payload !== 'object') return out
    const models = (payload as any).models
    if (!Array.isArray(models)) return out
    for (const item of models) {
        if (!item || typeof item !== 'object') continue
        const name = text((item as any).name).toLowerCase()
        if (name) out.add(name)
    }
    return out
}

function ollamaModelAvailable(requestedModel: string, available: Set<string>): boolean {
    const requested = text(requestedModel).toLowerCase()
    if (!requested) return available.size > 0
    if (available.has(requested)) return true
    const requestedBase = requested.split(':', 1)[0]
    if (!requestedBase) return false
    for (const modelName of available) {
        if (String(modelName).split(':', 1)[0] === requestedBase) {
            return true
        }
    }
    return false
}

export function issueFingerprint(issue: LlmRuntimeIssue): string {
    return [
        issue.source,
        issue.provider.toLowerCase(),
        issue.model.toLowerCase(),
        issue.apiBaseUrl.toLowerCase(),
        issue.message.slice(0, 220).toLowerCase(),
    ].join('|')
}

export function detectLlmRuntimeIssue(backgroundStatus: any): LlmRuntimeIssue | null {
    const analysis = backgroundStatus?.runtime?.analysis || {}
    const gate = analysis?.llm_gate || {}
    const runtime = gate?.runtime || {}

    const provider = text(runtime?.provider || analysis?.llm_provider).toLowerCase()
    const model = text(runtime?.model || analysis?.llm_model)
    const apiBaseUrl = text(runtime?.api_base_url)

    const gateReason = text(gate?.reason || analysis?.llm_block_reason)
    const gateRequired = Boolean(gate?.required ?? analysis?.llm_required ?? true)
    const analysisAllowed = Boolean(gate?.analysis_allowed ?? true)

    if (gateRequired && !analysisAllowed && gateReason) {
        return {
            source: 'gate',
            provider,
            model,
            apiBaseUrl,
            message: gateReason,
        }
    }

    const runtimeError = text(analysis?.last_error || backgroundStatus?.runtime?.analysis_worker?.last_error)
    if (runtimeError && CONNECTIVITY_FAILURE_PATTERN.test(runtimeError)) {
        return {
            source: 'runtime_error',
            provider,
            model,
            apiBaseUrl,
            message: runtimeError,
        }
    }

    const sampleErrors = Array.isArray(backgroundStatus?.scheduler?.last_analysis_stats?.sample_errors)
        ? backgroundStatus.scheduler.last_analysis_stats.sample_errors
        : []

    const sampleError = sampleErrors.find((err: unknown) => CONNECTIVITY_FAILURE_PATTERN.test(text(err)))
    if (sampleError) {
        return {
            source: 'sample_error',
            provider,
            model,
            apiBaseUrl,
            message: text(sampleError),
        }
    }

    return null
}

async function ollamaIssueStillActive(issue: LlmRuntimeIssue): Promise<boolean> {
    const base = text(issue.apiBaseUrl || 'http://127.0.0.1:11434').replace(/\/+$/, '')
    if (!/^https?:\/\//i.test(base)) return true

    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 1500)
    try {
        const res = await fetch(`${base}/api/tags`, {
            method: 'GET',
            signal: controller.signal,
        })
        if (!res.ok) return true
        const payload = await res.json()
        const available = toModelNames(payload)
        if (available.size === 0) return true
        if (!ollamaModelAvailable(issue.model, available)) return true
        return false
    } catch {
        return true
    } finally {
        window.clearTimeout(timeout)
    }
}

export async function confirmIssueStillActive(issue: LlmRuntimeIssue): Promise<boolean> {
    if (!issue) return false
    if (issue.source === 'gate') return true

    const provider = text(issue.provider).toLowerCase()
    const message = text(issue.message).toLowerCase()
    const looksLikeOllama = provider === 'ollama' || message.includes('ollama')
    if (looksLikeOllama) {
        return ollamaIssueStillActive(issue)
    }
    return true
}
