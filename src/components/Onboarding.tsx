import { useState } from 'react'
import { api } from '../lib/api'
import { ArrowRight, Loader2 } from 'lucide-react'
import { MnesisWordmark } from './Logo'

const QUESTIONS = [
    { id: 'name', q: "What is your name?", category: "identity", placeholder: "e.g. Thomas" },
    { id: 'profession', q: "What do you do professionally?", category: "identity", placeholder: "e.g. Senior Software Engineer" },
    { id: 'project', q: "What are you currently working on?", category: "projects", placeholder: "e.g. Building Mnesis, a local memory layer for LLMs" },
    { id: 'communication', q: "How should LLMs communicate with you?", category: "preferences", options: ["Concise", "Detailed", "Casual", "Formal"] }
]

export function Onboarding({ onComplete }: { onComplete: () => void }) {
    const [step, setStep] = useState(0)
    const [answer, setAnswer] = useState('')
    const [loading, setLoading] = useState(false)

    const currentQ = QUESTIONS[step]
    const isLast = step === QUESTIONS.length - 1
    const progress = (step / QUESTIONS.length) * 100

    const handleNext = async () => {
        if (!answer.trim()) return
        setLoading(true)
        try {
            let content = answer
            if (currentQ.id === 'name') content = `User's name is ${answer}.`
            if (currentQ.id === 'profession') content = `User works as: ${answer}.`
            if (currentQ.id === 'communication') content = `User prefers ${answer} communication style.`

            await api.memories.create({ content, category: currentQ.category, level: 'semantic', source_llm: 'manual', confidence_score: 0.9 })
            setAnswer('')

            if (isLast) { await api.admin.completeOnboarding(); onComplete() }
            else setStep(s => s + 1)
        } catch (err) { console.error(err) }
        finally { setLoading(false) }
    }

    return (
        <div style={{
            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
            minHeight: '100vh', background: '#0a0a0a', color: '#f5f3ee', padding: '40px',
        }}>
            <div style={{ width: '100%', maxWidth: '480px' }}>
                {/* Wordmark */}
                <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '40px' }}>
                    <MnesisWordmark color="#f5f3ee" iconSize={32} textSize={26} gap={12} />
                </div>
                <p style={{ fontSize: '11px', color: '#444', margin: '0 0 0', textAlign: 'center' }}>Let's get to know you so your AI assistants can too.</p>

                {/* Card */}
                <div style={{
                    background: '#080808', border: '1px solid #1a1a1a',
                    borderRadius: '4px', overflow: 'hidden',
                }}>
                    {/* Progress */}
                    <div style={{ height: '2px', background: '#1a1a1a' }}>
                        <div style={{ height: '100%', background: '#f5f3ee', width: `${progress}%`, transition: 'width 400ms ease' }} />
                    </div>

                    <div style={{ padding: '28px 28px 24px' }}>
                        {/* Step indicator */}
                        <p style={{ fontSize: '9px', fontWeight: 800, letterSpacing: '0.3em', textTransform: 'uppercase', color: '#333', margin: '0 0 12px' }}>
                            {step + 1} / {QUESTIONS.length}
                        </p>
                        <h2 style={{ fontSize: '16px', fontWeight: 800, color: '#f5f3ee', margin: '0 0 24px', letterSpacing: '-0.01em' }}>
                            {currentQ.q}
                        </h2>

                        {/* Input / Options */}
                        {currentQ.options ? (
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px', marginBottom: '20px' }}>
                                {currentQ.options.map(opt => (
                                    <button
                                        key={opt}
                                        onClick={() => setAnswer(opt)}
                                        style={{
                                            padding: '10px', border: '1px solid',
                                            borderColor: answer === opt ? '#f5f3ee' : '#1e1e1e',
                                            borderRadius: '4px', background: answer === opt ? '#f5f3ee' : 'transparent',
                                            color: answer === opt ? '#0a0a0a' : '#444',
                                            fontSize: '11px', fontWeight: 800, letterSpacing: '0.1em', textTransform: 'uppercase',
                                            cursor: 'pointer', fontFamily: 'inherit', transition: 'all 150ms ease',
                                        }}
                                    >
                                        {opt}
                                    </button>
                                ))}
                            </div>
                        ) : (
                            <input
                                autoFocus
                                value={answer}
                                onChange={e => setAnswer(e.target.value)}
                                onKeyDown={e => e.key === 'Enter' && handleNext()}
                                placeholder={currentQ.placeholder}
                                style={{
                                    width: '100%', background: '#060606',
                                    border: '1px solid #1e1e1e', borderRadius: '4px',
                                    padding: '11px 14px', fontSize: '13px', color: '#d0d0d0',
                                    outline: 'none', fontFamily: 'inherit', boxSizing: 'border-box',
                                    marginBottom: '20px', transition: 'border-color 150ms ease',
                                }}
                                onFocus={e => (e.target.style.borderColor = '#2a2a2a')}
                                onBlur={e => (e.target.style.borderColor = '#1e1e1e')}
                            />
                        )}

                        <button
                            onClick={handleNext}
                            disabled={!answer || loading}
                            style={{
                                width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px',
                                padding: '12px', borderRadius: '4px', border: 'none',
                                fontFamily: 'inherit', fontWeight: 800, fontSize: '10px',
                                letterSpacing: '0.2em', textTransform: 'uppercase', cursor: !answer ? 'not-allowed' : 'pointer',
                                background: !answer ? '#111' : '#f5f3ee',
                                color: !answer ? '#222' : '#0a0a0a',
                                transition: 'all 150ms ease',
                            }}
                        >
                            {loading
                                ? <Loader2 size={15} style={{ animation: 'spin 1s linear infinite' }} />
                                : <>{isLast ? 'Finish Setup' : 'Next'}{!isLast && <ArrowRight size={15} />}</>
                            }
                        </button>
                    </div>
                </div>

                <div style={{ textAlign: 'center', marginTop: '16px' }}>
                    <button
                        onClick={() => { api.admin.completeOnboarding(); onComplete() }}
                        style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '11px', color: '#2a2a2a', fontFamily: 'inherit' }}
                    >
                        Skip for now
                    </button>
                </div>
            </div>
        </div>
    )
}
