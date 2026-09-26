import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router'
import AppointmentPanel, { StatusActions, StatusPill } from '../components/AppointmentPanel'
import BookingDialog from '../components/BookingDialog'
import PatientName from '../components/PatientName'
import { formatPhone } from '../lib/patients'
import { Button, Card, ErrorText, Input, Select } from '../components/ui'
import {
  STATUS_STYLE,
  addDays,
  clinicDate,
  clinicMinutes,
  clinicTime,
  formatDay,
  getBranches,
  getDay,
  getDayColumns,
  type Appointment,
  type DoctorDay,
} from '../lib/scheduling'

const PX_PER_MIN = 1.4
const STEP = 15

function toHHMM(minutes: number) {
  return `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`
}

function Grid({
  columns,
  appointments,
  date,
  onSlot,
  onOpen,
}: {
  columns: DoctorDay[]
  appointments: Appointment[]
  date: string
  onSlot: (doctorId: string, time: string) => void
  onOpen: (a: Appointment) => void
}) {
  const { i18n } = useTranslation()
  // visible range: working hours and bookings, padded to whole hours (default 08-18)
  const edges = [
    ...columns.flatMap((c) =>
      c.windows.flatMap((w) => [clinicMinutes(w.starts_at), clinicMinutes(w.ends_at)]),
    ),
    ...appointments.flatMap((a) => [clinicMinutes(a.starts_at), clinicMinutes(a.ends_at)]),
  ]
  const from = Math.floor(Math.min(8 * 60, ...edges) / 60) * 60
  const to = Math.ceil(Math.max(18 * 60, ...edges) / 60) * 60
  const height = (to - from) * PX_PER_MIN
  const rows = Array.from({ length: (to - from) / STEP }, (_, i) => from + i * STEP)
  const visible = appointments.filter((a) => a.status !== 'rescheduled')

  return (
    <div className="overflow-x-auto">
      <div className="flex min-w-max">
        <div className="w-14 shrink-0 pt-9">
          <div className="relative" style={{ height }}>
            {rows
              .filter((m) => m % 60 === 0)
              .map((m) => (
                <div
                  key={m}
                  className="absolute right-2 -translate-y-2 text-xs text-slate-500"
                  style={{ top: (m - from) * PX_PER_MIN }}
                >
                  {toHHMM(m)}
                </div>
              ))}
          </div>
        </div>
        {columns.map((col) => (
          <div key={col.doctor_id} className="w-44 shrink-0 border-l border-slate-200">
            <div
              className="h-9 truncate border-b border-slate-200 px-2 py-2 text-sm font-medium"
              style={col.color ? { borderTop: `3px solid ${col.color}` } : undefined}
              title={col.doctor_name}
            >
              {col.doctor_name}
            </div>
            <div className="relative bg-slate-100" style={{ height }}>
              {col.windows.map((w) => (
                <div
                  key={w.starts_at}
                  className="absolute inset-x-0 bg-white"
                  style={{
                    top: (clinicMinutes(w.starts_at) - from) * PX_PER_MIN,
                    height: (clinicMinutes(w.ends_at) - clinicMinutes(w.starts_at)) * PX_PER_MIN,
                  }}
                />
              ))}
              {rows.map((m) => (
                <button
                  key={m}
                  aria-label={`${col.doctor_name} ${toHHMM(m)}`}
                  className={`absolute inset-x-0 border-t hover:bg-teal-50/70 ${m % 60 === 0 ? 'border-slate-200' : 'border-slate-100'}`}
                  style={{ top: (m - from) * PX_PER_MIN, height: STEP * PX_PER_MIN }}
                  onClick={() => onSlot(col.doctor_id, toHHMM(m))}
                />
              ))}
              {visible
                .filter((a) => a.doctor_id === col.doctor_id && clinicDate(a.starts_at) === date)
                .map((a) => (
                  <button
                    key={a.id}
                    onClick={() => onOpen(a)}
                    className={`absolute inset-x-1 overflow-hidden rounded border-l-4 px-1.5 py-0.5 text-left text-xs shadow-sm ${STATUS_STYLE[a.status]}`}
                    style={{
                      top: (clinicMinutes(a.starts_at) - from) * PX_PER_MIN + 1,
                      height: Math.max(
                        (clinicMinutes(a.ends_at) - clinicMinutes(a.starts_at)) * PX_PER_MIN - 2,
                        16,
                      ),
                    }}
                    title={`${clinicTime(a.starts_at)} ${a.patient_name}`}
                  >
                    <div className="truncate font-medium">
                      {clinicTime(a.starts_at)} <PatientName name={a.patient_name} />
                    </div>
                    <div className="truncate opacity-80">
                      {a.services.map((s) => (i18n.language === 'ru' ? s.name_ru : s.name_uz)).join(', ')}
                    </div>
                  </button>
                ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function List({ appointments, onOpen }: { appointments: Appointment[]; onOpen: (a: Appointment) => void }) {
  const { t, i18n } = useTranslation()
  if (appointments.length === 0)
    return <p className="py-6 text-center text-sm text-slate-500">{t('schedule.empty')}</p>
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-left text-sm">
        <thead className="text-xs text-slate-500 uppercase">
          <tr>
            <th className="pb-2 font-medium">{t('schedule.time')}</th>
            <th className="pb-2 font-medium">{t('schedule.patient')}</th>
            <th className="pb-2 font-medium">{t('schedule.doctor')}</th>
            <th className="pb-2 font-medium">{t('schedule.services')}</th>
            <th className="pb-2 font-medium">{t('schedule.status')}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {appointments.map((a) => (
            <tr key={a.id} className="border-t border-slate-100 align-top">
              <td className="py-2 pr-3 whitespace-nowrap tabular-nums">
                {clinicTime(a.starts_at)}–{clinicTime(a.ends_at)}
              </td>
              <td className="py-2 pr-3">
                <button className="font-medium text-teal-800 hover:underline" onClick={() => onOpen(a)}>
                  <PatientName name={a.patient_name} />
                </button>
                {a.patient_phone && (
                  <div className="text-xs text-slate-500">{formatPhone(a.patient_phone)}</div>
                )}
              </td>
              <td className="py-2 pr-3">{a.doctor_name}</td>
              <td className="py-2 pr-3">
                {a.services.map((s) => (i18n.language === 'ru' ? s.name_ru : s.name_uz)).join(', ')}
              </td>
              <td className="py-2 pr-3">
                <StatusPill status={a.status} />
              </td>
              <td className="py-2">
                <StatusActions a={a} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function SchedulePage() {
  const { t, i18n } = useTranslation()
  const [params, setParams] = useSearchParams()
  const date = params.get('date') ?? clinicDate()
  const view = params.get('view') === 'list' ? 'list' : 'grid'
  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn: getBranches,
    staleTime: 300_000,
  })
  const branchId = params.get('branch') ?? branches.find((b) => b.is_main)?.id ?? branches[0]?.id ?? ''
  const [booking, setBooking] = useState<{ doctorId?: string; time?: string } | null>(null)
  // only the id: the panel shows the appointment from the refreshed day, not a stale snapshot
  const [openedId, setOpenedId] = useState<string | null>(null)

  const set = (key: string, value: string) =>
    setParams((prev) => {
      const next = new URLSearchParams(prev)
      next.set(key, value)
      return next
    })

  const columns = useQuery({
    queryKey: ['appointments', 'columns', date, branchId],
    queryFn: () => getDayColumns(date, branchId),
    enabled: Boolean(branchId),
  })
  const day = useQuery({
    queryKey: ['appointments', 'day', date, branchId],
    queryFn: () => getDay(date, branchId),
    enabled: Boolean(branchId),
    refetchInterval: 60_000,
  })
  const appointments = day.data ?? []
  const active = appointments.filter((a) => !['cancelled', 'rescheduled'].includes(a.status))
  const opened = openedId ? appointments.find((a) => a.id === openedId) : undefined
  const open = (a: Appointment) => setOpenedId(a.id)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">{t('schedule.title')}</h1>
        <Button onClick={() => setBooking({})}>{t('booking.title')}</Button>
      </div>

      <Card>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="secondary"
            onClick={() => set('date', addDays(date, -1))}
            aria-label={t('app.prev')}
          >
            ←
          </Button>
          <Input
            type="date"
            value={date}
            onChange={(e) => e.target.value && set('date', e.target.value)}
            className="w-40"
          />
          <Button
            variant="secondary"
            onClick={() => set('date', addDays(date, 1))}
            aria-label={t('app.next')}
          >
            →
          </Button>
          <Button variant="ghost" onClick={() => set('date', clinicDate())}>
            {t('schedule.today')}
          </Button>
          <span className="text-sm font-medium">{formatDay(date, i18n.language)}</span>
          <div className="flex w-full flex-wrap gap-2 sm:ml-auto sm:w-auto">
            <Select
              value={branchId}
              onChange={(e) => set('branch', e.target.value)}
              className="min-w-0 flex-1 sm:w-56 sm:flex-none"
            >
              {branches
                .filter((b) => b.is_active)
                .map((b) => (
                  <option key={b.id} value={b.id}>
                    {i18n.language === 'ru' ? b.name_ru : b.name_uz}
                  </option>
                ))}
            </Select>
            <Select value={view} onChange={(e) => set('view', e.target.value)} className="w-32">
              <option value="grid">{t('schedule.grid')}</option>
              <option value="list">{t('schedule.list')}</option>
            </Select>
          </div>
        </div>
        <p className="mt-2 text-xs text-slate-500">
          {t('schedule.count', { count: active.length })}
          {view === 'grid' && ` · ${t('schedule.clickToBook')}`}
        </p>
      </Card>

      <ErrorText error={columns.error ?? day.error} />
      <Card>
        {view === 'list' ? (
          <List appointments={appointments} onOpen={open} />
        ) : columns.data && columns.data.length === 0 ? (
          <p className="py-6 text-center text-sm text-slate-500">{t('schedule.noDoctors')}</p>
        ) : (
          <Grid
            columns={columns.data ?? []}
            appointments={appointments}
            date={date}
            onSlot={(doctorId, time) => setBooking({ doctorId, time })}
            onOpen={open}
          />
        )}
      </Card>

      {booking && (
        <BookingDialog
          branchId={branchId}
          doctorId={booking.doctorId}
          at={booking.time ? { date, time: booking.time } : undefined}
          onClose={() => setBooking(null)}
        />
      )}
      {opened && <AppointmentPanel a={opened} onClose={() => setOpenedId(null)} />}
    </div>
  )
}
