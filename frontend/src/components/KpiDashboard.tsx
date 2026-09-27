/**
 * KPI tiles, trend charts, sources, funnel and the operator leaderboard (TZ 1.1 "Rahbar
 * KPI'larni real vaqtda ko'radi", 4.11). The home page of the owner and the supervisor, and the
 * building blocks of the reports page. Loaded lazily: it brings the chart library along.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { ScoreBadge } from './CallAnalysisDialog'
import { BarRows, ChartCard, DataTable, Funnel, Legend, TrendChart } from './charts'
import { ErrorText } from './ui'
import {
  DASHBOARD_TILES,
  PERCENT,
  PERIODS,
  SERIES,
  delta,
  periodRange,
  shortDay,
  useFormatKpi,
  useKpiData,
  type Kpi,
  type KpiKey,
  type OperatorRow,
  type PeriodKey,
  type Series,
} from '../lib/reports'

/** One KPI: value, change against the previous period, and the TZ formula on demand. */
export function KpiTile({ k, data, to, sub }: { k: KpiKey; data: Kpi; to?: string; sub?: string }) {
  const { t } = useTranslation()
  const fmt = useFormatKpi()
  const [open, setOpen] = useState(false)
  const value = data[k] as number | null
  const before = data.previous?.[k] as number | null | undefined
  const d = data.previous ? delta(k, value, before) : null
  const unit = PERCENT.includes(k) ? t('dash.pp') : ''
  return (
    <div className="flex min-w-0 flex-col rounded-lg border border-slate-200 bg-white px-4 py-3">
      <div className="flex items-start justify-between gap-2">
        <div className="text-xs text-slate-500">{t(`kpi.${k}`)}</div>
        <button
          type="button"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          aria-label={t('dash.howCounted')}
          title={t(`kpiDefs.${k}`)}
          className="-mt-0.5 -mr-1 shrink-0 rounded-full px-1.5 text-xs text-slate-400 hover:bg-slate-100 hover:text-slate-700"
        >
          ⓘ
        </button>
      </div>
      {to ? (
        <Link to={to} className="mt-1 text-2xl font-semibold text-slate-900 hover:text-teal-800">
          {fmt(k, value)}
        </Link>
      ) : (
        <div className="mt-1 text-2xl font-semibold text-slate-900">{fmt(k, value)}</div>
      )}
      {d && (
        <div
          className={`mt-0.5 text-xs ${d.tone === 'good' ? 'text-emerald-700' : d.tone === 'bad' ? 'text-red-700' : 'text-slate-500'}`}
          title={t('dash.previous', { value: fmt(k, before ?? null) })}
        >
          {d.diff > 0 ? '▲' : d.diff < 0 ? '▼' : '='} {d.diff > 0 ? '+' : ''}
          {d.diff.toLocaleString('ru-RU')}
          {unit} <span className="text-slate-500">{t('dash.vsPrevious')}</span>
        </div>
      )}
      {sub && <div className="text-xs text-slate-500">{sub}</div>}
      {open && (
        <p className="mt-2 border-t border-slate-100 pt-2 text-xs text-slate-600">{t(`kpiDefs.${k}`)}</p>
      )}
    </div>
  )
}

export function KpiTiles({ data, keys }: { data: Kpi; keys: KpiKey[] }) {
  const { t } = useTranslation()
  const fmt = useFormatKpi()
  const links: Partial<Record<KpiKey, string>> = {
    inbound_missed: '/calls?status=unanswered',
    qa_score: '/qa',
  }
  const subs: Partial<Record<KpiKey, string | undefined>> = {
    inbound_missed:
      data.missed_callback_avg_min !== null
        ? t('dash.callbackAvg', { n: fmt('missed_callback_avg_min', data.missed_callback_avg_min) })
        : data.inbound_calls === null
          ? t('dash.noTelephony')
          : undefined,
    qa_score: t('dash.qaCalls', { count: data.qa_analysed }),
    lead_to_booking: t('dash.leadsCount', { count: data.leads_total }),
    booking_to_visit: t('dash.visitsCount', { count: data.visits }),
  }
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {keys.map((k) => (
        <KpiTile key={k} k={k} data={data} to={links[k]} sub={subs[k]} />
      ))}
    </div>
  )
}

