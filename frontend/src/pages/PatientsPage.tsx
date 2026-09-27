import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useSearchParams } from 'react-router'
import PatientForm from '../components/PatientForm'
import PatientRow, { PatientListCard, PatientTableRow } from '../components/PatientRow'
import { Button, Card, ErrorText, Input, Select } from '../components/ui'
import { ApiError } from '../lib/api'
import { categoryName, getCategories } from '../lib/diagnoses'
import {
  CHECK_TAG,
  KINDS,
  NO_DISTRICT,
  PATIENT_SORTS,
  SOURCES,
  TAG_LABELS,
  createPatient,
  getDistricts,
  getTags,
  searchPatients,
  type DuplicateCandidate,
  type PatientInput,
  type PatientKind,
  type PatientSort,
  type Source,
} from '../lib/patients'

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

const PAGE_SIZES = [25, 50, 100]
const FILTERS = ['kind', 'category', 'district', 'source', 'tag', 'phone'] as const

function SortHeader({
  label,
  sort,
  current,
  onSort,
}: {
  label: string
  sort: PatientSort
  current: string
  onSort: (s: PatientSort | '') => void
}) {
  const active = current === sort
  return (
    <th className="pb-2 font-medium" aria-sort={active ? 'ascending' : undefined}>
      <button
        className={`inline-flex items-center gap-1 uppercase hover:text-slate-800 ${active ? 'text-teal-800' : ''}`}
        onClick={() => onSort(active ? '' : sort)}
      >
        {label}
        <span aria-hidden>{active ? '▲' : '↕'}</span>
      </button>
    </th>
  )
}

function SkeletonRows() {
  return (
    <div className="space-y-2" aria-hidden>
      {Array.from({ length: 6 }, (_, i) => (
        <div key={i} className="h-10 animate-pulse rounded bg-slate-100" />
      ))}
    </div>
  )
}

