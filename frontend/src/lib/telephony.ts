import { api, apiBlob } from './api'

export type CallDirection = 'in' | 'out'
export type CallStatus =
  'ringing' | 'answered' | 'missed' | 'abandoned' | 'after_hours' | 'no_answer' | 'busy' | 'failed'
export const CALL_STATUSES: CallStatus[] = [
  'answered',
  'missed',
  'abandoned',
  'after_hours',
  'no_answer',
  'busy',
  'failed',
  'ringing',
]

export interface SoftphoneCredentials {
  enabled: boolean
  extension: string | null
  password: string | null
}

export interface CallerLookup {
  phone: string | null
  patient: {
    id: string
    full_name: string
    kind: string
    do_not_call: boolean
    district: string | null
  } | null
  lead: { id: string; name: string | null; stage: string; interest: string | null } | null
  open_tasks: number
  next_visit: string | null
}

export interface CallRecord {
  id: string
  direction: CallDirection
  status: CallStatus
  phone: string | null
  /** caller id as the PBX saw it (anonymous, foreign); `phone` is set only for valid +998 */
  caller_raw?: string | null
  patient_id: string | null
  patient_name: string | null
  lead_id: string | null
  task_id: string | null
  user_id: string | null
  user_name: string | null
  extension: string | null
  started_at: string
  ended_at: string | null
  wait_seconds: number | null
  talk_seconds: number | null
  callback_requested: boolean
  recording_status: 'pending' | 'ready' | 'missing' | 'failed' | null
  ai_status: string | null
  ai_score: number | null
  ai_red_flags: boolean
}

export const getSoftphone = () => api<SoftphoneCredentials>('/telephony/me')

export const lookupCaller = (phone: string) =>
  api<CallerLookup>(`/telephony/lookup?phone=${encodeURIComponent(phone)}`)

export function getCalls(filters: {
  day?: string
  direction?: string
  status?: string
  who?: 'all' | 'mine'
  patientId?: string
}) {
  const q = new URLSearchParams()
  if (filters.day) q.set('day', filters.day)
  if (filters.direction) q.set('direction', filters.direction)
  if (filters.status) q.set('status', filters.status)
  if (filters.who) q.set('who', filters.who)
  if (filters.patientId) q.set('patient_id', filters.patientId)
  return api<CallRecord[]>(`/telephony/calls?${q}`)
}

export type CallLogItem = CallRecord & {
  task_type: string | null
  task_outcome: string | null
  task_outcome_reason: string | null
  ai_outcome: string | null
  called_back_at: string | null
}
export type CallLogSummary = {
  total: number
  inbound: number
  outbound: number
  answered: number
  missed: number
  missed_not_called_back: number
  outbound_answered: number
  avg_wait_sec: number | null
  talk_minutes: number
}
export type CallLogFilters = {
  from: string
  to: string
  direction?: string
  /** a CallStatus, or 'unanswered' = every missed inbound kind */
  status?: string
  user_id?: string
  who?: 'all' | 'mine'
  q?: string
  offset?: number
}
export const CALL_LOG_PAGE = 50
export function getCallLog(f: CallLogFilters) {
  const q = new URLSearchParams({ limit: String(CALL_LOG_PAGE) })
  for (const [k, v] of Object.entries(f)) if (v !== undefined && v !== '' && v !== 0) q.set(k, String(v))
  return api<{ total: number; items: CallLogItem[]; summary: CallLogSummary }>(`/telephony/call-log?${q}`)
}

/** <audio> can't send the bearer token, so the recording is fetched and played from a blob URL. */
export async function recordingUrl(callId: string): Promise<string> {
  return URL.createObjectURL(await apiBlob(`/telephony/calls/${callId}/recording`))
}

/** 125 -> '2:05' */
export function formatDuration(seconds: number | null): string {
  if (seconds === null) return '—'
  const m = Math.floor(seconds / 60)
  return `${m}:${String(seconds % 60).padStart(2, '0')}`
}

/** Anything the operator types or the PBX reports -> the 9 national digits the dialplan wants. */
export function dialable(number: string): string {
  const digits = number.replace(/\D/g, '')
  if (digits.length === 12 && digits.startsWith('998')) return digits.slice(3)
  if (digits.length === 10 && digits.startsWith('8')) return digits.slice(1)
  return digits
}