/** Trends, sources and the funnel of one period. */
export function DashboardCharts({ series, qa = true }: { series: Series; qa?: boolean }) {
  const { t } = useTranslation()
  const days = series.days
  const noLeads = days.every((d) => !d.leads && !d.bookings)
  const noCalls = days.every((d) => !d.calls_in && !d.calls_out)
  const noQa = days.every((d) => d.qa_score === null)
  const leadSeries = [
    { key: 'leads', label: t('dash.series.leads'), color: SERIES[0] },
    { key: 'bookings', label: t('dash.series.bookings'), color: SERIES[1] },
  ]
  const callSeries = [
    { key: 'calls_in', label: t('dash.series.callsIn'), color: SERIES[0] },
    { key: 'calls_out', label: t('dash.series.callsOut'), color: SERIES[1] },
    { key: 'calls_missed', label: t('dash.series.callsMissed'), color: SERIES[2] },
  ]
  const qaSeries = [{ key: 'qa_score', label: t('kpi.qa_score'), color: SERIES[0] }]
  const dayCol = { key: 'date' as const, label: t('dash.day'), format: (v: unknown) => shortDay(String(v)) }
  const sourceLabel = (s: string) => t(`sources.${s}`, { defaultValue: t('dash.unknownSource') })
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <ChartCard
        title={t('dash.charts.leads')}
        empty={noLeads && t('dash.empty.leads')}
        legend={<Legend series={leadSeries} />}
        table={
          <DataTable
            rows={days}
            columns={[
              dayCol,
              { key: 'leads', label: t('dash.series.leads') },
              { key: 'bookings', label: t('dash.series.bookings') },
              { key: 'visits', label: t('dash.series.visits') },
            ]}
          />
        }
      >
        <TrendChart data={days} xKey="date" series={leadSeries} />
      </ChartCard>
      <ChartCard
        title={t('dash.charts.calls')}
        empty={noCalls && t('dash.empty.calls')}
        legend={<Legend series={callSeries} />}
        table={
          <DataTable
            rows={days}
            columns={[
              dayCol,
              { key: 'calls_in', label: t('dash.series.callsIn') },
              { key: 'calls_out', label: t('dash.series.callsOut') },
              { key: 'calls_missed', label: t('dash.series.callsMissed') },
            ]}
          />
        }
      >
        <TrendChart data={days} xKey="date" series={callSeries} />
      </ChartCard>
      {qa && (
        <ChartCard
          title={t('dash.charts.qa')}
          hint={t('dash.charts.qaHint')}
          empty={noQa && t('dash.empty.qa')}
          table={
            <DataTable
              rows={days}
              columns={[
                dayCol,
                { key: 'qa_score', label: t('kpi.qa_score') },
                { key: 'qa_calls', label: t('dash.series.qaCalls') },
              ]}
            />
          }
        >
          <TrendChart data={days} xKey="date" series={qaSeries} yDomain={[0, 100]} />
        </ChartCard>
      )}
      <ChartCard
        title={t('dash.charts.sources')}
        empty={series.sources.length === 0 && t('dash.empty.leads')}
        table={
          <DataTable
            rows={series.sources}
            columns={[
              { key: 'source', label: t('dash.source'), format: (v) => sourceLabel(String(v)) },
              { key: 'leads', label: t('dash.series.leads') },
              { key: 'booked', label: t('dash.series.bookedLeads') },
              {
                key: 'conversion',
                label: t('kpi.lead_to_booking'),
                format: (v) => (v === null ? '—' : `${v}%`),
              },
            ]}
          />
        }
      >
        <BarRows
          data={series.sources}
          labelKey="source"
          valueKey="leads"
          label={t('dash.series.leads')}
          labelFormat={sourceLabel}
          extra={(r) => t('dash.sourceBooked', { booked: r.booked, pct: r.conversion ?? 0 })}
        />
      </ChartCard>
      <ChartCard
        title={t('dash.charts.funnel')}
        hint={t('dash.charts.funnelHint')}
        empty={(series.funnel[0]?.count ?? 0) === 0 && t('dash.empty.leads')}
        table={
          <DataTable
            rows={series.funnel}
            columns={[
              { key: 'stage', label: t('dash.stage'), format: (v) => t(`dash.funnel.${String(v)}`) },
              { key: 'count', label: t('dash.count') },
              { key: 'share', label: t('dash.share'), format: (v) => (v === null ? '—' : `${v}%`) },
            ]}
          />
        }
      >
        <Funnel
          steps={series.funnel.map((f) => ({
            key: f.stage,
            label: t(`dash.funnel.${f.stage}`),
            count: f.count,
            share: f.share,
          }))}
        />
      </ChartCard>
    </div>
  )
}

