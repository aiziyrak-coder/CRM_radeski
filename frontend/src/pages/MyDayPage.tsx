import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { StatusActions, StatusPill } from '../components/AppointmentPanel'
import PatientName from '../components/PatientName'
import { Badge, Button, Card, ErrorText, Field, Input, Notice, Select } from '../components/ui'
import { ApiError } from '../lib/api'
import { formatDate, formatPhone } from '../lib/patients'
import {
  INACTIVE_STATUSES,
  addDays,
  clinicDate,
  clinicTime,
  createRecommendation,
  dismissRecommendation,
  formatDay,
  formatShortDay,
  getMyDay,
  getPatientContext,
  getRange,
  serviceName,
  updateRecommendation,
  useReasonLabel,
  weekStart,
  type Appointment,
  type Recommendation,
} from '../lib/scheduling'

const UNIT_DAYS = { days: 1, weeks: 7, months: 30 } as const
const REC_TONE = { open: 'info', booked: 'good', dismissed: 'neutral' } as const

function RecommendationForm({ a, onSaved }: { a: Appointment; onSaved: () => void }) {
  const { t, i18n } = useTranslation()
  const [amount, setAmount] = useState(2)
  const [unit, setUnit] = useState<keyof typeof UNIT_DAYS>('weeks')
  const [serviceId, setServiceId] = useState(a.services[0]?.service_id ?? '')
  const [note, setNote] = useState('')
  const save = useMutation({
    mutationFn: () =>
      createRecommendation({
        patient_id: a.patient_id,
        appointment_id: a.id,
        due_date: addDays(clinicDate(a.starts_at), amount * UNIT_DAYS[unit]),
        service_id: serviceId || null,
        note: note.trim() || null,
      }),
    onSuccess: onSaved,
  })
  if (save.isSuccess) return <Notice>{t('myday.saved')}</Notice>
  return (
    <div className="grid grid-cols-1 gap-2 rounded-md bg-slate-50 p-3 sm:grid-cols-[auto_1fr_auto]">
      <Field label={t('myday.in')}>
        <div className="flex gap-1">
          <Input
            type="number"
            min={1}
            max={365}
            value={amount}
            onChange={(e) => setAmount(Number(e.target.value))}
            className="w-20"
          />
          <Select
            value={unit}
            onChange={(e) => setUnit(e.target.value as keyof typeof UNIT_DAYS)}
            className="w-28"
          >
            {(Object.keys(UNIT_DAYS) as (keyof typeof UNIT_DAYS)[]).map((u) => (
              <option key={u} value={u}>
                {t(`myday.${u}`)}
              </option>
            ))}
          </Select>
        </div>
      </Field>
      <Field label={t('schedule.note')}>
        <Input value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />
      </Field>
      <div className="flex items-end">
        <Button disabled={save.isPending || amount < 1} onClick={() => save.mutate()}>
          {t('myday.save')}
        </Button>
      </div>
      {a.services.length > 1 && (
        <Field label={t('myday.service')}>
          <Select value={serviceId} onChange={(e) => setServiceId(e.target.value)}>
            <option value="">—</option>
            {a.services.map((s) => (
              <option key={s.service_id} value={s.service_id}>
                {serviceName(s, i18n.language)}
              </option>
            ))}
          </Select>
        </Field>
      )}
      <ErrorText error={save.error} />
    </div>
  )
}

