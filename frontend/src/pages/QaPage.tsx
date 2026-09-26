import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import CallAnalysisDialog, { ScoreBadge } from '../components/CallAnalysisDialog'
import PatientName from '../components/PatientName'
import { Badge, Button, Card, ErrorText, Field, Input, Notice, Select } from '../components/ui'
import {
  getAiStatus,
  getCriteria,
  getDigest,
  getQaCalls,
  getQaOverview,
  makeDigest,
  updateCriterion,
  type QaCriterion,
} from '../lib/ai'
import { useAuth } from '../lib/auth-context'
import { canOpen } from '../lib/navigation'
import { formatDate, formatDateTime } from '../lib/patients'
import { addDays, clinicDate } from '../lib/scheduling'

type Tab = 'overview' | 'calls' | 'criteria' | 'digest'

function Stat({ label, value }: { label: string; value: string | number | null }) {
  return (
    <div className="rounded-md border border-slate-200 bg-white px-4 py-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value ?? '—'}</div>
    </div>
  )
}

function Overview({ from, to, userId }: { from: string; to: string; userId: string }) {
  const { t, i18n } = useTranslation()
  const { data, error } = useQuery({
    queryKey: ['ai', 'qa', 'overview', from, to, userId],
    queryFn: () => getQaOverview(from, to, userId || undefined),
    placeholderData: keepPreviousData,
  })
  if (error) return <ErrorText error={error} />
  if (!data) return null
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label={t('ai.analysed')} value={data.analysed} />
        <Stat label={t('ai.avgScore')} value={data.avg_score} />
        <Stat label={t('ai.redFlagsOpen')} value={data.red_flags_open} />
        <Stat
          label={t('ai.corrections')}
          value={`${data.reviews.corrected ?? 0} / ${(data.reviews.corrected ?? 0) + (data.reviews.confirmed ?? 0)}`}
        />
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title={t('ai.byOperator')}>
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
          {data.operators.length === 0 && <p className="text-sm text-slate-500">{t('ai.noData')}</p>}
        </Card>
        <Card title={t('ai.byCriterion')}>
          <ul className="space-y-2 text-sm">
            {data.criteria.map((c) => (
              <li key={c.code}>
                <div className="flex justify-between">
                  <span>{i18n.language === 'ru' ? c.name_ru : c.name_uz}</span>
                  <span className="tabular-nums">{c.pass_rate === null ? '—' : `${c.pass_rate}%`}</span>
                </div>
                <div className="mt-1 h-1.5 rounded bg-slate-100">
                  <div
                    className={`h-1.5 rounded ${(c.pass_rate ?? 0) >= 80 ? 'bg-emerald-500' : (c.pass_rate ?? 0) >= 60 ? 'bg-amber-400' : 'bg-red-500'}`}
                    style={{ width: `${c.pass_rate ?? 0}%` }}
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
        <Select value={order} onChange={(e) => setOrder(e.target.value as typeof order)} className="w-48">
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
          onChange={(e) => setForm({ ...form, name_uz: e.target.value })}
        />
        <Input
          value={form.name_ru}
          disabled={!canEdit}
          onChange={(e) => setForm({ ...form, name_ru: e.target.value })}
        />
      </div>
      <textarea
        value={form.description}
        disabled={!canEdit}
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

function Criteria() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const { data, error } = useQuery({ queryKey: ['ai', 'criteria'], queryFn: getCriteria })
  const canEdit = user?.role === 'supervisor' || user?.role === 'admin'
  return (
    <Card title={t('ai.criteriaTitle')}>
      <p className="mb-2 text-xs text-slate-500">{t('ai.criteriaHint')}</p>
      <ErrorText error={error} />
      <ul className="divide-y divide-slate-100">
        {data?.map((c) => (
          <CriterionRow key={`${c.id}-${c.weight}-${c.active}-${c.name_uz}`} c={c} canEdit={canEdit} />
        ))}
      </ul>
    </Card>
  )
}

function DigestView() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const { data, error } = useQuery({ queryKey: ['ai', 'digest'], queryFn: getDigest })
  const make = useMutation({
    mutationFn: makeDigest,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['ai', 'digest'] }),
  })
  const canMake = user?.role === 'supervisor' || user?.role === 'admin'
  return (
    <Card title={t('ai.digest')}>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        {data && (
          <span className="text-sm text-slate-600">
            {formatDate(data.period_from)} — {formatDate(data.period_to)}
          </span>
        )}
        {canMake && (
          <Button variant="secondary" disabled={make.isPending} onClick={() => make.mutate()}>
            {make.isPending ? t('app.loading') : t('ai.makeDigest')}
          </Button>
        )}
      </div>
      <ErrorText error={error ?? make.error} />
      {!data && <p className="text-sm text-slate-500">{t('ai.noDigest')}</p>}
      {data && (
        <div className="space-y-3 text-sm">
          <p className="text-slate-600">
            {t('ai.digestStats', { calls: data.stats.calls_analysed, score: data.stats.avg_score ?? '—' })}
          </p>
          {data.content ? (
            <>
              <p>{data.content.summary}</p>
              {(['top_questions', 'objections'] as const).map((k) => (
                <div key={k}>
                  <h3 className="font-medium">{t(`ai.digestParts.${k}`)}</h3>
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
          {Object.keys(data.stats.refusal_reasons).length > 0 && (
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
      )}
    </Card>
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
  return (
    <div className="max-w-6xl space-y-4">
      <h1 className="text-2xl font-semibold">{t('ai.title')}</h1>
      {status && !status.enabled && <Notice>{t('ai.disabled')}</Notice>}
      {status?.enabled && (
        <p className="text-xs text-slate-500">
          {t('ai.spend', {
            spent: status.spent_today_usd.toFixed(3),
            budget: status.daily_budget_usd,
          })}
          {status.daily_budget_usd > 0 && status.spent_today_usd >= status.daily_budget_usd && (
            <span className="ml-2 font-medium text-amber-800">{t('ai.budgetReached')}</span>
          )}
        </p>
      )}
      <div className="flex gap-1 overflow-x-auto overflow-y-hidden border-b border-slate-200">
        {(['overview', 'calls', 'criteria', 'digest'] as const).map((k) => (
          <button
            key={k}
            onClick={() => setTab(k)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm whitespace-nowrap ${tab === k ? 'border-teal-700 font-medium text-teal-800' : 'border-transparent text-slate-600'}`}
          >
            {t(`ai.tabs.${k}`)}
          </button>
        ))}
      </div>
      {(tab === 'overview' || tab === 'calls') && (
        <div className="flex flex-wrap items-end gap-2">
          <Field label={t('reports.from')}>
            <Input
              type="date"
              value={from}
              onChange={(e) => e.target.value && setFrom(e.target.value)}
              className="w-44"
            />
          </Field>
          <Field label={t('reports.to')}>
            <Input
              type="date"
              value={to}
              onChange={(e) => e.target.value && setTo(e.target.value)}
              className="w-44"
            />
          </Field>
          <Field label={t('reports.operator')}>
            <Select value={userId} onChange={(e) => setUserId(e.target.value)} className="w-56">
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
      {tab === 'overview' && <Overview from={from} to={to} userId={userId} />}
      {tab === 'calls' && <Calls from={from} to={to} userId={userId} />}
      {tab === 'criteria' && <Criteria />}
      {tab === 'digest' && <DigestView />}
    </div>
  )
}
