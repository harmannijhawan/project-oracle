import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Loader2 } from 'lucide-react'

export function Page({ title, subtitle, actions, children }: { title: string; subtitle?: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <div className="mx-auto w-full max-w-5xl px-8 py-8">
      <header className="mb-7 flex items-end justify-between gap-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-white">{title}</h1>
          {subtitle && <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-zinc-400">{subtitle}</p>}
        </div>
        {actions && <div className="flex shrink-0 gap-2">{actions}</div>}
      </header>
      <div className="space-y-5">{children}</div>
    </div>
  )
}

export function Card({ title, hint, children, className = '' }: { title?: string; hint?: string; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-xl border border-ink-700 bg-ink-900 p-5 ${className}`}>
      {title && (
        <div className="mb-4">
          <h2 className="text-sm font-semibold text-zinc-100">{title}</h2>
          {hint && <p className="mt-0.5 text-xs text-zinc-500">{hint}</p>}
        </div>
      )}
      {children}
    </section>
  )
}

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost'
const variants: Record<Variant, string> = {
  primary: 'bg-accent text-ink-950 hover:bg-teal-200 font-semibold',
  secondary: 'bg-ink-700 text-zinc-100 hover:bg-ink-600',
  danger: 'bg-red-600 text-white hover:bg-red-500 font-semibold',
  ghost: 'text-zinc-300 hover:bg-ink-800',
}

export function Button({ variant = 'secondary', busy, className = '', children, disabled, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; busy?: boolean }) {
  return (
    <button
      {...rest}
      disabled={disabled || busy}
      className={`inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-45 ${variants[variant]} ${className}`}
    >
      {busy && <Loader2 className="size-4 animate-spin" />}
      {children}
    </button>
  )
}

export function Badge({ tone = 'neutral', children }: { tone?: 'neutral' | 'good' | 'warn' | 'bad'; children: ReactNode }) {
  const t = { neutral: 'bg-ink-700 text-zinc-300', good: 'bg-emerald-500/15 text-emerald-300', warn: 'bg-amber-500/15 text-amber-300', bad: 'bg-red-500/15 text-red-300' }[tone]
  return <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${t}`}>{children}</span>
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: string }) {
  return (
    <div>
      <div className="text-xs text-zinc-500">{label}</div>
      <div className="mt-1 text-xl font-semibold tabular-nums text-white">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-zinc-500">{sub}</div>}
    </div>
  )
}

export function Toggle({ checked, onChange, label, description, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; description?: string; disabled?: boolean }) {
  return (
    <label className={`flex items-start justify-between gap-6 py-2 ${disabled ? 'opacity-50' : 'cursor-pointer'}`}>
      <span>
        <span className="block text-sm text-zinc-100">{label}</span>
        {description && <span className="mt-0.5 block text-xs leading-relaxed text-zinc-500">{description}</span>}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 h-6 w-11 shrink-0 rounded-full transition-colors ${checked ? 'bg-accent' : 'bg-ink-600'}`}
      >
        <span className={`absolute top-0.5 size-5 rounded-full bg-white shadow transition-all ${checked ? 'left-[22px]' : 'left-0.5'}`} />
      </button>
    </label>
  )
}

export function Slider({ label, value, min, max, step, unit = '', onChange, description }: { label: string; value: number; min: number; max: number; step: number; unit?: string; onChange: (v: number) => void; description?: string }) {
  return (
    <div className="py-2">
      <div className="flex items-baseline justify-between">
        <span className="text-sm text-zinc-100">{label}</span>
        <span className="font-mono text-xs tabular-nums text-zinc-400">
          {value}
          {unit}
        </span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} className="mt-2 w-full accent-teal-300" />
      {description && <p className="mt-1 text-xs text-zinc-500">{description}</p>}
    </div>
  )
}

export function Meter({ value, tone = 'accent' }: { value: number; tone?: 'accent' | 'warn' }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-ink-700">
      <div className={`h-full rounded-full transition-[width] duration-150 ${tone === 'warn' ? 'bg-amber-400' : 'bg-accent'}`} style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }} />
    </div>
  )
}

export function ErrorLine({ error }: { error: string | null }) {
  if (!error) return null
  return <p role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">{error}</p>
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-lg border border-dashed border-ink-600 px-4 py-6 text-center text-sm text-zinc-500">{children}</p>
}

export const pct = (v: number, d = 0): string => `${(v * 100).toFixed(d)}%`
export const timeOf = (ts: number): string => new Date(ts * 1000).toLocaleTimeString()
