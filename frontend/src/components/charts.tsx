/**
 * Chart building blocks for dashboards, reports and the QA panel (recharts, loaded only with
 * the pages that draw charts). Light theme only, like the rest of the app.
 *
 * Colour: categorical slots in fixed order (validated for colour-vision deficiency, adjacent
 * pairs), one colour per entity, never by rank. Slot 3 is under 3:1 contrast on white, so every
 * chart has a table view. Text always uses slate ink, never the series colour.
 */
import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { AXIS, GRID, SERIES, SURFACE, shortDay, type SeriesDef } from '../lib/reports'

type TooltipRow = { dataKey?: unknown; value?: unknown; color?: string; name?: unknown }

function ChartTooltip({
  active,
  payload,
  label,
  series,
  format,
  labelFormat,
}: {
  active?: boolean
  payload?: readonly TooltipRow[]
  label?: unknown
  series: SeriesDef[]
  format: (v: number | null) => string
  labelFormat: (l: string) => string
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs shadow-sm">
      <div className="mb-1 text-slate-500">{labelFormat(String(label))}</div>
      {series.map((s) => {
        const row = payload.find((p) => p.dataKey === s.key)
        const v = row?.value
        return (
          <div key={s.key} className="flex items-center gap-2">
            <span className="inline-block h-0.5 w-3 rounded" style={{ background: s.color }} />
            <span className="font-semibold text-slate-900 tabular-nums">
              {format(typeof v === 'number' ? v : null)}
            </span>
            <span className="text-slate-500">{s.label}</span>
          </div>
        )
      })}
    </div>
  )
}

export function Legend({ series, kind = 'line' }: { series: SeriesDef[]; kind?: 'line' | 'bar' }) {
  if (series.length < 2) return null
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">
      {series.map((s) => (
        <li key={s.key} className="flex items-center gap-1.5">
          <span
            className={
              kind === 'line' ? 'inline-block h-0.5 w-4 rounded' : 'inline-block h-2.5 w-2.5 rounded-sm'
            }
            style={{ background: s.color }}
          />
          {s.label}
        </li>
      ))}
    </ul>
  )
}

/** A chart card with a switch to the same numbers as a table (the accessible view). */
export function ChartCard({
  title,
  hint,
  legend,
  table,
  empty,
  children,
}: {
  title: string
  hint?: string
  legend?: ReactNode
  table: ReactNode
  /** shown instead of the chart when there is nothing to draw */
  empty?: string | false
  children: ReactNode
}) {
  const { t } = useTranslation()
  const [asTable, setAsTable] = useState(false)
  return (
    <section className="min-w-0 rounded-lg border border-slate-200 bg-white">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">{title}</h2>
          {hint && <p className="text-xs text-slate-500">{hint}</p>}
        </div>
        {!empty && (
          <button
            type="button"
            onClick={() => setAsTable(!asTable)}
            className="rounded px-2 py-1 text-xs text-teal-800 hover:bg-slate-100"
            aria-pressed={asTable}
          >
            {asTable ? t('charts.showChart') : t('charts.showTable')}
          </button>
        )}
      </header>
      <div className="space-y-2 p-4">
        {empty ? (
          <p className="py-8 text-center text-sm text-slate-500">{empty}</p>
        ) : asTable ? (
          <div className="max-h-72 overflow-auto">{table}</div>
        ) : (
          <>
            {legend}
            {children}
          </>
        )}
      </div>
    </section>
  )
}

