// Call-center operations: task queue, leads, scripts, campaigns, reports (phase 2).
import { useTranslation } from 'react-i18next'
import { api, apiBlob, type Language } from './api'
import { UNKNOWN_NAME, formatDate, type PatientKind, type Source } from './patients'
import { clinicTime } from './scheduling'

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
  recommendation_id?: string | null
  recommendation_due?: string | null
  campaign_id: string | null
  campaign_name?: string | null
  created_at: string
  completed_at?: string | null
  completed_by_name?: string | null
  /** a supervisor took it off the queue */
  cancel_reason?: string | null
  /** what the script placeholders [shifokor], [xizmat], [filial] stand for */
  context?: ScriptContext
  /** the AI's reading of the last call made from this task, until the operator confirms it */
  ai_suggestion: {
    analysis_id: string
    call_id: string
    outcome: Outcome | null
    reason: string | null
    summary: string | null
    next_step: string | null
  } | null
}

export type ScriptContext = {
  doctor_uz: string | null
  doctor_ru: string | null
  services_uz: string | null
  services_ru: string | null
  branch_uz: string | null
  branch_ru: string | null
}

export type TaskSummary = {
  by_type: Record<string, number>
  total_due: number
  overdue: number
  lead_sla_breached: number
  /** campaigns with open calls (the queue's campaign filter) */
  campaigns?: { id: string; name: string; open: number }[]
}

export const getTasks = (view: 'today' | 'all', types: TaskType[] = [], campaignId = '') => {
  const qs = new URLSearchParams({ view })
  types.forEach((t) => qs.append('types', t))
  if (campaignId) qs.set('campaign_id', campaignId)
  return api<Task[]>(`/tasks?${qs}`)
}

export type TaskAttempt = {
  id: string
  outcome: Outcome
  reason: string | null
  note: string | null
  user_name: string | null
  /** closed by the system (e.g. a booking), not by a call */
  automatic: boolean
  created_at: string
}
export const getTaskAttempts = (id: string) => api<TaskAttempt[]>(`/tasks/${id}/attempts`)

export type DonePage = {
  total: number
  items: Task[]
  by_user: { user_id: string | null; name: string | null; count: number }[]
}
export function getDoneTasks(period: 'today' | 'week', userId = '', offset = 0) {
  const qs = new URLSearchParams({ period, offset: String(offset), limit: '100' })
  if (userId) qs.set('user_id', userId)
  return api<DonePage>(`/tasks/done?${qs}`)
}

/** supervisor: move an open task and / or change its priority */
export const updateTask = (id: string, body: { due_at?: string; priority?: number }) =>
  api<Task>(`/tasks/${id}`, { method: 'PATCH', body })
export const cancelTask = (id: string, reason: string) =>
  api<Task>(`/tasks/${id}/cancel`, { method: 'POST', body: { reason } })
export const SUPERVISOR_ROLES = ['supervisor', 'admin']
export const getTaskSummary = () => api<TaskSummary>('/tasks/summary')
export const getPatientTasks = (patientId: string) => api<Task[]>(`/tasks/patient/${patientId}`)
export const recordResult = (
  id: string,
  body: {
    outcome: Outcome
    reason?: string | null
    note?: string | null
    callback_at?: string | null
    analysis_id?: string | null
  },
) => api<Task>(`/tasks/${id}/result`, { method: 'POST', body })
export const createCallback = (patient_id: string, due_at: string, note?: string) =>
  api<{ created: boolean }>('/tasks', { method: 'POST', body: { patient_id, due_at, note } })

export type ShiftNote = { id: string; user_name: string | null; text: string; created_at: string }
export const getShiftNotes = () => api<ShiftNote[]>('/tasks/shift-notes')
export const addShiftNote = (text: string) =>
  api<ShiftNote>('/tasks/shift-notes', { method: 'POST', body: { text } })

// --- leads ---

