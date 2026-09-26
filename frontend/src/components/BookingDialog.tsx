import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../lib/auth-context'
import { SOURCES, type PatientListItem, type Source } from '../lib/patients'
import {
  book,
  clinicDate,
  clinicTime,
  findSlots,
  formatDay,
  getBranches,
  getDoctors,
  rescheduleAppointment,
  toClinicIso,
  type Appointment,
  type ServiceItem,
  type Slot,
} from '../lib/scheduling'
import { PatientPicker, ServicePicker } from './Pickers'
import { Button, ErrorText, Field, Input, Modal, Notice, Select } from './ui'

type Props = {
  onClose: () => void
  onDone?: (a: Appointment) => void
  patient?: PatientListItem | null
  branchId?: string
  doctorId?: string
  /** prefilled manual time (from clicking the schedule grid): YYYY-MM-DD + HH:MM */
  at?: { date: string; time: string }
  /** reschedule mode: services/patient come from the appointment */
  reschedule?: Appointment
}

const OVERRIDE_ROLES = ['registrar', 'supervisor', 'admin']

export default function BookingDialog({
  onClose,
  onDone,
  patient: initialPatient,
  branchId,
  doctorId,
  at,
  reschedule,
}: Props) {
  const { t, i18n } = useTranslation()
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn: getBranches,
    staleTime: 300_000,
  })
  const { data: doctors = [] } = useQuery({
    queryKey: ['doctors'],
    queryFn: () => getDoctors(),
    staleTime: 300_000,
  })

  const [patient, setPatient] = useState<PatientListItem | null>(initialPatient ?? null)
  const [services, setServices] = useState<ServiceItem[]>([])
  // a reschedule keeps the original branch (the backend moves only time and doctor)
  const [branch, setBranch] = useState(reschedule?.branch_id ?? branchId ?? '')
  const [doctor, setDoctor] = useState(doctorId ?? reschedule?.doctor_id ?? '')
  const [part, setPart] = useState('')
  const [dateFrom, setDateFrom] = useState(at?.date ?? clinicDate())
  const [manual, setManual] = useState(Boolean(at))
  const [time, setTime] = useState(at?.time ?? '09:00')
  const [outside, setOutside] = useState(false)
  const [source, setSource] = useState<Source | ''>('')
  const [note, setNote] = useState('')
  const [limit, setLimit] = useState(3)
  const [chosen, setChosen] = useState<Slot | null>(null)

  const effectiveBranch = branch || branches.find((b) => b.is_main)?.id || branches[0]?.id || ''
  const serviceIds = reschedule ? reschedule.services.map((s) => s.service_id) : services.map((s) => s.id)
  const patientId = reschedule?.patient_id ?? patient?.id

  const slots = useMutation({
    mutationFn: (lim: number) =>
      findSlots({
        serviceIds,
        branchId: effectiveBranch,
        doctorId: doctor || undefined,
        patientId,
        dateFrom,
        part: part || undefined,
        limit: lim,
        excludeAppointmentId: reschedule?.id,
      }),
    onSuccess: () => setChosen(null),
  })
  /** any change to what the slots were searched for drops the found slots and the choice */
  const refilter =
    <T,>(set: (v: T) => void) =>
    (v: T) => {
      set(v)
      setChosen(null)
      setLimit(3)
      slots.reset()
    }

  const done = (a: Appointment) => {
    void queryClient.invalidateQueries({ queryKey: ['appointments'] })
    void queryClient.invalidateQueries({ queryKey: ['patient'] })
    void queryClient.invalidateQueries({ queryKey: ['tasks'] })
    void queryClient.invalidateQueries({ queryKey: ['leads'] })
    onDone?.(a)
  }
  const submit = useMutation({
    mutationFn: () => {
      const startsAt = manual ? toClinicIso(dateFrom, time) : chosen!.starts_at
      const doctorId = manual ? doctor : chosen!.doctor_id
      if (reschedule) return rescheduleAppointment(reschedule.id, startsAt, doctorId || undefined)
      return book({
        patient_id: patientId!,
        branch_id: effectiveBranch,
        doctor_id: doctorId,
        service_ids: serviceIds,
        starts_at: startsAt,
        source: source || null,
        note: note.trim() || null,
        allow_outside_hours: manual && outside,
      })
    },
    onSuccess: done,
  })

  const ready = Boolean(patientId && serviceIds.length && effectiveBranch)
  const canSubmit = ready && (manual ? Boolean(doctor && time) : Boolean(chosen))
  const docName = (id: string) => {
    const d = doctors.find((x) => x.id === id)
    return d ? (i18n.language === 'ru' ? d.name_ru : d.name_uz) : ''
  }

  if (submit.isSuccess) {
    const a = submit.data
    return (
      <Modal title={t(reschedule ? 'booking.rescheduleTitle' : 'booking.title')} onClose={onClose}>
        <Notice>
          {t('booking.booked')}: {formatDay(clinicDate(a.starts_at), i18n.language)},{' '}
          {clinicTime(a.starts_at)} — {a.doctor_name}
        </Notice>
        <div className="mt-4 text-right">
          <Button onClick={onClose}>{t('schedule.close')}</Button>
        </div>
      </Modal>
    )
  }

  return (
    <Modal title={t(reschedule ? 'booking.rescheduleTitle' : 'booking.title')} onClose={onClose} wide>
      <div className="space-y-4">
        {reschedule ? (
          <p className="text-sm">
            <span className="font-medium">{reschedule.patient_name}</span> ·{' '}
            {reschedule.services.map((s) => (i18n.language === 'ru' ? s.name_ru : s.name_uz)).join(', ')}
          </p>
        ) : (
          <>
            <Field label={t('booking.patient')}>
              <PatientPicker value={patient} onChange={refilter(setPatient)} />
            </Field>
            <Field label={t('booking.services')}>
              <ServicePicker value={services} onChange={refilter(setServices)} />
            </Field>
          </>
        )}

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label={t('schedule.branch')}>
            <Select
              value={effectiveBranch}
              onChange={(e) => refilter(setBranch)(e.target.value)}
              disabled={Boolean(reschedule)}
            >
              {branches
                .filter((b) => b.is_active)
                .map((b) => (
                  <option key={b.id} value={b.id}>
                    {i18n.language === 'ru' ? b.name_ru : b.name_uz}
                  </option>
                ))}
            </Select>
          </Field>
          <Field label={t('booking.doctor')}>
            <Select value={doctor} onChange={(e) => refilter(setDoctor)(e.target.value)}>
              <option value="">{t('booking.anyDoctor')}</option>
              {doctors.map((d) => (
                <option key={d.id} value={d.id}>
                  {docName(d.id)}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t('booking.from')}>
            <Input
              type="date"
              value={dateFrom}
              min={clinicDate()}
              onChange={(e) => refilter(setDateFrom)(e.target.value)}
            />
          </Field>
          {manual ? (
            <Field label={t('booking.startsAt')}>
              <Input type="time" step={900} value={time} onChange={(e) => setTime(e.target.value)} />
            </Field>
          ) : (
            <Field label={t('booking.part')}>
              <Select value={part} onChange={(e) => refilter(setPart)(e.target.value)}>
                <option value="">{t('booking.anyTime')}</option>
                <option value="morning">{t('booking.morning')}</option>
                <option value="afternoon">{t('booking.afternoon')}</option>
                <option value="evening">{t('booking.evening')}</option>
              </Select>
            </Field>
          )}
        </div>

        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={manual} onChange={(e) => setManual(e.target.checked)} />
          {t('booking.manual')}
        </label>
        {manual && user && OVERRIDE_ROLES.includes(user.role) && !reschedule && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={outside} onChange={(e) => setOutside(e.target.checked)} />
            {t('booking.outside')}
          </label>
        )}

        {!manual && (
          <div className="space-y-2">
            <Button
              variant="secondary"
              disabled={!ready || slots.isPending}
              onClick={() => slots.mutate(limit)}
            >
              {t('booking.find')}
            </Button>
            {slots.data && slots.data.length === 0 && (
              <p className="text-sm text-slate-600">{t('booking.noSlots')}</p>
            )}
            {slots.data && slots.data.length > 0 && (
              <div>
                <p className="mb-2 text-sm text-slate-600">{t('booking.chooseSlot')}</p>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                  {slots.data.map((s) => (
                    <button
                      key={`${s.starts_at}-${s.doctor_id}`}
                      onClick={() => setChosen(s)}
                      className={`rounded-md border px-3 py-2 text-left text-sm ${
                        chosen === s
                          ? 'border-teal-600 bg-teal-50'
                          : 'border-slate-200 hover:border-slate-300'
                      }`}
                    >
                      <div className="font-medium">
                        {formatDay(clinicDate(s.starts_at), i18n.language)}, {clinicTime(s.starts_at)}
                      </div>
                      <div className="text-xs text-slate-500">{docName(s.doctor_id) || s.doctor_name}</div>
                    </button>
                  ))}
                </div>
                {slots.data.length >= limit && (
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setLimit(limit + 6)
                      slots.mutate(limit + 6)
                    }}
                  >
                    {t('booking.more')}
                  </Button>
                )}
              </div>
            )}
          </div>
        )}

        {!reschedule && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label={t('booking.source')}>
              <Select value={source} onChange={(e) => setSource(e.target.value as Source | '')}>
                <option value="">—</option>
                {SOURCES.map((s) => (
                  <option key={s} value={s}>
                    {t(`sources.${s}`)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label={t('schedule.note')}>
              <Input value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />
            </Field>
          </div>
        )}

        <ErrorText error={slots.error ?? submit.error} />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t('patients.cancel')}
          </Button>
          <Button disabled={!canSubmit || submit.isPending} onClick={() => submit.mutate()}>
            {t(reschedule ? 'booking.moveTo' : 'booking.confirm')}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
