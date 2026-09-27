import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import CallAnalysisDialog, { ScoreBadge } from '../components/CallAnalysisDialog'
import { ChartCard, DataTable, Legend, TrendChart } from '../components/charts'
import PatientName from '../components/PatientName'
import RecordingPlayer from '../components/RecordingPlayer'
import { Badge, Button, Card, ErrorText, Field, Input, Notice, Select } from '../components/ui'
import {
  createCriterion,
  errorKey,
  getAiStatus,
  getCriteria,
  getDigestById,
  getDigests,
  getQaCalls,
  getQaOverview,
  getQaQueue,
  getQaTrend,
  getViolations,
  makeDigest,
  retryAnalyses,
  updateCriterion,
  type Digest,
  type QaCriterion,
  type QaTrend,
} from '../lib/ai'
import { useAuth } from '../lib/auth-context'
import { canOpen } from '../lib/navigation'
import { formatDate, formatDateTime } from '../lib/patients'
import { SERIES, shortDay, type SeriesDef } from '../lib/reports'
import { addDays, clinicDate } from '../lib/scheduling'
import { formatDuration } from '../lib/telephony'

type Tab = 'overview' | 'violations' | 'calls' | 'queue' | 'criteria' | 'digest'
const TABS: Tab[] = ['overview', 'violations', 'calls', 'queue', 'criteria', 'digest']
const RED_FLAGS = ['diagnosis', 'pressure', 'false_promise', 'complaint']

function Stat({ label, value }: { label: string; value: string | number | null }) {
  return (
    <div className="rounded-md border border-slate-200 bg-white px-4 py-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value ?? '—'}</div>
    </div>
  )
}

function useCriterionName() {
  const { t, i18n } = useTranslation()
  const { data: criteria = [] } = useQuery({
    queryKey: ['ai', 'criteria'],
    queryFn: getCriteria,
    staleTime: 600_000,
  })
  return (code: string) => {
    if (RED_FLAGS.includes(code)) return t(`ai.flags.${code}`)
    const c = criteria.find((x) => x.code === code)
    if (c) return i18n.language === 'ru' ? c.name_ru : c.name_uz
    return t(`ai.criteria.${code}`, { defaultValue: code })
  }
}

/** Average score over days/weeks: the whole team plus each operator (colour per operator). */
function ScoreTrend({ trend }: { trend: QaTrend }) {
  const { t } = useTranslation()
  const operators = [...trend.operators].filter((o) => o.user_id).sort((a, b) => a.name.localeCompare(b.name))
  const shown = operators.slice(0, 3)
  const series: SeriesDef[] = [
    { key: 'all', label: t('qa.team'), color: SERIES[0] },
    ...shown.map((o, i) => ({ key: o.user_id!, label: o.name, color: SERIES[i + 1] })),
  ]
  const rows = trend.points.map((p, i) => ({
    start: p.start,
    all: p.avg_score,
    ...Object.fromEntries(shown.map((o) => [o.user_id!, o.points[i]?.avg_score ?? null])),
  })) as Record<string, string | number | null>[]
  const xFormat = (x: string) =>
    trend.bucket === 'week' ? t('qa.weekOf', { day: shortDay(x) }) : shortDay(x)
  return (
    <ChartCard
      title={t('qa.scoreTrend')}
      hint={operators.length > shown.length ? t('qa.topOperators', { n: shown.length }) : undefined}
      empty={trend.points.every((p) => p.avg_score === null) && t('ai.noData')}
      legend={<Legend series={series} />}
      table={
        <DataTable
          rows={rows}
          columns={[
            { key: 'start', label: t('qa.period'), format: (v) => xFormat(String(v)) },
            ...series.map((s) => ({ key: s.key, label: s.label })),
          ]}
        />
      }
    >
      <TrendChart data={rows} xKey="start" series={series} yDomain={[0, 100]} xFormat={xFormat} />
    </ChartCard>
  )
}