export type LeadChannel = 'call' | 'missed_call' | 'website' | 'telegram' | 'instagram' | 'walk_in' | 'manual'
export type LeadStage = 'new' | 'contacted' | 'booked' | 'confirmed' | 'visited' | 'later' | 'lost'
export const LEAD_STAGES: LeadStage[] = [
  'new',
  'contacted',
  'later',
  'booked',
  'confirmed',
  'visited',
  'lost',
]
/** TZ 4.4 funnel order; "later" and "lost" are side exits */
export const FUNNEL: LeadStage[] = ['new', 'contacted', 'booked', 'confirmed', 'visited']
/** kanban columns (funnel, then the side exits) */
export const BOARD: LeadStage[] = [...FUNNEL, 'later', 'lost']
/** stages an operator sets by hand; the rest follow the booking and the visit */
export const MANUAL_STAGES: LeadStage[] = ['contacted', 'later', 'lost']
export const OPEN_LEAD_STAGES: LeadStage[] = ['new', 'contacted', 'later']
export type SlaState = 'waiting' | 'overdue' | 'met' | 'late' | 'none'
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
  /** overdue: nobody answered and the 15 minutes are up (the row is red) */
  sla_state?: SlaState
  first_response_at: string | null
  appointment_id: string | null
  created_at: string
  updated_at?: string
}

export type LeadPage = {
  total: number
  items: Lead[]
  by_stage: Record<string, number>
  /** how many of the filtered inquiries reached each funnel step */
  funnel?: Record<string, number>
}

export function getLeads(p: {
  stage?: string
  channel?: string
  source?: string
  q?: string
  patientId?: string
  since?: string
  until?: string
  overdue?: boolean
  offset?: number
  limit?: number
}) {
  const qs = new URLSearchParams({ offset: String(p.offset ?? 0), limit: String(p.limit ?? 50) })
  if (p.stage) qs.set('stage', p.stage)
  if (p.channel) qs.set('channel', p.channel)
  if (p.source) qs.set('source', p.source)
  if (p.q?.trim()) qs.set('q', p.q.trim())
  if (p.patientId) qs.set('patient_id', p.patientId)
  if (p.since) qs.set('since', p.since)
  if (p.until) qs.set('until', p.until)
  if (p.overdue) qs.set('sla', 'overdue')
  return api<LeadPage>(`/leads?${qs}`)
}

export type LeadDetail = Lead & {
  history: {
    old_stage: LeadStage | null
    new_stage: LeadStage
    reason: string | null
    user_name: string | null
    created_at: string
  }[]
  tasks: {
    id: string
    type: TaskType
    status: 'open' | 'done' | 'cancelled'
    due_at: string
    outcome: Outcome | null
    attempts: Omit<TaskAttempt, 'id'>[]
  }[]
  calls: {
    id: string
    direction: 'in' | 'out'
    status: string
    started_at: string
    talk_seconds: number | null
    user_name: string | null
    user_id: string | null
    has_recording: boolean
    summary: string | null
  }[]
  messages: { channel: string; direction: 'in' | 'out'; text: string; created_at: string }[]
}
export const getLead = (id: string) => api<LeadDetail>(`/leads/${id}`)

/** conversion between two funnel counts, whole percent; null when there is nothing to divide */
export function conversion(from: number | undefined, to: number | undefined): number | null {
  if (!from || to === undefined) return null
  return Math.round((to / from) * 100)
}

/** minutes left until the SLA deadline (negative once it passed) */
export function slaMinutesLeft(dueAt: string, now: number = Date.now()): number {
  return Math.floor((new Date(dueAt).getTime() - now) / 60_000)
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
  script_code_b: string | null
  daily_limit: number
  status: 'draft' | 'active' | 'paused' | 'finished'
  ends_on: string | null
  created_at: string
  audience: number
  stats: Record<string, number>
  ab:
    | {
        variant: 'a' | 'b'
        script_code: string
        tasks: number
        done: number
        reached: number
        booked: number
        booking_rate: number | null
      }[]
    | null
}
export const getCampaigns = () => api<Campaign[]>('/campaigns')
export const previewSegment = (segment: Segment) =>
  api<{ audience: number }>('/campaigns/preview', { method: 'POST', body: segment })
