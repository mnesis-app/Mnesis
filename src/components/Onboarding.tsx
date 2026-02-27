import { useMemo, useState } from 'react'
import { api } from '../lib/api'
import { ArrowLeft, ArrowRight, CheckCircle2, Loader2, Sparkles } from 'lucide-react'
import { MnesisWordmark } from './Logo'
import './Onboarding.css'

const CLIENT_DISPLAY_NAMES: Record<string, string> = {
    claude_desktop: 'Claude Desktop',
    cursor: 'Cursor',
    windsurf: 'Windsurf',
    chatgpt: 'ChatGPT',
    anythingllm: 'AnythingLLM',
    gemini: 'Gemini',
    ollama: 'Ollama',
}

function formatClientName(key: string): string {
    return (
        CLIENT_DISPLAY_NAMES[key] ||
        key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
    )
}

type Question = {
    id: string
    prompt: string
    helper?: string
    placeholder?: string
    options?: string[]
    category: string
    level: 'semantic' | 'episodic'
    required?: boolean
    toMemory: (value: string) => string
}

const QUESTIONS: Question[] = [
    {
        id: 'name',
        prompt: 'How should assistants address you?',
        helper: 'Used for tone and direct references.',
        placeholder: 'e.g. Julien',
        category: 'identity',
        level: 'semantic',
        required: false,
        toMemory: (value) => `The user prefers to be addressed as ${value}.`,
    },
    {
        id: 'profession',
        prompt: 'What do you do professionally?',
        helper: 'Role, domain, or context that should shape answers.',
        placeholder: 'e.g. Computer engineering student',
        category: 'identity',
        level: 'semantic',
        required: false,
        toMemory: (value) => `The user works or studies as: ${value}.`,
    },
    {
        id: 'focus',
        prompt: 'What are you currently focused on?',
        helper: 'Current project, sprint, or objective.',
        placeholder: 'e.g. Shipping Mnesis v1 with better memory quality',
        category: 'projects',
        level: 'episodic',
        required: false,
        toMemory: (value) => `Current focus/project: ${value}.`,
    },
    {
        id: 'communication',
        prompt: 'How should AI communicate with you?',
        helper: 'You can change this later in Memories.',
        options: ['Concise', 'Detailed', 'Direct', 'Formal'],
        category: 'preferences',
        level: 'semantic',
        required: false,
        toMemory: (value) => `Preferred communication style: ${value}.`,
    },
    {
        id: 'constraints',
        prompt: 'Any constraints assistants should always respect?',
        helper: 'Examples: language, output format, or strict no-go rules.',
        placeholder: 'e.g. Answer in French, no filler, code first',
        category: 'preferences',
        level: 'semantic',
        required: false,
        toMemory: (value) => `Important assistant constraints: ${value}.`,
    },
]

const MIN_REQUIRED_CHARS = 3

