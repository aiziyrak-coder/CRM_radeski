import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, apiBlob } from './api'
import type { Source } from './patients'
import { addDays, clinicDate } from './scheduling'

/** TZ 4.11 filters (branch, operator, source, service direction). */
export type ReportFilters = {
  branch_id?: string
  user_id?: string
  source?: Source | ''
  category_id?: string
}

/** Telephony figures (all null until the PBX has reported a call). */
export type CallStats = {
  inbound_calls: number | null
  inbound_answered: number | null
  inbound_missed: number | null
  inbound_answer_rate: number | null
  callbacks_requested: number | null
  avg_wait_sec: number | null
  outbound_calls: number | null
  outbound_answered: number | null
  talk_minutes: number | null
}

export type DailyReport = CallStats & {
  date: string
  outbound_attempts: number
  reached: number
  dial_rate: number | null
  new_leads: number
  booked: number
  repeat_bookings: number
  not_booked: number
  reasons: Record<string, number>
  cancellations: number
  reschedules: number
  no_shows: number
  outcomes: Record<string, number>
  campaign_outcomes: Record<string, number>
}

export type KpiFigures = CallStats & {
  missed_total: number
  missed_called_back: number
  missed_not_called_back: number
  missed_callback_avg_min: number | null
  missed_callback_median_min: number | null
  leads_total: number
  leads_handled: number
  lead_to_booking: number | null
  first_response_median_min: number | null
  sla_breached: number
  attempts: number
  dial_rate: number | null
  confirmation_rate: number | null
  bookings: number
  visits: number
  booking_to_visit: number | null
  no_show_rate: number | null
  repeat_rate: number | null
  returned_patients: number
  qa_analysed: number
  qa_score: number | null
}

export type OperatorRow = {
  user_id: string
  name: string
  attempts: number
  reached: number
  booked_by_phone: number
  dial_rate: number | null
  appointments_created: number
  talk_minutes: number
  qa_calls: number
  qa_score: number | null
}

export type Kpi = KpiFigures & {
  from: string
  to: string
  operators: OperatorRow[]
  /** the equally long period right before (with `compare`) */
  previous?: Partial<KpiFigures> & { from: string; to: string }
}

export type SeriesDay = {
  date: string
  leads: number
  bookings: number
  visits: number
  no_shows: number
  calls_in: number
  calls_out: number
  calls_missed: number
  qa_calls: number
  qa_score: number | null
}

export type FunnelStage = 'new' | 'contacted' | 'booked' | 'confirmed' | 'visited'

export type Series = {
  from: string
  to: string
  days: SeriesDay[]
  sources: { source: Source | 'unknown'; leads: number; booked: number; conversion: number | null }[]
  funnel: { stage: FunnelStage; count: number; share: number | null }[]
}

function query(params: Record<string, string | boolean | undefined>) {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== '') q.set(k, String(v))
  return q.toString()
}

export const getKpi = (from: string, to: string, f: ReportFilters = {}, compare = false) =>
  api<Kpi>(`/reports/kpi?${query({ from, to, ...f, compare: compare || undefined })}`)

export const getSeries = (from: string, to: string, f: ReportFilters = {}) =>
  api<Series>(`/reports/series?${query({ from, to, ...f })}`)

export const getDaily = (date: string, f: ReportFilters = {}) =>
  api<DailyReport>(`/reports/daily?${query({ date, ...f })}`)

/** people the reports can be filtered by (managers only) */
export const getReportOperators = () => api<{ id: string; full_name: string }[]>('/reports/operators')

export type ServiceCategory = { id: string; name_uz: string; name_ru: string }
export const getServiceCategories = () => api<ServiceCategory[]>('/catalog/service-categories')

