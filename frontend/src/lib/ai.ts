import { api } from './api'

export interface AiStatus {
  enabled: boolean
  stt_model: string
  llm_model: string
  spent_today_usd: number
  daily_budget_usd: number
}

export interface TranscriptSegment {
  ch: 'operator' | 'patient'
  start: number
  end: number
  text: string
}

export interface CriterionResult {
  code: string
  passed: boolean | null
  comment: string
}

export interface Quote {
  quote: string
  at: number | null
}

export type RedFlagCode = 'diagnosis' | 'pressure' | 'false_promise' | 'complaint'

export interface CallAnalysis {
  id: string
  call_id: string
  status: 'pending' | 'transcribing' | 'analyzing' | 'ready' | 'failed' | 'skipped'
  error: string | null
  stt_model: string | null
  llm_model: string | null
  prompt_version: string | null
  transcript: TranscriptSegment[] | null
  language: string | null
  conversation_type: string | null
  score: number | null
  criteria: CriterionResult[] | null
  violations: (Quote & { criterion: string })[] | null
  red_flags: (Quote & { code: RedFlagCode })[] | null
  summary: string | null
  suggested_outcome: string | null
  suggested_reason: string | null
  extracted: {
    interest: string | null
    preferred_time: string | null
    source: string | null
    next_step: string | null
  } | null
  questions: string[] | null
  objections: string[] | null
  review: 'confirmed' | 'corrected' | null
  corrections: Record<string, { ai: string | null; operator: string | null }> | null
  flags_reviewed_at: string | null
}

export interface QaOverview {
  analysed: number
  avg_score: number | null
  red_flags_open: number
  operators: {
    user_id: string | null
    name: string
    calls: number
    avg_score: number | null
    red_flags: number
  }[]
  criteria: { code: string; name_uz: string; name_ru: string; applicable: number; pass_rate: number | null }[]
  reviews: Record<string, number>
}

export interface QaCall {
  analysis_id: string
  call_id: string
  started_at: string
  direction: 'in' | 'out'
  talk_seconds: number | null
  user_id: string | null
  user_name: string | null
  patient_id: string | null
  patient_name: string | null
  score: number | null
  conversation_type: string | null
  red_flags: RedFlagCode[]
  flags_reviewed: boolean
  summary: string | null
  review: string | null
}

export interface QaCriterion {
  id: string
  code: string
  name_uz: string
  name_ru: string
  description: string
  weight: number
  active: boolean
  sort_order: number
}

export interface Digest {
  id: string
  period_from: string
  period_to: string
  model: string | null
  stats: {
    calls_analysed: number
    avg_score: number | null
    red_flags: Record<string, number>
    refusal_reasons: Record<string, number>
  }
  content: {
    summary: string
    top_questions: { text: string; count: number }[]
    objections: { text: string; count: number }[]
    complaints: string[]
    recommendations: string[]
  } | null
  created_at: string
}

export const getAiStatus = () => api<AiStatus>('/ai/status')
export const getCallAnalysis = (callId: string) => api<CallAnalysis>(`/ai/calls/${callId}`)
export const markFlagsReviewed = (callId: string) =>
  api<void>(`/ai/calls/${callId}/flags-reviewed`, { method: 'POST' })

const period = (from: string, to: string) => `from=${from}&to=${to}`
export const getQaOverview = (from: string, to: string, userId?: string) =>
  api<QaOverview>(`/ai/qa/overview?${period(from, to)}${userId ? `&user_id=${userId}` : ''}`)
export const getQaCalls = (
  from: string,
  to: string,
  options: { userId?: string; flagged?: boolean; order?: 'recent' | 'worst' | 'best' } = {},
) => {
  const q = new URLSearchParams({ from, to, order: options.order ?? 'recent' })
  if (options.userId) q.set('user_id', options.userId)
  if (options.flagged) q.set('flagged', 'true')
  return api<QaCall[]>(`/ai/qa/calls?${q}`)
}