/** Pass rate of one criterion over time; the weakest one is shown first. */
function CriterionTrend({ trend }: { trend: QaTrend }) {
  const { t, i18n } = useTranslation()
  const withData = trend.criteria.filter((c) => c.points.some((p) => p.applicable > 0))
  const overall = (c: QaTrend['criteria'][number]) => {
    const n = c.points.reduce((s, p) => s + p.applicable, 0)
    const ok = c.points.reduce((s, p) => s + ((p.pass_rate ?? 0) * p.applicable) / 100, 0)
    return n ? ok / n : 1
  }
  const weakest = [...withData].sort((a, b) => overall(a) - overall(b))[0]
  const [code, setCode] = useState<string>('')
  const current = withData.find((c) => c.code === code) ?? weakest
  const name = (c: QaTrend['criteria'][number]) => (i18n.language === 'ru' ? c.name_ru : c.name_uz)
  const xFormat = (x: string) =>
    trend.bucket === 'week' ? t('qa.weekOf', { day: shortDay(x) }) : shortDay(x)
  const rows = current?.points ?? []
  return (
    <ChartCard
      title={t('qa.criterionTrend')}
      hint={current ? name(current) : undefined}
      empty={!current && t('ai.noData')}
      table={
        <DataTable
          rows={rows}
          columns={[
            { key: 'start', label: t('qa.period'), format: (v) => xFormat(String(v)) },
            { key: 'pass_rate', label: t('qa.passRate'), format: (v) => (v === null ? '—' : `${v}%`) },
            { key: 'applicable', label: t('qa.applicable') },
          ]}
        />
      }
    >
      <Select
        value={current?.code ?? ''}
        onChange={(e) => setCode(e.target.value)}
        aria-label={t('qa.criterion')}
        className="w-full sm:w-80"
      >
        {withData.map((c) => (
          <option key={c.code} value={c.code}>
            {name(c)}
          </option>
        ))}
      </Select>
      <TrendChart
        data={rows}
        xKey="start"
        series={[{ key: 'pass_rate', label: t('qa.passRate'), color: SERIES[0] }]}
        yDomain={[0, 100]}
        format={(v) => (v === null ? '—' : `${v}%`)}
        xFormat={xFormat}
      />
    </ChartCard>
  )
}