export const createCampaign = (body: {
  name: string
  segment: Segment
  script_code?: string | null
  script_code_b?: string | null
  daily_limit: number
}) => api<Campaign>('/campaigns', { method: 'POST', body })
export const setCampaignStatus = (id: string, status: Campaign['status']) =>
  api<Campaign>(`/campaigns/${id}/status`, { method: 'POST', body: { status } })

// --- reports ---

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
export type Kpi = CallStats & {
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
    talk_minutes: number
  }[]
}
export const getDaily = (date: string, userId?: string) =>
  api<DailyReport>(`/reports/daily?date=${date}${userId ? `&user_id=${userId}` : ''}`)
export const getKpi = (from: string, to: string) => api<Kpi>(`/reports/kpi?from=${from}&to=${to}`)
/** people the daily report can be filtered by (managers only) */
export const getReportOperators = () => api<{ id: string; full_name: string }[]>('/reports/operators')

/** Excel export needs the bearer token, so it's fetched and saved as a blob. */
export async function downloadKpi(from: string, to: string) {
  const blob = await apiBlob(`/reports/kpi.xlsx?from=${from}&to=${to}`)
  const url = URL.createObjectURL(blob)
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

/** TZ 4.6 "E'tirozlar": objection scripts kept apart from the call script, one button each */
export const OBJECTIONS = ['thinking', 'price', 'medical', 'complaint'] as const

/**
 * A task's script placeholders in the script's language: [shifokor], [xizmat], [filial] from the
 * task's appointment (or the doctor's recommendation), [sana] / [vaqt] from the appointment time.
 */
export function taskScriptValues(
  task: Pick<Task, 'appointment_at' | 'context'>,
  lang: Language,
  base: Record<string, string | null | undefined> = {},
): Record<string, string | null | undefined> {
  const c = task.context
  const pick = (uz: string | null | undefined, ru: string | null | undefined) =>
    (lang === 'ru' ? (ru ?? uz) : (uz ?? ru)) || undefined
  return {
    ...base,
    shifokor: pick(c?.doctor_uz, c?.doctor_ru),
    xizmat: pick(c?.services_uz, c?.services_ru),
    filial: pick(c?.branch_uz, c?.branch_ru),
    sana: task.appointment_at ? formatDate(task.appointment_at) : undefined,
    vaqt: task.appointment_at ? clinicTime(task.appointment_at) : undefined,
  }
}

/** Script placeholders for a task in the script's language: operator, patient, visit details. */
export function useTaskScriptValues(
  task: Pick<Task, 'appointment_at' | 'context' | 'patient_name'>,
  user: { full_name: string } | null,
) {
  const { t } = useTranslation()
  const base = {
    Ism: user?.full_name.split(' ')[0],
    Bemor: task.patient_name === UNKNOWN_NAME ? t('patients.tagNoName') : task.patient_name,
  }
  return (lang: Language) => taskScriptValues(task, lang, base)
}

/** What the AI heard, as a starting point for the result form (the operator decides). */
export function suggestedResult(task: Pick<Task, 'type' | 'ai_suggestion'>) {
  const ai = task.ai_suggestion
  const allowed = OUTCOMES_FOR[task.type]
  return {
    outcome: ai?.outcome && allowed.includes(ai.outcome) ? ai.outcome : allowed[0],
    reason: ai?.reason ?? '',
    note: ai ? [ai.summary, ai.next_step].filter(Boolean).join(' ') : '',
  }
}

/** named priority levels a supervisor picks from (lower = more urgent; rule defaults are 4..45) */
export const PRIORITIES = [
  { value: 3, key: 'urgent' },
  { value: 10, key: 'high' },
  { value: 20, key: 'normal' },
  { value: 40, key: 'low' },
] as const
export type PriorityLevel = (typeof PRIORITIES)[number]['key']

export function priorityLevel(priority: number): PriorityLevel {
  if (priority <= 5) return 'urgent'
  if (priority <= 15) return 'high'
  if (priority <= 30) return 'normal'
  return 'low'
}