export function Onboarding({ onComplete }: { onComplete: () => void }) {
    const [step, setStep] = useState(0)
    const [answers, setAnswers] = useState<Record<string, string>>({})
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [configResult, setConfigResult] = useState<Record<string, unknown> | null>(null)

    const reviewStepIndex = QUESTIONS.length
    const isReviewStep = step === reviewStepIndex
    const currentQ = !isReviewStep ? QUESTIONS[step] : null
    const currentAnswer = currentQ ? String(answers[currentQ.id] || '') : ''
    const trimmedAnswer = currentAnswer.trim()
    const progress = Math.round((Math.min(step, QUESTIONS.length) / QUESTIONS.length) * 100)
    const filledCount = useMemo(
        () => QUESTIONS.filter((q) => String(answers[q.id] || '').trim().length > 0).length,
        [answers]
    )

    const updateAnswer = (value: string) => {
        if (!currentQ) return
        setAnswers((prev) => ({ ...prev, [currentQ.id]: value }))
        if (error) setError(null)
    }

    const handleNext = () => {
        if (isReviewStep) return
        if (currentQ?.required && trimmedAnswer.length < MIN_REQUIRED_CHARS) {
            setError(`Please provide at least ${MIN_REQUIRED_CHARS} characters.`)
            return
        }
        setError(null)
        if (step < reviewStepIndex) setStep((s) => s + 1)
    }

    const handleBack = () => {
        if (loading) return
        setError(null)
        setStep((s) => Math.max(0, s - 1))
    }

    const completeOnboarding = async () => {
        setLoading(true)
        setError(null)
        try {
            for (const q of QUESTIONS) {
                const value = String(answers[q.id] || '').trim()
                if (!value) continue
                const content = q.toMemory(value)
                try {
                    await api.memories.create({
                        content,
                        category: q.category,
                        level: q.level,
                        source_llm: 'onboarding',
                        confidence_score: 0.95,
                    })
                } catch {
                    // Non-blocking: onboarding should still complete even if one write fails.
                }
            }

            const onboardingResult = await api.admin.completeOnboarding()
            if (onboardingResult?.status !== 'ok') {
                setError(onboardingResult?.message || 'Could not complete onboarding.')
                return
            }
            // Show "Setup complete" screen with MCP auto-config results
            const mcpResult = onboardingResult?.mcp_autoconfig
            setConfigResult(
                mcpResult && typeof mcpResult === 'object'
                    ? (mcpResult as Record<string, unknown>)
                    : {}
            )
        } catch (err) {
            console.error(err)
            setError('Could not complete onboarding right now. Please try again.')
        } finally {
            setLoading(false)
        }
    }

    const handleSkipAll = async () => {
        setLoading(true)
        setError(null)
        try {
            const onboardingResult = await api.admin.completeOnboarding()
            if (onboardingResult?.status !== 'ok') {
                setError(onboardingResult?.message || 'Could not complete onboarding.')
                return
            }
            onComplete()
        } catch (err) {
            console.error(err)
            setError('Could not skip onboarding right now. Please try again.')
        } finally {
            setLoading(false)
        }
    }

    // "Setup complete" screen — shown after successful onboarding completion
    if (configResult !== null) {
        const configured = (configResult.configured_clients as string[]) || []
        const detected = (configResult.detected_clients as string[]) || []
        const notConfigured = detected.filter((k) => !configured.includes(k))

        return (
            <div className="onboarding-shell">
                <div className="onboarding-wrap">
                    <div className="onboarding-brand">
                        <MnesisWordmark color="#f5f3ee" iconSize={34} textSize={28} gap={12} />
                    </div>

                    <div className="onboarding-card">
                        <div className="onboarding-body onboarding-success">
                            <div className="onboarding-success-icon">
                                <CheckCircle2 size={28} strokeWidth={1.5} />
                            </div>
                            <h2 className="onboarding-title">You're all set.</h2>
                            <p className="onboarding-helper">
                                Your initial memories are saved. MCP clients have been auto-configured where possible.
                            </p>

                            <div className="onboarding-clients">
                                {configured.length > 0 ? (
                                    <ul className="onboarding-clients-list">
                                        {configured.map((key) => (
                                            <li key={key} className="onboarding-client-row onboarding-client-row--ok">
                                                <CheckCircle2 size={11} />
                                                {formatClientName(key)}
                                            </li>
                                        ))}
                                        {notConfigured.map((key) => (
                                            <li key={key} className="onboarding-client-row onboarding-client-row--warn">
                                                <span className="onboarding-client-dash">—</span>
                                                {formatClientName(key)} (detected, restart required)
                                            </li>
                                        ))}
                                    </ul>
                                ) : (
                                    <p className="onboarding-clients-none">
                                        No MCP clients were auto-configured.{' '}
                                        Open <strong>Settings → MCP</strong> to add Mnesis manually.
                                    </p>
                                )}
                            </div>

                            <button
                                type="button"
                                className="onboarding-button onboarding-button--primary"
                                onClick={onComplete}
                            >
                                <Sparkles size={14} />
                                Get started
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        )
    }

    return (
        <div className="onboarding-shell">
            <div className="onboarding-wrap">
                <div className="onboarding-brand">
                    <MnesisWordmark color="#f5f3ee" iconSize={34} textSize={28} gap={12} />
                </div>
                <p className="onboarding-subtitle">
                    Quick setup so all connected AI clients start with the right context.
                </p>

                <div className="onboarding-card">
                    <div className="onboarding-progress-track">
                        <div className="onboarding-progress-fill" style={{ width: `${progress}%` }} />
                    </div>

                    <div className="onboarding-body">
                        <div className="onboarding-step-meta">
                            <span>{isReviewStep ? 'Review' : `Step ${step + 1}/${QUESTIONS.length}`}</span>
                            <span>{filledCount} memories prepared</span>
                        </div>

                        {!isReviewStep && currentQ && (
                            <>
                                <h2 className="onboarding-title">{currentQ.prompt}</h2>
                                {currentQ.helper && <p className="onboarding-helper">{currentQ.helper}</p>}

                                {currentQ.options ? (
                                    <div className="onboarding-options-grid">
                                        {currentQ.options.map((option) => {
                                            const selected = trimmedAnswer.toLowerCase() === option.toLowerCase()
                                            return (
                                                <button
                                                    key={option}
                                                    type="button"
                                                    className={`onboarding-option ${selected ? 'onboarding-option--active' : ''}`}
                                                    onClick={() => updateAnswer(option)}
                                                >
                                                    {option}
                                                </button>
                                            )
                                        })}
                                    </div>
                                ) : (
                                    <textarea
                                        autoFocus
                                        rows={3}
                                        className="onboarding-input"
                                        value={currentAnswer}
                                        placeholder={currentQ.placeholder}
                                        onChange={(e) => updateAnswer(e.target.value)}
                                    />
                                )}

                                <p className="onboarding-note">
                                    {currentQ.required ? 'Required' : 'Optional'} - you can edit or add memories later.
                                </p>
                            </>
                        )}

                        {isReviewStep && (
                            <div className="onboarding-review">
                                <h2 className="onboarding-title">Review before finishing</h2>
                                <p className="onboarding-helper">
                                    Mnesis will save only filled answers as initial memories and auto-configure supported MCP clients.
                                </p>
                                <div className="onboarding-review-list">
                                    {QUESTIONS.map((q) => {
                                        const value = String(answers[q.id] || '').trim()
                                        return (
                                            <div key={q.id} className="onboarding-review-item">
                                                <p className="onboarding-review-label">{q.prompt}</p>
                                                <p className="onboarding-review-value">
                                                    {value || <span className="onboarding-review-empty">Skipped</span>}
                                                </p>
                                            </div>
                                        )
                                    })}
                                </div>
                                <div className="onboarding-review-summary">
                                    <CheckCircle2 size={14} />
                                    <span>{filledCount} memory {filledCount === 1 ? 'entry' : 'entries'} will be created.</span>
                                </div>
                            </div>
                        )}

                        {error && <p className="onboarding-error">{error}</p>}

                        <div className="onboarding-actions">
                            <button
                                type="button"
                                className="onboarding-button onboarding-button--ghost"
                                onClick={handleBack}
                                disabled={loading || step === 0}
                            >
                                <ArrowLeft size={14} />
                                Back
                            </button>

                            {!isReviewStep ? (
                                <button
                                    type="button"
                                    className="onboarding-button onboarding-button--primary"
                                    onClick={handleNext}
                                    disabled={loading}
                                >
                                    Next
                                    <ArrowRight size={14} />
                                </button>
                            ) : (
                                <button
                                    type="button"
                                    className="onboarding-button onboarding-button--primary"
                                    onClick={() => { void completeOnboarding() }}
                                    disabled={loading}
                                >
                                    {loading ? <Loader2 size={14} className="onboarding-spin" /> : <Sparkles size={14} />}
                                    Finish setup
                                </button>
                            )}
                        </div>
                    </div>
                </div>

                <button
                    type="button"
                    className="onboarding-skip"
                    onClick={() => { void handleSkipAll() }}
                    disabled={loading}
                >
                    Skip onboarding for now
                </button>
            </div>
        </div>
    )
}
