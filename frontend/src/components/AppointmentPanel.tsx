import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { formatDateTime, formatPhone } from '../lib/patients'
import {
  CANCEL_REASONS,
  NEXT_ACTIONS,
  NO_SHOW_REASONS,
  STATUS_STYLE,
  clinicDate,
  clinicTime,
  formatDay,
  formatPrice,
  getResources,
  serviceName,
  setAppointmentResource,
  setAppointmentStatus,
  useReasonLabel,
  type Appointment,
  type AppointmentStatus,
} from '../lib/scheduling'
import BookingDialog from './BookingDialog'
import PatientName from './PatientName'
import { Button, ErrorText, Field, Modal, Select } from './ui'

export function StatusPill({ status }: { status: AppointmentStatus }) {
  const { t } = useTranslation()
  return (
    <span className={`inline-block rounded border px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[status]}`}>
      {t(`appt.${status}`)}
    </span>
  )
}

/** Reason chips shown when a visit is marked "didn't come" (TZ 4.3). */
export function NoShowReasons({
  onPick,
  onCancel,
  disabled,
  big,
}: {
  onPick: (reason: string) => void
  onCancel: () => void
  disabled?: boolean
  big?: boolean
}) {
  const { t } = useTranslation()
  return (
    <div className="rounded-md border border-red-200 bg-red-50/60 p-2">
      <p className="mb-2 text-xs font-medium text-red-900">{t('sched.noShowWhy')}</p>
      <div className="flex flex-wrap gap-1.5">
        {NO_SHOW_REASONS.map((r) => (
          <Button
            key={r}
            variant="secondary"
            disabled={disabled}
            onClick={() => onPick(r)}
            className={big ? 'min-h-11 px-3 text-sm' : 'px-2 py-1 text-xs'}
          >
            {t(`noShowReasons.${r}`)}
          </Button>
        ))}
        <Button variant="ghost" onClick={onCancel} className={big ? 'min-h-11' : 'px-2 py-1 text-xs'}>
          {t('patients.cancel')}
        </Button>
      </div>
    </div>
  )
}

/** Quick status buttons used in lists (registrar / doctor). */
export function StatusActions({ a, allowed }: { a: Appointment; allowed?: AppointmentStatus[] }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [askReason, setAskReason] = useState(false)
  const change = useMutation({
    mutationFn: ({ s, reason }: { s: AppointmentStatus; reason?: string }) =>
      setAppointmentStatus(a.id, s, reason),
    onSuccess: () => {
      setAskReason(false)
      void queryClient.invalidateQueries({ queryKey: ['appointments'] })
    },
  })
  const actions = NEXT_ACTIONS[a.status].filter((s) => !allowed || allowed.includes(s))
  if (askReason) {
    return (
      <span className="block">
        <NoShowReasons
          disabled={change.isPending}
          onPick={(reason) => change.mutate({ s: 'no_show', reason })}
          onCancel={() => setAskReason(false)}
        />
        <ErrorText error={change.error} />
      </span>
    )
  }
  return (
    <span className="inline-flex flex-wrap gap-1">
      {actions.map((s) => (
        <Button
          key={s}
          variant={s === 'no_show' ? 'danger' : 'secondary'}
          disabled={change.isPending}
          onClick={() => (s === 'no_show' ? setAskReason(true) : change.mutate({ s }))}
          className="px-2 py-1 text-xs"
        >
          {t(`apptAction.${s}`)}
        </Button>
      ))}
      <ErrorText error={change.error} />
    </span>
  )
}

function ResourcePicker({ a }: { a: Appointment }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { data: resources = [] } = useQuery({
    queryKey: ['resources', a.branch_id],
    queryFn: () => getResources(a.branch_id),
    staleTime: 300_000,
  })
  const save = useMutation({
    mutationFn: (id: string | null) => setAppointmentResource(a.id, id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['appointments'] }),
  })
  const current = resources.find((r) => r.id === a.resource_id)
  // a device visit can only move to another device of the same type; others go into rooms
  const options = resources.filter(
    (r) =>
      r.is_active &&
      (current?.kind === 'device'
        ? r.kind === 'device' && r.device_type === current.device_type
        : r.kind === 'room'),
  )
  const editable = ['scheduled', 'confirmed', 'arrived'].includes(a.status)
  if (!editable) return <span>{a.resource_name ?? '—'}</span>
  return (
    <span className="block">
      <Select
        value={a.resource_id ?? ''}
        disabled={save.isPending}
        onChange={(e) => save.mutate(e.target.value || null)}
        className="py-1 text-sm"
        aria-label={t('sched.resource')}
      >
        {current?.kind !== 'device' && <option value="">{t('sched.noRoom')}</option>}
        {current && !options.includes(current) && <option value={current.id}>{current.name}</option>}
        {options.map((r) => (
          <option key={r.id} value={r.id}>
            {r.name}
          </option>
        ))}
      </Select>
      {resources.length === 0 && (
        <span className="mt-1 block text-xs text-slate-500">{t('sched.noRooms')}</span>
      )}
      <ErrorText error={save.error} />
    </span>
  )
}

/** Link to another visit on the schedule (moved from / moved to). */
function VisitLink({ id, startsAt, branchId }: { id: string; startsAt: string; branchId: string }) {
  const { i18n } = useTranslation()
  const date = clinicDate(startsAt)
  return (
    <Link
      to={`/schedule?date=${date}&branch=${branchId}&mode=day&open=${id}`}
      className="text-teal-800 hover:underline"
    >
      {formatDay(date, i18n.language)}, {clinicTime(startsAt)}
    </Link>
  )
}

