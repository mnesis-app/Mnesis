/**
 * Shared primitives for Settings sub-components.
 * Imported by Settings.tsx, SettingsSync.tsx, SettingsInsights.tsx,
 * SettingsMaintenance.tsx, and SettingsMcp.tsx.
 */
import { Loader2 } from 'lucide-react'
import { type ReactNode } from 'react'

// ── Helpers ────────────────────────────────────────────────────────────────

export function cx(...parts: Array<string | false | null | undefined>) {
    return parts.filter(Boolean).join(' ')
}

export function isDangerMessage(message: string | null): boolean {
    if (!message) return false
    return /failed|error|required|at least|invalid/i.test(message)
}

// ── Layout components ──────────────────────────────────────────────────────

export function SectionBlock({
    title,
    description,
    children,
}: {
    title: string
    description: string
    children: ReactNode
}) {
    return (
        <section className="settings-section">
            <div className="settings-section-head">
                <h2>{title}</h2>
                <p>{description}</p>
            </div>
            {children}
        </section>
    )
}

export function Panel({ children }: { children: ReactNode }) {
    return <div className="settings-panel">{children}</div>
}

export function Field({
    label,
    children,
    helper,
    extra,
}: {
    label: string
    children: ReactNode
    helper?: string
    extra?: string
}) {
    return (
        <div className="settings-field">
            <label>{label}</label>
            {children}
            {helper && <p className="settings-helper-text">{helper}</p>}
            {extra && <p className="settings-helper-text settings-helper-text--extra">{extra}</p>}
        </div>
    )
}

export function StatCell({ label, value }: { label: string; value: string }) {
    return (
        <div className="settings-stat-cell">
            <div className="settings-stat-label">{label}</div>
            <div className="settings-stat-value">{value}</div>
        </div>
    )
}

export function CheckboxLabel({
    checked,
    onChange,
    children,
}: {
    checked: boolean
    onChange: (value: boolean) => void
    children: ReactNode
}) {
    return (
        <label className="settings-checkbox">
            <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
            <span>{children}</span>
        </label>
    )
}

export function InlineMessage({ children, danger = false }: { children: ReactNode; danger?: boolean }) {
    return (
        <p className={cx('settings-inline-message', danger && 'settings-inline-message--danger')}>
            {children}
        </p>
    )
}

export function IconButton({
    onClick,
    title,
    disabled,
    children,
}: {
    onClick: () => void
    title: string
    disabled?: boolean
    children: ReactNode
}) {
    return (
        <button onClick={onClick} title={title} disabled={disabled} className="settings-icon-button">
            {children}
        </button>
    )
}

export function ActionButton({
    onClick,
    busy,
    disabled,
    icon,
    children,
}: {
    onClick: () => void
    busy: boolean
    disabled?: boolean
    icon: ReactNode
    children: ReactNode
}) {
    return (
        <button onClick={onClick} disabled={busy || !!disabled} className="settings-action-button">
            {busy ? <Loader2 size={13} className="settings-spinner" /> : icon}
            {children}
        </button>
    )
}