/** Per operator: calls, dial rate, bookings, talk time and QA score, best first. */
export function OperatorBoard({ rows }: { rows: OperatorRow[] }) {
  const { t } = useTranslation()
  if (rows.length === 0) return <p className="text-sm text-slate-500">{t('dash.noOperators')}</p>
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-left text-sm">
        <thead className="text-xs text-slate-500 uppercase">
          <tr>
            <th className="pb-2">#</th>
            <th className="pb-2">{t('reports.operator')}</th>
            <th className="pb-2 pl-3 text-right">{t('reports.attempts')}</th>
            <th className="pb-2 pl-3 text-right">{t('reports.dialRate')}</th>
            <th className="pb-2 pl-3 text-right">{t('reports.bookedByPhone')}</th>
            <th className="pb-2 pl-3 text-right">{t('reports.created')}</th>
            <th className="pb-2 pl-3 text-right">{t('reports.talkMin')}</th>
            <th className="pb-2 pl-3 text-right">{t('kpi.qa_score')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((o, i) => (
            <tr key={o.user_id} className="border-t border-slate-100">
              <td className="py-2 text-slate-500 tabular-nums">{i + 1}</td>
              <td className="py-2 font-medium">{o.name}</td>
              <td className="py-2 text-right tabular-nums">{o.attempts}</td>
              <td className="py-2 text-right tabular-nums">
                {o.dial_rate === null ? '—' : `${o.dial_rate}%`}
              </td>
              <td className="py-2 text-right tabular-nums">{o.booked_by_phone}</td>
              <td className="py-2 text-right tabular-nums">{o.appointments_created}</td>
              <td className="py-2 text-right tabular-nums">{o.talk_minutes}</td>
              <td className="py-2 text-right">
                <ScoreBadge score={o.qa_score} />
                {o.qa_calls > 0 && <span className="ml-1 text-xs text-slate-400">×{o.qa_calls}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function PeriodPicker({ value, onChange }: { value: PeriodKey; onChange: (p: PeriodKey) => void }) {
  const { t } = useTranslation()
  return (
    <div
      role="radiogroup"
      aria-label={t('dash.period')}
      className="inline-flex rounded-md border border-slate-300 bg-white p-0.5"
    >
      {PERIODS.map((p) => (
        <button
          key={p}
          type="button"
          role="radio"
          aria-checked={value === p}
          onClick={() => onChange(p)}
          className={`rounded px-3 py-1.5 text-sm ${value === p ? 'bg-teal-700 font-medium text-white' : 'text-slate-700 hover:bg-slate-100'}`}
        >
          {t(`dash.periods.${p}`)}
        </button>
      ))}
    </div>
  )
}

/** Owner / supervisor home: the clinic's KPIs for today, 7 or 30 days. */
export default function KpiDashboard() {
  const { t } = useTranslation()
  const [period, setPeriod] = useState<PeriodKey>('7d')
  const { from, to } = periodRange(period)
  const { kpi, series } = useKpiData(from, to)
  const loading = kpi.isFetching || series.isFetching
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">{t('dash.title')}</h2>
        <div className="flex flex-wrap items-center gap-2">
          <PeriodPicker value={period} onChange={setPeriod} />
          <Link to="/reports" className="text-sm font-medium text-teal-800 hover:underline">
            {t('dash.allReports')} →
          </Link>
        </div>
      </div>
      <ErrorText error={kpi.error ?? series.error} />
      {!kpi.data && !kpi.error && <p className="text-sm text-slate-500">{t('app.loading')}</p>}
      <div className={`space-y-4 transition-opacity ${loading && kpi.data ? 'opacity-60' : ''}`}>
        {kpi.data && <KpiTiles data={kpi.data} keys={DASHBOARD_TILES} />}
        {series.data && <DashboardCharts series={series.data} />}
        {kpi.data && (
          <section className="rounded-lg border border-slate-200 bg-white">
            <header className="border-b border-slate-200 px-4 py-3">
              <h2 className="text-sm font-semibold">{t('dash.leaderboard')}</h2>
            </header>
            <div className="p-4">
              <OperatorBoard rows={kpi.data.operators} />
            </div>
          </section>
        )}
      </div>
    </div>
  )
}
