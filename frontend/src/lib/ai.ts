import { api } from './api'

export interface AiStatus {
  enabled: boolean
  stt_model: string
  llm_model: string
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

export const getBrief = (patientId: string, lang: 'uz' | 'ru') =>
  api<{ text: string; ai: boolean }>(`/ai/patients/${patientId}/brief?lang=${lang}`)

/** 83.4 -> '1:23' */
export function formatAt(seconds: number | null): string {
  if (seconds === null) return ''
  const s = Math.max(0, Math.floor(seconds))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}
