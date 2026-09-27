import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { DashboardCharts, KpiTile, OperatorBoard } from '../components/KpiDashboard'
import { Button, Card, ErrorText, Field, Input, Select } from '../components/ui'
import { useAuth } from '../lib/auth-context'
import { SOURCES } from '../lib/patients'
import {
  downloadDaily,
  downloadKpi,
  getDaily,
  getReportOperators,
  getServiceCategories,
  useKpiData,
  type CallStats,
  type KpiKey,
  type ReportFilters,
} from '../lib/reports'
import { addDays, clinicDate, getBranches } from '../lib/scheduling'

function Stat({ label, value, hint }: { label: string; value: string | number | null; hint?: string }) {
  return (
    <div className="rounded-md border border-slate-200 bg-white px-4 py-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value ?? '—'}</div>
      {hint && <div className="text-xs text-slate-500">{hint}</div>}
    </div>
  )
}

// roles the backend lets list operators and read KPIs
const MANAGERS = ['supervisor', 'owner', 'admin']

const pct = (v: number | null) => (v === null ? null : `${v}%`)

function CallStatsRow({ data }: { data: CallStats }) {
  const { t } = useTranslation()
  if (data.inbound_calls === null) {
    return <p className="text-sm text-slate-500">{t('reports.telephonyNote')}</p>
  }
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Stat
        label={t('reports.inbound')}
        value={data.inbound_calls}
        hint={t('reports.inboundHint', { answered: data.inbound_answered, missed: data.inbound_missed })}
      />
      <Stat
        label={t('reports.answerRate')}
        value={pct(data.inbound_answer_rate)}
        hint={t('reports.callbacks', { count: data.callbacks_requested ?? 0 })}
      />
      <Stat
        label={t('reports.avgWait')}
        value={data.avg_wait_sec === null ? null : t('reports.seconds', { n: data.avg_wait_sec })}
      />
      <Stat
        label={t('reports.outboundCalls')}
        value={data.outbound_calls}
        hint={t('reports.talk', { n: data.talk_minutes })}
      />
    </div>
  )
}

/** Branch, operator, source and service direction (TZ 4.11), one row above everything. */
function FilterBar({
  value,
  onChange,
  withOperator,
}: {
  value: ReportFilters
  onChange: (f: ReportFilters) => void
  withOperator: boolean
}) {
  const { t, i18n } = useTranslation()
  const ru = i18n.language === 'ru'
  const { data: branches = [] } = useQuery({
    queryKey: ['catalog', 'branches'],
    queryFn: getBranches,
    staleTime: 600_000,
  })
  const { data: categories = [] } = useQuery({
    queryKey: ['catalog', 'service-categories'],
    queryFn: getServiceCategories,
    staleTime: 600_000,
  })
  const { data: users = [] } = useQuery({
    queryKey: ['reports', 'operators'],
    queryFn: getReportOperators,
    enabled: withOperator,
    staleTime: 300_000,
  })
  const set = (patch: ReportFilters) => onChange({ ...value, ...patch })
  const active = Object.values(value).some(Boolean)
  return (
    <>
      <Field label={t('reports.branch')}>
        <Select
          value={value.branch_id ?? ''}
          onChange={(e) => set({ branch_id: e.target.value })}
          className="w-full sm:w-44"
        >
          <option value="">{t('reports.allBranches')}</option>
          {branches
            .filter((b) => b.is_active)
            .map((b) => (
              <option key={b.id} value={b.id}>
                {ru ? b.name_ru : b.name_uz}
              </option>
            ))}
        </Select>
      </Field>
      {withOperator && (
        <Field label={t('reports.operator')}>
          <Select
            value={value.user_id ?? ''}
            onChange={(e) => set({ user_id: e.target.value })}
            className="w-full sm:w-52"
          >
            <option value="">{t('reports.allOperators')}</option>
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.full_name}
              </option>
            ))}
          </Select>
        </Field>
      )}
      <Field label={t('reports.source')}>
        <Select
          value={value.source ?? ''}
          onChange={(e) => set({ source: e.target.value as ReportFilters['source'] })}
          className="w-full sm:w-44"
        >
          <option value="">{t('reports.allSources')}</option>
          {SOURCES.map((s) => (
            <option key={s} value={s}>
              {t(`sources.${s}`)}
            </option>
          ))}
        </Select>
      </Field>
      <Field label={t('reports.direction')}>
        <Select
          value={value.category_id ?? ''}
          onChange={(e) => set({ category_id: e.target.value })}
          className="w-full sm:w-52"
        >
          <option value="">{t('reports.allDirections')}</option>
          {categories.map((c) => (
            <option key={c.id} value={c.id}>
              {ru ? c.name_ru : c.name_uz}
            </option>
          ))}
        </Select>
      </Field>
      {active && (
        <Button variant="ghost" onClick={() => onChange({})}>
          {t('reports.clearFilters')}
        </Button>
      )}
    </>
  )
}

