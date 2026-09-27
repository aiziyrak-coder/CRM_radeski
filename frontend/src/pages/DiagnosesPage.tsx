import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Badge, Button, Card, ErrorText, Input, Modal, Notice, Select } from '../components/ui'
import { getAiStatus } from '../lib/ai'
import { useAuth } from '../lib/auth-context'
import {
  approveCategory,
  approveMappings,
  categoryName,
  getCategories,
  getMappings,
  getReviewProgress,
  setMappingCategory,
  syncDiagnoses,
  aiSuggestDiagnoses,
  type Category,
  type Mapping,
  type MappingStatus,
} from '../lib/diagnoses'

const PAGE = 100
const STATUS_TONE: Record<MappingStatus, 'neutral' | 'good' | 'info'> = {
  pending: 'neutral',
  suggested: 'info',
  approved: 'good',
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const id = window.setTimeout(() => setV(value), ms)
    return () => window.clearTimeout(id)
  }, [value, ms])
  return v
}

function CategoryGrid({
  categories,
  selected,
  onSelect,
}: {
  categories: Category[]
  selected: string
  onSelect: (code: string) => void
}) {
  const { t, i18n } = useTranslation()
  // compact chips: 34 categories must not push the review table off-screen
  return (
    <div className="flex flex-wrap gap-1.5">
      {categories.map((c) => (
        <button
          key={c.code}
          onClick={() => onSelect(selected === c.code ? '' : c.code)}
          title={t(`diagnoses.specialties.${c.specialty}`)}
          className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors ${
            selected === c.code
              ? 'border-teal-600 bg-teal-50 text-teal-900'
              : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300'
          }`}
        >
          <span className="font-medium">{categoryName(c, i18n.language)}</span>
          <span className="text-emerald-700 tabular-nums">{c.patients}</span>
          {c.suggested_texts > 0 && (
            <span className="rounded-full bg-amber-100 px-1.5 text-amber-800 tabular-nums">
              {c.suggested_texts}
            </span>
          )}
        </button>
      ))}
    </div>
  )
}

function Meter({ value, total }: { value: number; total: number }) {
  const pct = total ? Math.round((100 * value) / total) : 0
  return (
    <div className="h-2 overflow-hidden rounded-full bg-slate-100" role="progressbar" aria-valuenow={pct}>
      <div className="h-full rounded-full bg-teal-600" style={{ width: `${pct}%` }} />
    </div>
  )
}

/** TZ 4.8.4 review progress: texts a doctor has approved, patients who already have a category. */
function ReviewProgressCard() {
  const { t } = useTranslation()
  const { data: p } = useQuery({ queryKey: ['diagnoses', 'progress'], queryFn: getReviewProgress })
  if (!p || p.total === 0) return null
  const pct = (a: number, b: number) => (b ? Math.round((100 * a) / b) : 0)
  return (
    <Card title={t('diagnoses.progress.title')}>
      <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
        <div>
          <div className="mb-1 flex justify-between gap-2 text-sm">
            <span>{t('diagnoses.progress.texts', { approved: p.approved, total: p.total })}</span>
            <span className="font-semibold tabular-nums">{pct(p.approved, p.total)}%</span>
          </div>
          <Meter value={p.approved} total={p.total} />
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">
            <span>{t('diagnoses.progress.rule', { n: p.suggested_rule })}</span>
            <span>{t('diagnoses.progress.ai', { n: p.suggested_ai })}</span>
            <span>{t('diagnoses.progress.pending', { n: p.pending })}</span>
          </div>
        </div>
        <div>
          <div className="mb-1 flex justify-between gap-2 text-sm">
            <span>
              {t('diagnoses.progress.patients', { done: p.patients_categorized, total: p.patients })}
            </span>
            <span className="font-semibold tabular-nums">{pct(p.patients_categorized, p.patients)}%</span>
          </div>
          <Meter value={p.patients_categorized} total={p.patients} />
          <p className="mt-2 text-xs text-slate-600">{t('diagnoses.progress.patientsHint')}</p>
        </div>
      </div>
    </Card>
  )
}

/** Bulk approval of one category, after the doctor sees exactly which texts it covers. */
function BulkApprove({ category, onClose }: { category: Category; onClose: () => void }) {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const [withAi, setWithAi] = useState(false)
  const { data, error } = useQuery({
    queryKey: ['diagnoses', 'mappings', 'bulk', category.code],
    queryFn: () => getMappings({ status: 'suggested', category: category.code, offset: 0, limit: 500 }),
  })
  const items = data?.items.filter((m) => withAi || m.method === 'rule') ?? []
  const approve = useMutation({
    mutationFn: () => approveCategory(category.code, withAi ? null : 'rule'),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['diagnoses'] })
      void queryClient.invalidateQueries({ queryKey: ['patients'] })
    },
  })
  const name = categoryName(category, i18n.language)
  return (
    <Modal title={t('diagnoses.bulk.title', { name })} onClose={onClose} wide>
      {approve.data ? (
        <div className="space-y-3">
          <Notice>{t('diagnoses.approved', { count: approve.data.approved })}</Notice>
          <div className="flex justify-end">
            <Button onClick={onClose}>{t('app.close')}</Button>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-slate-700">{t('diagnoses.bulk.hint', { name })}</p>
          {category.suggested_ai > 0 && (
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={withAi} onChange={(e) => setWithAi(e.target.checked)} />
              {t('diagnoses.bulk.withAi', { n: category.suggested_ai })}
            </label>
          )}
          <ErrorText error={error ?? approve.error} />
          <div className="max-h-[50vh] overflow-y-auto rounded-md border border-slate-200">
            <table className="w-full text-left text-sm">
              <thead className="sticky top-0 bg-white text-xs text-slate-500 uppercase">
                <tr>
                  <th className="px-3 py-2 font-medium">{t('diagnoses.text')}</th>
                  <th className="px-3 py-2 text-right font-medium">{t('diagnoses.count')}</th>
                  <th className="px-3 py-2 font-medium" />
                </tr>
              </thead>
              <tbody>
                {items.map((m) => (
                  <tr key={m.id} className="border-t border-slate-100">
                    <td className="px-3 py-1.5">{m.text}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{m.patients}</td>
                    <td className="px-3 py-1.5 text-xs text-slate-500">
                      {m.method && t(`diagnoses.methods.${m.method}`)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data && items.length === 0 && (
              <p className="p-3 text-sm text-slate-500">{t('diagnoses.bulk.nothing')}</p>
            )}
          </div>
          {data && data.total > 500 && <p className="text-xs text-amber-800">{t('diagnoses.bulk.more')}</p>}
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="secondary" onClick={onClose}>
              {t('patients.cancel')}
            </Button>
            <Button
              disabled={!data || items.length === 0 || approve.isPending}
              onClick={() => approve.mutate()}
            >
              {t('diagnoses.bulk.confirm', { n: items.length })}
            </Button>
          </div>
        </div>
      )}
    </Modal>
  )
}

const QUEUE_ROWS = 8

/** Categories that still have suggestions: review a category, then approve all of it at once. */
function ReviewQueue({ categories, onShow }: { categories: Category[]; onShow: (code: string) => void }) {
  const { t, i18n } = useTranslation()
  const [bulk, setBulk] = useState<Category | null>(null)
  const [all, setAll] = useState(false)
  const waiting = categories
    .filter((c) => c.suggested_texts > 0)
    .sort((a, b) => b.suggested_texts - a.suggested_texts)
  if (waiting.length === 0) return null
  const shown = all ? waiting : waiting.slice(0, QUEUE_ROWS)
  return (
    <Card title={t('diagnoses.bulk.queue')}>
      <p className="mb-3 text-xs text-slate-500">{t('diagnoses.bulk.queueHint')}</p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-left text-sm">
          <thead className="text-xs text-slate-500 uppercase">
            <tr>
              <th className="pb-2 font-medium">{t('diagnoses.category')}</th>
              <th className="pb-2 text-right font-medium">{t('diagnoses.bulk.rule')}</th>
              <th className="pb-2 text-right font-medium">{t('diagnoses.bulk.ai')}</th>
              <th className="pb-2 text-right font-medium">{t('diagnoses.bulk.approvedCol')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {shown.map((c) => (
              <tr key={c.code} className="border-t border-slate-100">
                <td className="py-2 pr-3">
                  <div className="font-medium">{categoryName(c, i18n.language)}</div>
                  <div className="text-xs text-slate-500">{t(`diagnoses.specialties.${c.specialty}`)}</div>
                </td>
                <td className="py-2 pr-3 text-right tabular-nums">{c.suggested_rule}</td>
                <td className="py-2 pr-3 text-right tabular-nums">{c.suggested_ai}</td>
                <td className="py-2 pr-3 text-right tabular-nums">{c.approved_texts}</td>
                <td className="py-2 text-right whitespace-nowrap">
                  <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => onShow(c.code)}>
                    {t('diagnoses.bulk.show')}
                  </Button>
                  <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => setBulk(c)}>
                    {t('diagnoses.bulk.approveAll')}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {waiting.length > QUEUE_ROWS && (
        <Button variant="ghost" className="mt-2 px-2 py-1 text-xs" onClick={() => setAll(!all)}>
          {all ? t('diagnoses.bulk.fewer') : t('diagnoses.bulk.all', { n: waiting.length })}
        </Button>
      )}
      {bulk && <BulkApprove category={bulk} onClose={() => setBulk(null)} />}
    </Card>
  )
}

function MappingRow({
  m,
  categories,
  canEdit,
  checked,
  onCheck,
}: {
  m: Mapping
  categories: Category[]
  canEdit: boolean
  checked: boolean
  onCheck: (v: boolean) => void
}) {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const set = useMutation({
    mutationFn: (code: string) => setMappingCategory(m.id, code),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['diagnoses'] })
      void queryClient.invalidateQueries({ queryKey: ['patients'] }) // category badges and filter
    },
  })
  const current = categories.find((c) => c.code === m.category_code)

  return (
    <tr className="border-t border-slate-100 align-top">
      {canEdit && (
        <td className="py-2 pr-2">
          <input
            type="checkbox"
            aria-label={m.text}
            disabled={m.status !== 'suggested'}
            checked={checked}
            onChange={(e) => onCheck(e.target.checked)}
          />
        </td>
      )}
      <td className="py-2 pr-4">{m.text}</td>
      <td className="py-2 pr-4 text-right tabular-nums">{m.patients}</td>
      <td className="py-2 pr-4">
        {canEdit ? (
          <Select
            value={m.category_code ?? ''}
            disabled={set.isPending}
            onChange={(e) => e.target.value && set.mutate(e.target.value)}
            className="min-w-44 max-w-64"
          >
            <option value="">{t('diagnoses.choose')}</option>
            {categories.map((c) => (
              <option key={c.code} value={c.code}>
                {categoryName(c, i18n.language)}
              </option>
            ))}
          </Select>
        ) : (
          (current && categoryName(current, i18n.language)) || '—'
        )}
        <ErrorText error={set.error} />
      </td>
      <td className="py-2 whitespace-nowrap">
        <Badge tone={STATUS_TONE[m.status]}>{t(`diagnoses.statuses.${m.status}`)}</Badge>
        {m.method && (
          <span className="ml-1 text-xs text-slate-500">{t(`diagnoses.methods.${m.method}`)}</span>
        )}
      </td>
    </tr>
  )
}

export default function DiagnosesPage() {
  const { t, i18n } = useTranslation()
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const canEdit = user?.role === 'admin' || user?.role === 'doctor'
  const [status, setStatus] = useState<MappingStatus | ''>('suggested')
  const [category, setCategory] = useState('')
  const [q, setQ] = useState('')
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const debouncedQ = useDebounced(q, 300)

  const { data: categories = [] } = useQuery({
    queryKey: ['diagnoses', 'categories'],
    queryFn: getCategories,
  })
  // while the AI job runs in the background, the list refreshes itself for a while
  const [aiStartedAt, setAiStartedAt] = useState<number | null>(null)
  const { data, error, isFetching } = useQuery({
    queryKey: ['diagnoses', 'mappings', status, category, debouncedQ, offset],
    queryFn: () => getMappings({ status, category, q: debouncedQ, offset, limit: PAGE }),
    placeholderData: keepPreviousData,
    refetchInterval: () => (aiStartedAt && Date.now() - aiStartedAt < 10 * 60_000 ? 15_000 : false),
  })

  const invalidate = () => {
    setSelected(new Set())
    void queryClient.invalidateQueries({ queryKey: ['diagnoses'] })
    void queryClient.invalidateQueries({ queryKey: ['patients'] })
  }
  const approve = useMutation({ mutationFn: approveMappings, onSuccess: invalidate })
  const sync = useMutation({ mutationFn: syncDiagnoses, onSuccess: invalidate })
  const aiSuggest = useMutation({
    mutationFn: aiSuggestDiagnoses,
    onSuccess: () => setAiStartedAt(Date.now()),
  })
  const { data: ai } = useQuery({ queryKey: ['ai', 'status'], queryFn: getAiStatus, staleTime: 600_000 })

  const [bulk, setBulk] = useState<Category | null>(null)
  const selectedCategory = categories.find((c) => c.code === category)
  const suggestedOnPage = data?.items.filter((m) => m.status === 'suggested').map((m) => m.id) ?? []
  const resetPaging = () => {
    setOffset(0)
    setSelected(new Set())
  }

  return (
    <div className="max-w-6xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">{t('diagnoses.title')}</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-600">{t('diagnoses.intro')}</p>
        {!canEdit && <p className="mt-2 text-sm text-amber-800">{t('diagnoses.readOnly')}</p>}
      </div>

      <ReviewProgressCard />
      {canEdit && (
        <ReviewQueue
          categories={categories}
          onShow={(code) => {
            setCategory(code)
            setStatus('suggested')
            resetPaging()
            document.getElementById('mappings')?.scrollIntoView({ behavior: 'smooth' })
          }}
        />
      )}

      <Card title={t('diagnoses.categories')}>
        <p className="mb-3 text-xs text-slate-500">{t('diagnoses.legend')}</p>
        <CategoryGrid
          categories={categories}
          selected={category}
          onSelect={(code) => {
            setCategory(code)
            resetPaging()
          }}
        />
      </Card>

      <div id="mappings" />
      <Card>
        <div className="mb-4 flex flex-col gap-3 md:flex-row">
          <Input
            type="search"
            placeholder={t('diagnoses.search')}
            value={q}
            onChange={(e) => {
              setQ(e.target.value)
              resetPaging()
            }}
            className="md:flex-1"
          />
          <Select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value as MappingStatus | '')
              resetPaging()
            }}
            className="md:w-56"
          >
            <option value="">{t('diagnoses.allStatuses')}</option>
            {(['suggested', 'pending', 'approved'] as const).map((s) => (
              <option key={s} value={s}>
                {t(`diagnoses.statuses.${s}`)} ({data?.by_status[s] ?? 0})
              </option>
            ))}
          </Select>
        </div>

        {canEdit && (
          <div className="mb-4 flex flex-wrap gap-2">
            <Button
              disabled={selected.size === 0 || approve.isPending}
              onClick={() => approve.mutate([...selected])}
            >
              {t('diagnoses.approveSelected', { count: selected.size })}
            </Button>
            <Button
              variant="secondary"
              disabled={suggestedOnPage.length === 0 || approve.isPending}
              onClick={() => approve.mutate(suggestedOnPage)}
            >
              {t('diagnoses.approvePage')}
            </Button>
            {selectedCategory && selectedCategory.suggested_texts > 0 && (
              <Button variant="secondary" onClick={() => setBulk(selectedCategory)}>
                {t('diagnoses.bulk.approveCategory', {
                  name: categoryName(selectedCategory, i18n.language),
                  n: selectedCategory.suggested_rule,
                })}
              </Button>
            )}
            <Button variant="ghost" disabled={sync.isPending} onClick={() => sync.mutate()}>
              {t('diagnoses.sync')}
            </Button>
            {ai?.enabled && (data?.by_status.pending ?? 0) > 0 && (
              <Button
                variant="secondary"
                disabled={aiSuggest.isPending || aiSuggest.isSuccess}
                onClick={() => aiSuggest.mutate()}
              >
                {aiSuggest.isPending ? t('app.loading') : t('diagnoses.aiSuggest')}
              </Button>
            )}
          </div>
        )}
        {aiSuggest.isSuccess && <Notice>{t('diagnoses.aiStarted')}</Notice>}
        {approve.data && <Notice>{t('diagnoses.approved', { count: approve.data.approved })}</Notice>}
        <ErrorText error={error ?? approve.error ?? sync.error ?? aiSuggest.error} />

        {data && (
          <div className={`mt-3 overflow-x-auto ${isFetching ? 'opacity-60' : ''}`}>
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="text-xs text-slate-500 uppercase">
                <tr>
                  {canEdit && <th />}
                  <th className="pb-2 font-medium">{t('diagnoses.text')}</th>
                  <th className="pb-2 text-right font-medium">{t('diagnoses.count')}</th>
                  <th className="pb-2 pl-4 font-medium">{t('diagnoses.category')}</th>
                  <th className="pb-2 font-medium">{t('diagnoses.status')}</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((m) => (
                  <MappingRow
                    key={m.id}
                    m={m}
                    categories={categories}
                    canEdit={canEdit}
                    checked={selected.has(m.id)}
                    onCheck={(v) =>
                      setSelected((prev) => {
                        const next = new Set(prev)
                        if (v) next.add(m.id)
                        else next.delete(m.id)
                        return next
                      })
                    }
                  />
                ))}
              </tbody>
            </table>
            <div className="mt-4 flex items-center justify-between text-sm text-slate-600">
              <span>{t('patients.total', { count: data.total })}</span>
              <div className="flex gap-2">
                <Button
                  variant="secondary"
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - PAGE))}
                >
                  {t('audit.prev')}
                </Button>
                <Button
                  variant="secondary"
                  disabled={offset + PAGE >= data.total}
                  onClick={() => setOffset(offset + PAGE)}
                >
                  {t('audit.next')}
                </Button>
              </div>
            </div>
          </div>
        )}
      </Card>
      {bulk && <BulkApprove category={bulk} onClose={() => setBulk(null)} />}
    </div>
  )
}
