import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Badge, Button, Card, ErrorText, Input, Notice, Select } from '../components/ui'
import { getAiStatus } from '../lib/ai'
import { useAuth } from '../lib/auth-context'
import {
  approveMappings,
  categoryName,
  getCategories,
  getMappings,
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
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['diagnoses'] }),
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
  const { t } = useTranslation()
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
  const { data, error, isFetching } = useQuery({
    queryKey: ['diagnoses', 'mappings', status, category, debouncedQ, offset],
    queryFn: () => getMappings({ status, category, q: debouncedQ, offset, limit: PAGE }),
    placeholderData: keepPreviousData,
  })

  const invalidate = () => {
    setSelected(new Set())
    void queryClient.invalidateQueries({ queryKey: ['diagnoses'] })
    void queryClient.invalidateQueries({ queryKey: ['patients'] })
  }
  const approve = useMutation({ mutationFn: approveMappings, onSuccess: invalidate })
  const sync = useMutation({ mutationFn: syncDiagnoses, onSuccess: invalidate })
  const aiSuggest = useMutation({ mutationFn: aiSuggestDiagnoses, onSuccess: invalidate })
  const { data: ai } = useQuery({ queryKey: ['ai', 'status'], queryFn: getAiStatus, staleTime: 600_000 })

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
            <Button variant="ghost" disabled={sync.isPending} onClick={() => sync.mutate()}>
              {t('diagnoses.sync')}
            </Button>
            {ai?.enabled && (data?.by_status.pending ?? 0) > 0 && (
              <Button variant="secondary" disabled={aiSuggest.isPending} onClick={() => aiSuggest.mutate()}>
                {aiSuggest.isPending ? t('app.loading') : t('diagnoses.aiSuggest')}
              </Button>
            )}
          </div>
        )}
        {aiSuggest.data && (
          <Notice>
            {t('diagnoses.aiSuggested', {
              count: aiSuggest.data.suggested ?? 0,
              checked: aiSuggest.data.checked ?? 0,
            })}
          </Notice>
        )}
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
    </div>
  )
}
