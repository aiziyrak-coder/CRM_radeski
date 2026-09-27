import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router'
import CampaignForm from '../components/CampaignForm'
import { ProgressBar, SegmentChips, StatusActions } from '../components/CampaignParts'
import { Badge, Button, Card, ErrorText, Select } from '../components/ui'
import {
  STATUS_TONE,
  getCampaign,
  getMembers,
  makeAiSummary,
  toInput,
  type AiSummary,
  type CampaignDetail,
} from '../lib/campaigns'
import { getCategories } from '../lib/diagnoses'
import { formatDate, formatDateTime, formatPhone } from '../lib/patients'

const PAGE = 50
const OUTCOMES = [
  'booked',
  'refused',
  'thinking',
  'callback',
  'no_answer',
  'wrong_number',
  'do_not_call',
  'done',
] as const

function Kpi({ label, value, hint }: { label: string; value: string | number | null; hint?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-4 py-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value ?? '—'}</div>
      {hint && <div className="mt-0.5 text-xs text-slate-500">{hint}</div>}
    </div>
  )
}

function Breakdown({
  rows,
  label,
  empty,
}: {
  rows: [string, number][]
  label: (k: string) => string
  empty: string
}) {
  const total = rows.reduce((s, [, n]) => s + n, 0)
  if (total === 0) return <p className="text-sm text-slate-500">{empty}</p>
  return (
    <ul className="space-y-1.5">
      {rows
        .sort((a, b) => b[1] - a[1])
        .map(([k, n]) => (
          <li key={k} className="text-sm">
            <div className="flex justify-between gap-2">
              <span className="min-w-0 truncate">{label(k)}</span>
              <span className="shrink-0 tabular-nums">
                {n} <span className="text-xs text-slate-500">({Math.round((100 * n) / total)}%)</span>
              </span>
            </div>
            <ProgressBar percent={(100 * n) / total} className="mt-0.5 h-1.5" />
          </li>
        ))}
    </ul>
  )
}

