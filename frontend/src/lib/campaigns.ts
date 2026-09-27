// Campaigns (TZ 4.9): segments, suggested segments, results, members and the AI summary (4.8.3).
import { api } from './api'
import type { PatientKind } from './patients'

export type CampaignStatus = 'draft' | 'active' | 'paused' | 'finished'
export type Gender = 'male' | 'female'

export type Segment = {
  kinds?: PatientKind[]
  categories?: string[]
  districts?: string[]
  sources?: string[]
  tags?: string[]
  gender?: Gender
  last_visit_before_days?: number
  age_min?: number
  age_max?: number
}

export type AbVariant = {
  variant: 'a' | 'b'
  script_code: string | null
  tasks: number
  done: number
  reached: number
  booked: number
  booking_rate: number | null
}

export type Progress = {
  audience: number
  tasked: number
  remaining: number
  percent: number
  days_left: number | null
}

export type Results = {
  tasks: number
  open: number
  closed: number
  calls: number
  called: number
  reached: number
  dial_rate: number | null
  booked: number
  booking_rate: number | null
  arrived: number
  arrival_rate: number | null
  outcomes: Record<string, number>
  refusal_reasons: Record<string, number>
  today: { tasks: number; calls: number }
}

export type Campaign = {
  id: string
  name: string
  description: string | null
  segment: Segment
  script_code: string | null
  script_code_b: string | null
  daily_limit: number
  status: CampaignStatus
  ends_on: string | null
  created_at: string
  audience: number
  stats: Record<string, number>
  ab: AbVariant[] | null
  progress: Progress
  results: Results
}

export type AiSummary = {
  summary: string
  what_worked: string[]
  problems: string[]
  refusal_insights: string[]
  ab_verdict: string | null
  recommendations: string[]
}

export type CampaignDetail = Campaign & {
  ai_summary: AiSummary | null
  ai_summary_at: string | null
  ai_summary_stale: boolean
}

export type CampaignInput = {
  name: string
  description: string | null
  segment: Segment
  script_code: string | null
  script_code_b: string | null
  daily_limit: number
  ends_on: string | null
}

export type Bucket = { key: string | null; count: number }
export type Audience = {
  audience: number
  by_kind: Bucket[]
  by_district: Bucket[]
  by_source: Bucket[]
  by_category: Bucket[]
  by_recency: Bucket[]
}

export type Suggestion = {
  code: string
  priority: number
  script_code: string
  segment: Segment
  categories?: string[]
  specialty?: string | null
  audience: number
  days: number
  campaign: string | null
}

export type Member = {
  task_id: string
  patient_id: string | null
  patient_name: string | null
  phone: string | null
  status: 'open' | 'done' | 'cancelled'
  outcome: string | null
  reason: string | null
  attempts: number
  variant: 'a' | 'b'
  created_at: string
  last_attempt_at: string | null
  completed_at: string | null
  booked: boolean
  arrived: boolean
}

export const getCampaignList = (status?: CampaignStatus) =>
  api<Campaign[]>(`/campaigns${status ? `?status=${status}` : ''}`)
export const getCampaign = (id: string) => api<CampaignDetail>(`/campaigns/${id}`)
export const createCampaign = (body: CampaignInput) => api<Campaign>('/campaigns', { method: 'POST', body })
export const updateCampaign = (id: string, body: CampaignInput) =>
  api<Campaign>(`/campaigns/${id}`, { method: 'PUT', body })
export const setCampaignStatus = (id: string, status: CampaignStatus) =>
  api<Campaign>(`/campaigns/${id}/status`, { method: 'POST', body: { status } })
export const getAudience = (segment: Segment) =>
  api<Audience>('/campaigns/audience', { method: 'POST', body: segment })
export const getSuggestions = () => api<Suggestion[]>('/campaigns/suggestions')
export const getCampaignTags = () => api<{ tag: string; count: number }[]>('/campaigns/tags')
export const makeAiSummary = (id: string) =>
  api<{ content: AiSummary; model: string | null; cached: boolean; created_at: string | null }>(
    `/campaigns/${id}/ai-summary`,
    { method: 'POST' },
  )

export function getMembers(
  id: string,
  p: { status?: string; outcome?: string; variant?: string; offset: number; limit: number },
) {
  const qs = new URLSearchParams({ offset: String(p.offset), limit: String(p.limit) })
  if (p.status) qs.set('status', p.status)
  if (p.outcome) qs.set('outcome', p.outcome)
  if (p.variant) qs.set('variant', p.variant)
  return api<{ total: number; items: Member[] }>(`/campaigns/${id}/members?${qs}`)
}

/** Campaign fields as the create/edit form starts them (optionally from a suggestion). */
export function toInput(c?: Partial<Campaign>): CampaignInput {
  return {
    name: c?.name ?? '',
    description: c?.description ?? null,
    segment: c?.segment ?? { kinds: ['legacy'] },
    script_code: c?.script_code ?? 'reactivation',
    script_code_b: c?.script_code_b ?? null,
    daily_limit: c?.daily_limit ?? 30,
    ends_on: c?.ends_on ?? null,
  }
}

export const STATUS_TONE: Record<CampaignStatus, 'good' | 'info' | 'neutral'> = {
  active: 'good',
  paused: 'info',
  draft: 'neutral',
  finished: 'neutral',
}