async function save(path: string, filename: string) {
  const url = URL.createObjectURL(await apiBlob(path))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

/** Excel exports need the bearer token, so they are fetched and saved as a blob. */
export const downloadKpi = (from: string, to: string, f: ReportFilters = {}) =>
  save(`/reports/kpi.xlsx?${query({ from, to, ...f })}`, `kpi_${from}_${to}.xlsx`)
export const downloadDaily = (date: string, f: ReportFilters = {}) =>
  save(`/reports/daily.xlsx?${query({ date, ...f })}`, `daily_${date}.xlsx`)

export type PeriodKey = 'today' | '7d' | '30d'
export const PERIODS: PeriodKey[] = ['today', '7d', '30d']
/** the dashboard's period presets as clinic-calendar dates */
export function periodRange(key: PeriodKey, today = clinicDate()): { from: string; to: string } {
  const days = key === 'today' ? 1 : key === '7d' ? 7 : 30
  return { from: addDays(today, 1 - days), to: today }
}

/** Which way is better for each KPI: up (more is good) or down (less is good). */
export const BETTER: Partial<Record<keyof KpiFigures, 'up' | 'down'>> = {
  dial_rate: 'up',
  lead_to_booking: 'up',
  booking_to_visit: 'up',
  no_show_rate: 'down',
  repeat_rate: 'up',
  first_response_median_min: 'down',
  inbound_missed: 'down',
  missed_not_called_back: 'down',
  missed_callback_avg_min: 'down',
  qa_score: 'up',
  confirmation_rate: 'up',
  leads_total: 'up',
  leads_handled: 'up',
  bookings: 'up',
  visits: 'up',
  sla_breached: 'down',
  returned_patients: 'up',
}

export type Delta = { diff: number; tone: 'good' | 'bad' | 'flat' }
/** change against the previous period; null when either side is unknown */
export function delta(
  key: keyof KpiFigures,
  now: number | null,
  before: number | null | undefined,
): Delta | null {
  if (now === null || before === null || before === undefined) return null
  const diff = Math.round((now - before) * 10) / 10
  const better = BETTER[key]
  if (diff === 0 || !better) return { diff, tone: 'flat' }
  return { diff, tone: diff > 0 === (better === 'up') ? 'good' : 'bad' }
}

// --- chart palette -----------------------------------------------------------------------------

export const SERIES = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948']
export const GRID = '#e2e8f0' // slate-200 hairline
export const AXIS = '#64748b' // slate-500 labels
export const SURFACE = '#ffffff'

export type SeriesDef = { key: string; label: string; color: string }

/** '2026-09-27' -> '27.09' */
export const shortDay = (iso: string) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}`

// --- KPI formatting and data ------------------------------------------------------------------

export type KpiKey = keyof KpiFigures

export const PERCENT: KpiKey[] = [
  'dial_rate',
  'lead_to_booking',
  'booking_to_visit',
  'no_show_rate',
  'repeat_rate',
  'confirmation_rate',
  'inbound_answer_rate',
]
const MINUTES: KpiKey[] = [
  'first_response_median_min',
  'missed_callback_avg_min',
  'missed_callback_median_min',
]

/** the eight tiles of the dashboard (TZ 1.1 + 4.11) */
export const DASHBOARD_TILES: KpiKey[] = [
  'dial_rate',
  'lead_to_booking',
  'booking_to_visit',
  'no_show_rate',
  'repeat_rate',
  'first_response_median_min',
  'inbound_missed',
  'qa_score',
]

export function useFormatKpi() {
  const { t } = useTranslation()
  return (key: KpiKey, v: number | null | undefined): string => {
    if (v === null || v === undefined) return '—'
    if (PERCENT.includes(key)) return `${v}%`
    if (MINUTES.includes(key)) {
      if (v < 60) return t('reports.minutes', { n: v })
      const h = Math.floor(v / 60)
      return t('dash.hoursMinutes', { h, m: Math.round(v - h * 60) })
    }
    if (key === 'avg_wait_sec') return t('reports.seconds', { n: v })
    return v.toLocaleString('ru-RU')
  }
}

export function useKpiData(from: string, to: string, filters: ReportFilters = {}) {
  const kpi = useQuery({
    queryKey: ['reports', 'kpi', from, to, filters, 'compare'],
    queryFn: () => getKpi(from, to, filters, true),
    placeholderData: keepPreviousData,
    refetchInterval: 120_000,
  })
  const series = useQuery({
    queryKey: ['reports', 'series', from, to, filters],
    queryFn: () => getSeries(from, to, filters),
    placeholderData: keepPreviousData,
    refetchInterval: 120_000,
  })
  return { kpi, series }
}
