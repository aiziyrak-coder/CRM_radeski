// Call-center operations: task queue, leads, scripts, campaigns, reports (phase 2).
import { api, getAccessToken, type Language } from './api'
import type { PatientKind, Source } from './patients'

export type TaskType =
  | 'confirm_visit'
  | 'missed_call'
  | 'new_lead'
  | 'lost_lead'
  | 'no_show'
  | 'repeat_visit'
  | 'post_procedure'
  | 'course_continue'
  | 'reactivation'
  | 'campaign'
  | 'callback'

export type Outcome =
  | 'booked'
  | 'confirmed'
  | 'rescheduled'
  | 'cancelled'
  | 'refused'
  | 'thinking'
  | 'callback'
  | 'no_answer'
  | 'wrong_number'
  | 'do_not_call'
  | 'done'

export const REASONS = [
  'price',
  'time',
  'other_clinic',
  'better',
  'far',
  'no_need',
  'doctor',
  'illness',
  'forgot',
  'no_money',
  'other',
] as const

/** outcomes offered per task type, most likely first (booking itself happens via the booking dialog) */
export const OUTCOMES_FOR: Record<TaskType, Outcome[]> = {
  confirm_visit: ['confirmed', 'cancelled', 'no_answer', 'callback', 'wrong_number'],
  missed_call: ['done', 'thinking', 'refused', 'callback', 'no_answer', 'wrong_number'],
  new_lead: ['thinking', 'refused', 'callback', 'no_answer', 'wrong_number', 'done'],
  lost_lead: ['thinking', 'refused', 'callback', 'no_answer', 'do_not_call'],
  no_show: ['thinking', 'refused', 'callback', 'no_answer'],
  repeat_visit: ['thinking', 'refused', 'callback', 'no_answer', 'done'],
  post_procedure: ['done', 'callback', 'no_answer'],
  course_continue: ['thinking', 'refused', 'callback', 'no_answer'],
  reactivation: ['thinking', 'refused', 'callback', 'no_answer', 'do_not_call', 'wrong_number'],
  campaign: ['thinking', 'refused', 'callback', 'no_answer', 'do_not_call', 'wrong_number'],
  callback: ['done', 'thinking', 'refused', 'callback', 'no_answer'],
}
export const NEEDS_REASON: Outcome[] = ['refused', 'cancelled']

export type Task = {
  id: string
  type: TaskType
  status: 'open' | 'done' | 'cancelled'
  priority: number
  due_at: string
  overdue: boolean
  attempts: number
  last_attempt_at: string | null
  outcome: Outcome | null
  outcome_reason: string | null
  note: string | null
  script_code: string | null
  patient_id: string | null
  patient_name: string | null
  patient_phone: string | null
  patient_language: Language | null
  do_not_call: boolean
  lead_id: string | null
  lead_channel: string | null
  appointment_id: string | null
  appointment_at: string | null
  campaign_id: string | null
  created_at: string
}

export type TaskSummary = {
  by_type: Record<string, number>
  total_due: number
  overdue: number
  lead_sla_breached: number
}

export const getTasks = (view: 'today' | 'all', types: TaskType[] = []) => {
  const qs = new URLSearchParams({ view })
  types.forEach((t) => qs.append('types', t))
  return api<Task[]>(`/tasks?${qs}`)
}
export const getTaskSummary = () => api<TaskSummary>('/tasks/summary')
export const getPatientTasks = (patientId: string) => api<Task[]>(`/tasks/patient/${patientId}`)
export const recordResult = (
  id: string,
  body: { outcome: Outcome; reason?: string | null; note?: string | null; callback_at?: string | null },
) => api<Task>(`/tasks/${id}/result`, { method: 'POST', body })
export const createCallback = (patient_id: string, due_at: string, note?: string) =>
  api<{ created: boolean }>('/tasks', { method: 'POST', body: { patient_id, due_at, note } })

export type ShiftNote = { id: string; user_name: string | null; text: string; created_at: string }
export const getShiftNotes = () => api<ShiftNote[]>('/tasks/shift-notes')
export const addShiftNote = (text: string) =>
  api<ShiftNote>('/tasks/shift-notes', { method: 'POST', body: { text } })

// --- leads ---

export type LeadChannel = 'call' | 'missed_call' | 'website' | 'telegram' | 'instagram' | 'walk_in' | 'manual'
export type LeadStage = 'new' | 'contacted' | 'booked' | 'visited' | 'later' | 'lost'
export const LEAD_STAGES: LeadStage[] = ['new', 'contacted', 'later', 'booked', 'visited', 'lost']
export const LEAD_CHANNELS: LeadChannel[] = [
  'call',
  'missed_call',
  'website',
  'telegram',
  'instagram',
  'walk_in',
  'manual',
]

