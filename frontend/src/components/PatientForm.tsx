import { useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import type { Language } from '../lib/api'
import { GENDERS, SOURCES, getDistricts, type Patient, type PatientInput } from '../lib/patients'
import { Button, ErrorText, Field, Input, Select } from './ui'

type Props = {
  initial?: Patient
  /** create mode shows the phone field; on the card phones are managed separately */
  withPhone?: boolean
  busy: boolean
  error: unknown
  onSubmit: (data: PatientInput) => void
  onCancel: () => void
}

const toNull = (v: string) => (v.trim() === '' ? null : v.trim())

export default function PatientForm({ initial, withPhone, busy, error, onSubmit, onCancel }: Props) {
  const { t } = useTranslation()
  const { data: districts = [] } = useQuery({
    queryKey: ['districts'],
    queryFn: getDistricts,
    staleTime: Infinity,
  })
  const [form, setForm] = useState({
    full_name: initial?.full_name ?? '',
    birth_date: initial?.birth_date ?? '',
    gender: initial?.gender ?? 'unknown',
    district: initial?.district ?? '',
    address: initial?.address ?? '',
    language: initial?.language ?? 'uz',
    source: initial?.source ?? '',
    notes: initial?.notes ?? '',
    phone: '',
    phone_note: '',
  })
  const set = (k: keyof typeof form, v: string) => setForm((f) => ({ ...f, [k]: v }))

  const submit = (e: FormEvent) => {
    e.preventDefault()
    onSubmit({
      full_name: form.full_name.trim(),
      birth_date: toNull(form.birth_date),
      gender: form.gender as PatientInput['gender'],
      district: toNull(form.district),
      address: toNull(form.address),
      language: form.language as Language,
      source: (form.source || 'other') as PatientInput['source'],
      notes: toNull(form.notes),
      phones: withPhone ? [{ number: form.phone, note: toNull(form.phone_note) }] : [],
    })
  }

  return (
    <form onSubmit={submit} className="grid gap-4 md:grid-cols-2">
      <Field label={t('patients.name')}>
        <Input
          value={form.full_name}
          onChange={(e) => set('full_name', e.target.value)}
          required
          minLength={2}
          autoFocus
        />
      </Field>
      <Field label={t('patients.birthDate')}>
        <Input
          type="date"
          min="1900-01-01"
          max={new Date().toISOString().slice(0, 10)}
          value={form.birth_date}
          onChange={(e) => set('birth_date', e.target.value)}
        />
      </Field>
      {withPhone && (
        <>
          <Field label={t('patients.phone')}>
            <Input
              type="tel"
              inputMode="tel"
              placeholder="90 000 22 44"
              value={form.phone}
              onChange={(e) => set('phone', e.target.value)}
              required
            />
          </Field>
          <Field label={t('patients.phoneNote')}>
            <Input
              value={form.phone_note}
              onChange={(e) => set('phone_note', e.target.value)}
              maxLength={100}
            />
          </Field>
        </>
      )}
      <Field label={t('patients.gender')}>
        <Select value={form.gender} onChange={(e) => set('gender', e.target.value)}>
          {GENDERS.map((g) => (
            <option key={g} value={g}>
              {t(`genders.${g}`)}
            </option>
          ))}
        </Select>
      </Field>
      <Field label={t('patients.language')}>
        <Select value={form.language} onChange={(e) => set('language', e.target.value)}>
          <option value="uz">{t('lang.uz')}</option>
          <option value="ru">{t('lang.ru')}</option>
        </Select>
      </Field>
      <Field label={t('patients.district')}>
        <Input
          list="districts"
          value={form.district}
          onChange={(e) => set('district', e.target.value)}
          maxLength={100}
        />
        <datalist id="districts">
          {districts.map((d) => (
            <option key={d} value={d} />
          ))}
        </datalist>
      </Field>
      <Field label={t('patients.source')}>
        <Select value={form.source} onChange={(e) => set('source', e.target.value)} required>
          <option value="" disabled>
            —
          </option>
          {/* keep a legacy value (import / cold base) selectable when editing */}
          {[...new Set([...SOURCES, ...(initial?.source ? [initial.source] : [])])].map((s) => (
            <option key={s} value={s}>
              {t(`sources.${s}`)}
            </option>
          ))}
        </Select>
      </Field>
      <div className="md:col-span-2">
        <Field label={t('patients.address')}>
          <Input value={form.address} onChange={(e) => set('address', e.target.value)} maxLength={500} />
        </Field>
      </div>
      <div className="md:col-span-2">
        <Field label={t('patients.notes')}>
          <textarea
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-600/20"
            rows={3}
            value={form.notes}
            onChange={(e) => set('notes', e.target.value)}
            maxLength={5000}
          />
        </Field>
      </div>
      <div className="md:col-span-2">
        <ErrorText error={error} />
      </div>
      <div className="flex gap-2 md:col-span-2">
        <Button type="submit" disabled={busy}>
          {t('patients.save')}
        </Button>
        <Button variant="secondary" onClick={onCancel}>
          {t('patients.cancel')}
        </Button>
      </div>
    </form>
  )
}
