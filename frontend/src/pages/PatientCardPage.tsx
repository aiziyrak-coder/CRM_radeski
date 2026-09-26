import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, useLocation, useParams } from 'react-router'
import PatientForm from '../components/PatientForm'
import PatientName from '../components/PatientName'
import PatientTags from '../components/PatientTags'
import PatientRow from '../components/PatientRow'
import { Badge, Button, Card, ErrorText, Field, Input, Notice } from '../components/ui'
import { useAuth } from '../lib/auth-context'
import { categoryName, getCategories } from '../lib/diagnoses'
import {
  addPhone,
  deletePhone,
  formatDate,
  getPatient,
  mergePatients,
  searchPatients,
  setDoNotCall,
  updatePatient,
  updatePhone,
  type Patient,
} from '../lib/patients'

function useSetPatient(id: string) {
  const queryClient = useQueryClient()
  return (p: Patient) => {
    queryClient.setQueryData(['patient', id], p)
    void queryClient.invalidateQueries({ queryKey: ['patients'] })
  }
}

function Info({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="text-sm">{value || '—'}</dd>
    </div>
  )
}

function Details({ patient }: { patient: Patient }) {
  const { t } = useTranslation()
  const [editing, setEditing] = useState(false)
  const setPatient = useSetPatient(patient.id)
  const save = useMutation({
    mutationFn: (data: Parameters<typeof updatePatient>[1]) => updatePatient(patient.id, data),
    onSuccess: (p) => {
      setPatient(p)
      setEditing(false)
    },
  })

  if (editing) {
    return (
      <Card title={t('patients.edit')}>
        <PatientForm
          initial={patient}
          busy={save.isPending}
          error={save.error}
          onSubmit={({ phones: _phones, ...data }) => save.mutate(data)}
          onCancel={() => setEditing(false)}
        />
      </Card>
    )
  }
  return (
    <Card
      actions={
        <Button variant="secondary" onClick={() => setEditing(true)}>
          {t('patients.edit')}
        </Button>
      }
      title={t('patients.details')}
    >
      <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Info label={t('patients.birthDate')} value={formatDate(patient.birth_date)} />
        <Info label={t('patients.gender')} value={t(`genders.${patient.gender}`)} />
        <Info label={t('patients.language')} value={t(`lang.${patient.language}`)} />
        <Info label={t('patients.district')} value={patient.district} />
        <Info label={t('patients.source')} value={patient.source && t(`sources.${patient.source}`)} />
        <Info
          label={t('patients.lastVisit')}
          value={patient.last_visit_at && formatDate(patient.last_visit_at)}
        />
        <div className="sm:col-span-2 lg:col-span-3">
          <Info label={t('patients.address')} value={patient.address} />
        </div>
        {patient.notes && (
          <div className="sm:col-span-2 lg:col-span-3">
            <dt className="text-xs text-slate-500">{t('patients.notes')}</dt>
            <dd className="text-sm whitespace-pre-line">{patient.notes}</dd>
          </div>
        )}
      </dl>
    </Card>
  )
}