function Daily({ filters, setFilters }: { filters: ReportFilters; setFilters: (f: ReportFilters) => void }) {
  const { t } = useTranslation()
  const { user } = useAuth()
  const [date, setDate] = useState(clinicDate())
  const isManager = MANAGERS.includes(user?.role ?? '')
  const { data, error, isFetching } = useQuery({
    queryKey: ['reports', 'daily', date, filters],
    queryFn: () => getDaily(date, filters),
    placeholderData: keepPreviousData,
  })
  const download = useMutation({ mutationFn: () => downloadDaily(date, filters) })
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 items-end gap-2 sm:flex sm:flex-wrap">
        <Field label={t('reports.date')}>
          <Input
            type="date"
            value={date}
            max={clinicDate()}
            onChange={(e) => e.target.value && setDate(e.target.value)}
            className="w-full sm:w-44"
          />
        </Field>
        <FilterBar value={filters} onChange={setFilters} withOperator={isManager} />
        <Button variant="secondary" disabled={download.isPending} onClick={() => download.mutate()}>
          {t('reports.download')}
        </Button>
      </div>
      <p className="text-xs text-slate-500">{t('reports.dailyHint')}</p>
      <ErrorText error={error ?? download.error} />
      {data && (
        <div className={`space-y-4 ${isFetching ? 'opacity-60' : ''}`}>
          <CallStatsRow data={data} />
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label={t('reports.outbound')} value={data.outbound_attempts} />
            <Stat
              label={t('reports.dialRate')}
              value={pct(data.dial_rate)}
              hint={t('reports.reachedHint', { n: data.reached })}
            />
            <Stat label={t('reports.newLeads')} value={data.new_leads} />
            <Stat label={t('reports.booked')} value={data.booked} />
            <Stat label={t('reports.repeat')} value={data.repeat_bookings} />
            <Stat label={t('reports.notBooked')} value={data.not_booked} />
            <Stat label={t('reports.noShows')} value={data.no_shows} />
            <Stat label={t('reports.cancellations')} value={data.cancellations} />
            <Stat label={t('reports.reschedules')} value={data.reschedules} />
          </div>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            {(
              [
                ['reports.outcomes', data.outcomes, 'outcomes'],
                ['reports.reasons', data.reasons, 'reasons'],
                ['reports.campaign', data.campaign_outcomes, 'outcomes'],
              ] as const
            ).map(([title, rows, ns]) => (
              <Card key={title} title={t(title)}>
                <ul className="space-y-1 text-sm">
                  {Object.keys(rows).length === 0 && (
                    <li className="text-slate-500">{t('reports.nothing')}</li>
                  )}
                  {Object.entries(rows)
                    .sort((a, b) => b[1] - a[1])
                    .map(([k, n]) => (
                      <li key={k} className="flex justify-between gap-2">
                        <span>{t(`${ns}.${k}`, { defaultValue: k })}</span>
                        <span className="tabular-nums">{n}</span>
                      </li>
                    ))}
                </ul>
              </Card>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

const GROUPS: { key: string; tiles: KpiKey[] }[] = [
  {
    key: 'calls',
    tiles: [
      'inbound_calls',
      'inbound_answer_rate',
      'inbound_missed',
      'missed_callback_avg_min',
      'missed_not_called_back',
      'avg_wait_sec',
      'outbound_calls',
      'dial_rate',
    ],
  },
  {
    key: 'leads',
    tiles: ['leads_total', 'leads_handled', 'lead_to_booking', 'first_response_median_min', 'sla_breached'],
  },
  {
    key: 'visits',
    tiles: [
      'bookings',
      'visits',
      'confirmation_rate',
      'booking_to_visit',
      'no_show_rate',
      'repeat_rate',
      'returned_patients',
    ],
  },
  { key: 'quality', tiles: ['qa_score'] },
]

const PRESETS = [7, 30, 90] as const

function KpiView({
  filters,
  setFilters,
}: {
  filters: ReportFilters
  setFilters: (f: ReportFilters) => void
}) {
  const { t } = useTranslation()
  const today = clinicDate()
  const [from, setFrom] = useState(addDays(today, -29))
  const [to, setTo] = useState(today)
  const { kpi, series } = useKpiData(from, to, filters)
  const download = useMutation({ mutationFn: () => downloadKpi(from, to, filters) })
  const data = kpi.data
  const loading = kpi.isFetching || series.isFetching
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 items-end gap-2 sm:flex sm:flex-wrap">
        <div className="col-span-2 flex flex-wrap items-end gap-2">
          <Field label={t('reports.from')}>
            <Input
              type="date"
              value={from}
              max={to}
              onChange={(e) => e.target.value && setFrom(e.target.value)}
              className="w-40"
            />
          </Field>
          <Field label={t('reports.to')}>
            <Input
              type="date"
              value={to}
              min={from}
              onChange={(e) => e.target.value && setTo(e.target.value)}
              className="w-40"
            />
          </Field>
          <div className="flex gap-1 pb-0.5">
            {PRESETS.map((n) => (
              <Button
                key={n}
                variant={from === addDays(today, 1 - n) && to === today ? 'primary' : 'secondary'}
                className="px-2 py-1.5 text-xs"
                onClick={() => {
                  setFrom(addDays(today, 1 - n))
                  setTo(today)
                }}
              >
                {t('reports.lastDays', { n })}
              </Button>
            ))}
          </div>
        </div>
        <FilterBar value={filters} onChange={setFilters} withOperator />
        <Button variant="secondary" disabled={download.isPending} onClick={() => download.mutate()}>
          {t('reports.download')}
        </Button>
      </div>
      <p className="text-xs text-slate-500">{t('reports.filtersScope')}</p>
      <ErrorText error={kpi.error ?? series.error ?? download.error} />
      {!data && !kpi.error && <p className="text-sm text-slate-500">{t('app.loading')}</p>}
      {data && (
        <div className={`space-y-6 transition-opacity ${loading ? 'opacity-60' : ''}`}>
          {data.previous && (
            <p className="text-xs text-slate-500">
              {t('reports.comparedWith', { from: data.previous.from, to: data.previous.to })}
            </p>
          )}
          {GROUPS.map((g) => (
            <section key={g.key} className="space-y-2">
              <h2 className="text-sm font-semibold text-slate-700">{t(`reports.groups.${g.key}`)}</h2>
              {g.key === 'calls' && data.inbound_calls === null ? (
                <p className="text-sm text-slate-500">{t('reports.telephonyNote')}</p>
              ) : (
                <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                  {g.tiles.map((k) => (
                    <KpiTile
                      key={k}
                      k={k}
                      data={data}
                      to={
                        k === 'inbound_missed' || k === 'missed_not_called_back'
                          ? '/calls?status=unanswered'
                          : undefined
                      }
                    />
                  ))}
                </div>
              )}
            </section>
          ))}
          {series.data && <DashboardCharts series={series.data} />}
          <Card
            title={t('reports.operators')}
            actions={
              <Link to="/qa" className="text-sm font-medium text-teal-800 hover:underline">
                {t('nav.qa')} →
              </Link>
            }
          >
            <OperatorBoard rows={data.operators} />
          </Card>
        </div>
      )}
    </div>
  )
}

export default function ReportsPage() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const canKpi = MANAGERS.includes(user?.role ?? '')
  const [tab, setTab] = useState<'daily' | 'kpi'>(canKpi ? 'kpi' : 'daily')
  const [filters, setFilters] = useState<ReportFilters>({})
  return (
    <div className="max-w-6xl space-y-4">
      <h1 className="text-2xl font-semibold">{t('reports.title')}</h1>
      <div className="flex gap-1 border-b border-slate-200">
        {(canKpi ? (['kpi', 'daily'] as const) : (['daily'] as const)).map((k) => (
          <button
            key={k}
            onClick={() => setTab(k)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${tab === k ? 'border-teal-700 font-medium text-teal-800' : 'border-transparent text-slate-600'}`}
          >
            {t(`reports.${k}`)}
          </button>
        ))}
      </div>
      {tab === 'kpi' ? (
        <KpiView filters={filters} setFilters={setFilters} />
      ) : (
        <Daily filters={filters} setFilters={setFilters} />
      )}
    </div>
  )
}
