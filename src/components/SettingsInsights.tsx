import { Cloud, Wifi } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useInsightsConfig, useUpdateInsightsConfig } from '../lib/queries'
import { api } from '../lib/api'
import {
    ActionButton,
    CheckboxLabel,
    Field,
    InlineMessage,
    Panel,
    SectionBlock,
    isDangerMessage,
} from './SettingsShared'

const INSIGHTS_PROVIDER_OPTIONS = [
    { value: 'openai', label: 'OpenAI' },
    { value: 'anthropic', label: 'Anthropic' },
    { value: 'ollama', label: 'Ollama (Local)' },
]

function insightsProviderHelp(provider: string): string {
    if (provider === 'openai') return 'Uses OpenAI Chat Completions API.'
    if (provider === 'anthropic') return 'Uses Anthropic Messages API.'
    if (provider === 'ollama') return 'Uses local Ollama endpoint. No API key is required for localhost in most setups.'
    return 'Configure an insights model provider.'
}

function insightsModelPlaceholder(provider: string): string {
    if (provider === 'anthropic') return 'claude-3-5-haiku-latest'
    if (provider === 'ollama') return 'llama3.2:3b'
    return 'gpt-4o-mini'
}

function insightsBaseUrlPlaceholder(provider: string): string {
    if (provider === 'anthropic') return 'https://api.anthropic.com/v1'
    if (provider === 'ollama') return 'http://127.0.0.1:11434'
    return 'https://api.openai.com/v1'
}

