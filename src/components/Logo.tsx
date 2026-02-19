/**
 * Mnesis Logo System — Logo 1 (Palimpseste)
 *
 * Exports:
 *   PalimpsestIcon  — icon only (the fragmenting horizontal lines)
 *   Logo            — alias for PalimpsestIcon (sidebar, favicon-sized contexts)
 *   MnesisWordmark  — icon + "mnesis" Syne text side by side (splash, loader)
 */

// ─── Palimpseste icon (all lines use currentColor via prop) ──────────────────

export const PalimpsestIcon = ({
    className = "w-6 h-6",
    color = "currentColor",
    style,
}: {
    className?: string
    color?: string
    style?: React.CSSProperties
}) => (
    <svg
        viewBox="0 0 100 100"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className={className}
        style={style}
        role="img"
        aria-label="Mnesis"
    >
        {/* Line 1 — intact */}
        <line x1="10" y1="16" x2="90" y2="16" stroke={color} strokeWidth="2.8" strokeLinecap="round" />
        {/* Line 2 — one gap */}
        <line x1="10" y1="27" x2="54" y2="27" stroke={color} strokeWidth="2.8" strokeLinecap="round" />
        <line x1="60" y1="27" x2="90" y2="27" stroke={color} strokeWidth="2.8" strokeLinecap="round" />
        {/* Line 3 — two gaps */}
        <line x1="10" y1="38" x2="38" y2="38" stroke={color} strokeWidth="2.5" strokeLinecap="round" />
        <line x1="44" y1="38" x2="68" y2="38" stroke={color} strokeWidth="2.5" strokeLinecap="round" />
        <line x1="74" y1="38" x2="90" y2="38" stroke={color} strokeWidth="2.5" strokeLinecap="round" />
        {/* Line 4 — three gaps */}
        <line x1="10" y1="49" x2="28" y2="49" stroke={color} strokeWidth="2.2" strokeLinecap="round" />
        <line x1="35" y1="49" x2="52" y2="49" stroke={color} strokeWidth="2.2" strokeLinecap="round" />
        <line x1="59" y1="49" x2="73" y2="49" stroke={color} strokeWidth="2.2" strokeLinecap="round" />
        <line x1="79" y1="49" x2="90" y2="49" stroke={color} strokeWidth="2.2" strokeLinecap="round" />
        {/* Line 5 — five segments */}
        <line x1="10" y1="60" x2="22" y2="60" stroke={color} strokeWidth="2.0" strokeLinecap="round" />
        <line x1="29" y1="60" x2="40" y2="60" stroke={color} strokeWidth="2.0" strokeLinecap="round" />
        <line x1="47" y1="60" x2="57" y2="60" stroke={color} strokeWidth="2.0" strokeLinecap="round" />
        <line x1="63" y1="60" x2="72" y2="60" stroke={color} strokeWidth="2.0" strokeLinecap="round" />
        <line x1="78" y1="60" x2="87" y2="60" stroke={color} strokeWidth="2.0" strokeLinecap="round" />
        {/* Line 6 — six tiny segments */}
        <line x1="10" y1="71" x2="18" y2="71" stroke={color} strokeWidth="1.7" strokeLinecap="round" />
        <line x1="25" y1="71" x2="32" y2="71" stroke={color} strokeWidth="1.7" strokeLinecap="round" />
        <line x1="40" y1="71" x2="46" y2="71" stroke={color} strokeWidth="1.7" strokeLinecap="round" />
        <line x1="53" y1="71" x2="59" y2="71" stroke={color} strokeWidth="1.7" strokeLinecap="round" />
        <line x1="66" y1="71" x2="72" y2="71" stroke={color} strokeWidth="1.7" strokeLinecap="round" />
        <line x1="78" y1="71" x2="84" y2="71" stroke={color} strokeWidth="1.7" strokeLinecap="round" />
        {/* Line 7 — dots */}
        <line x1="13" y1="82" x2="17" y2="82" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
        <line x1="26" y1="82" x2="30" y2="82" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
        <line x1="40" y1="82" x2="44" y2="82" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
        <line x1="53" y1="82" x2="57" y2="82" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
        <line x1="66" y1="82" x2="70" y2="82" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
        <line x1="79" y1="82" x2="83" y2="82" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
        {/* Line 8 — barely there */}
        <line x1="15" y1="93" x2="18" y2="93" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
        <line x1="32" y1="93" x2="35" y2="93" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
        <line x1="52" y1="93" x2="55" y2="93" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
        <line x1="72" y1="93" x2="75" y2="93" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
    </svg>
)

// Sidebar / small-context alias
export const Logo = PalimpsestIcon

// ─── Wordmark lockup (icon + Syne "mnesis" text) ────────────────────────────

export const MnesisWordmark = ({
    color = "#f5f3ee",
    iconSize = 48,
    textSize = 42,
    gap = 20,
    style,
}: {
    color?: string
    iconSize?: number
    textSize?: number
    gap?: number
    style?: React.CSSProperties
}) => (
    <div style={{ display: 'flex', alignItems: 'center', gap, ...style }}>
        <PalimpsestIcon
            color={color}
            style={{ width: iconSize, height: iconSize, flexShrink: 0 }}
        />
        <span style={{
            fontFamily: "'Syne', sans-serif",
            fontWeight: 800,
            fontSize: textSize,
            letterSpacing: '-0.02em',
            lineHeight: 1,
            color,
            userSelect: 'none',
        }}>
            mnesis
        </span>
    </div>
)
