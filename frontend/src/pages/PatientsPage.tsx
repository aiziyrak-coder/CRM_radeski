import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useSearchParams } from 'react-router'
import PatientForm from '../components/PatientForm'
import PatientRow from '../components/PatientRow'
import { Button, Card, ErrorText, Input, Select } from '../components/ui'
import { ApiError } from '../lib/api'
import {
  KINDS,
  createPatient,
  searchPatients,
  type DuplicateCandidate,
  type PatientInput,
  type PatientKind,
} from '../lib/patients'

const PAGE = 25

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), ms)
    return () => window.clearTimeout(id)
  }, [value, ms])
  return debounced
}

function Duplicates({
  candidates,
  onCreateAnyway,
  busy,
}: {
  candidates: DuplicateCandidate[]
  onCreateAnyway: () => void
  busy: boolean
}) {
  const { t } = useTranslation()
  const ref = useRef<HTMLDivElement>(null)
  // the warning renders below a long form; bring it into view so it isn't missed
  useEffect(() => {
    ref.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [candidates])
  return (
    <div ref={ref} role="alert" className="space-y-3 rounded-md border border-amber-200 bg-amber-50 p-4">
      <p className="font-medium text-amber-900">{t('patients.dupTitle')}</p>
      <p className="text-sm text-amber-900">{t('patients.dupText')}</p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-sm">
          <tbody>
            {candidates.map((c) => (
              <PatientRow
                key={c.id}
                p={c}
                action={
                  <span className="text-xs text-amber-800">
                    {c.reasons
                      .map((r) => t(r === 'phone' ? 'patients.dupPhone' : 'patients.dupName'))
                      .join(', ')}
                  </span>
                }
              />
            ))}
          </tbody>
        </table>
      </div>
      <Button variant="secondary" onClick={onCreateAnyway} disabled={busy}>
        {t('patients.createAnyway')}
      </Button>
    </div>
  )
}

function NewPatient({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [pending, setPending] = useState<PatientInput | null>(null)
  const create = useMutation({
    mutationFn: ({ data, force }: { data: PatientInput; force: boolean }) => createPatient(data, force),
    onSuccess: (p) => {
      void queryClient.invalidateQueries({ queryKey: ['patients'] })
      navigate(`/patients/${p.id}`)
    },
  })
  const dupes =
    create.error instanceof ApiError && create.error.code === 'possible_duplicates'
      ? (create.error.data.candidates as DuplicateCandidate[])
      : null

  return (
    <Card title={t('patients.new')}>
      <div className="space-y-4">
        <PatientForm
          withPhone
          busy={create.isPending}
          error={dupes ? null : create.error}
          onSubmit={(data) => {
            setPending(data)
            create.mutate({ data, force: false })
          }}
          onCancel={onClose}
        />
        {dupes && pending && (
          <Duplicates
            candidates={dupes}
            busy={create.isPending}
            onCreateAnyway={() => create.mutate({ data: pending, force: true })}
          />
        )}
      </div>
    </Card>
  )
}

export default function PatientsPage() {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const [q, setQ] = useState(params.get('q') ?? '')
  const kind = (params.get('kind') ?? '') as PatientKind | ''
  const offset = Number(params.get('offset') ?? 0)
  const [adding, setAdding] = useState(false)
  const debouncedQ = useDebounced(q, 300)

  // keep the URL in sync so Back returns to the same search
  useEffect(() => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (debouncedQ.trim()) next.set('q', debouncedQ.trim())
        else next.delete('q')
        if ((prev.get('q') ?? '') !== debouncedQ.trim()) next.delete('offset')
        return next
      },
      { replace: true },
    )
  }, [debouncedQ, setParams])

  const { data, error, isFetching } = useQuery({
    queryKey: ['patients', debouncedQ.trim(), kind, offset],
    queryFn: () => searchPatients({ q: debouncedQ, kind, offset, limit: PAGE }),
    placeholderData: keepPreviousData,
  })

  const setParam = (key: string, value: string) =>
    setParams((prev) => {
      const next = new URLSearchParams(prev)
      if (value) next.set(key, value)
      else next.delete(key)
      if (key !== 'offset') next.delete('offset')
      return next
    })

  return (
    <div className="max-w-6xl space-y-6">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold">{t('patients.title')}</h1>
        {!adding && <Button onClick={() => setAdding(true)}>{t('patients.new')}</Button>}
      </div>

      {adding && <NewPatient onClose={() => setAdding(false)} />}

      <Card>
        <div className="mb-4 flex flex-col gap-3 md:flex-row">
          <Input
            type="search"
            placeholder={t('patients.search')}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            autoFocus={!adding}
            className="md:flex-1"
          />
          <Select value={kind} onChange={(e) => setParam('kind', e.target.value)} className="md:w-56">
            <option value="">{t('patients.allKinds')}</option>
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {t(`kinds.${k}`)}
              </option>
            ))}
          </Select>
        </div>
        <ErrorText error={error} />
        {data && (
          <>
            <div className={`overflow-x-auto ${isFetching ? 'opacity-60' : ''}`}>
              <table className="w-full min-w-[640px] text-left text-sm">
                <thead className="text-xs text-slate-500 uppercase">
                  <tr>
                    <th className="pb-2 font-medium">{t('patients.name')}</th>
                    <th className="pb-2 font-medium">{t('patients.phones')}</th>
                    <th className="pb-2 font-medium">{t('patients.birthDate')}</th>
                    <th className="pb-2 font-medium">{t('patients.district')}</th>
                    <th className="pb-2 font-medium">{t('patients.kind')}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((p) => (
                    <PatientRow key={p.id} p={p} />
                  ))}
                </tbody>
              </table>
            </div>
            {data.items.length === 0 && (
              <p className="py-6 text-center text-sm text-slate-500">{t('patients.empty')}</p>
            )}
            <div className="mt-4 flex items-center justify-between text-sm text-slate-600">
              <span>{t('patients.total', { count: data.total })}</span>
              <div className="flex gap-2">
                <Button
                  variant="secondary"
                  disabled={offset === 0}
                  onClick={() => setParam('offset', String(Math.max(0, offset - PAGE)))}
                >
                  {t('audit.prev')}
                </Button>
                <Button
                  variant="secondary"
                  disabled={offset + PAGE >= data.total}
                  onClick={() => setParam('offset', String(offset + PAGE))}
                >
                  {t('audit.next')}
                </Button>
              </div>
            </div>
          </>
        )}
      </Card>
    </div>
  )
}