export default function AppointmentPanel({ a, onClose }: { a: Appointment; onClose: () => void }) {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const reasonLabel = useReasonLabel()
  const [cancelling, setCancelling] = useState(false)
  const [reason, setReason] = useState<string>(CANCEL_REASONS[0])
  const [rescheduling, setRescheduling] = useState(false)
  const cancel = useMutation({
    mutationFn: () => setAppointmentStatus(a.id, 'cancelled', reason),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['appointments'] })
      onClose()
    },
  })
  const open = ['scheduled', 'confirmed', 'no_show'].includes(a.status)
  const total = a.services.reduce((sum, s) => sum + (s.price ?? 0), 0)
  const hasPrices = a.services.some((s) => s.price != null)

  if (rescheduling) {
    return <BookingDialog reschedule={a} onClose={onClose} />
  }
  return (
    <Modal title={t('schedule.details')} onClose={onClose}>
      <div className="space-y-4 text-sm">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <Link
            to={`/patients/${a.patient_id}`}
            className="text-base font-semibold text-teal-800 hover:underline"
          >
            <PatientName name={a.patient_name} />
          </Link>
          {a.patient_phone && (
            <a href={`tel:${a.patient_phone}`} className="text-slate-600 hover:underline">
              {formatPhone(a.patient_phone)}
            </a>
          )}
          <StatusPill status={a.status} />
        </div>
        {a.cancel_reason && (
          <p className="rounded-md bg-slate-50 px-3 py-2 text-slate-700">
            {t(a.status === 'no_show' ? 'sched.noShowReason' : 'schedule.cancelReason')}:{' '}
            <span className="font-medium">{reasonLabel(a.status, a.cancel_reason)}</span>
          </p>
        )}
        <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <dt className="text-xs text-slate-500">{t('schedule.time')}</dt>
            <dd>
              {formatDay(clinicDate(a.starts_at), i18n.language)}, {clinicTime(a.starts_at)}–
              {clinicTime(a.ends_at)}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">{t('schedule.doctor')}</dt>
            <dd>{a.doctor_name}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">{t('sched.resource')}</dt>
            <dd>
              <ResourcePicker a={a} />
            </dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">{t('booking.source')}</dt>
            <dd>{a.source ? t(`sources.${a.source}`) : '—'}</dd>
          </div>
          <div className="sm:col-span-2">
            <dt className="mb-1 text-xs text-slate-500">{t('schedule.services')}</dt>
            <dd>
              <ul className="divide-y divide-slate-100 rounded-md border border-slate-200">
                {a.services.map((s) => (
                  <li key={s.service_id} className="flex items-start justify-between gap-3 px-3 py-1.5">
                    <span>
                      {serviceName(s, i18n.language)}{' '}
                      <span className="text-xs text-slate-500">
                        · {t('sched.minutes', { count: s.duration_min })}
                      </span>
                    </span>
                    <span className="whitespace-nowrap tabular-nums">{formatPrice(s.price)}</span>
                  </li>
                ))}
                {a.services.length > 1 && hasPrices && (
                  <li className="flex justify-between px-3 py-1.5 font-medium">
                    <span>{t('sched.total')}</span>
                    <span className="tabular-nums">{formatPrice(total)}</span>
                  </li>
                )}
              </ul>
            </dd>
          </div>
          {a.note && (
            <div className="sm:col-span-2">
              <dt className="text-xs text-slate-500">{t('schedule.note')}</dt>
              <dd className="whitespace-pre-line">{a.note}</dd>
            </div>
          )}
          {a.rescheduled_from_id && a.rescheduled_from_starts_at && (
            <div>
              <dt className="text-xs text-slate-500">{t('sched.movedFrom')}</dt>
              <dd>
                <VisitLink
                  id={a.rescheduled_from_id}
                  startsAt={a.rescheduled_from_starts_at}
                  branchId={a.branch_id}
                />
              </dd>
            </div>
          )}
          {a.rescheduled_to_id && a.rescheduled_to_starts_at && (
            <div>
              <dt className="text-xs text-slate-500">{t('sched.movedTo')}</dt>
              <dd>
                <VisitLink
                  id={a.rescheduled_to_id}
                  startsAt={a.rescheduled_to_starts_at}
                  branchId={a.branch_id}
                />
              </dd>
            </div>
          )}
          <div className="text-xs text-slate-500 sm:col-span-2">
            {t('sched.createdBy', {
              who: a.created_by_name ?? t('sched.system'),
              when: a.created_at ? formatDateTime(a.created_at) : '—',
            })}
            {a.status_changed_at && (
              <span> · {t('sched.statusChanged', { when: formatDateTime(a.status_changed_at) })}</span>
            )}
          </div>
        </dl>

        <StatusActions a={a} />

        {open && !cancelling && (
          <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-3">
            <Button variant="secondary" onClick={() => setRescheduling(true)}>
              {t('schedule.reschedule')}
            </Button>
            <Button variant="danger" onClick={() => setCancelling(true)}>
              {t('schedule.cancel')}
            </Button>
          </div>
        )}
        {cancelling && (
          <div className="flex flex-wrap items-end gap-2 border-t border-slate-100 pt-3">
            <Field label={t('schedule.cancelReason')}>
              <Select value={reason} onChange={(e) => setReason(e.target.value)}>
                {CANCEL_REASONS.map((r) => (
                  <option key={r} value={r}>
                    {t(`cancelReasons.${r}`)}
                  </option>
                ))}
              </Select>
            </Field>
            <Button variant="danger" disabled={cancel.isPending} onClick={() => cancel.mutate()}>
              {t('schedule.cancel')}
            </Button>
            <Button variant="ghost" onClick={() => setCancelling(false)}>
              {t('patients.cancel')}
            </Button>
          </div>
        )}
        <ErrorText error={cancel.error} />
      </div>
    </Modal>
  )
}
