/** Class-name join and the status colour palette shared by the component kit. */

export const cx = (...parts: (string | false | null | undefined)[]) => parts.filter(Boolean).join(' ')

// --- colours -------------------------------------------------------------------------------------

/** One palette for statuses everywhere (a "confirmed" pill looks the same on every page). */
export type Tone =
  'neutral' | 'teal' | 'blue' | 'green' | 'amber' | 'red' | 'violet' | 'good' | 'bad' | 'info'

export const TONES: Record<Tone, { pill: string; dot: string; soft: string; icon: string }> = {
  neutral: {
    pill: 'bg-slate-100 text-slate-700 ring-slate-200',
    dot: 'bg-slate-400',
    soft: 'bg-slate-50',
    icon: 'bg-slate-100 text-slate-600',
  },
  teal: {
    pill: 'bg-teal-50 text-teal-800 ring-teal-200',
    dot: 'bg-teal-500',
    soft: 'bg-teal-50',
    icon: 'bg-teal-100 text-teal-700',
  },
  blue: {
    pill: 'bg-sky-50 text-sky-800 ring-sky-200',
    dot: 'bg-sky-500',
    soft: 'bg-sky-50',
    icon: 'bg-sky-100 text-sky-700',
  },
  green: {
    pill: 'bg-emerald-50 text-emerald-800 ring-emerald-200',
    dot: 'bg-emerald-500',
    soft: 'bg-emerald-50',
    icon: 'bg-emerald-100 text-emerald-700',
  },
  amber: {
    pill: 'bg-amber-50 text-amber-900 ring-amber-200',
    dot: 'bg-amber-500',
    soft: 'bg-amber-50',
    icon: 'bg-amber-100 text-amber-700',
  },
  red: {
    pill: 'bg-red-50 text-red-800 ring-red-200',
    dot: 'bg-red-500',
    soft: 'bg-red-50',
    icon: 'bg-red-100 text-red-700',
  },
  violet: {
    pill: 'bg-violet-50 text-violet-800 ring-violet-200',
    dot: 'bg-violet-500',
    soft: 'bg-violet-50',
    icon: 'bg-violet-100 text-violet-700',
  },
  // older names kept for existing callers
  good: {
    pill: 'bg-emerald-50 text-emerald-800 ring-emerald-200',
    dot: 'bg-emerald-500',
    soft: 'bg-emerald-50',
    icon: 'bg-emerald-100 text-emerald-700',
  },
  bad: {
    pill: 'bg-red-50 text-red-800 ring-red-200',
    dot: 'bg-red-500',
    soft: 'bg-red-50',
    icon: 'bg-red-100 text-red-700',
  },
  info: {
    pill: 'bg-amber-50 text-amber-900 ring-amber-200',
    dot: 'bg-amber-500',
    soft: 'bg-amber-50',
    icon: 'bg-amber-100 text-amber-700',
  },
}