export function SettingsInsights() {
    const { data: insightsConfigData } = useInsightsConfig()
    const updateInsightsConfig = useUpdateInsightsConfig()

    const [insightsMessage, setInsightsMessage] = useState<string | null>(null)
    const [insightsTestResult, setInsightsTestResult] = useState<string | null>(null)
    const [insightsTestBusy, setInsightsTestBusy] = useState(false)
    const [insightsForm, setInsightsForm] = useState({
        enabled: true,
        provider: 'openai',
        model: 'gpt-4o-mini',
        api_key: '',
        api_base_url: '',
    })

    useEffect(() => {
        if (!insightsConfigData?.insights) return
        const insights = insightsConfigData.insights
        setInsightsForm({
            enabled: !!insights.enabled,
            provider: insights.provider || 'openai',
            model: insights.model || 'gpt-4o-mini',
            api_key: insights.api_key || '',
            api_base_url: insights.api_base_url || '',
        })
    }, [insightsConfigData])

    const handleSaveInsights = async () => {
        setInsightsMessage(null)
        if (!insightsForm.model.trim()) {
            setInsightsMessage('Model is required for insights generation.')
            return
        }
        if (insightsForm.provider === 'ollama' && !insightsForm.api_base_url.trim()) {
            setInsightsMessage('Ollama base URL is required (ex: http://127.0.0.1:11434).')
            return
        }
        try {
            await updateInsightsConfig.mutateAsync(insightsForm)
            setInsightsMessage('Insights AI settings saved.')
        } catch (e: any) {
            setInsightsMessage(e?.message || 'Failed to save insights settings.')
        }
    }

    const handleTestInsights = async () => {
        setInsightsTestResult(null)
        setInsightsTestBusy(true)
        try {
            const res = await api.admin.insightsTest()
            setInsightsTestResult(`Connected (${res.latency_ms}ms) · ${res.provider} / ${res.model}`)
        } catch (e: any) {
            setInsightsTestResult(e?.message || 'Connection test failed.')
        } finally {
            setInsightsTestBusy(false)
        }
    }

    return (
        <SectionBlock
            title="Insights AI"
            description="Configure the model used to generate daily textual insights (max 1 generation/day, cached locally)."
        >
            <Panel>
                <div className="settings-fields-grid">
                    <Field label="Provider" helper={insightsProviderHelp(insightsForm.provider)}>
                        <select
                            value={insightsForm.provider}
                            onChange={(e) => {
                                const provider = e.target.value
                                setInsightsForm((s) => {
                                    const next = { ...s, provider }
                                    if (provider === 'ollama') {
                                        if (!next.model || next.model === 'gpt-4o-mini' || next.model === 'claude-3-5-haiku-latest') {
                                            next.model = 'llama3.2:3b'
                                        }
                                        if (!next.api_base_url || next.api_base_url.includes('openai.com') || next.api_base_url.includes('anthropic.com')) {
                                            next.api_base_url = 'http://127.0.0.1:11434'
                                        }
                                    } else if (provider === 'anthropic') {
                                        if (!next.model || next.model === 'gpt-4o-mini' || next.model === 'llama3.2:3b') {
                                            next.model = 'claude-3-5-haiku-latest'
                                        }
                                    } else if (provider === 'openai') {
                                        if (!next.model || next.model === 'claude-3-5-haiku-latest' || next.model === 'llama3.2:3b') {
                                            next.model = 'gpt-4o-mini'
                                        }
                                    }
                                    return next
                                })
                            }}
                            className="settings-input"
                        >
                            {INSIGHTS_PROVIDER_OPTIONS.map((opt) => (
                                <option key={opt.value} value={opt.value}>{opt.label}</option>
                            ))}
                        </select>
                    </Field>

                    <Field label="Model">
                        <input
                            value={insightsForm.model}
                            onChange={(e) => setInsightsForm((s) => ({ ...s, model: e.target.value }))}
                            className="settings-input"
                            placeholder={insightsModelPlaceholder(insightsForm.provider)}
                        />
                    </Field>

                    <Field label={insightsForm.provider === 'ollama' ? 'API Key (optional)' : 'API Key'}>
                        <input
                            type="password"
                            value={insightsForm.api_key}
                            onChange={(e) => setInsightsForm((s) => ({ ...s, api_key: e.target.value }))}
                            className="settings-input"
                            placeholder={insightsForm.provider === 'ollama' ? 'Optional (proxy auth)' : 'sk-... / ant-...'}
                        />
                    </Field>

                    <Field label={insightsForm.provider === 'ollama' ? 'Ollama Base URL' : 'API Base URL (optional)'}>
                        <input
                            value={insightsForm.api_base_url}
                            onChange={(e) => setInsightsForm((s) => ({ ...s, api_base_url: e.target.value }))}
                            className="settings-input"
                            placeholder={insightsBaseUrlPlaceholder(insightsForm.provider)}
                        />
                    </Field>
                </div>

                <div className="settings-toggle-row settings-toggle-row--tight">
                    <CheckboxLabel checked={insightsForm.enabled} onChange={(checked) => setInsightsForm((s) => ({ ...s, enabled: checked }))}>
                        Enable LLM insight generation
                    </CheckboxLabel>
                </div>

                <div className="settings-actions-row settings-actions-row--tight">
                    <ActionButton onClick={handleSaveInsights} busy={updateInsightsConfig.isPending} icon={<Cloud size={14} />}>
                        Save insights settings
                    </ActionButton>
                    <ActionButton onClick={handleTestInsights} busy={insightsTestBusy} icon={<Wifi size={14} />}>
                        Test LLM connection
                    </ActionButton>
                </div>

                {insightsTestResult && <InlineMessage danger={isDangerMessage(insightsTestResult)}>{insightsTestResult}</InlineMessage>}

                {insightsConfigData?.insights_cache?.generated_at && (
                    <p className="settings-helper-text settings-helper-text--top-space">
                        Last generation: {new Date(insightsConfigData.insights_cache.generated_at).toLocaleString()} · source: {insightsConfigData.insights_cache.source || 'unknown'}
                    </p>
                )}
                {insightsMessage && <InlineMessage danger={isDangerMessage(insightsMessage)}>{insightsMessage}</InlineMessage>}
            </Panel>
        </SectionBlock>
    )
}
