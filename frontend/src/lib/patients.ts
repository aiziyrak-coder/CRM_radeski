import { api, type Language } from './api'

export type Gender = 'male' | 'female' | 'unknown'
export type PatientKind = 'active' | 'legacy' | 'cold' | 'lead'
export type Source =
  | 'instagram'
  | 'telegram'
  | 'google'
  | 'maps'
  | 'website'
  | 'recommendation'
  | 'advertising'
  | 'returning'
  | 'import'
  | 'cold_base'
  | 'other'

export const KINDS: PatientKind[] = ['active', 'legacy', 'cold', 'lead']
export const GENDERS: Gender[] = ['unknown', 'female', 'male']
/** sources an operator can pick; import / cold_base are set by the importer only */
export const SOURCES: Source[] = [
  'instagram',
  'telegram',
  'google',
  'maps',
  'website',
  'recommendation',
  'advertising',
  'returning',
  'other',
]

export type Phone = { id: string; number: string; display: string; is_primary: boolean; note: string | null }

export type PatientListItem = {
  id: string
  full_name: string
  birth_date: string | null
  district: string | null
  kind: PatientKind
  do_not_call: boolean
  tags: string[]
  last_visit_at: string | null
  phones: Phone[]
}

export type Condition = {
  id: string
  raw_text: string
  category_code: string | null
  visit_type: 'first' | 'repeat' | null
  source: string
}

export type Patient = PatientListItem & {
  gender: Gender
  address: string | null
  language: Language
  source: Source | null
  notes: string | null
  conditions: Condition[]
  do_not_call_reason: string | null
  merged_into_id: string | null
  created_at: string
}

export type DuplicateCandidate = PatientListItem & { reasons: ('phone' | 'name')[] }

export type PatientInput = {
  full_name: string
  birth_date: string | null
  gender: Gender
  address: string | null
  district: string | null
  language: Language
  source: Source
  notes: string | null
  phones: { number: string; note?: string | null }[]
}

export function searchPatients(params: {
  q?: string
  kind?: PatientKind | ''
  category?: string
  offset: number
  limit: number
}) {
  const qs = new URLSearchParams({ offset: String(params.offset), limit: String(params.limit) })
  if (params.q?.trim()) qs.set('q', params.q.trim())
  if (params.kind) qs.set('kind', params.kind)
  if (params.category) qs.set('category', params.category)
  return api<{ total: number; items: PatientListItem[] }>(`/patients?${qs}`)
}

export const getPatient = (id: string) => api<Patient>(`/patients/${id}`)

export type TimelineKind =
  | 'registered'
  | 'legacy_visit'
  | 'lead'
  | 'appointment'
  | 'call'
  | 'planned_call'
  | 'recommendation'
  | 'phone'
  | 'message'

export interface TimelineEvent {
  kind: TimelineKind
  at: string
  status: string | null
  title: string | null
  detail: string | null
  reason: string | null
  user: string | null
  ref: string | null
  seconds: number | null
}

export const getTimeline = (id: string, lang: Language) =>
  api<TimelineEvent[]>(`/patients/${id}/timeline?lang=${lang}`)

export const createPatient = (body: PatientInput, force = false) =>
  api<Patient>(`/patients${force ? '?force=true' : ''}`, { method: 'POST', body })

export const updatePatient = (id: string, body: Partial<Omit<PatientInput, 'phones'>>) =>
  api<Patient>(`/patients/${id}`, { method: 'PATCH', body })

export const addPhone = (id: string, body: { number: string; note?: string | null; is_primary?: boolean }) =>
  api<Patient>(`/patients/${id}/phones`, { method: 'POST', body })

export const updatePhone = (
  id: string,
  phoneId: string,
  body: { is_primary?: boolean; note?: string | null },
) => api<Patient>(`/patients/${id}/phones/${phoneId}`, { method: 'PATCH', body })

export const deletePhone = (id: string, phoneId: string) =>
  api<Patient>(`/patients/${id}/phones/${phoneId}`, { method: 'DELETE' })

export const setDoNotCall = (id: string, doNotCall: boolean, reason: string | null) =>
  api<Patient>(`/patients/${id}/do-not-call`, { method: 'PUT', body: { do_not_call: doNotCall, reason } })

export const mergePatients = (targetId: string, sourceId: string) =>
  api<Patient>(`/patients/${targetId}/merge`, { method: 'POST', body: { source_id: sourceId } })

export const getDistricts = () => api<string[]>('/patients/meta/districts')

// set by the legacy importer (backend app/importer/legacy.py)
export const UNKNOWN_NAME = "Ismi noma'lum"
export const TAG_LABELS: Record<string, string> = {
  'tekshirish-kerak': 'patients.tagCheck',
  ismsiz: 'patients.tagNoName',
}

/** '1985-04-12' -> '12.04.1985' */
export function formatDate(iso: string | null): string {
  if (!iso) return '—'
  const [y, m, d] = iso.slice(0, 10).split('-')
  return `${d}.${m}.${y}`
}

/** '+998900001122' -> '+998 90 000-11-22' (display only; mirrors backend format_uz_phone) */
export function formatPhone(e164: string | null): string {
  if (!e164) return ''
  const d = e164.replace(/^\+998/, '')
  if (d.length !== 9) return e164
  return `+998 ${d.slice(0, 2)} ${d.slice(2, 5)}-${d.slice(5, 7)}-${d.slice(7)}`
}

/** ISO timestamp -> '12.04.2026 14:30' in the clinic time zone */
export function formatDateTime(iso: string | null): string {
  if (!iso) return '—'
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Tashkent',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    })
      .formatToParts(new Date(iso))
      .map((p) => [p.type, p.value]),
  )
  return `${parts.day}.${parts.month}.${parts.year} ${parts.hour}:${parts.minute}`
}