/** An earlier recommendation; the doctor who made it can move the date, edit or withdraw it. */
function RecommendationItem({ r, onChanged }: { r: Recommendation; onChanged: () => void }) {
  const { t, i18n } = useTranslation()
  const [editing, setEditing] = useState(false)
  const [due, setDue] = useState(r.due_date)
  const [note, setNote] = useState(r.note ?? '')
  const save = useMutation({
    mutationFn: () => updateRecommendation(r.id, { due_date: due, note: note.trim() || null }),
    onSuccess: () => {
      setEditing(false)
      onChanged()
    },
  })
  const dismiss = useMutation({ mutationFn: () => dismissRecommendation(r.id), onSuccess: onChanged })
  const service = i18n.language === 'ru' ? r.service_name_ru : r.service_name_uz
  return (
    <li className="py-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-medium tabular-nums">{formatDate(r.due_date)}</span>
        <Badge tone={REC_TONE[r.status]}>{t(`recommendations.${r.status}`)}</Badge>
        {service && <span>{service}</span>}
        {r.doctor_name && <span className="text-xs text-slate-500">{r.doctor_name}</span>}
        {r.can_edit && !editing && (
          <span className="ml-auto flex gap-1">
            <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => setEditing(true)}>
              {t('settings.edit')}
            </Button>
            <Button
              variant="ghost"
              className="px-2 py-1 text-xs text-red-700"
              disabled={dismiss.isPending}
              onClick={() => window.confirm(t('mydayx.dismissConfirm')) && dismiss.mutate()}
            >
              {t('mydayx.dismiss')}
            </Button>
          </span>
        )}
      </div>
      {r.note && !editing && <p className="mt-0.5 text-slate-600">{r.note}</p>}
      {editing && (
        <div className="mt-2 grid grid-cols-1 gap-2 rounded-md bg-slate-50 p-2 sm:grid-cols-[10rem_1fr_auto]">
          <Input type="date" value={due} min={clinicDate()} onChange={(e) => setDue(e.target.value)} />
          <Input value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />
          <div className="flex gap-1">
            <Button disabled={!due || save.isPending} onClick={() => save.mutate()}>
              {t('settings.save')}
            </Button>
            <Button variant="ghost" onClick={() => setEditing(false)}>
              {t('patients.cancel')}
            </Button>
          </div>
        </div>
      )}
      <ErrorText error={save.error ?? dismiss.error} />
    </li>
  )
}

