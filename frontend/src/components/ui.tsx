/**
 * The app's component kit. Every page builds on these so the CRM looks and reads the same
 * everywhere: a page header that says what the page is for, cards with a title and a short
 * explanation, stat cards, status pills with fixed colours, empty states that say what to do
 * next, and tabs. Icons come from lucide-react.
 */
import type { LucideIcon } from 'lucide-react'
import { CircleHelp, Inbox as InboxIcon, X } from 'lucide-react'
import {
  useEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { ApiError } from '../lib/api'
import { cx, TONES, type Tone } from '../lib/cx'

// --- buttons & form controls --------------------------------------------------------------------

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost'
  size?: 'sm' | 'md'
  icon?: LucideIcon
}

export function Button({
  variant = 'primary',
  size = 'md',
  icon: Icon,
  className,
  children,
  ...props
}: ButtonProps) {
  const styles = {
    primary: 'bg-teal-700 text-white shadow-sm hover:bg-teal-800 disabled:bg-teal-700/50',
    secondary:
      'border border-slate-300 bg-white text-slate-800 shadow-sm hover:bg-slate-50 disabled:text-slate-400',
    danger: 'border border-red-200 bg-white text-red-700 hover:bg-red-50 disabled:text-red-300',
    ghost: 'text-slate-600 hover:bg-slate-100 disabled:text-slate-300',
  }[variant]
  const sizes = { sm: 'px-2.5 py-1.5 text-xs', md: 'px-3.5 py-2 text-sm' }[size]
  return (
    <button
      type="button"
      className={cx(
        'inline-flex items-center justify-center gap-1.5 rounded-lg font-medium',
        'transition-colors focus-visible:ring-2 focus-visible:ring-teal-600/40 focus-visible:outline-none disabled:cursor-not-allowed',
        sizes,
        styles,
        className,
      )}
      {...props}
    >
      {Icon && <Icon className={size === 'sm' ? 'size-3.5' : 'size-4'} aria-hidden />}
      {children}
    </button>
  )
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-slate-700">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  )
}

const control =
  'rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm outline-none ' +
  'placeholder:text-slate-400 focus:border-teal-600 focus:ring-2 focus:ring-teal-600/20 disabled:bg-slate-50'
// full width unless the caller sets a width (w-40, md:w-56, ...)
const width = (className?: string) => (/(^|\s|:)w-/.test(className ?? '') ? '' : 'w-full')

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(control, width(props.className), props.className)} />
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cx(control, width(props.className), props.className)} />
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cx(control, width(props.className), props.className)} />
}

// --- page structure -----------------------------------------------------------------------------

/** Top of every page: what it is, what it is for (one sentence), and its main actions. */
export function PageHeader({
  title,
  description,
  icon: Icon,
  actions,
  help,
  children,
}: {
  title: string
  description?: ReactNode
  icon?: LucideIcon
  actions?: ReactNode
  /** longer "how does this work" text, behind a (?) button */
  help?: ReactNode
  /** tabs / filters row under the title */
  children?: ReactNode
}) {
  return (
    <header className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          {Icon && (
            <span className="mt-0.5 hidden rounded-xl bg-teal-100 p-2.5 text-teal-700 sm:block">
              <Icon className="size-5" aria-hidden />
            </span>
          )}
          <div className="min-w-0">
            <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight text-slate-900">
              {title}
              {help && <InfoTip text={help} />}
            </h1>
            {description && <p className="mt-1 max-w-3xl text-sm text-slate-600">{description}</p>}
          </div>
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {children}
    </header>
  )
}

