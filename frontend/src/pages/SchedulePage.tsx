import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router'
import AppointmentPanel, { StatusActions, StatusPill } from '../components/AppointmentPanel'
import BookingDialog from '../components/BookingDialog'
import PatientName from '../components/PatientName'
import RegistrarToday from '../components/RegistrarToday'
import ScheduleWeek from '../components/ScheduleWeek'
import { Button, Card, ErrorText, Input, Select } from '../components/ui'
import { useAuth } from '../lib/auth-context'
import { formatPhone } from '../lib/patients'
import {
  INACTIVE_STATUSES,
  STATUS_STYLE,
  addDays,
  branchName,
  clinicDate,
  clinicMinutes,
  clinicTime,
  defaultBranchId,
  formatDay,
  formatShortDay,
  getBranches,
  getDay,
  getDayColumns,
  getRange,
  getResources,
  getScheduleRange,
  minToHhmm,
  serviceName,
  weekStart,
  type Appointment,
  type AppointmentStatus,
} from '../lib/scheduling'

const PX_PER_MIN = 1.4
const STEP = 15
type Mode = 'today' | 'day' | 'week'
const MODES: Mode[] = ['today', 'day', 'week']
const STATUS_FILTERS: AppointmentStatus[] = [
  'scheduled',
  'confirmed',
  'arrived',
  'completed',
  'no_show',
  'cancelled',
]

/** One grid column: a doctor, or a room / device (TZ 4.3 "ustunlar shifokorlar yoki kabinetlar"). */
type Column = {
  key: string
  name: string
  sub?: string
  color: string | null
  /** working hours; null = the whole visible day is open (rooms, devices) */
  windows: { starts_at: string; ends_at: string }[] | null
  doctorId?: string
  match: (a: Appointment) => boolean
}

/** Side-by-side lanes for visits that overlap in one column (rooms, "no room", cancelled ones). */
function layoutLanes(items: Appointment[]) {
  const out = new Map<string, { lane: number; lanes: number }>()
  const sorted = [...items].sort((a, b) => Date.parse(a.starts_at) - Date.parse(b.starts_at))
  let cluster: { id: string; lane: number }[] = []
  let laneEnds: number[] = []
  let clusterEnd = 0
  const flush = () => {
    for (const c of cluster) out.set(c.id, { lane: c.lane, lanes: laneEnds.length })
    cluster = []
    laneEnds = []
  }
  for (const a of sorted) {
    const start = Date.parse(a.starts_at)
    const end = Date.parse(a.ends_at)
    if (cluster.length && start >= clusterEnd) flush()
    let lane = laneEnds.findIndex((e) => e <= start)
    if (lane === -1) {
      lane = laneEnds.length
      laneEnds.push(end)
    } else laneEnds[lane] = end
    cluster.push({ id: a.id, lane })
    clusterEnd = cluster.length === 1 ? end : Math.max(clusterEnd, end)
  }
  flush()
  return out
}