/** What the doctor needs about the patient at the visit (not an EMR: categories, history, advice). */
function PatientContextView({ a }: { a: Appointment }) {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const reasonLabel = useReasonLabel()
  const ctx = useQuery({
    queryKey: ['patient-context', a.patient_id],
    queryFn: () => getPatientContext(a.patient_id),
  })
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ['patient-context', a.patient_id] })
  if (ctx.isPending) return <p className="text-sm text-slate-500">{t('app.loading')}</p>
  if (ctx.error) return <ErrorText error={ctx.error} />
  const { patient, conditions, visits, recommendations } = ctx.data
  const categories = [
    ...new Map(
      conditions
        .filter((c) => c.category_code)
        .map((c) => [c.category_code, i18n.language === 'ru' ? c.category_name_ru : c.category_name_uz]),
    ),
  ]
  const unmapped = conditions.filter((c) => !c.category_code)
  const past = visits.filter((v) => v.id !== a.id)
  return (
    <div className="grid grid-cols-1 gap-4 border-t border-slate-100 pt-3 text-sm lg:grid-cols-2">
      <section>
        <h3 className="mb-1 text-xs font-semibold text-slate-500 uppercase">{t('mydayx.diagnoses')}</h3>
        {categories.length === 0 && unmapped.length === 0 && (
          <p className="text-slate-500">{t('mydayx.noDiagnoses')}</p>
        )}
        <div className="flex flex-wrap gap-1.5">
          {categories.map(([code, name]) => (
            <span key={code} className="rounded-full bg-teal-50 px-2.5 py-0.5 text-teal-900">
              {name ?? code}
            </span>
          ))}
        </div>
        {unmapped.length > 0 && (
          <p className="mt-1 text-xs text-slate-500">
            {t('mydayx.rawDiagnoses')}: {unmapped.map((c) => c.raw_text).join('; ')}
          </p>
        )}
        {patient.birth_date && (
          <p className="mt-2 text-slate-600">
            {t('mydayx.born')}: {formatDate(patient.birth_date)}
          </p>
        )}
        <h3 className="mt-3 mb-1 text-xs font-semibold text-slate-500 uppercase">{t('mydayx.notes')}</h3>
        <p className="whitespace-pre-line text-slate-700">{patient.notes || '—'}</p>
      </section>
      <section>
        <h3 className="mb-1 text-xs font-semibold text-slate-500 uppercase">{t('mydayx.lastVisits')}</h3>
        {past.length === 0 ? (
          <p className="text-slate-500">{t('mydayx.firstVisit')}</p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {past.slice(0, 5).map((v) => (
              <li key={v.id} className="flex flex-wrap items-center gap-x-2 py-1.5">
                <span className="tabular-nums">{formatDate(v.starts_at)}</span>
                <StatusPill status={v.status} />
                <span className="text-slate-700">
                  {v.services.map((s) => serviceName(s, i18n.language)).join(', ')}
                </span>
                <span className="text-xs text-slate-500">{v.doctor_name}</span>
                {v.cancel_reason && (
                  <span className="text-xs text-slate-500">({reasonLabel(v.status, v.cancel_reason)})</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="lg:col-span-2">
        <h3 className="mb-1 text-xs font-semibold text-slate-500 uppercase">{t('recommendations.title')}</h3>
        {recommendations.length === 0 ? (
          <p className="text-slate-500">{t('recommendations.none')}</p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {recommendations.map((r) => (
              <RecommendationItem key={r.id} r={r} onChanged={refresh} />
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

function VisitCard({ a }: { a: Appointment }) {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const [expanded, setExpanded] = useState(false)
  const [recommending, setRecommending] = useState(false)
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <button
          className="min-w-0 flex-1 text-left"
          onClick={() => setExpanded(!expanded)}
          aria-expanded={expanded}
        >
          <div className="font-medium">
            <span className="mr-2 tabular-nums">{clinicTime(a.starts_at)}</span>
            <PatientName name={a.patient_name} />
            <span className="ml-2 text-xs text-teal-800">{expanded ? '▲' : '▼'}</span>
          </div>
          <div className="text-sm text-slate-600">
            {a.services.map((s) => serviceName(s, i18n.language)).join(', ')}
            {a.resource_name && <span className="text-slate-500"> · {a.resource_name}</span>}
          </div>
          {a.patient_phone && <div className="text-xs text-slate-500">{formatPhone(a.patient_phone)}</div>}
          {a.note && <div className="mt-1 text-xs text-slate-500">{a.note}</div>}
        </button>
        <div className="flex flex-wrap items-center gap-2">
          <StatusPill status={a.status} />
          <StatusActions a={a} allowed={['arrived', 'completed']} />
        </div>
      </div>
      {expanded && (
        <div className="mt-3">
          <PatientContextView a={a} />
        </div>
      )}
      {['arrived', 'completed'].includes(a.status) && (
        <div className="mt-3">
          {recommending ? (
            <RecommendationForm
              a={a}
              onSaved={() =>
                void queryClient.invalidateQueries({ queryKey: ['patient-context', a.patient_id] })
              }
            />
          ) : (
            <Button variant="ghost" onClick={() => setRecommending(true)}>
              + {t('myday.recommend')}
            </Button>
          )}
        </div>
      )}
    </Card>
  )
}

function WeekList({ start, onOpenDay }: { start: string; onOpenDay: (date: string) => void }) {
  const { t, i18n } = useTranslation()
  const weekdays = t('weekdays', { returnObjects: true }) as string[]
  const { data, error, isPending } = useQuery({
    queryKey: ['appointments', 'my-week', start],
    queryFn: () => getRange({ dateFrom: start }),
  })
  if (isPending) return <p className="text-sm text-slate-500">{t('app.loading')}</p>
  if (error) return <ErrorText error={error} />
  const visits = data.filter((a) => !INACTIVE_STATUSES.includes(a.status))
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: 7 }, (_, i) => addDays(start, i)).map((date, i) => {
        const items = visits.filter((a) => clinicDate(a.starts_at) === date)
        return (
          <button
            key={date}
            onClick={() => onOpenDay(date)}
            className={`rounded-lg border bg-white p-3 text-left hover:border-teal-500 ${
              date === clinicDate() ? 'border-teal-500' : 'border-slate-200'
            }`}
          >
            <div className="flex items-baseline justify-between">
              <span className="font-medium">
                {weekdays[i]}, {formatShortDay(date, i18n.language)}
              </span>
              <span className="text-sm text-slate-500">{t('sched.visits', { count: items.length })}</span>
            </div>
            <ul className="mt-1 space-y-0.5 text-sm text-slate-600">
              {items.slice(0, 6).map((a) => (
                <li key={a.id} className="truncate">
                  <span className="tabular-nums">{clinicTime(a.starts_at)}</span>{' '}
                  <PatientName name={a.patient_name} />
                </li>
              ))}
              {items.length > 6 && <li className="text-xs">+{items.length - 6}</li>}
            </ul>
          </button>
        )
      })}
    </div>
  )
}

export default function MyDayPage() {
  const { t, i18n } = useTranslation()
  const [date, setDate] = useState(clinicDate())
  const [mode, setMode] = useState<'day' | 'week'>('day')
  const { data, error, isPending } = useQuery({
    queryKey: ['appointments', 'my-day', date],
    queryFn: () => getMyDay(date),
    refetchInterval: 60_000,
    retry: (count, err) => !(err instanceof ApiError && err.code === 'not_a_doctor') && count < 2,
  })
  const list = (data ?? []).filter((a) => !INACTIVE_STATUSES.includes(a.status))
  const done = list.filter((a) => a.status === 'completed').length
  const here = list.filter((a) => a.status === 'arrived').length
  const step = mode === 'week' ? 7 : 1

  if (error instanceof ApiError && error.code === 'not_a_doctor') {
    return (
      <div className="max-w-2xl space-y-4">
        <h1 className="text-2xl font-semibold">{t('myday.title')}</h1>
        <Card>
          <p className="font-medium">{t('mydayx.notLinkedTitle')}</p>
          <p className="mt-2 text-sm text-slate-600">{t('mydayx.notLinkedHelp')}</p>
        </Card>
      </div>
    )
  }

  return (
    <div className="max-w-4xl space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="mr-auto text-2xl font-semibold">{t('myday.title')}</h1>
        <div className="inline-flex rounded-md border border-slate-300 bg-white p-0.5">
          {(['day', 'week'] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              aria-pressed={mode === m}
              className={`rounded px-3 py-1.5 text-sm ${mode === m ? 'bg-teal-700 font-medium text-white' : 'text-slate-700 hover:bg-slate-100'}`}
            >
              {t(`sched.mode.${m}`)}
            </button>
          ))}
        </div>
        <Button variant="secondary" onClick={() => setDate(addDays(date, -step))} aria-label={t('app.prev')}>
          ←
        </Button>
        <Input
          type="date"
          value={date}
          onChange={(e) => e.target.value && setDate(e.target.value)}
          className="w-40"
        />
        <Button variant="secondary" onClick={() => setDate(addDays(date, step))} aria-label={t('app.next')}>
          →
        </Button>
        {date !== clinicDate() && (
          <Button variant="ghost" onClick={() => setDate(clinicDate())}>
            {t('schedule.today')}
          </Button>
        )}
      </div>

      {mode === 'week' ? (
        <WeekList
          start={weekStart(date)}
          onOpenDay={(d) => {
            setDate(d)
            setMode('day')
          }}
        />
      ) : (
        <>
          <p className="text-sm text-slate-600">
            {formatDay(date, i18n.language)}
            {list.length > 0 && ` · ${t('mydayx.summary', { count: list.length, here, done })}`}
          </p>
          <ErrorText error={error} />
          {isPending && <p className="text-sm text-slate-500">{t('app.loading')}</p>}
          {data && list.length === 0 && (
            <Card>
              <p className="text-sm text-slate-500">{t('myday.empty')}</p>
            </Card>
          )}
          {list.map((a) => (
            <VisitCard key={a.id} a={a} />
          ))}
        </>
      )}
    </div>
  )
}