/** Plain table of the rows a chart draws. */
export function DataTable<T extends Record<string, unknown>>({
  rows,
  columns,
}: {
  rows: T[]
  columns: { key: keyof T & string; label: string; format?: (v: T[keyof T], row: T) => ReactNode }[]
}) {
  return (
    <table className="w-full text-left text-xs">
      <thead className="sticky top-0 bg-white text-slate-500">
        <tr>
          {columns.map((c, i) => (
            <th key={c.key} className={`pb-1 ${i ? 'pl-3 text-right' : ''}`}>
              {c.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, n) => (
          <tr key={n} className="border-t border-slate-100">
            {columns.map((c, i) => (
              <td key={c.key} className={`py-1 tabular-nums ${i ? 'pl-3 text-right' : ''}`}>
                {c.format ? c.format(r[c.key], r) : ((r[c.key] as ReactNode) ?? '—')}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

const defaultFormat = (v: number | null) => (v === null ? '—' : v.toLocaleString('ru-RU'))

/** Lines over days/weeks: 2px lines, a crosshair tooltip listing every series at that x. */
type Row = Record<string, unknown>

export function TrendChart({
  data,
  xKey,
  series,
  height = 220,
  yDomain,
  format = defaultFormat,
  xFormat = shortDay,
}: {
  data: Row[]
  xKey: string
  series: SeriesDef[]
  height?: number
  yDomain?: [number, number]
  format?: (v: number | null) => string
  xFormat?: (x: string) => string
}) {
  const dots = data.length <= 1
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
          <CartesianGrid vertical={false} stroke={GRID} />
          <XAxis
            dataKey={xKey}
            tickFormatter={(v) => xFormat(String(v))}
            tick={{ fontSize: 11, fill: AXIS }}
            tickLine={false}
            axisLine={{ stroke: GRID }}
            minTickGap={16}
          />
          <YAxis
            tick={{ fontSize: 11, fill: AXIS }}
            tickLine={false}
            axisLine={false}
            allowDecimals={false}
            domain={yDomain ?? [0, 'auto']}
            width={44}
          />
          <Tooltip
            cursor={{ stroke: AXIS, strokeWidth: 1 }}
            content={(props) => (
              <ChartTooltip
                active={props.active}
                payload={props.payload as readonly TooltipRow[] | undefined}
                label={props.label}
                series={series}
                format={format}
                labelFormat={xFormat}
              />
            )}
          />
          {series.map((s) => (
            <Line
              key={s.key}
              dataKey={s.key}
              name={s.label}
              type="linear"
              stroke={s.color}
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
              dot={dots ? { r: 4, fill: s.color, stroke: SURFACE, strokeWidth: 2 } : false}
              activeDot={{ r: 4, fill: s.color, stroke: SURFACE, strokeWidth: 2 }}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

/** Horizontal bars of one series (e.g. inquiries per source), value at the tip. */
export function BarRows<T extends Row>({
  data,
  labelKey,
  valueKey,
  label,
  color = SERIES[0],
  labelFormat = (v) => v,
  extra,
}: {
  data: T[]
  labelKey: keyof T & string
  valueKey: keyof T & string
  label: string
  color?: string
  labelFormat?: (v: string) => string
  /** second line of the tooltip */
  extra?: (row: T) => string
}) {
  const height = Math.max(80, data.length * 30 + 16)
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 0, right: 36, bottom: 0, left: 0 }}
          barCategoryGap={6}
        >
          <XAxis type="number" hide allowDecimals={false} />
          <YAxis
            type="category"
            dataKey={labelKey as string}
            tickFormatter={(v) => labelFormat(String(v))}
            tick={{ fontSize: 12, fill: '#334155' }}
            tickLine={false}
            axisLine={{ stroke: GRID }}
            width={120}
          />
          <Tooltip
            cursor={{ fill: '#f1f5f9' }}
            content={(props) => {
              const row = props.payload?.[0]?.payload as T | undefined
              if (!props.active || !row) return null
              return (
                <div className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs shadow-sm">
                  <div className="text-slate-500">{labelFormat(String(row[labelKey]))}</div>
                  <div className="flex items-center gap-2">
                    <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: color }} />
                    <span className="font-semibold text-slate-900 tabular-nums">{String(row[valueKey])}</span>
                    <span className="text-slate-500">{label}</span>
                  </div>
                  {extra && <div className="text-slate-600">{extra(row)}</div>}
                </div>
              )
            }}
          />
          <Bar
            dataKey={valueKey as string}
            name={label}
            fill={color}
            barSize={16}
            radius={[0, 4, 4, 0]}
            isAnimationActive={false}
          >
            <LabelList
              dataKey={valueKey as string}
              position="right"
              style={{ fontSize: 11, fill: '#334155' }}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

/** Ordered stages that only narrow (the inquiry funnel): bar length = share of the first. */
export function Funnel({
  steps,
}: {
  steps: { key: string; label: string; count: number; share: number | null }[]
}) {
  const first = steps[0]?.count ?? 0
  return (
    <ol className="space-y-2">
      {steps.map((s, i) => {
        const prev = i ? steps[i - 1].count : null
        const step = prev ? Math.round((100 * s.count) / prev) : null
        return (
          <li
            key={s.key}
            className="grid grid-cols-[7rem_1fr] items-center gap-2 text-sm sm:grid-cols-[9rem_1fr]"
          >
            <span className="truncate text-slate-700" title={s.label}>
              {s.label}
            </span>
            <div className="flex min-w-0 items-center gap-2">
              <div className="h-4 min-w-0 flex-1 rounded-r bg-slate-100">
                <div
                  className="h-4 rounded-r"
                  style={{ width: `${first ? (100 * s.count) / first : 0}%`, background: SERIES[0] }}
                />
              </div>
              <span className="w-24 shrink-0 text-right text-xs text-slate-600 tabular-nums">
                <b className="text-slate-900">{s.count}</b>
                {step !== null && <span className="ml-1">({step}%)</span>}
              </span>
            </div>
          </li>
        )
      })}
    </ol>
  )
}
