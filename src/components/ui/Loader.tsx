import { PalimpsestIcon } from '../Logo'

const loaderStyle = `
@keyframes mnesis-fade-in {
    from { opacity: 0; transform: translateY(4px); }
    to   { opacity: 1; transform: translateY(0); }
}

.mnesis-wordmark {
    animation: mnesis-fade-in 600ms ease both;
}

.mnesis-wordmark-icon line {
    stroke-dasharray: 1;
    stroke-dashoffset: 1;
    animation: mnesis-line-draw 1.2s ease forwards;
}

@keyframes mnesis-line-draw {
    to { stroke-dashoffset: 0; }
}

.mnesis-wordmark-icon line:nth-child(1)  { animation-delay: 0ms; }
.mnesis-wordmark-icon line:nth-child(2)  { animation-delay: 60ms; }
.mnesis-wordmark-icon line:nth-child(3)  { animation-delay: 60ms; }
.mnesis-wordmark-icon line:nth-child(4)  { animation-delay: 120ms; }
.mnesis-wordmark-icon line:nth-child(5)  { animation-delay: 120ms; }
.mnesis-wordmark-icon line:nth-child(6)  { animation-delay: 120ms; }
.mnesis-wordmark-icon line:nth-child(7)  { animation-delay: 180ms; }
.mnesis-wordmark-icon line:nth-child(8)  { animation-delay: 180ms; }
.mnesis-wordmark-icon line:nth-child(9)  { animation-delay: 180ms; }
.mnesis-wordmark-icon line:nth-child(10) { animation-delay: 180ms; }
.mnesis-wordmark-icon line:nth-child(n+11) { animation-delay: 240ms; }
`

export function MnesisLoader({
    className = "",
    size = "md",
    detail
}: {
    className?: string
    size?: "sm" | "md" | "lg"
    detail?: string
}) {
    const iconSize = { sm: 24, md: 40, lg: 64 }[size]
    const textSize = { sm: '18px', md: '28px', lg: '44px' }[size]
    const gap = { sm: '10px', md: '16px', lg: '24px' }[size]

    return (
        <div className={`flex flex-col items-center justify-center gap-5 ${className}`}>
            <style>{loaderStyle}</style>
            <div className="mnesis-wordmark" style={{ display: 'flex', alignItems: 'center', gap }}>
                <PalimpsestIcon
                    className="mnesis-wordmark-icon"
                    color="#f5f3ee"
                    style={{ width: iconSize, height: iconSize, flexShrink: 0 }}
                />
                <span style={{
                    fontFamily: "'Syne', sans-serif",
                    fontWeight: 800,
                    fontSize: textSize,
                    letterSpacing: '-0.02em',
                    lineHeight: 1,
                    color: '#f5f3ee',
                    userSelect: 'none',
                }}>
                    mnesis
                </span>
            </div>
            {detail && (
                <p style={{
                    fontSize: '11px',
                    color: '#555',
                    margin: 0,
                    fontFamily: "'Inter', sans-serif",
                    letterSpacing: '0.02em',
                }}>
                    {detail}
                </p>
            )}
        </div>
    )
}