function Overview({ from, to, userId }: { from: string; to: string; userId: string }) {
  const { t, i18n } = useTranslation()
  const [bucket, setBucket] = useState<'day' | 'week'>('day')
  const { data, error } = useQuery({
    queryKey: ['ai', 'qa', 'overview', from, to, userId],
    queryFn: () => getQaOverview(from, to, userId || undefined),
    placeholderData: keepPreviousData,
  })
  const trend = useQuery({
    queryKey: ['ai', 'qa', 'trend', from, to, userId, bucket],
    queryFn: () => getQaTrend(from, to, bucket, userId || undefined),
    placeholderData: keepPreviousData,
  })
  if (error) return <ErrorText error={error} />
  if (!data) return <p className="text-sm text-slate-500">{t('app.loading')}</p>
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label={t('ai.analysed')} value={data.analysed} />
        <Stat label={t('ai.avgScore')} value={data.avg_score} />
        <Stat label={t('ai.redFlagsOpen')} value={data.red_flags_open} />
        <Stat
          label={t('ai.corrections')}
          value={`${data.reviews.corrected ?? 0} / ${(data.reviews.corrected ?? 0) + (data.reviews.confirmed ?? 0)}`}
        />
      </div>
      <div className="flex items-center gap-2 text-sm">
        <span className="text-slate-600">{t('qa.bucket')}:</span>
        {(['day', 'week'] as const).map((b) => (
          <Button
            key={b}
            variant={bucket === b ? 'primary' : 'secondary'}
            className="px-2 py-1 text-xs"
            aria-pressed={bucket === b}
            onClick={() => setBucket(b)}
          >
            {t(`qa.buckets.${b}`)}
          </Button>
        ))}
      </div>
      <ErrorText error={trend.error} />
      {trend.data && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <ScoreTrend trend={trend.data} />
          <CriterionTrend trend={trend.data} />
        </div>
      )}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title={t('ai.byOperator')}>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-slate-500 uppercase">
                <tr>
                  <th className="pb-2">{t('reports.operator')}</th>
                  <th className="pb-2 pl-3 text-right">{t('ai.calls')}</th>
                  <th className="pb-2 pl-3 text-right">{t('ai.avgScore')}</th>
                  <th className="pb-2 pl-3 text-right">{t('ai.redFlags')}</th>
                </tr>
              </thead>
              <tbody>
                {data.operators.map((o) => (
                  <tr key={o.user_id ?? 'none'} className="border-t border-slate-100">
                    <td className="py-2">{o.name}</td>
                    <td className="py-2 text-right tabular-nums">{o.calls}</td>
                    <td className="py-2 text-right">
                      <ScoreBadge score={o.avg_score} />
                    </td>
                    <td className="py-2 text-right tabular-nums">{o.red_flags}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.operators.length === 0 && <p className="text-sm text-slate-500">{t('ai.noData')}</p>}
        </Card>
        <Card title={t('ai.byCriterion')}>
          <ul className="space-y-2 text-sm">
            {data.criteria.map((c) => (
              <li key={c.code}>
                <div className="flex justify-between gap-2">
                  <span>{i18n.language === 'ru' ? c.name_ru : c.name_uz}</span>
                  <span className="tabular-nums">{c.pass_rate === null ? '—' : `${c.pass_rate}%`}</span>
                </div>
                <div className="mt-1 h-1.5 rounded bg-slate-100">
                  <div
                    className="h-1.5 rounded"
                    style={{ width: `${c.pass_rate ?? 0}%`, background: SERIES[0] }}
                  />
                </div>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  )
}

function Violations({ from, to, userId }: { from: string; to: string; userId: string }) {
  const { t } = useTranslation()
  const { user } = useAuth()
  const name = useCriterionName()
  const [kind, setKind] = useState<'all' | 'violation' | 'red_flag'>('all')
  const [code, setCode] = useState('')
  const [offset, setOffset] = useState(0)
  const [open, setOpen] = useState<string | null>(null)
  const { data, error, isFetching } = useQuery({
    queryKey: ['ai', 'qa', 'violations', from, to, userId, kind, code, offset],
    queryFn: () =>
      getViolations(from, to, { userId: userId || undefined, kind, code: code || undefined, offset }),
    placeholderData: keepPreviousData,
  })
  const counts = Object.entries(data?.counts ?? {}).sort((a, b) => b[1] - a[1])
  return (
    <Card>
      <div className="mb-3 grid grid-cols-1 gap-2 sm:flex sm:flex-wrap sm:items-end">
        <Field label={t('qa.kind')}>
          <Select
            value={kind}
            onChange={(e) => {
              setKind(e.target.value as typeof kind)
              setCode('')
              setOffset(0)
            }}
            className="w-full sm:w-64"
          >
            {(['all', 'violation', 'red_flag'] as const).map((k) => (
              <option key={k} value={k}>
                {t(`qa.kinds.${k}`)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t('qa.criterion')}>
          <Select
            value={code}
            onChange={(e) => {
              setCode(e.target.value)
              setOffset(0)
            }}
            className="w-full sm:w-80"
          >
            <option value="">{t('qa.allCriteria')}</option>
            {counts.map(([c, n]) => (
              <option key={c} value={c}>
                {name(c)} ({n})
              </option>
            ))}
          </Select>
        </Field>
      </div>
      <ErrorText error={error} />
      {data && data.items.length === 0 && (
        <p className="py-4 text-center text-sm text-slate-500">{t('qa.noViolations')}</p>
      )}
      <ul className={`divide-y divide-slate-100 ${isFetching ? 'opacity-70' : ''}`}>
        {data?.items.map((v, i) => (
          <li
            key={`${v.analysis_id}-${v.kind}-${v.code}-${i}`}
            className="flex flex-wrap items-start gap-3 py-3 text-sm"
          >
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={v.kind === 'red_flag' ? (v.reviewed ? 'neutral' : 'bad') : 'info'}>
                  {name(v.code)}
                </Badge>
                <span className="text-xs text-slate-500 tabular-nums">{formatDateTime(v.started_at)}</span>
                <span className="text-slate-600">{v.user_name ?? '—'}</span>
                {v.patient_id &&
                  (canOpen(user?.role, '/patients') ? (
                    <Link to={`/patients/${v.patient_id}`} className="text-teal-800 hover:underline">
                      <PatientName name={v.patient_name ?? '—'} />
                    </Link>
                  ) : (
                    <PatientName name={v.patient_name ?? '—'} />
                  ))}
              </div>
              {v.quote && <p className="mt-1 text-slate-800">«{v.quote}»</p>}
            </div>
            <div className="flex items-center gap-2">
              <RecordingPlayer callId={v.call_id} at={v.at} />
              <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => setOpen(v.call_id)}>
                {t('ai.open')}
              </Button>
            </div>
          </li>
        ))}
      </ul>
      {data && data.total > 50 && (
        <div className="mt-3 flex items-center justify-between gap-2 text-sm">
          <span className="text-slate-600">
            {t('calls.pageInfo', {
              from: offset + 1,
              to: Math.min(data.total, offset + 50),
              total: data.total,
            })}
          </span>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - 50))}
            >
              ← {t('app.prev')}
            </Button>
            <Button
              variant="secondary"
              disabled={offset + 50 >= data.total}
              onClick={() => setOffset(offset + 50)}
            >
              {t('app.next')} →
            </Button>
          </div>
        </div>
      )}
      {open && (
        <CallAnalysisDialog
          callId={open}
          onClose={() => setOpen(null)}
          canAck={user?.role === 'supervisor' || user?.role === 'admin'}
        />
      )}
    </Card>
  )
}

function Calls({ from, to, userId }: { from: string; to: string; userId: string }) {
  const { t } = useTranslation()
  const { user } = useAuth()
  const [order, setOrder] = useState<'recent' | 'worst' | 'best'>('recent')
  const [flagged, setFlagged] = useState(false)
  const [open, setOpen] = useState<string | null>(null)
  const { data, error } = useQuery({
    queryKey: ['ai', 'qa', 'calls', from, to, userId, order, flagged],
    queryFn: () => getQaCalls(from, to, { userId: userId || undefined, order, flagged }),
    placeholderData: keepPreviousData,
  })
  return (
    <Card>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <Select
          value={order}
          onChange={(e) => setOrder(e.target.value as typeof order)}
          className="w-48"
          aria-label={t('qa.order')}
        >
          {(['recent', 'worst', 'best'] as const).map((o) => (
            <option key={o} value={o}>
              {t(`ai.order.${o}`)}
            </option>
          ))}
        </Select>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={flagged} onChange={(e) => setFlagged(e.target.checked)} />
          {t('ai.onlyFlagged')}
        </label>
      </div>
      <ErrorText error={error} />
      {data && data.length === 0 && (
        <p className="py-4 text-center text-sm text-slate-500">{t('ai.noData')}</p>
      )}
      <ul className="divide-y divide-slate-100">
        {data?.map((c) => (
          <li key={c.analysis_id} className="flex flex-wrap items-start gap-3 py-3">
            <ScoreBadge score={c.score} />
            <div className="min-w-0 flex-1 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-slate-500 tabular-nums">{formatDateTime(c.started_at)}</span>
                <span>{t(`calls.dir.${c.direction}`)}</span>
                <span className="text-slate-600">{c.user_name ?? '—'}</span>
                {c.patient_id &&
                  (canOpen(user?.role, '/patients') ? (
                    <Link to={`/patients/${c.patient_id}`} className="text-teal-800 hover:underline">
                      <PatientName name={c.patient_name ?? '—'} />
                    </Link>
                  ) : (
                    <PatientName name={c.patient_name ?? '—'} />
                  ))}
                {c.red_flags.map((f) => (
                  <Badge key={f} tone={c.flags_reviewed ? 'neutral' : 'bad'}>
                    {t(`ai.flags.${f}`)}
                  </Badge>
                ))}
              </div>
              <p className="mt-1 text-slate-700">{c.summary}</p>
            </div>
            <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => setOpen(c.call_id)}>
              {t('ai.open')}
            </Button>
          </li>
        ))}
      </ul>
      {open && (
        <CallAnalysisDialog
          callId={open}
          onClose={() => setOpen(null)}
          canAck={user?.role === 'supervisor' || user?.role === 'admin'}
        />
      )}
    </Card>
  )
}

/** Recorded calls without a usable analysis; the supervisor can send them again. */
function Queue({ from, to, aiEnabled }: { from: string; to: string; aiEnabled: boolean }) {
  const { t } = useTranslation()
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const canRetry = (user?.role === 'supervisor' || user?.role === 'admin') && aiEnabled
  const { data, error } = useQuery({
    queryKey: ['ai', 'qa', 'queue', from, to],
    queryFn: () => getQaQueue(from, to),
    refetchInterval: 30_000,
  })
  const retry = useMutation({
    mutationFn: retryAnalyses,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['ai', 'qa', 'queue'] }),
  })
  const failed = data?.items.filter((i) => i.status === 'failed' || i.status === 'missing') ?? []
  return (
    <Card
      title={t('qa.queueTitle')}
      actions={
        canRetry &&
        failed.length > 0 && (
          <Button
            variant="secondary"
            className="px-2 py-1 text-xs"
            disabled={retry.isPending}
            onClick={() => retry.mutate(failed.map((i) => i.call_id))}
          >
            {t('qa.retryAll', { count: failed.length })}
          </Button>
        )
      }
    >
      <p className="mb-3 text-xs text-slate-500">{t('qa.queueHint')}</p>
      <ErrorText error={error ?? retry.error} />
      {retry.data && (
        <p className="mb-2 text-sm text-emerald-700">{t('qa.retried', { count: retry.data.queued })}</p>
      )}
      {data && (
        <div className="mb-3 flex flex-wrap gap-2">
          {Object.entries(data.counts).map(([k, n]) => (
            <Badge key={k} tone={k === 'failed' ? 'bad' : 'neutral'}>
              {t(`qa.queueStatus.${k}`)}: {n}
            </Badge>
          ))}
        </div>
      )}
      {data && data.total === 0 && (
        <p className="py-4 text-center text-sm text-slate-500">{t('qa.queueEmpty')}</p>
      )}
      {data && data.items.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead className="text-xs text-slate-500 uppercase">
              <tr>
                <th className="pb-2">{t('calls.time')}</th>
                <th className="pb-2">{t('calls.operator')}</th>
                <th className="pb-2">{t('calls.caller')}</th>
                <th className="pb-2 text-right">{t('calls.talk')}</th>
                <th className="pb-2 pl-3">{t('calls.status')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.items.map((i) => (
                <tr key={i.call_id} className="border-t border-slate-100 align-top">
                  <td className="py-2 pr-3 whitespace-nowrap tabular-nums">{formatDateTime(i.started_at)}</td>
                  <td className="py-2 pr-3">{i.user_name ?? '—'}</td>
                  <td className="py-2 pr-3">
                    {i.patient_name ? <PatientName name={i.patient_name} /> : '—'}
                  </td>
                  <td className="py-2 text-right tabular-nums">{formatDuration(i.talk_seconds)}</td>
                  <td className="py-2 pl-3">
                    <Badge tone={i.status === 'failed' ? 'bad' : 'neutral'}>
                      {t(`qa.queueStatus.${i.status}`)}
                    </Badge>
                    {i.attempts > 0 && <span className="ml-1 text-xs text-slate-500">×{i.attempts}</span>}
                    {i.error && (
                      <div className="text-xs text-red-700" title={i.error}>
                        {t(`ai.errors.${errorKey(i.error)}`)}
                      </div>
                    )}
                  </td>
                  <td className="py-2 text-right">
                    {canRetry && (i.status === 'failed' || i.status === 'missing') && (
                      <Button
                        variant="secondary"
                        className="px-2 py-1 text-xs"
                        disabled={retry.isPending}
                        onClick={() => retry.mutate([i.call_id])}
                      >
                        {t('qa.retry')}
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

function CriterionRow({ c, canEdit }: { c: QaCriterion; canEdit: boolean }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [form, setForm] = useState(c)
  const dirty = JSON.stringify(form) !== JSON.stringify(c)
  const save = useMutation({
    mutationFn: () => updateCriterion(c.id, form),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['ai', 'criteria'] }),
  })
  return (
    <li className="space-y-2 py-3">
      <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
        <Input
          value={form.name_uz}
          disabled={!canEdit}
          aria-label={t('qa.nameUz')}
          onChange={(e) => setForm({ ...form, name_uz: e.target.value })}
        />
        <Input
          value={form.name_ru}
          disabled={!canEdit}
          aria-label={t('qa.nameRu')}
          onChange={(e) => setForm({ ...form, name_ru: e.target.value })}
        />
      </div>
      <textarea
        value={form.description}
        disabled={!canEdit}
        aria-label={t('qa.description')}
        onChange={(e) => setForm({ ...form, description: e.target.value })}
        rows={2}
        className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
      />
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span className="font-mono text-xs text-slate-500">{c.code}</span>
        <label className="flex items-center gap-2">
          {t('ai.weight')}
          <Input
            type="number"
            min={0}
            max={100}
            value={form.weight}
            disabled={!canEdit}
            onChange={(e) => setForm({ ...form, weight: Number(e.target.value) })}
            className="w-20"
          />
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={form.active}
            disabled={!canEdit}
            onChange={(e) => setForm({ ...form, active: e.target.checked })}
          />
          {t('ai.active')}
        </label>
        {canEdit && dirty && (
          <Button className="px-2 py-1 text-xs" disabled={save.isPending} onClick={() => save.mutate()}>
            {t('patients.save')}
          </Button>
        )}
        <ErrorText error={save.error} />
      </div>
    </li>
  )
}

const EMPTY_CRITERION = { name_uz: '', name_ru: '', description: '', weight: 10, active: true }

function NewCriterion({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [form, setForm] = useState(EMPTY_CRITERION)
  const add = useMutation({
    mutationFn: () => createCriterion(form),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['ai', 'criteria'] })
      setForm(EMPTY_CRITERION)
      onDone()
    },
  })
  const valid =
    form.name_uz.trim().length >= 2 && form.name_ru.trim().length >= 2 && form.description.trim().length >= 5
  return (
    <div className="mb-4 space-y-2 rounded-md border border-teal-200 bg-teal-50/40 p-3">
      <h3 className="text-sm font-semibold">{t('qa.newCriterion')}</h3>
      <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
        <Field label={t('qa.nameUz')}>
          <Input value={form.name_uz} onChange={(e) => setForm({ ...form, name_uz: e.target.value })} />
        </Field>
        <Field label={t('qa.nameRu')}>
          <Input value={form.name_ru} onChange={(e) => setForm({ ...form, name_ru: e.target.value })} />
        </Field>
      </div>
      <Field label={t('qa.description')} hint={t('qa.descriptionHint')}>
        <textarea
          value={form.description}
          onChange={(e) => setForm({ ...form, description: e.target.value })}
          rows={2}
          className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
        />
      </Field>
      <div className="flex flex-wrap items-end gap-3">
        <Field label={t('ai.weight')}>
          <Input
            type="number"
            min={0}
            max={100}
            value={form.weight}
            onChange={(e) => setForm({ ...form, weight: Number(e.target.value) })}
            className="w-24"
          />
        </Field>
        <Button disabled={!valid || add.isPending} onClick={() => add.mutate()}>
          {t('qa.addCriterion')}
        </Button>
        <Button variant="ghost" onClick={onDone}>
          {t('qa.cancel')}
        </Button>
      </div>
      <ErrorText error={add.error} />
    </div>
  )
}

function Criteria() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const [adding, setAdding] = useState(false)
  const { data, error } = useQuery({ queryKey: ['ai', 'criteria'], queryFn: getCriteria })
  const canEdit = user?.role === 'supervisor' || user?.role === 'admin'
  return (
    <Card
      title={t('ai.criteriaTitle')}
      actions={
        canEdit &&
        !adding && (
          <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => setAdding(true)}>
            + {t('qa.newCriterion')}
          </Button>
        )
      }
    >
      <p className="mb-2 text-xs text-slate-500">{t('ai.criteriaHint')}</p>
      {adding && <NewCriterion onDone={() => setAdding(false)} />}
      <ErrorText error={error} />
      <ul className="divide-y divide-slate-100">
        {data?.map((c) => (
          <CriterionRow key={`${c.id}-${c.weight}-${c.active}-${c.name_uz}`} c={c} canEdit={canEdit} />
        ))}
      </ul>
    </Card>
  )
}

function DigestBody({ data }: { data: Digest }) {
  const { t } = useTranslation()
  return (
    <div className="space-y-3 text-sm">
      <p className="text-slate-600">
        {formatDate(data.period_from)} — {formatDate(data.period_to)} ·{' '}
        {t('ai.digestStats', { calls: data.stats.calls_analysed, score: data.stats.avg_score ?? '—' })}
      </p>
      {data.content ? (
        <>
          <p>{data.content.summary}</p>
          {(['top_questions', 'objections'] as const).map((k) => (
            <div key={k}>
              <h3 className="font-medium">{t(`ai.digestParts.${k}`)}</h3>
              {data.content![k].length === 0 && <p className="text-slate-500">—</p>}
              <ul className="list-disc pl-5">
                {data.content![k].map((q, i) => (
                  <li key={i}>
                    {q.text} <span className="text-slate-500">×{q.count}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
          {(['complaints', 'recommendations'] as const).map((k) => (
            <div key={k}>
              <h3 className="font-medium">{t(`ai.digestParts.${k}`)}</h3>
              {data.content![k].length === 0 && <p className="text-slate-500">—</p>}
              <ul className="list-disc pl-5">
                {data.content![k].map((q, i) => (
                  <li key={i}>{q}</li>
                ))}
              </ul>
            </div>
          ))}
        </>
      ) : (
        <Notice>{t('ai.digestNoAi')}</Notice>
      )}
      {Object.keys(data.stats.refusal_reasons ?? {}).length > 0 && (
        <div>
          <h3 className="font-medium">{t('reports.reasons')}</h3>
          <ul>
            {Object.entries(data.stats.refusal_reasons).map(([k, n]) => (
              <li key={k}>
                {t(`reasons.${k}`, { defaultValue: k })}: {n}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function DigestView() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<string | null>(null)
  const list = useQuery({ queryKey: ['ai', 'digests'], queryFn: getDigests })
  const id = selected ?? list.data?.[0]?.id ?? null
  const one = useQuery({
    queryKey: ['ai', 'digest', id],
    queryFn: () => getDigestById(id!),
    enabled: Boolean(id),
  })
  const make = useMutation({
    mutationFn: makeDigest,
    onSuccess: (d) => {
      setSelected(d.id)
      void queryClient.invalidateQueries({ queryKey: ['ai', 'digests'] })
    },
  })
  const canMake = user?.role === 'supervisor' || user?.role === 'admin'
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[18rem_1fr]">
      <Card
        title={t('qa.digestHistory')}
        actions={
          canMake && (
            <Button
              variant="secondary"
              className="px-2 py-1 text-xs"
              disabled={make.isPending}
              onClick={() => make.mutate()}
            >
              {make.isPending ? t('app.loading') : t('ai.makeDigest')}
            </Button>
          )
        }
      >
        <ErrorText error={list.error ?? make.error} />
        {list.data && list.data.length === 0 && <p className="text-sm text-slate-500">{t('ai.noDigest')}</p>}
        <ul className="-mx-2 space-y-1">
          {list.data?.map((d) => (
            <li key={d.id}>
              <button
                type="button"
                onClick={() => setSelected(d.id)}
                aria-current={d.id === id}
                className={`w-full rounded-md px-2 py-1.5 text-left text-sm ${d.id === id ? 'bg-teal-50 font-medium text-teal-900' : 'hover:bg-slate-50'}`}
              >
                <div>
                  {formatDate(d.period_from)} — {formatDate(d.period_to)}
                </div>
                <div className="text-xs text-slate-500">
                  {t('qa.digestItem', { calls: d.calls_analysed, score: d.avg_score ?? '—' })}
                  {!d.has_content && ` · ${t('qa.numbersOnly')}`}
                </div>
              </button>
            </li>
          ))}
        </ul>
      </Card>
      <Card title={t('ai.digest')}>
        <ErrorText error={one.error} />
        {!id && <p className="text-sm text-slate-500">{t('ai.noDigest')}</p>}
        {one.data && <DigestBody data={one.data} />}
      </Card>
    </div>
  )
}

export default function QaPage() {
  const { t } = useTranslation()
  const [tab, setTab] = useState<Tab>('overview')
  const [from, setFrom] = useState(addDays(clinicDate(), -6))
  const [to, setTo] = useState(clinicDate())
  const [userId, setUserId] = useState('')
  const { data: status } = useQuery({ queryKey: ['ai', 'status'], queryFn: getAiStatus })
  const { data: overview } = useQuery({
    queryKey: ['ai', 'qa', 'overview', from, to, ''],
    queryFn: () => getQaOverview(from, to),
  })
  const periodTabs: Tab[] = ['overview', 'violations', 'calls', 'queue']
  return (
    <div className="max-w-6xl space-y-4">
      <h1 className="text-2xl font-semibold">{t('ai.title')}</h1>
      {status && !status.enabled && <Notice>{t('ai.disabled')}</Notice>}
      {status?.enabled && status.spent_today_usd != null && (
        <p className="text-xs text-slate-500">
          {t(status.daily_budget_usd > 0 ? 'ai.spend' : 'ai.spendNoLimit', {
            spent: status.spent_today_usd.toFixed(3),
            budget: status.daily_budget_usd,
          })}
          {status.daily_budget_usd > 0 && status.spent_today_usd >= status.daily_budget_usd && (
            <span className="ml-2 font-medium text-amber-800">{t('ai.budgetReached')}</span>
          )}
        </p>
      )}
      <div className="flex gap-1 overflow-x-auto overflow-y-hidden border-b border-slate-200">
        {TABS.map((k) => (
          <button
            key={k}
            onClick={() => setTab(k)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm whitespace-nowrap ${tab === k ? 'border-teal-700 font-medium text-teal-800' : 'border-transparent text-slate-600'}`}
          >
            {t(`qa.tabs.${k}`)}
          </button>
        ))}
      </div>
      {periodTabs.includes(tab) && (
        <div className="grid grid-cols-2 items-end gap-2 sm:flex sm:flex-wrap">
          <Field label={t('reports.from')}>
            <Input
              type="date"
              value={from}
              max={to}
              onChange={(e) => e.target.value && setFrom(e.target.value)}
              className="w-full sm:w-44"
            />
          </Field>
          <Field label={t('reports.to')}>
            <Input
              type="date"
              value={to}
              min={from}
              onChange={(e) => e.target.value && setTo(e.target.value)}
              className="w-full sm:w-44"
            />
          </Field>
          {tab !== 'queue' && (
            <div className="col-span-2 sm:col-span-1">
              <Field label={t('reports.operator')}>
                <Select value={userId} onChange={(e) => setUserId(e.target.value)} className="w-full sm:w-56">
                  <option value="">{t('reports.allOperators')}</option>
                  {overview?.operators
                    .filter((o) => o.user_id)
                    .map((o) => (
                      <option key={o.user_id} value={o.user_id!}>
                        {o.name}
                      </option>
                    ))}
                </Select>
              </Field>
            </div>
          )}
        </div>
      )}
      {tab === 'overview' && <Overview from={from} to={to} userId={userId} />}
      {tab === 'violations' && <Violations from={from} to={to} userId={userId} />}
      {tab === 'calls' && <Calls from={from} to={to} userId={userId} />}
      {tab === 'queue' && <Queue from={from} to={to} aiEnabled={Boolean(status?.enabled)} />}
      {tab === 'criteria' && <Criteria />}
      {tab === 'digest' && <DigestView />}
    </div>
  )
}
