import { useTranslation } from 'react-i18next'
import {
  INACTIVE_STATUSES,
  addDays,
  clinicDate,
  clinicMinutes,
  formatShortDay,
  minToHhmm,
  type Appointment,
  type ScheduleDay,
} from '../lib/scheduling'

type Row = { id: string; name: string; color: string | null }

/** Week view: doctors × 7 days, compact. A click opens that day (optionally for one doctor). */
export default function ScheduleWeek({
  start,
  days,
  appointments,
  doctorFilter,
  onOpenDay,
}: {
  start: string
  days: ScheduleDay[]
  appointments: Appointment[]
  doctorFilter: string
  onOpenDay: (date: string, doctorId?: string) => void
}) {
  const { t, i18n } = useTranslation()
  const weekdays = t('weekdays', { returnObjects: true }) as string[]
  const today = clinicDate()
  const dates = Array.from({ length: 7 }, (_, i) => addDays(start, i))
  const active = appointments.filter((a) => !INACTIVE_STATUSES.includes(a.status))

  // every doctor who works or is booked this week, in the schedule's order
  const rows: Row[] = []
  for (const d of days)
    for (const c of d.doctors)
      if (!rows.some((r) => r.id === c.doctor_id))
        rows.push({ id: c.doctor_id, name: c.doctor_name, color: c.color })
  const shown = doctorFilter ? rows.filter((r) => r.id === doctorFilter) : rows

  const cell = (doctorId: string, date: string) => {
    const col = days.find((d) => d.date === date)?.doctors.find((c) => c.doctor_id === doctorId)
    const visits = active.filter((a) => a.doctor_id === doctorId && clinicDate(a.starts_at) === date)
    const hours = col?.windows.length
      ? `${minToHhmm(clinicMinutes(col.windows[0].starts_at))}–${minToHhmm(
          clinicMinutes(col.windows[col.windows.length - 1].ends_at),
        )}`
      : null
    const arrived = visits.filter((a) => a.status === 'arrived' || a.status === 'completed').length
    const noShow = visits.filter((a) => a.status === 'no_show').length
    return { hours, count: visits.length, arrived, noShow }
  }

  if (shown.length === 0) {
    return <p className="py-6 text-center text-sm text-slate-500">{t('sched.weekEmpty')}</p>
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] table-fixed border-collapse text-sm">
        <thead>
          <tr>
            <th className="w-44 pb-2 text-left text-xs font-medium text-slate-500 uppercase">
              {t('schedule.doctor')}
            </th>
            {dates.map((date, i) => {
              const total = active.filter((a) => clinicDate(a.starts_at) === date).length
              return (
                <th key={date} className="px-1 pb-2">
                  <button
                    onClick={() => onOpenDay(date)}
                    className={`w-full rounded-md px-1 py-1 text-center hover:bg-teal-50 ${
                      date === today ? 'bg-teal-50 text-teal-900' : ''
                    }`}
                  >
                    <div className="text-xs text-slate-500">{weekdays[i]}</div>
                    <div className="font-medium">{formatShortDay(date, i18n.language)}</div>
                    <div className="text-xs font-normal text-slate-500">
                      {t('sched.visits', { count: total })}
                    </div>
                  </button>
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {shown.map((r) => (
            <tr key={r.id} className="border-t border-slate-100">
              <td className="truncate py-1.5 pr-2 font-medium" title={r.name}>
                {r.color && (
                  <span
                    className="mr-2 inline-block h-2.5 w-2.5 rounded-full"
                    style={{ background: r.color }}
                  />
                )}
                {r.name}
              </td>
              {dates.map((date) => {
                const c = cell(r.id, date)
                const off = !c.hours && c.count === 0
                return (
                  <td key={date} className="p-1 align-top">
                    <button
                      onClick={() => onOpenDay(date, r.id)}
                      className={`h-full min-h-14 w-full rounded-md border px-1.5 py-1 text-left text-xs ${
                        off
                          ? 'border-dashed border-slate-200 text-slate-400'
                          : 'border-slate-200 bg-white hover:border-teal-500'
                      }`}
                    >
                      <div className="tabular-nums">{c.hours ?? t('sched.dayOff')}</div>
                      {c.count > 0 && (
                        <div className="mt-0.5 font-medium text-slate-800">
                          {t('sched.visits', { count: c.count })}
                        </div>
                      )}
                      {(c.arrived > 0 || c.noShow > 0) && (
                        <div className="text-[11px]">
                          {c.arrived > 0 && <span className="text-emerald-700">✓{c.arrived} </span>}
                          {c.noShow > 0 && <span className="text-red-700">✕{c.noShow}</span>}
                        </div>
                      )}
                    </button>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