export default function PatientsPage() {
  const { t, i18n } = useTranslation()
  const [params, setParams] = useSearchParams()
  const { data: categories = [] } = useQuery({
    queryKey: ['diagnoses', 'categories'],
    queryFn: getCategories,
    staleTime: 60_000,
  })
  const { data: districts = [] } = useQuery({
    queryKey: ['districts'],
    queryFn: getDistricts,
    staleTime: Infinity,
  })
  const { data: tags = [] } = useQuery({
    queryKey: ['patients', 'tags'],
    queryFn: getTags,
    staleTime: 60_000,
  })
  const [q, setQ] = useState(params.get('q') ?? '')
  const get = (k: string) => params.get(k) ?? ''
  const kind = get('kind') as PatientKind | ''
  const sort = get('sort') as PatientSort | ''
  const limit = PAGE_SIZES.includes(Number(get('size'))) ? Number(get('size')) : PAGE_SIZES[0]
  const offset = Number(get('offset') || 0)
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

  const query = {
    q: debouncedQ,
    kind,
    category: get('category'),
    district: get('district'),
    source: get('source') as Source | '',
    tag: get('tag'),
    hasPhone: get('phone') as '' | 'yes' | 'no',
    sort,
    offset,
    limit,
  }
  const { data, error, isFetching, isLoading } = useQuery({
    queryKey: ['patients', query],
    queryFn: () => searchPatients(query),
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
  const active = FILTERS.some((k) => params.get(k))
  const nameOf = (code: string) => {
    const c = categories.find((x) => x.code === code)
    return c ? categoryName(c, i18n.language) : code
  }
  const checkCount = tags.find((x) => x.tag === CHECK_TAG)?.count ?? 0
  const pages = data ? Math.max(1, Math.ceil(data.total / limit)) : 1

  return (
    <div className="max-w-7xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold">{t('patients.title')}</h1>
        {!adding && <Button onClick={() => setAdding(true)}>{t('patients.new')}</Button>}
      </div>

      {adding && <NewPatient onClose={() => setAdding(false)} />}

      <Card>
        <div className="mb-3 space-y-3">
          <Input
            type="search"
            placeholder={t('patients.search')}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            autoFocus={!adding}
          />
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
            <Select
              value={kind}
              onChange={(e) => setParam('kind', e.target.value)}
              aria-label={t('patients.kind')}
            >
              <option value="">{t('patients.allKinds')}</option>
              {KINDS.map((k) => (
                <option key={k} value={k}>
                  {t(`kinds.${k}`)}
                </option>
              ))}
            </Select>
            <Select
              value={get('category')}
              onChange={(e) => setParam('category', e.target.value)}
              aria-label={t('patients.categoryHint')}
            >
              <option value="">{t('patients.allCategories')}</option>
              {categories
                .filter((c) => c.patients > 0)
                .map((c) => (
                  <option key={c.code} value={c.code}>
                    {categoryName(c, i18n.language)} ({c.patients})
                  </option>
                ))}
            </Select>
            <Select
              value={get('district')}
              onChange={(e) => setParam('district', e.target.value)}
              aria-label={t('patients.district')}
            >
              <option value="">{t('patientList.allDistricts')}</option>
              <option value={NO_DISTRICT}>{t('patientList.noDistrict')}</option>
              {districts.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </Select>
            <Select
              value={get('source')}
              onChange={(e) => setParam('source', e.target.value)}
              aria-label={t('patients.source')}
            >
              <option value="">{t('patientList.allSources')}</option>
              {[...SOURCES, 'import', 'cold_base'].map((s) => (
                <option key={s} value={s}>
                  {t(`sources.${s}`)}
                </option>
              ))}
            </Select>
            <Select
              value={get('tag')}
              onChange={(e) => setParam('tag', e.target.value)}
              aria-label={t('patientList.tag')}
            >
              <option value="">{t('patientList.allTags')}</option>
              {tags.map((x) => (
                <option key={x.tag} value={x.tag}>
                  {TAG_LABELS[x.tag] ? t(TAG_LABELS[x.tag]) : x.tag} ({x.count})
                </option>
              ))}
            </Select>
            <Select
              value={get('phone')}
              onChange={(e) => setParam('phone', e.target.value)}
              aria-label={t('patients.phone')}
            >
              <option value="">{t('patientList.phoneAny')}</option>
              <option value="yes">{t('patientList.phoneYes')}</option>
              <option value="no">{t('patientList.phoneNo')}</option>
            </Select>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {checkCount > 0 && (
              <button
                aria-pressed={get('tag') === CHECK_TAG}
                onClick={() => setParam('tag', get('tag') === CHECK_TAG ? '' : CHECK_TAG)}
                className={`rounded-full border px-3 py-1 text-xs font-medium ${
                  get('tag') === CHECK_TAG
                    ? 'border-amber-500 bg-amber-100 text-amber-900'
                    : 'border-amber-200 bg-amber-50 text-amber-800 hover:bg-amber-100'
                }`}
              >
                {t('patientList.checkView', { count: checkCount })}
              </button>
            )}
            <label className="flex items-center gap-2 text-xs text-slate-600 md:hidden">
              {t('patientList.sort')}
              <Select
                value={sort}
                onChange={(e) => setParam('sort', e.target.value)}
                className="w-44 py-1 text-xs"
              >
                <option value="">{t('patientList.sorts.default')}</option>
                {PATIENT_SORTS.map((s) => (
                  <option key={s} value={s}>
                    {t(`patientList.sorts.${s}`)}
                  </option>
                ))}
              </Select>
            </label>
            {active && (
              <button
                className="text-xs text-teal-800 hover:underline"
                onClick={() =>
                  setParams((prev) => {
                    const next = new URLSearchParams(prev)
                    FILTERS.forEach((k) => next.delete(k))
                    next.delete('offset')
                    return next
                  })
                }
              >
                {t('patientList.clear')}
              </button>
            )}
          </div>
          {get('tag') === CHECK_TAG && (
            <p className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900">
              {t('patientList.checkHint')}
            </p>
          )}
        </div>
        <ErrorText error={error} />
        {isLoading && <SkeletonRows />}
        {data && data.items.length === 0 && (
          <div className="py-8 text-center">
            <p className="text-sm font-medium text-slate-700">{t('patients.empty')}</p>
            <p className="mt-1 text-sm text-slate-500">
              {active || q ? t('patientList.emptyFilteredHint') : t('patientList.emptyHint')}
            </p>
            {!adding && (
              <Button variant="secondary" className="mt-3" onClick={() => setAdding(true)}>
                {t('patients.new')}
              </Button>
            )}
          </div>
        )}
        {data && data.items.length > 0 && (
          <>
            <ul className={`md:hidden ${isFetching ? 'opacity-60' : ''}`}>
              {data.items.map((p) => (
                <PatientListCard key={p.id} p={p} nameOf={nameOf} />
              ))}
            </ul>
            <div className={`-mx-5 hidden overflow-x-auto px-5 md:block ${isFetching ? 'opacity-60' : ''}`}>
              <table className="w-full min-w-[1000px] text-left text-sm">
                <thead className="text-xs text-slate-500 uppercase">
                  <tr>
                    <SortHeader
                      label={t('patients.name')}
                      sort="name"
                      current={sort}
                      onSort={(s) => setParam('sort', s)}
                    />
                    <th className="pb-2 font-medium">{t('patients.phone')}</th>
                    <th className="pb-2 font-medium">{t('patients.kind')}</th>
                    <SortHeader
                      label={t('patientList.age')}
                      sort="birth_date"
                      current={sort}
                      onSort={(s) => setParam('sort', s)}
                    />
                    <th className="pb-2 font-medium">{t('patients.district')}</th>
                    <th className="pb-2 font-medium">{t('patientList.categories')}</th>
                    <SortHeader
                      label={t('patients.lastVisit')}
                      sort="last_visit"
                      current={sort}
                      onSort={(s) => setParam('sort', s)}
                    />
                    <SortHeader
                      label={t('patientList.nextVisit')}
                      sort="next_visit"
                      current={sort}
                      onSort={(s) => setParam('sort', s)}
                    />
                    <th className="pb-2 font-medium">{t('patients.source')}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((p) => (
                    <PatientTableRow key={p.id} p={p} nameOf={nameOf} />
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
        {data && data.total > 0 && (
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm text-slate-600">
            <span>{t('patients.total', { count: data.total })}</span>
            <div className="flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-2 text-xs">
                {t('patientList.pageSize')}
                <Select
                  value={String(limit)}
                  onChange={(e) => setParam('size', e.target.value)}
                  className="w-20 py-1"
                >
                  {PAGE_SIZES.map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </Select>
              </label>
              <span className="text-xs tabular-nums">
                {t('patientList.page', { page: Math.floor(offset / limit) + 1, pages })}
              </span>
              <Button
                variant="secondary"
                disabled={offset === 0}
                onClick={() => setParam('offset', String(Math.max(0, offset - limit)))}
              >
                {t('audit.prev')}
              </Button>
              <Button
                variant="secondary"
                disabled={offset + limit >= data.total}
                onClick={() => setParam('offset', String(offset + limit))}
              >
                {t('audit.next')}
              </Button>
            </div>
          </div>
        )}
        <p className="mt-3 text-xs text-slate-400">{t('patientList.noExport')}</p>
      </Card>
    </div>
  )
}