export function Card({
  title,
  description,
  icon: Icon,
  actions,
  children,
  flush,
  className,
}: {
  title?: ReactNode
  description?: ReactNode
  icon?: LucideIcon
  actions?: ReactNode
  children: ReactNode
  /** no inner padding (tables that run edge to edge) */
  flush?: boolean
  className?: string
}) {
  return (
    <section className={cx('rounded-xl border border-slate-200 bg-white shadow-sm', className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-5 py-3.5">
          <div className="flex min-w-0 items-start gap-2.5">
            {Icon && <Icon className="mt-0.5 size-4 shrink-0 text-teal-700" aria-hidden />}
            <div className="min-w-0">
              {title && <h2 className="text-[15px] font-semibold text-slate-900">{title}</h2>}
              {description && <p className="mt-0.5 text-xs text-slate-500">{description}</p>}
            </div>
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={flush ? '' : 'p-5'}>{children}</div>
    </section>
  )
}

/** A number that matters, with what it means. `value` null shows a dash and the `empty` reason. */
export function StatCard({
  label,
  value,
  hint,
  icon: Icon,
  tone = 'teal',
  to,
  trend,
  empty,
  info,
}: {
  label: string
  value: ReactNode | null
  hint?: ReactNode
  icon?: LucideIcon
  tone?: Tone
  to?: string
  /** change against the previous period; good=true paints it green */
  trend?: { text: string; good: boolean | null }
  empty?: string
  info?: ReactNode
}) {
  const body = (
    <div className="flex h-full items-start gap-3">
      {Icon && (
        <span className={cx('rounded-lg p-2', TONES[tone].icon)}>
          <Icon className="size-5" aria-hidden />
        </span>
      )}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1 text-xs font-medium text-slate-500">
          <span className="truncate">{label}</span>
          {info && <InfoTip text={info} />}
        </div>
        <div className="mt-1 text-2xl font-semibold tracking-tight text-slate-900 tabular-nums">
          {value ?? <span className="text-slate-300">—</span>}
        </div>
        {value == null && empty ? (
          <div className="mt-0.5 text-xs text-slate-400">{empty}</div>
        ) : (
          hint && <div className="mt-0.5 text-xs text-slate-500">{hint}</div>
        )}
        {trend && (
          <div
            className={cx(
              'mt-1 text-xs font-medium',
              trend.good === null ? 'text-slate-500' : trend.good ? 'text-emerald-700' : 'text-red-700',
            )}
          >
            {trend.text}
          </div>
        )}
      </div>
    </div>
  )
  const box = 'block h-full rounded-xl border border-slate-200 bg-white p-4 shadow-sm'
  return to ? (
    <Link to={to} className={cx(box, 'transition hover:border-teal-300 hover:shadow')}>
      {body}
    </Link>
  ) : (
    <div className={box}>{body}</div>
  )
}

/** Nothing to show yet: say why, and what to do (with a link or button). */
export function EmptyState({
  icon: Icon = InboxIcon,
  title,
  text,
  action,
  compact,
}: {
  icon?: LucideIcon
  title: string
  text?: ReactNode
  action?: ReactNode
  compact?: boolean
}) {
  return (
    <div className={cx('flex flex-col items-center text-center', compact ? 'py-6' : 'py-12')}>
      <span className="rounded-full bg-slate-100 p-3 text-slate-400">
        <Icon className={compact ? 'size-5' : 'size-6'} aria-hidden />
      </span>
      <p className="mt-3 text-sm font-medium text-slate-800">{title}</p>
      {text && <p className="mt-1 max-w-md text-sm text-slate-500">{text}</p>}
      {action && <div className="mt-4 flex flex-wrap justify-center gap-2">{action}</div>}
    </div>
  )
}

export function Badge({
  tone = 'neutral',
  children,
  dot,
}: {
  tone?: Tone
  children: ReactNode
  dot?: boolean
}) {
  return (
    <span
      className={cx(
        'inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium whitespace-nowrap ring-1 ring-inset',
        TONES[tone].pill,
      )}
    >
      {dot && <span className={cx('size-1.5 rounded-full', TONES[tone].dot)} aria-hidden />}
      {children}
    </span>
  )
}

export type TabItem<V extends string> = { value: V; label: string; count?: number; icon?: LucideIcon }

export function Tabs<V extends string>({
  value,
  onChange,
  items,
}: {
  value: V
  onChange: (v: V) => void
  items: TabItem<V>[]
}) {
  return (
    <div className="flex gap-1 overflow-x-auto overflow-y-hidden border-b border-slate-200" role="tablist">
      {items.map(({ value: v, label, count, icon: Icon }) => (
        <button
          key={v}
          role="tab"
          aria-selected={v === value}
          onClick={() => onChange(v)}
          className={cx(
            '-mb-px inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm whitespace-nowrap',
            v === value
              ? 'border-teal-700 font-medium text-teal-800'
              : 'border-transparent text-slate-600 hover:text-slate-900',
          )}
        >
          {Icon && <Icon className="size-4" aria-hidden />}
          {label}
          {count !== undefined && (
            <span
              className={cx(
                'rounded-full px-1.5 text-[11px] tabular-nums',
                v === value ? 'bg-teal-100 text-teal-800' : 'bg-slate-100 text-slate-600',
              )}
            >
              {count}
            </span>
          )}
        </button>
      ))}
    </div>
  )
}

/** A small (?) that explains a term (a KPI formula, a TZ rule) without cluttering the page. */
export function InfoTip({ text }: { text: ReactNode }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent ? e.key === 'Escape' : !box.current?.contains(e.target as Node))
        setOpen(false)
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', close)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', close)
    }
  }, [open])
  return (
    <span className="relative inline-flex" ref={box}>
      <button
        type="button"
        className="rounded-full text-slate-400 hover:text-teal-700"
        aria-label={t('app.help')}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <CircleHelp className="size-4" aria-hidden />
      </button>
      {open && (
        <span className="absolute top-6 left-1/2 z-30 w-72 -translate-x-1/2 rounded-lg border border-slate-200 bg-white p-3 text-left text-xs leading-relaxed font-normal text-slate-700 shadow-lg">
          {text}
        </span>
      )}
    </span>
  )
}