function AbCard({ c }: { c: CampaignDetail }) {
  const { t } = useTranslation()
  if (!c.ab) return null
  const best = c.ab.every((v) => v.booking_rate !== null)
    ? c.ab.reduce((a, b) => ((b.booking_rate ?? 0) > (a.booking_rate ?? 0) ? b : a)).variant
    : null
  return (
    <Card title={t('campaigns.ab.title')}>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[480px] text-left text-sm">
          <thead className="text-xs text-slate-500 uppercase">
            <tr>
              <th className="pb-2 pl-3">{t('campaigns.ab.variant')}</th>
              <th className="pb-2 pl-3 text-right">{t('campaigns.ab.tasks')}</th>
              <th className="pb-2 pl-3 text-right">{t('campaigns.ab.reached')}</th>
              <th className="pb-2 pl-3 text-right">{t('campaigns.ab.booked')}</th>
              <th className="pb-2 pl-3 text-right">{t('campaigns.ab.rate')}</th>
            </tr>
          </thead>
          <tbody>
            {c.ab.map((v) => (
              <tr key={v.variant} className="border-t border-slate-100">
                <td className="py-2 pr-3">
                  <b>{v.variant.toUpperCase()}</b> <span className="text-slate-600">{v.script_code}</span>
                  {best === v.variant && c.ab!.some((x) => x.booking_rate !== v.booking_rate) && (
                    <span className="ml-2">
                      <Badge tone="good">{t('campaigns.ab.leader')}</Badge>
                    </span>
                  )}
                </td>
                <td className="py-2 text-right tabular-nums">{v.tasks}</td>
                <td className="py-2 text-right tabular-nums">{v.reached}</td>
                <td className="py-2 text-right tabular-nums">{v.booked}</td>
                <td className="py-2 text-right font-semibold tabular-nums">
                  {v.booking_rate === null ? '—' : `${v.booking_rate}%`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-slate-500">{t('campaigns.ab.hint')}</p>
    </Card>
  )
}

function SummaryList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null
  return (
    <div>
      <div className="text-xs font-semibold text-slate-500 uppercase">{title}</div>
      <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm">
        {items.map((x, i) => (
          <li key={i}>{x}</li>
        ))}
      </ul>
    </div>
  )
}

function AiSummaryCard({ c }: { c: CampaignDetail }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const make = useMutation({
    mutationFn: () => makeAiSummary(c.id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['campaigns', 'detail', c.id] }),
  })
  const s: AiSummary | null = make.data?.content ?? c.ai_summary
  const noCalls = c.results.calls === 0
  return (
    <Card
      title={t('campaigns.ai.title')}
      actions={
        <Button
          variant="secondary"
          className="px-2 py-1 text-xs"
          disabled={make.isPending || noCalls}
          onClick={() => make.mutate()}
        >
          {make.isPending
            ? t('campaigns.ai.working')
            : s
              ? t('campaigns.ai.refresh')
              : t('campaigns.ai.make')}
        </Button>
      }
    >
      <ErrorText error={make.error} />
      {!s && (
        <p className="text-sm text-slate-500">
          {noCalls ? t('campaigns.ai.noCalls') : t('campaigns.ai.hint')}
        </p>
      )}
      {s && (
        <div className="space-y-3">
          {c.ai_summary_stale && !make.data && (
            <p className="text-xs text-amber-800">{t('campaigns.ai.stale')}</p>
          )}
          <p className="text-sm whitespace-pre-line">{s.summary}</p>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <SummaryList title={t('campaigns.ai.worked')} items={s.what_worked} />
            <SummaryList title={t('campaigns.ai.problems')} items={s.problems} />
            <SummaryList title={t('campaigns.ai.refusals')} items={s.refusal_insights} />
            <SummaryList title={t('campaigns.ai.next')} items={s.recommendations} />
          </div>
          {s.ab_verdict && (
            <p className="rounded-md bg-slate-50 px-3 py-2 text-sm">
              <b>A/B:</b> {s.ab_verdict}
            </p>
          )}
          <p className="text-[11px] text-slate-500">
            {t('campaigns.ai.footer', { at: formatDateTime(make.data?.created_at ?? c.ai_summary_at) })}
          </p>
        </div>
      )}
    </Card>
  )
}

function Members({ c }: { c: CampaignDetail }) {
  const { t } = useTranslation()
  const [status, setStatus] = useState('')
  const [outcome, setOutcome] = useState('')
  const [variant, setVariant] = useState('')
  const [offset, setOffset] = useState(0)
  const { data, error, isFetching } = useQuery({
    queryKey: ['campaigns', 'members', c.id, status, outcome, variant, offset],
    queryFn: () => getMembers(c.id, { status, outcome, variant, offset, limit: PAGE }),
    placeholderData: keepPreviousData,
  })
  const reset = (fn: () => void) => {
    fn()
    setOffset(0)
  }
  return (
    <Card title={t('campaigns.members.title')}>
      <div className="mb-3 flex flex-wrap gap-2">
        <Select
          value={status}
          onChange={(e) => reset(() => setStatus(e.target.value))}
          className="w-40 py-1 text-xs"
        >
          <option value="">{t('campaigns.members.anyStatus')}</option>
          {(['open', 'done', 'cancelled'] as const).map((s) => (
            <option key={s} value={s}>
              {t(`campaigns.members.statuses.${s}`)}
            </option>
          ))}
        </Select>
        <Select
          value={outcome}
          onChange={(e) => reset(() => setOutcome(e.target.value))}
          className="w-44 py-1 text-xs"
        >
          <option value="">{t('campaigns.members.anyOutcome')}</option>
          {OUTCOMES.map((o) => (
            <option key={o} value={o}>
              {t(`outcomes.${o}`)}
            </option>
          ))}
        </Select>
        {c.script_code_b && (
          <Select
            value={variant}
            onChange={(e) => reset(() => setVariant(e.target.value))}
            className="w-32 py-1 text-xs"
          >
            <option value="">A + B</option>
            <option value="a">A</option>
            <option value="b">B</option>
          </Select>
        )}
      </div>
      <ErrorText error={error} />
      {data && data.total === 0 && (
        <p className="py-4 text-sm text-slate-500">
          {c.status === 'draft' ? t('campaigns.members.draft') : t('campaigns.members.empty')}
        </p>
      )}
      {data && data.total > 0 && (
        <div className={`overflow-x-auto ${isFetching ? 'opacity-60' : ''}`}>
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead className="text-xs text-slate-500 uppercase">
              <tr>
                <th className="pb-2 pr-3">{t('campaigns.members.patient')}</th>
                <th className="pb-2 pr-3">{t('campaigns.members.status')}</th>
                <th className="pb-2 pr-3">{t('campaigns.members.result')}</th>
                <th className="pb-2 pr-3 text-right">{t('campaigns.members.attempts')}</th>
                <th className="pb-2 pr-3">{t('campaigns.members.when')}</th>
                <th className="pb-2 pr-3">{t('campaigns.members.visit')}</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((m) => (
                <tr key={m.task_id} className="border-t border-slate-100 align-top">
                  <td className="py-2 pr-3">
                    {m.patient_id ? (
                      <Link
                        to={`/patients/${m.patient_id}`}
                        className="font-medium text-teal-800 hover:underline"
                      >
                        {m.patient_name ?? '—'}
                      </Link>
                    ) : (
                      '—'
                    )}
                    <div className="text-xs text-slate-500 tabular-nums">
                      {formatPhone(m.phone)}
                      {c.script_code_b && ` · ${m.variant.toUpperCase()}`}
                    </div>
                  </td>
                  <td className="py-2 pr-3">
                    <Badge tone={m.status === 'open' ? 'info' : 'neutral'}>
                      {t(`campaigns.members.statuses.${m.status}`)}
                    </Badge>
                  </td>
                  <td className="py-2 pr-3">
                    {m.outcome ? t(`outcomes.${m.outcome}`) : '—'}
                    {m.reason && (
                      <div className="text-xs text-slate-500">
                        {t(`reasons.${m.reason}`, { defaultValue: m.reason })}
                      </div>
                    )}
                  </td>
                  <td className="py-2 pr-3 text-right tabular-nums">{m.attempts}</td>
                  <td className="py-2 pr-3 text-xs whitespace-nowrap text-slate-600">
                    {formatDateTime(m.last_attempt_at ?? m.created_at)}
                  </td>
                  <td className="py-2">
                    {m.arrived ? (
                      <Badge tone="good">{t('campaigns.members.arrived')}</Badge>
                    ) : m.booked ? (
                      <Badge tone="info">{t('campaigns.members.booked')}</Badge>
                    ) : (
                      <span className="text-slate-400">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && data.total > PAGE && (
        <div className="mt-3 flex items-center justify-between text-sm text-slate-600">
          <span>
            {offset + 1}–{Math.min(offset + PAGE, data.total)} / {data.total}
          </span>
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
      )}
    </Card>
  )
}

export default function CampaignDetailPage() {
  const { t } = useTranslation()
  const { id = '' } = useParams()
  const [editing, setEditing] = useState(false)
  const { data: categories = [] } = useQuery({
    queryKey: ['diagnoses', 'categories'],
    queryFn: getCategories,
  })
  const {
    data: c,
    error,
    isLoading,
  } = useQuery({
    queryKey: ['campaigns', 'detail', id],
    queryFn: () => getCampaign(id),
    refetchInterval: 60_000,
  })
  if (isLoading) return <p className="text-sm text-slate-500">{t('app.loading')}</p>
  if (error || !c)
    return (
      <div className="space-y-3">
        <ErrorText error={error ?? new Error('campaign_not_found')} />
        <Link to="/campaigns" className="text-sm text-teal-800 hover:underline">
          ← {t('campaigns.back')}
        </Link>
      </div>
    )
  const r = c.results
  const p = c.progress
  const pct = (v: number | null) => (v === null ? null : `${v}%`)

  return (
    <div className="max-w-6xl space-y-4">
      <Link to="/campaigns" className="text-sm text-teal-800 hover:underline">
        ← {t('campaigns.back')}
      </Link>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-semibold break-words">{c.name}</h1>
            <Badge tone={STATUS_TONE[c.status]}>{t(`campaigns.statuses.${c.status}`)}</Badge>
          </div>
          <p className="mt-1 text-xs text-slate-500">
            {t('campaigns.meta', {
              created: formatDate(c.created_at),
              limit: c.daily_limit,
              ends: c.ends_on ? formatDate(c.ends_on) : t('campaigns.noEnd'),
            })}
          </p>
          {c.description && (
            <p className="mt-2 max-w-3xl text-sm whitespace-pre-line text-slate-700">{c.description}</p>
          )}
          <div className="mt-2">
            <SegmentChips segment={c.segment} categories={categories} />
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {c.status !== 'finished' && !editing && (
            <Button variant="secondary" onClick={() => setEditing(true)}>
              {t('campaigns.edit')}
            </Button>
          )}
          <StatusActions c={c} />
        </div>
      </div>

      {editing && (
        <CampaignForm
          id={c.id}
          initial={toInput(c)}
          title={t('campaigns.edit')}
          onDone={() => setEditing(false)}
        />
      )}
      {c.status === 'draft' && !editing && (
        <p className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900">{t('campaigns.draftHint')}</p>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi
          label={t('campaigns.kpi.calls')}
          value={r.calls}
          hint={t('campaigns.kpi.callsHint', { count: r.called })}
        />
        <Kpi
          label={t('campaigns.kpi.dialRate')}
          value={pct(r.dial_rate)}
          hint={t('campaigns.kpi.dialHint', { reached: r.reached, called: r.called })}
        />
        <Kpi
          label={t('campaigns.kpi.booked')}
          value={r.booked}
          hint={r.booking_rate === null ? undefined : t('campaigns.kpi.bookedHint', { rate: r.booking_rate })}
        />
        <Kpi
          label={t('campaigns.kpi.arrived')}
          value={r.arrived}
          hint={
            r.arrival_rate === null ? undefined : t('campaigns.kpi.arrivedHint', { rate: r.arrival_rate })
          }
        />
      </div>

      <Card title={t('campaigns.progress')}>
        <div className="mb-2 flex flex-wrap justify-between gap-2 text-sm">
          <span>
            {t('campaigns.progressLine', { done: p.tasked, total: p.audience, percent: p.percent })}
          </span>
          <span className="text-slate-600">
            {p.days_left !== null
              ? t('campaigns.daysLeft', { count: p.days_left, limit: c.daily_limit })
              : ''}
          </span>
        </div>
        <ProgressBar percent={p.percent} className="h-3" />
        <div className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <div>
            <div className="text-xs text-slate-500">{t('campaigns.prog.remaining')}</div>
            <div className="font-semibold tabular-nums">{p.remaining}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500">{t('campaigns.prog.open')}</div>
            <div className="font-semibold tabular-nums">{r.open}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500">{t('campaigns.prog.todayTasks')}</div>
            <div className="font-semibold tabular-nums">
              {r.today.tasks} / {c.daily_limit}
            </div>
          </div>
          <div>
            <div className="text-xs text-slate-500">{t('campaigns.prog.todayCalls')}</div>
            <div className="font-semibold tabular-nums">{r.today.calls}</div>
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title={t('campaigns.outcomesTitle')}>
          <Breakdown
            rows={Object.entries(r.outcomes)}
            label={(k) => t(`outcomes.${k}`, { defaultValue: k })}
            empty={t('campaigns.noResults')}
          />
        </Card>
        <Card title={t('campaigns.reasonsTitle')}>
          <Breakdown
            rows={Object.entries(r.refusal_reasons)}
            label={(k) => t(`reasons.${k}`, { defaultValue: k })}
            empty={t('campaigns.noRefusals')}
          />
        </Card>
      </div>

      <AbCard c={c} />
      <AiSummaryCard c={c} />
      <Members c={c} />
    </div>
  )
}