export const getCriteria = () => api<QaCriterion[]>('/ai/criteria')
export const updateCriterion = (
  id: string,
  body: Pick<QaCriterion, 'name_uz' | 'name_ru' | 'description' | 'weight' | 'active'>,
) => api<QaCriterion>(`/ai/criteria/${id}`, { method: 'PUT', body })

export const getDigest = () => api<Digest | null>('/ai/digest')
export const makeDigest = () => api<Digest>('/ai/digest', { method: 'POST' })

export const createCriterion = (
  body: Pick<QaCriterion, 'name_uz' | 'name_ru' | 'description' | 'weight' | 'active'>,
) => api<QaCriterion>('/ai/criteria', { method: 'POST', body })

export type DigestItem = {
  id: string
  period_from: string
  period_to: string
  created_at: string
  calls_analysed: number
  avg_score: number | null
  has_content: boolean
}
export const getDigests = () => api<DigestItem[]>('/ai/digests')
export const getDigestById = (id: string) => api<Digest>(`/ai/digests/${id}`)

export type TrendPoint = { start: string; calls: number; avg_score: number | null }
export type QaTrend = {
  bucket: 'day' | 'week'
  points: TrendPoint[]
  operators: { user_id: string | null; name: string; calls: number; points: TrendPoint[] }[]
  criteria: {
    code: string
    name_uz: string
    name_ru: string
    active: boolean
    points: { start: string; applicable: number; pass_rate: number | null }[]
  }[]
}
export const getQaTrend = (from: string, to: string, bucket: 'day' | 'week', userId?: string) => {
  const q = new URLSearchParams({ from, to, bucket })
  if (userId) q.set('user_id', userId)
  return api<QaTrend>(`/ai/qa/trend?${q}`)
}

export type ViolationItem = {
  analysis_id: string
  call_id: string
  started_at: string
  user_id: string | null
  user_name: string | null
  patient_id: string | null
  patient_name: string | null
  kind: 'violation' | 'red_flag'
  code: string
  quote: string
  at: number | null
  reviewed: boolean
}
export type ViolationPage = { total: number; items: ViolationItem[]; counts: Record<string, number> }
export const getViolations = (
  from: string,
  to: string,
  options: { userId?: string; code?: string; kind?: 'all' | 'violation' | 'red_flag'; offset?: number },
) => {
  const q = new URLSearchParams({ from, to, kind: options.kind ?? 'all', limit: '50' })
  if (options.userId) q.set('user_id', options.userId)
  if (options.code) q.set('code', options.code)
  if (options.offset) q.set('offset', String(options.offset))
  return api<ViolationPage>(`/ai/qa/violations?${q}`)
}

export type QueueItem = {
  call_id: string
  started_at: string
  direction: 'in' | 'out'
  talk_seconds: number | null
  user_name: string | null
  patient_id: string | null
  patient_name: string | null
  status: 'missing' | 'pending' | 'transcribing' | 'analyzing' | 'failed'
  attempts: number
  error: string | null
  updated_at: string | null
}
export type QaQueue = { total: number; counts: Record<string, number>; items: QueueItem[] }
export const getQaQueue = (from: string, to: string) => api<QaQueue>(`/ai/qa/queue?${period(from, to)}`)
export const retryAnalyses = (callIds: string[]) =>
  api<{ queued: number; skipped: number }>('/ai/qa/retry', { method: 'POST', body: { call_ids: callIds } })

export const getBrief = (patientId: string, lang: 'uz' | 'ru') =>
  api<{ text: string; ai: boolean }>(`/ai/patients/${patientId}/brief?lang=${lang}`)

/** 83.4 -> '1:23' */
export function formatAt(seconds: number | null): string {
  if (seconds === null) return ''
  const s = Math.max(0, Math.floor(seconds))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

/** Why an analysis was skipped or failed: the worker stores a code or a raw exception message. */
export function errorKey(error: string): string {
  if (error === 'too_short' || error === 'no_speech') return error
  if (/budget/i.test(error)) return 'budget'
  if (/OPENAI_API_KEY/.test(error)) return 'disabled'
  return 'generic'
}
