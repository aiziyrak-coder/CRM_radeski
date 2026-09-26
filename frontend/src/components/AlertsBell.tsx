import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { useAuth } from '../lib/auth-context'
import { canOpen } from '../lib/navigation'
import { STATUS_ROLES, useSystemStatus } from '../lib/system'

/** Header alert (TZ 4.4, ARXITEKTURA 4.2): inquiries past their SLA, unreviewed red flags and
 * today's missed calls, for whoever can act on them. */
export default function AlertsBell() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
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
  const { data } = useSystemStatus(Boolean(user && STATUS_ROLES.includes(user.role)))
  if (!user || !data) return null
  const items = (
    [
      ['sla', data.today.leads_sla_breached ?? 0, '/leads'],
      // only supervisor and admin can mark flags reviewed; the owner sees them in QA
      ['redFlags', user.role === 'owner' ? 0 : (data.qa?.red_flags_open ?? 0), '/qa'],
      // callbacks still to make, not every missed call of the day
      ['missed', data.today.missed_open ?? 0, '/tasks'],
    ] as const
  ).filter(([, n, path]) => n > 0 && canOpen(user.role, path))
  const total = items.reduce((sum, [, n]) => sum + n, 0)
  if (!total) return null
  return (
    <div className="relative" ref={box}>
      <button
        className="flex items-center gap-1 rounded-full bg-red-100 px-2.5 py-1 text-sm font-semibold text-red-800 hover:bg-red-200"
        aria-label={t('alerts.title')}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8">
          <path d="M10 3a5 5 0 0 0-5 5v3l-1.5 3h13L15 11V8a5 5 0 0 0-5-5ZM8 17a2 2 0 0 0 4 0" />
        </svg>
        <span className="tabular-nums">{total}</span>
      </button>
      {open && (
        <ul className="absolute right-0 z-30 mt-2 w-64 rounded-md border border-slate-200 bg-white p-1 text-sm shadow-lg">
          {items.map(([key, n, path]) => (
            <li key={key}>
              <Link
                to={path}
                onClick={() => setOpen(false)}
                className="flex items-center justify-between rounded px-3 py-2 hover:bg-slate-50"
              >
                <span>{t(`alerts.${key}`)}</span>
                <span className="font-semibold text-red-700 tabular-nums">{n}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