function Conditions({ patient }: { patient: Patient }) {
  const { t, i18n } = useTranslation()
  const { data: categories = [] } = useQuery({
    queryKey: ['diagnoses', 'categories'],
    queryFn: getCategories,
    staleTime: 60_000,
  })
  const nameOf = (code: string | null) => {
    const c = categories.find((x) => x.code === code)
    return c ? categoryName(c, i18n.language) : null
  }
  if (patient.conditions.length === 0 && patient.kind !== 'legacy') return null
  return (
    <Card title={t('patients.conditions')}>
      {patient.conditions.length === 0 ? (
        <p className="text-sm text-slate-500">{t('patients.noConditions')}</p>
      ) : (
        <ul className="space-y-1 text-sm">
          {patient.conditions.map((c) => (
            <li key={c.id}>
              {c.category_code && (
                <span className="mr-2">
                  <Badge tone="good">{nameOf(c.category_code)}</Badge>
                </span>
              )}
              {c.raw_text}
              {c.visit_type && (
                <span className="ml-2 text-xs text-slate-500">
                  ({t(c.visit_type === 'first' ? 'patients.visitFirst' : 'patients.visitRepeat')})
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function Phones({ patient }: { patient: Patient }) {
  const { t } = useTranslation()
  const setPatient = useSetPatient(patient.id)
  const [number, setNumber] = useState('')
  const [note, setNote] = useState('')
  const opts = { onSuccess: setPatient }
  const add = useMutation({
    mutationFn: () => addPhone(patient.id, { number, note: note.trim() || null }),
    onSuccess: (p) => {
      setPatient(p)
      setNumber('')
      setNote('')
    },
  })
  const primary = useMutation({
    mutationFn: (phoneId: string) => updatePhone(patient.id, phoneId, { is_primary: true }),
    ...opts,
  })
  const remove = useMutation({ mutationFn: (phoneId: string) => deletePhone(patient.id, phoneId), ...opts })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    add.mutate()
  }

  return (
    <Card title={t('patients.phones')}>
      <ul className="divide-y divide-slate-100">
        {patient.phones.map((ph) => (
          <li key={ph.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <div>
              <a href={`tel:${ph.number}`} className="font-medium text-teal-800 hover:underline">
                {ph.display}
              </a>
              {ph.note && <span className="ml-2 text-sm text-slate-500">{ph.note}</span>}
              {ph.is_primary && (
                <span className="ml-2">
                  <Badge tone="good">{t('patients.primary')}</Badge>
                </span>
              )}
            </div>
            <div className="flex gap-1">
              {!ph.is_primary && (
                <Button variant="ghost" onClick={() => primary.mutate(ph.id)} disabled={primary.isPending}>
                  {t('patients.makePrimary')}
                </Button>
              )}
              {patient.phones.length > 1 && (
                <Button variant="ghost" onClick={() => remove.mutate(ph.id)} disabled={remove.isPending}>
                  {t('patients.remove')}
                </Button>
              )}
            </div>
          </li>
        ))}
      </ul>
      {/* the card sits in a narrow column, so fields always stack */}
      <form onSubmit={submit} className="mt-3 space-y-2">
        <Input
          type="tel"
          inputMode="tel"
          placeholder="90 123 45 67"
          value={number}
          onChange={(e) => setNumber(e.target.value)}
          required
        />
        <Input
          placeholder={t('patients.phoneNote')}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={100}
        />
        <Button type="submit" variant="secondary" disabled={add.isPending} className="w-full">
          {t('patients.addPhone')}
        </Button>
      </form>
      <div className="mt-2">
        <ErrorText error={add.error ?? primary.error ?? remove.error} />
      </div>
    </Card>
  )
}

function DoNotCall({ patient }: { patient: Patient }) {
  const { t } = useTranslation()
  const setPatient = useSetPatient(patient.id)
  const [reason, setReason] = useState('')
  const toggle = useMutation({
    mutationFn: () =>
      setDoNotCall(patient.id, !patient.do_not_call, patient.do_not_call ? null : reason.trim() || null),
    onSuccess: (p) => {
      setPatient(p)
      setReason('')
    },
  })

  return (
    <Card title={t('patients.dnc')}>
      {patient.do_not_call ? (
        <div className="space-y-3">
          <p className="text-sm">
            <Badge tone="bad">{t('patients.dnc')}</Badge>
            {patient.do_not_call_reason && (
              <span className="ml-2 text-slate-600">{patient.do_not_call_reason}</span>
            )}
          </p>
          <Button variant="secondary" onClick={() => toggle.mutate()} disabled={toggle.isPending}>
            {t('patients.dncClear')}
          </Button>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-slate-600">{t('patients.dncHint')}</p>
          <Field label={t('patients.dncReason')}>
            <Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={255} />
          </Field>
          <Button variant="danger" onClick={() => toggle.mutate()} disabled={toggle.isPending}>
            {t('patients.dncSet')}
          </Button>
        </div>
      )}
      <ErrorText error={toggle.error} />
    </Card>
  )
}

function Merge({ patient }: { patient: Patient }) {
  const { t } = useTranslation()
  const setPatient = useSetPatient(patient.id)
  const [q, setQ] = useState('')
  const { data } = useQuery({
    queryKey: ['patients', 'merge-search', q],
    queryFn: () => searchPatients({ q, offset: 0, limit: 10 }),
    enabled: q.trim().length >= 3,
  })
  const merge = useMutation({
    mutationFn: (sourceId: string) => mergePatients(patient.id, sourceId),
    onSuccess: (p) => {
      setPatient(p)
      setQ('')
    },
  })
  const candidates = data?.items.filter((p) => p.id !== patient.id) ?? []

  return (
    <Card title={t('patients.merge')}>
      <p className="mb-3 text-sm text-slate-600">{t('patients.mergeHint')}</p>
      <Input
        type="search"
        placeholder={t('patients.mergeSearch')}
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      {candidates.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-sm">
            <tbody>
              {candidates.map((c) => (
                <PatientRow
                  key={c.id}
                  p={c}
                  action={
                    <Button
                      variant="danger"
                      disabled={merge.isPending}
                      onClick={() => {
                        if (window.confirm(t('patients.mergeConfirm', { name: c.full_name })))
                          merge.mutate(c.id)
                      }}
                    >
                      {t('patients.merge')}
                    </Button>
                  }
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {merge.isSuccess && (
        <div className="mt-3">
          <Notice>{t('patients.merged')}</Notice>
        </div>
      )}
      <ErrorText error={merge.error} />
    </Card>
  )
}

export default function PatientCardPage() {
  const { t } = useTranslation()
  const { id = '' } = useParams()
  const { user } = useAuth()
  const location = useLocation()
  const redirectedFromMerge = Boolean((location.state as { mergedFrom?: string } | null)?.mergedFrom)
  const { data: patient, error } = useQuery({ queryKey: ['patient', id], queryFn: () => getPatient(id) })

  if (error) return <ErrorText error={error} />
  if (!patient) return null
  if (patient.merged_into_id) {
    return <Navigate to={`/patients/${patient.merged_into_id}`} replace state={{ mergedFrom: patient.id }} />
  }
  const canMerge = user?.role === 'supervisor' || user?.role === 'admin'

  return (
    <div className="max-w-6xl space-y-6">
      <div>
        <Link to="/patients" className="text-sm text-teal-800 hover:underline">
          ← {t('patients.back')}
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold">
            <PatientName name={patient.full_name} />
          </h1>
          <Badge tone={patient.kind === 'active' ? 'good' : 'neutral'}>{t(`kinds.${patient.kind}`)}</Badge>
          {patient.do_not_call && <Badge tone="bad">{t('patients.dnc')}</Badge>}
          <PatientTags tags={patient.tags} />
        </div>
        <p className="mt-1 text-sm text-slate-500">
          {t('patients.created')}: {formatDate(patient.created_at)}
        </p>
      </div>

      {redirectedFromMerge && <Notice>{t('patients.mergedRedirect')}</Notice>}
      {patient.kind === 'legacy' && (
        <p className="rounded-md bg-slate-100 px-3 py-2 text-sm text-slate-700">{t('patients.legacyNote')}</p>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Details patient={patient} />
          <Conditions patient={patient} />
          <Card title={t('patients.history')}>
            <p className="text-sm text-slate-500">{t('patients.historySoon')}</p>
          </Card>
        </div>
        <div className="space-y-6">
          <Phones patient={patient} />
          <DoNotCall patient={patient} />
          {canMerge && <Merge patient={patient} />}
        </div>
      </div>
    </div>
  )
}
