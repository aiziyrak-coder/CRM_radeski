import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { StatusActions, StatusPill } from '../components/AppointmentPanel'
import PatientName from '../components/PatientName'
import { Button, Card, ErrorText, Field, Input, Notice, Select } from '../components/ui'
import {
  addDays,
  clinicDate,
  clinicTime,
  createRecommendation,
  formatDay,
  getMyDay,
  type Appointment,
} from '../lib/scheduling'

const UNIT_DAYS = { days: 1, weeks: 7, months: 30 } as const

function RecommendationForm({ a }: { a: Appointment }) {
  const { t } = useTranslation()
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
  })
  if (save.isSuccess) return <Notice>{t('myday.saved')}</Notice>
  return (
    <div className="grid gap-2 rounded-md bg-slate-50 p-3 sm:grid-cols-[auto_1fr_auto]">
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
                {s.name_uz}
              </option>
            ))}
          </Select>
        </Field>
      )}
      <ErrorText error={save.error} />
    </div>
  )
}

export default function MyDayPage() {
  const { t, i18n } = useTranslation()
  const [date, setDate] = useState(clinicDate())
  const [recommending, setRecommending] = useState<string | null>(null)
  const { data, error } = useQuery({
    queryKey: ['appointments', 'my-day', date],
    queryFn: () => getMyDay(date),
    refetchInterval: 60_000,
  })
  const list = (data ?? []).filter((a) => !['cancelled', 'rescheduled'].includes(a.status))

  return (
    <div className="max-w-4xl space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="mr-auto text-2xl font-semibold">{t('myday.title')}</h1>
        <Button variant="secondary" onClick={() => setDate(addDays(date, -1))}>
          ←
        </Button>
        <Input
          type="date"
          value={date}
          onChange={(e) => e.target.value && setDate(e.target.value)}
          className="w-40"
        />
        <Button variant="secondary" onClick={() => setDate(addDays(date, 1))}>
          →
        </Button>
      </div>
      <p className="text-sm text-slate-600">{formatDay(date, i18n.language)}</p>
      <ErrorText error={error} />
      {data && list.length === 0 && (
        <Card>
          <p className="text-sm text-slate-500">{t('myday.empty')}</p>
        </Card>
      )}
      {list.map((a) => (
        <Card key={a.id}>
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <div className="font-medium">
                <span className="mr-2 tabular-nums">{clinicTime(a.starts_at)}</span>
                <PatientName name={a.patient_name} />
              </div>
              <div className="text-sm text-slate-600">
                {a.services.map((s) => (i18n.language === 'ru' ? s.name_ru : s.name_uz)).join(', ')}
              </div>
              {a.note && <div className="mt-1 text-xs text-slate-500">{a.note}</div>}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <StatusPill status={a.status} />
              <StatusActions a={a} allowed={['arrived', 'completed']} />
            </div>
          </div>
          {['arrived', 'completed'].includes(a.status) && (
            <div className="mt-3">
              {recommending === a.id ? (
                <RecommendationForm a={a} />
              ) : (
                <Button variant="ghost" onClick={() => setRecommending(a.id)}>
                  + {t('myday.recommend')}
                </Button>
              )}
            </div>
          )}
        </Card>
      ))}
    </div>
  )
}
