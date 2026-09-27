import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { formatPhone } from '../lib/patients'
import {
  clinicMinutes,
  clinicTime,
  serviceName,
  setAppointmentStatus,
  type Appointment,
  type AppointmentStatus,
  useReasonLabel,
} from '../lib/scheduling'
import { NoShowReasons, StatusPill } from './AppointmentPanel'
import PatientName from './PatientName'
import { Button, ErrorText, Input } from './ui'

type Bucket = 'waiting' | 'arrived' | 'no_show'
const BUCKET: Partial<Record<AppointmentStatus, Bucket>> = {
  scheduled: 'waiting',
  confirmed: 'waiting',
  arrived: 'arrived',
  completed: 'arrived',
  no_show: 'no_show',
}
const digits = (v: string) => v.replace(/\D/g, '')

/** Minutes since clinic-local midnight right now (ticks every minute for "late" badges). */
function useNowMinutes() {
  const [now, setNow] = useState(() => clinicMinutes(new Date().toISOString()))
  useEffect(() => {
    const id = window.setInterval(() => setNow(clinicMinutes(new Date().toISOString())), 60_000)
    return () => window.clearInterval(id)
  }, [])
  return now
}

function PatientCard({ a, now, onOpen }: { a: Appointment; now: number; onOpen: () => void }) {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const reasonLabel = useReasonLabel()
  const [askReason, setAskReason] = useState(false)
  const change = useMutation({
    mutationFn: ({ s, reason }: { s: AppointmentStatus; reason?: string }) =>
      setAppointmentStatus(a.id, s, reason),
    onSuccess: () => {
      setAskReason(false)
      void queryClient.invalidateQueries({ queryKey: ['appointments'] })
    },
  })
  const busy = change.isPending
  const waiting = a.status === 'scheduled' || a.status === 'confirmed'
  const late = waiting ? now - clinicMinutes(a.starts_at) : 0
  const big = 'min-h-12 px-4 text-base'
  const tone =
    a.status === 'arrived' || a.status === 'completed'
      ? 'border-emerald-300 bg-emerald-50/50'
      : a.status === 'no_show'
        ? 'border-red-200 bg-red-50/40'
        : late > 15
          ? 'border-amber-300'
          : 'border-slate-200'

  return (
    <li className={`rounded-lg border bg-white p-3 sm:p-4 ${tone}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="text-lg font-semibold tabular-nums">{clinicTime(a.starts_at)}</span>
            <button
              className="text-left text-lg font-semibold text-teal-800 hover:underline"
              onClick={onOpen}
            >
              <PatientName name={a.patient_name} />
            </button>
            <StatusPill status={a.status} />
            {late > 15 && (
              <span className="rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900">
                {t('registrar.late', { count: late })}
              </span>
            )}
          </div>
          <div className="mt-1 text-sm text-slate-600">
            {a.patient_phone && (
              <a href={`tel:${a.patient_phone}`} className="mr-3 whitespace-nowrap hover:underline">
                {formatPhone(a.patient_phone)}
              </a>
            )}
            <span className="mr-3">{a.doctor_name}</span>
            {a.resource_name && <span className="mr-3 text-slate-500">· {a.resource_name}</span>}
          </div>
          <div className="text-sm text-slate-500">
            {a.services.map((s) => serviceName(s, i18n.language)).join(', ')}
          </div>
          {a.status === 'no_show' && a.cancel_reason && (
            <div className="mt-1 text-sm text-red-800">{reasonLabel(a.status, a.cancel_reason)}</div>
          )}
        </div>
        {!askReason && (
          <div className="flex w-full flex-wrap gap-2 sm:w-auto sm:justify-end">
            {waiting && (
              <button
                type="button"
                className={`${big} inline-flex flex-1 items-center justify-center gap-2 rounded-md bg-emerald-600 font-medium text-white hover:bg-emerald-700 disabled:opacity-50 sm:flex-none`}
                disabled={busy}
                onClick={() => change.mutate({ s: 'arrived' })}
              >
                ✓ {t('registrar.arrived')}
              </button>
            )}
            {a.status === 'scheduled' && (
              <Button
                variant="secondary"
                className={`${big} flex-1 sm:flex-none`}
                disabled={busy}
                onClick={() => change.mutate({ s: 'confirmed' })}
              >
                {t('registrar.confirmed')}
              </Button>
            )}
            {waiting && (
              <Button
                variant="danger"
                className={`${big} flex-1 sm:flex-none`}
                disabled={busy}
                onClick={() => setAskReason(true)}
              >
                ✕ {t('registrar.noShow')}
              </Button>
            )}
            {a.status === 'no_show' && (
              <>
                <Button
                  className={`${big} flex-1 sm:flex-none`}
                  disabled={busy}
                  onClick={() => change.mutate({ s: 'arrived' })}
                >
                  {t('registrar.cameLate')}
                </Button>
                <Button variant="ghost" disabled={busy} onClick={() => change.mutate({ s: 'scheduled' })}>
                  {t('registrar.undo')}
                </Button>
              </>
            )}
            {a.status === 'arrived' && (
              <Button variant="ghost" disabled={busy} onClick={() => change.mutate({ s: 'confirmed' })}>
                {t('registrar.undo')}
              </Button>
            )}
          </div>
        )}
      </div>
      {askReason && (
        <div className="mt-3">
          <NoShowReasons
            big
            disabled={busy}
            onPick={(reason) => change.mutate({ s: 'no_show', reason })}
            onCancel={() => setAskReason(false)}
          />
        </div>
      )}
      <ErrorText error={change.error} />
    </li>
  )
}

/** TZ 4.3 "Registrator ekrani": today's patients of the branch, one tap for "came" / "didn't come". */
export default function RegistrarToday({
  appointments,
  loading,
  onOpen,
  onWalkIn,
}: {
  appointments: Appointment[]
  loading: boolean
  onOpen: (a: Appointment) => void
  onWalkIn: () => void
}) {
  const { t } = useTranslation()
  const now = useNowMinutes()
  const [q, setQ] = useState('')
  const [bucket, setBucket] = useState<Bucket | ''>('')
  const [showCancelled, setShowCancelled] = useState(false)

  const live = appointments.filter((a) => BUCKET[a.status])
  const counts = {
    waiting: live.filter((a) => BUCKET[a.status] === 'waiting').length,
    arrived: live.filter((a) => BUCKET[a.status] === 'arrived').length,
    no_show: live.filter((a) => BUCKET[a.status] === 'no_show').length,
  }
  const cancelled = appointments.filter((a) => a.status === 'cancelled')

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase()
    const needleDigits = digits(needle)
    return (showCancelled ? [...live, ...cancelled] : live)
      .filter((a) => !bucket || BUCKET[a.status] === bucket)
      .filter(
        (a) =>
          !needle ||
          a.patient_name.toLowerCase().includes(needle) ||
          (needleDigits.length >= 3 && digits(a.patient_phone ?? '').includes(needleDigits)),
      )
      .sort((x, y) => x.starts_at.localeCompare(y.starts_at))
  }, [live, cancelled, q, bucket, showCancelled])

  // grouped by the hour the visit starts
  const groups = useMemo(() => {
    const out: { hour: string; items: Appointment[] }[] = []
    for (const a of shown) {
      const hour = `${clinicTime(a.starts_at).slice(0, 2)}:00`
      const last = out[out.length - 1]
      if (last?.hour === hour) last.items.push(a)
      else out.push({ hour, items: [a] })
    }
    return out
  }, [shown])

  const counter = (key: Bucket, tone: string) => (
    <button
      onClick={() => setBucket(bucket === key ? '' : key)}
      aria-pressed={bucket === key}
      className={`rounded-lg border px-4 py-3 text-left transition-colors ${
        bucket === key ? 'border-teal-600 ring-2 ring-teal-600/20' : 'border-slate-200'
      } bg-white`}
    >
      <div className={`text-3xl font-semibold tabular-nums ${tone}`}>{counts[key]}</div>
      <div className="text-sm text-slate-600">{t(`registrar.${key}`)}</div>
    </button>
  )

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-2 sm:gap-3">
        {counter('waiting', 'text-sky-800')}
        {counter('arrived', 'text-emerald-700')}
        {counter('no_show', 'text-red-700')}
      </div>
      <div className="flex flex-wrap gap-2">
        <Input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t('registrar.search')}
          className="min-h-12 min-w-0 flex-1 text-base"
        />
        <Button className="min-h-12 px-5 text-base" onClick={onWalkIn}>
          + {t('sched.walkIn')}
        </Button>
      </div>
      {cancelled.length > 0 && (
        <label className="flex items-center gap-2 text-sm text-slate-600">
          <input
            type="checkbox"
            checked={showCancelled}
            onChange={(e) => setShowCancelled(e.target.checked)}
          />
          {t('registrar.showCancelled', { count: cancelled.length })}
        </label>
      )}

      {loading && <p className="py-6 text-center text-sm text-slate-500">{t('app.loading')}</p>}
      {!loading && live.length === 0 && (
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-6 text-center">
          <p className="text-slate-600">{t('registrar.empty')}</p>
          <Button className="mt-3" onClick={onWalkIn}>
            + {t('sched.walkIn')}
          </Button>
        </div>
      )}
      {!loading && live.length > 0 && shown.length === 0 && (
        <p className="py-6 text-center text-sm text-slate-500">{t('registrar.nothingFound')}</p>
      )}
      {groups.map((g) => (
        <section key={g.hour}>
          <h2 className="mb-2 text-sm font-semibold text-slate-500 tabular-nums">{g.hour}</h2>
          <ul className="space-y-2">
            {g.items.map((a) => (
              <PatientCard key={a.id} a={a} now={now} onOpen={() => onOpen(a)} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}
