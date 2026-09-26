import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import {
  CANCEL_REASONS,
  NEXT_ACTIONS,
  STATUS_STYLE,
  clinicDate,
  clinicTime,
  formatDay,
  setAppointmentStatus,
  type Appointment,
  type AppointmentStatus,
} from '../lib/scheduling'
import { formatPhone } from '../lib/patients'
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

/** Quick status buttons used in lists (registrar / doctor). */
export function StatusActions({ a, allowed }: { a: Appointment; allowed?: AppointmentStatus[] }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const change = useMutation({
    mutationFn: (s: AppointmentStatus) => setAppointmentStatus(a.id, s),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['appointments'] }),
  })
  const actions = NEXT_ACTIONS[a.status].filter((s) => !allowed || allowed.includes(s))
  return (
    <span className="inline-flex flex-wrap gap-1">
      {actions.map((s) => (
        <Button
          key={s}
          variant={s === 'no_show' ? 'danger' : 'secondary'}
          disabled={change.isPending}
          onClick={() => change.mutate(s)}
          className="px-2 py-1 text-xs"
        >
          {t(`apptAction.${s}`)}
        </Button>
      ))}
      <ErrorText error={change.error} />
    </span>
  )
}

export default function AppointmentPanel({ a, onClose }: { a: Appointment; onClose: () => void }) {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
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

  if (rescheduling) {
    return <BookingDialog reschedule={a} onClose={onClose} />
  }
  return (
    <Modal title={t('schedule.details')} onClose={onClose}>
      <div className="space-y-4 text-sm">
        <div>
          <Link
            to={`/patients/${a.patient_id}`}
            className="text-base font-semibold text-teal-800 hover:underline"
          >
            <PatientName name={a.patient_name} />
          </Link>
          {a.patient_phone && (
            <a href={`tel:${a.patient_phone}`} className="ml-2 text-slate-600">
              {formatPhone(a.patient_phone)}
            </a>
          )}
        </div>
        <dl className="grid grid-cols-2 gap-3">
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
          <div className="col-span-2">
            <dt className="text-xs text-slate-500">{t('schedule.services')}</dt>
            <dd>{a.services.map((s) => (i18n.language === 'ru' ? s.name_ru : s.name_uz)).join(', ')}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">{t('schedule.status')}</dt>
            <dd>
              <StatusPill status={a.status} />
              {a.cancel_reason && (
                <span className="ml-2 text-xs text-slate-500">
                  {t(`cancelReasons.${a.cancel_reason}`, { defaultValue: a.cancel_reason })}
                </span>
              )}
            </dd>
          </div>
          {a.note && (
            <div className="col-span-2">
              <dt className="text-xs text-slate-500">{t('schedule.note')}</dt>
              <dd className="whitespace-pre-line">{a.note}</dd>
            </div>
          )}
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
          <div className="flex items-end gap-2 border-t border-slate-100 pt-3">
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
          </div>
        )}
        <ErrorText error={cancel.error} />
      </div>
    </Modal>
  )
}