export type Lead = {
  id: string
  patient_id: string | null
  phone: string | null
  name: string | null
  channel: LeadChannel
  source: Source | null
  interest: string | null
  stage: LeadStage
  lost_reason: string | null
  note: string | null
  sla_due_at: string
  sla_breached: boolean
  first_response_at: string | null
  appointment_id: string | null
  created_at: string
}

export function getLeads(p: {
  stage?: string
  channel?: string
  q?: string
  patientId?: string
  offset?: number
}) {
  const qs = new URLSearchParams({ offset: String(p.offset ?? 0), limit: '50' })
  if (p.stage) qs.set('stage', p.stage)
  if (p.channel) qs.set('channel', p.channel)
  if (p.q?.trim()) qs.set('q', p.q.trim())
  if (p.patientId) qs.set('patient_id', p.patientId)
  return api<{ total: number; items: Lead[]; by_stage: Record<string, number> }>(`/leads?${qs}`)
}
export const createLead = (
  body: Partial<Pick<Lead, 'phone' | 'name' | 'channel' | 'source' | 'interest' | 'note'>>,
) => api<Lead>('/leads', { method: 'POST', body })
export const updateLead = (
  id: string,
  body: Partial<Pick<Lead, 'stage' | 'lost_reason' | 'note' | 'interest' | 'source' | 'name'>>,
) => api<Lead>(`/leads/${id}`, { method: 'PATCH', body })
export const leadPatient = (id: string) =>
  api<{ patient_id: string }>(`/leads/${id}/patient`, { method: 'POST' })

// --- scripts ---

export type Script = {
  id: string
  code: string
  language: Language
  title: string
  body: string
  sort_order: number
  updated_at: string
}
export const getScripts = (language?: Language) =>
  api<Script[]>(`/scripts${language ? `?language=${language}` : ''}`)
export const saveScript = (code: string, language: Language, body: { title: string; body: string }) =>
  api<Script>(`/scripts/${code}/${language}`, { method: 'PUT', body })

// --- campaigns ---

export type Segment = {
  kinds?: PatientKind[]
  categories?: string[]
  districts?: string[]
  sources?: Source[]
  gender?: 'male' | 'female'
  last_visit_before_days?: number
  age_min?: number
  age_max?: number
}
export type Campaign = {
  id: string
  name: string
  segment: Segment
  script_code: string | null
  daily_limit: number
  status: 'draft' | 'active' | 'paused' | 'finished'
  ends_on: string | null
  created_at: string
  audience: number
  stats: Record<string, number>
}
export const getCampaigns = () => api<Campaign[]>('/campaigns')
export const previewSegment = (segment: Segment) =>
  api<{ audience: number }>('/campaigns/preview', { method: 'POST', body: segment })
export const createCampaign = (body: {
  name: string
  segment: Segment
  script_code?: string | null
  daily_limit: number
}) => api<Campaign>('/campaigns', { method: 'POST', body })
export const setCampaignStatus = (id: string, status: Campaign['status']) =>
  api<Campaign>(`/campaigns/${id}/status`, { method: 'POST', body: { status } })

// --- reports ---

export type DailyReport = {
  date: string
  inbound_calls: number | null
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
export type Kpi = {
  from: string
  to: string
  leads_total: number
  lead_to_booking: number | null
  first_response_median_min: number | null
  sla_breached: number
  attempts: number
  dial_rate: number | null
  confirmation_rate: number | null
  booking_to_visit: number | null
  no_show_rate: number | null
  repeat_rate: number | null
  returned_patients: number
  operators: {
    user_id: string
    name: string
    attempts: number
    reached: number
    dial_rate: number | null
    booked_by_phone: number
    appointments_created: number
  }[]
}
export const getDaily = (date: string, userId?: string) =>
  api<DailyReport>(`/reports/daily?date=${date}${userId ? `&user_id=${userId}` : ''}`)
export const getKpi = (from: string, to: string) => api<Kpi>(`/reports/kpi?from=${from}&to=${to}`)

/** Excel export needs the bearer token, so it's fetched and saved as a blob. */
export async function downloadKpi(from: string, to: string) {
  const resp = await fetch(`/api/reports/kpi.xlsx?from=${from}&to=${to}`, {
    headers: { Authorization: `Bearer ${getAccessToken() ?? ''}` },
  })
  if (!resp.ok) throw new Error(`http_${resp.status}`)
  const url = URL.createObjectURL(await resp.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = `kpi_${from}_${to}.xlsx`
  a.click()
  URL.revokeObjectURL(url)
}

/** Fills script placeholders ([Ism], [Bemor], ...) with what we know; unknown ones stay visible. */
export function fillScript(body: string, values: Record<string, string | null | undefined>) {
  return body.replace(/\[([^\]]+)\]/g, (whole, key: string) => values[key] ?? whole)
}