function Grid({
  columns,
  appointments,
  date,
  showDoctor,
  onSlot,
  onOpen,
}: {
  columns: Column[]
  appointments: Appointment[]
  date: string
  showDoctor: boolean
  onSlot: (col: Column, time: string) => void
  onOpen: (a: Appointment) => void
}) {
  const { i18n } = useTranslation()
  // visible range: working hours and bookings, padded to whole hours (default 08-18)
  const edges = [
    ...columns.flatMap((c) =>
      (c.windows ?? []).flatMap((w) => [clinicMinutes(w.starts_at), clinicMinutes(w.ends_at)]),
    ),
    ...appointments.flatMap((a) => [clinicMinutes(a.starts_at), clinicMinutes(a.ends_at)]),
  ]
  const from = Math.floor(Math.min(8 * 60, ...edges) / 60) * 60
  const to = Math.ceil(Math.max(18 * 60, ...edges) / 60) * 60
  const height = (to - from) * PX_PER_MIN
  const rows = Array.from({ length: (to - from) / STEP }, (_, i) => from + i * STEP)
  const visible = appointments.filter((a) => a.status !== 'rescheduled' && clinicDate(a.starts_at) === date)

  return (
    <div className="overflow-x-auto">
      <div className="flex min-w-max">
        <div className="w-14 shrink-0 pt-11">
          <div className="relative" style={{ height }}>
            {rows
              .filter((m) => m % 60 === 0)
              .map((m) => (
                <div
                  key={m}
                  className="absolute right-2 -translate-y-2 text-xs text-slate-500"
                  style={{ top: (m - from) * PX_PER_MIN }}
                >
                  {minToHhmm(m)}
                </div>
              ))}
          </div>
        </div>
        {columns.map((col) => {
          const items = visible.filter(col.match)
          const lanes = layoutLanes(items)
          const maxLanes = Math.max(1, ...[...lanes.values()].map((l) => l.lanes))
          return (
            <div
              key={col.key}
              className="shrink-0 border-l border-slate-200"
              style={{ width: `${11 * Math.min(maxLanes, 3)}rem` }}
            >
              <div
                className="h-11 border-b border-slate-200 px-2 py-1 text-sm font-medium"
                style={col.color ? { borderTop: `3px solid ${col.color}` } : undefined}
                title={col.name}
              >
                <div className="truncate">{col.name}</div>
                {col.sub && <div className="truncate text-xs font-normal text-slate-500">{col.sub}</div>}
              </div>
              <div className={`relative ${col.windows ? 'bg-slate-100' : 'bg-white'}`} style={{ height }}>
                {col.windows?.map((w) => (
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
                    aria-label={`${col.name} ${minToHhmm(m)}`}
                    className={`absolute inset-x-0 border-t hover:bg-teal-50/70 ${m % 60 === 0 ? 'border-slate-200' : 'border-slate-100'}`}
                    style={{ top: (m - from) * PX_PER_MIN, height: STEP * PX_PER_MIN }}
                    onClick={() => onSlot(col, minToHhmm(m))}
                  />
                ))}
                {items.map((a) => {
                  const { lane, lanes: n } = lanes.get(a.id) ?? { lane: 0, lanes: 1 }
                  return (
                    <button
                      key={a.id}
                      onClick={() => onOpen(a)}
                      className={`absolute overflow-hidden rounded border-l-4 px-1.5 py-0.5 text-left text-xs shadow-sm ${STATUS_STYLE[a.status]}`}
                      style={{
                        left: `calc(${(lane / n) * 100}% + 2px)`,
                        width: `calc(${100 / n}% - 4px)`,
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
                      {showDoctor && <div className="truncate opacity-80">{a.doctor_name}</div>}
                      <div className="truncate opacity-80">
                        {a.services.map((s) => serviceName(s, i18n.language)).join(', ')}
                      </div>
                    </button>
                  )
                })}
              </div>
            </div>
          )
        })}
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
      <table className="w-full min-w-[860px] text-left text-sm">
        <thead className="text-xs text-slate-500 uppercase">
          <tr>
            <th className="pb-2 font-medium">{t('schedule.time')}</th>
            <th className="pb-2 font-medium">{t('schedule.patient')}</th>
            <th className="pb-2 font-medium">{t('schedule.doctor')}</th>
            <th className="pb-2 font-medium">{t('sched.resource')}</th>
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
              <td className="py-2 pr-3 text-slate-600">{a.resource_name ?? '—'}</td>
              <td className="py-2 pr-3">{a.services.map((s) => serviceName(s, i18n.language)).join(', ')}</td>
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
  const { user } = useAuth()
  const [params, setParams] = useSearchParams()
  const isRegistrar = user?.role === 'registrar'
  const mode: Mode = MODES.find((m) => m === params.get('mode')) ?? (isRegistrar ? 'today' : 'day')
  const date = mode === 'today' ? clinicDate() : (params.get('date') ?? clinicDate())
  const view = params.get('view') === 'list' ? 'list' : 'grid'
  const cols = params.get('cols') === 'resources' ? 'resources' : 'doctors'
  const doctorFilter = params.get('doctor') ?? ''
  const statusFilter = (params.get('status') ?? '') as AppointmentStatus | ''
  const openedId = params.get('open')
  const week = weekStart(date)

  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn: getBranches,
    staleTime: 300_000,
  })
  const branchId = params.get('branch') ?? defaultBranchId(branches, user?.branch_id)
  const [booking, setBooking] = useState<{ doctorId?: string; time?: string; walkIn?: boolean } | null>(null)

  const update = (changes: Record<string, string | null>) =>
    setParams((prev) => {
      const next = new URLSearchParams(prev)
      for (const [k, v] of Object.entries(changes)) {
        if (v) next.set(k, v)
        else next.delete(k)
      }
      return next
    })
  // another day, branch or screen: the open panel doesn't belong to it
  const set = (key: string, value: string) => update({ [key]: value, open: null })
  const open = (a: Appointment) => update({ open: a.id })

  const columns = useQuery({
    queryKey: ['appointments', 'columns', date, branchId],
    queryFn: () => getDayColumns(date, branchId),
    enabled: Boolean(branchId) && mode === 'day',
  })
  const day = useQuery({
    queryKey: ['appointments', 'day', date, branchId],
    queryFn: () => getDay(date, branchId),
    enabled: Boolean(branchId) && mode !== 'week',
    refetchInterval: mode === 'today' ? 30_000 : 60_000,
  })
  const resources = useQuery({
    queryKey: ['resources', branchId],
    queryFn: () => getResources(branchId),
    enabled: Boolean(branchId) && mode === 'day' && cols === 'resources',
    staleTime: 300_000,
  })
  const weekDays = useQuery({
    queryKey: ['appointments', 'week-columns', week, branchId],
    queryFn: () => getScheduleRange(week, branchId),
    enabled: Boolean(branchId) && mode === 'week',
  })
  const weekVisits = useQuery({
    queryKey: ['appointments', 'week', week, branchId],
    queryFn: () => getRange({ dateFrom: week, branchId }),
    enabled: Boolean(branchId) && mode === 'week',
    refetchInterval: 120_000,
  })

  const appointments = day.data ?? []
  const filtered = appointments.filter(
    (a) =>
      (!doctorFilter || a.doctor_id === doctorFilter) &&
      (statusFilter ? a.status === statusFilter : a.status !== 'rescheduled'),
  )
  const active = appointments.filter((a) => !INACTIVE_STATUSES.includes(a.status))
  const opened = openedId ? appointments.find((a) => a.id === openedId) : undefined

  // doctors known today (columns + anyone booked) for the doctor filter
  const doctorOptions = new Map<string, string>()
  for (const c of columns.data ?? []) doctorOptions.set(c.doctor_id, c.doctor_name)
  for (const d of weekDays.data ?? [])
    for (const c of d.doctors) doctorOptions.set(c.doctor_id, c.doctor_name)
  for (const a of appointments) doctorOptions.set(a.doctor_id, a.doctor_name)

  const gridColumns: Column[] =
    cols === 'resources'
      ? [
          ...(resources.data ?? [])
            .filter((r) => r.is_active)
            .map<Column>((r) => ({
              key: r.id,
              name: r.name,
              sub: r.kind === 'device' ? t('settings.device') : t('settings.room'),
              color: null,
              windows: null,
              match: (a) => a.resource_id === r.id,
            })),
          {
            key: 'none',
            name: t('sched.unassigned'),
            sub: t('sched.unassignedHint'),
            color: null,
            windows: null,
            match: (a) => !a.resource_id,
          },
        ]
      : (columns.data ?? [])
          .filter((c) => !doctorFilter || c.doctor_id === doctorFilter)
          .map((c) => ({
            key: c.doctor_id,
            name: c.doctor_name,
            color: c.color,
            windows: c.windows,
            doctorId: c.doctor_id,
            match: (a: Appointment) => a.doctor_id === c.doctor_id,
          }))

  const branchSelect = (
    <Select
      value={branchId}
      onChange={(e) => set('branch', e.target.value)}
      className="min-w-0 flex-1 sm:w-56 sm:flex-none"
      aria-label={t('schedule.branch')}
    >
      {branches
        .filter((b) => b.is_active)
        .map((b) => (
          <option key={b.id} value={b.id}>
            {branchName(b, i18n.language)}
          </option>
        ))}
    </Select>
  )
  const step = mode === 'week' ? 7 : 1

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">
          {mode === 'today' ? t('registrar.title') : t('schedule.title')}
        </h1>
        <div className="flex flex-wrap gap-2">
          <div className="inline-flex rounded-md border border-slate-300 bg-white p-0.5" role="tablist">
            {MODES.map((m) => (
              <button
                key={m}
                role="tab"
                aria-selected={mode === m}
                onClick={() => update({ mode: m, open: null, ...(m === 'today' ? { date: null } : {}) })}
                className={`rounded px-3 py-1.5 text-sm ${mode === m ? 'bg-teal-700 font-medium text-white' : 'text-slate-700 hover:bg-slate-100'}`}
              >
                {t(`sched.mode.${m}`)}
              </button>
            ))}
          </div>
          {mode !== 'today' && <Button onClick={() => setBooking({})}>{t('booking.title')}</Button>}
        </div>
      </div>

      {branches.length === 0 && !day.isPending && (
        <Card>
          <p className="text-sm text-slate-600">{t('sched.noBranches')}</p>
          {user?.role === 'admin' && (
            <Link
              to="/settings"
              className="mt-2 inline-block text-sm font-medium text-teal-800 hover:underline"
            >
              {t('nav.settings')} →
            </Link>
          )}
        </Card>
      )}

      {mode === 'today' ? (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-base font-medium">{formatDay(date, i18n.language)}</span>
            <div className="flex w-full sm:ml-auto sm:w-auto">{branchSelect}</div>
          </div>
          <ErrorText error={day.error} />
          <RegistrarToday
            appointments={appointments}
            loading={day.isPending && Boolean(branchId)}
            onOpen={open}
            onWalkIn={() => setBooking({ walkIn: true })}
          />
        </>
      ) : (
        <>
          <Card>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="secondary"
                onClick={() => set('date', addDays(date, -step))}
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
                onClick={() => set('date', addDays(date, step))}
                aria-label={t('app.next')}
              >
                →
              </Button>
              <Button variant="ghost" onClick={() => set('date', clinicDate())}>
                {t('schedule.today')}
              </Button>
              <span className="text-sm font-medium">
                {mode === 'week'
                  ? `${formatShortDay(week, i18n.language)} – ${formatShortDay(addDays(week, 6), i18n.language)}`
                  : formatDay(date, i18n.language)}
              </span>
              <div className="flex w-full flex-wrap gap-2 sm:ml-auto sm:w-auto">{branchSelect}</div>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Select
                value={doctorFilter}
                onChange={(e) => set('doctor', e.target.value)}
                className="min-w-0 flex-1 sm:w-56 sm:flex-none"
                aria-label={t('schedule.doctor')}
              >
                <option value="">{t('sched.allDoctors')}</option>
                {[...doctorOptions].map(([id, name]) => (
                  <option key={id} value={id}>
                    {name}
                  </option>
                ))}
              </Select>
              {mode === 'day' && (
                <>
                  <Select
                    value={statusFilter}
                    onChange={(e) => set('status', e.target.value)}
                    className="min-w-0 flex-1 sm:w-48 sm:flex-none"
                    aria-label={t('schedule.status')}
                  >
                    <option value="">{t('sched.allStatuses')}</option>
                    {STATUS_FILTERS.map((s) => (
                      <option key={s} value={s}>
                        {t(`appt.${s}`)}
                      </option>
                    ))}
                  </Select>
                  <Select
                    value={cols}
                    onChange={(e) => set('cols', e.target.value)}
                    className="w-full sm:w-52"
                    aria-label={t('sched.columns')}
                    disabled={view === 'list'}
                  >
                    <option value="doctors">{t('sched.colsDoctors')}</option>
                    <option value="resources">{t('sched.colsResources')}</option>
                  </Select>
                  <Select value={view} onChange={(e) => set('view', e.target.value)} className="w-32">
                    <option value="grid">{t('schedule.grid')}</option>
                    <option value="list">{t('schedule.list')}</option>
                  </Select>
                </>
              )}
            </div>
            <p className="mt-2 text-xs text-slate-500">
              {mode === 'day'
                ? `${t('schedule.count', { count: active.length })}${view === 'grid' ? ` · ${t('schedule.clickToBook')}` : ''}`
                : t('sched.weekHint')}
            </p>
          </Card>

          <ErrorText
            error={columns.error ?? day.error ?? weekDays.error ?? weekVisits.error ?? resources.error}
          />
          <Card>
            {mode === 'week' ? (
              weekDays.isPending || weekVisits.isPending ? (
                <p className="py-6 text-center text-sm text-slate-500">{t('app.loading')}</p>
              ) : (
                <ScheduleWeek
                  start={week}
                  days={weekDays.data ?? []}
                  appointments={weekVisits.data ?? []}
                  doctorFilter={doctorFilter}
                  onOpenDay={(d, doctorId) =>
                    update({ mode: 'day', date: d, doctor: doctorId ?? doctorFilter, open: null })
                  }
                />
              )
            ) : view === 'list' ? (
              <List appointments={filtered} onOpen={open} />
            ) : cols === 'resources' && resources.data && resources.data.every((r) => !r.is_active) ? (
              <div className="py-6 text-center text-sm text-slate-500">
                <p>{t('sched.noRooms')}</p>
                {user?.role === 'admin' && (
                  <Link
                    to="/settings?tab=resources"
                    className="mt-2 inline-block font-medium text-teal-800 hover:underline"
                  >
                    {t('settings.resources')} →
                  </Link>
                )}
              </div>
            ) : cols === 'doctors' && columns.data && columns.data.length === 0 ? (
              <div className="py-6 text-center text-sm text-slate-500">
                <p>{t('schedule.noDoctors')}</p>
                {(user?.role === 'admin' || user?.role === 'supervisor') && (
                  <Link
                    to="/settings"
                    className="mt-2 inline-block font-medium text-teal-800 hover:underline"
                  >
                    {t('settings.doctors')} →
                  </Link>
                )}
              </div>
            ) : (
              <Grid
                columns={gridColumns}
                appointments={filtered}
                date={date}
                showDoctor={cols === 'resources'}
                onSlot={(col, time) => setBooking({ doctorId: col.doctorId, time })}
                onOpen={open}
              />
            )}
          </Card>
        </>
      )}

      {booking && (
        <BookingDialog
          branchId={branchId}
          doctorId={booking.doctorId}
          walkIn={booking.walkIn}
          at={booking.time ? { date, time: booking.time } : undefined}
          onClose={() => setBooking(null)}
        />
      )}
      {opened && <AppointmentPanel a={opened} onClose={() => update({ open: null })} />}
    </div>
  )
}