const AVATAR_TONES = [
  'bg-teal-100 text-teal-800',
  'bg-sky-100 text-sky-800',
  'bg-violet-100 text-violet-800',
  'bg-amber-100 text-amber-900',
  'bg-rose-100 text-rose-800',
  'bg-emerald-100 text-emerald-800',
]

/** Initials in a coloured circle (the colour is stable per name). */
export function Avatar({ name, size = 'md' }: { name: string; size?: 'sm' | 'md' | 'lg' }) {
  const initials =
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0]?.toUpperCase())
      .join('') || '?'
  let hash = 0
  for (const ch of name) hash = (hash * 31 + ch.charCodeAt(0)) | 0
  const sizes = { sm: 'size-7 text-[11px]', md: 'size-9 text-xs', lg: 'size-12 text-base' }[size]
  return (
    <span
      className={cx(
        'inline-flex shrink-0 items-center justify-center rounded-full font-semibold',
        sizes,
        AVATAR_TONES[Math.abs(hash) % AVATAR_TONES.length],
      )}
      aria-hidden
    >
      {initials}
    </span>
  )
}

/** Label / value pairs in a responsive grid (patient details, appointment details...). */
export function KeyValue({ items }: { items: { label: string; value: ReactNode }[] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
      {items.map(({ label, value }) => (
        <div key={label} className="min-w-0">
          <dt className="text-xs text-slate-500">{label}</dt>
          <dd className="mt-0.5 text-sm break-words text-slate-900">{value ?? '—'}</dd>
        </div>
      ))}
    </dl>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx('animate-pulse rounded-md bg-slate-200/70', className ?? 'h-4 w-full')} />
}

/** Table shell with consistent header/row styling; rows get `hover:bg-slate-50` from here. */
export function Table({ head, children }: { head: ReactNode; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-slate-50/80 text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
          {head}
        </thead>
        <tbody className="divide-y divide-slate-100 [&>tr:hover]:bg-slate-50">{children}</tbody>
      </table>
    </div>
  )
}

// --- feedback -----------------------------------------------------------------------------------

export function ErrorText({ error }: { error: unknown }) {
  const { t } = useTranslation()
  if (!error) return null
  const code = error instanceof ApiError ? error.code : 'generic'
  return (
    <p role="alert" className="text-sm text-red-700">
      {t(`errors.${code}`, { defaultValue: t('errors.generic') })}
    </p>
  )
}

export function Notice({ children, tone = 'green' }: { children: ReactNode; tone?: Tone }) {
  return (
    <div className={cx('rounded-lg px-3 py-2 text-sm ring-1 ring-inset', TONES[tone].pill)}>{children}</div>
  )
}

export function Modal({
  title,
  onClose,
  children,
  wide,
}: {
  title: string
  onClose: () => void
  children: ReactNode
  wide?: boolean
}) {
  const { t } = useTranslation()
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto p-4 sm:p-8"
      role="dialog"
      aria-modal="true"
    >
      <button
        className="fixed inset-0 bg-slate-900/40 backdrop-blur-[1px]"
        aria-label={t('app.close')}
        onClick={onClose}
      />
      <section
        className={cx('relative w-full rounded-xl bg-white shadow-2xl', wide ? 'max-w-3xl' : 'max-w-lg')}
      >
        <header className="flex items-center justify-between border-b border-slate-100 px-5 py-3.5">
          <h2 className="text-base font-semibold">{title}</h2>
          <button
            className="rounded-md p-1 text-slate-500 hover:bg-slate-100"
            aria-label={t('app.close')}
            onClick={onClose}
          >
            <X className="size-4" aria-hidden />
          </button>
        </header>
        <div className="p-5">{children}</div>
      </section>
    </div>
  )
}
