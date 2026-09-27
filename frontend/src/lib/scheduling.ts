import { useTranslation } from 'react-i18next'
import { api } from './api'
import type { Specialty } from './diagnoses'
import type { Source } from './patients'

export const TZ = 'Asia/Tashkent'

export type Branch = {
  id: string
  name_uz: string
  name_ru: string
  address_uz: string | null
  phone: string | null
  is_main: boolean
  is_active: boolean
}

export type Doctor = {
  id: string
  name_uz: string
  name_ru: string
  title_uz: string | null
  title_ru: string | null
  specialties: Specialty[]
  color: string | null
  is_active: boolean
  user_id: string | null
}

export type ServiceItem = {
  id: string
  category_id: string | null
  name_uz: string
  name_ru: string
  price: number | null
  is_active: boolean
  duration_min: number
  /** false while the duration is still the sync's 30-minute placeholder */
  duration_confirmed: boolean
  device_type: string | null
  requires_consultation: boolean
  is_consultation: boolean
  course_sessions: number | null
  min_interval_days: number | null
  followup_call_days: number | null
  prep_uz: string | null
  prep_ru: string | null
}

export type Resource = {
  id: string
  branch_id: string
  name: string
  kind: 'room' | 'device'
  device_type: string | null
  is_active: boolean
}

export type AppointmentStatus =
  'scheduled' | 'confirmed' | 'arrived' | 'completed' | 'no_show' | 'cancelled' | 'rescheduled'

export type Appointment = {
  id: string
  patient_id: string
  patient_name: string
  patient_phone: string | null
  branch_id: string
  doctor_id: string
  doctor_name: string
  resource_id: string | null
  resource_name?: string | null
  resource_kind?: 'room' | 'device' | null
  starts_at: string
  ends_at: string
  status: AppointmentStatus
  source: Source | null
  note: string | null
  cancel_reason: string | null
  rescheduled_from_id: string | null
  /** when the visit it was moved from was planned */
  rescheduled_from_starts_at?: string | null
  /** a moved ("rescheduled") visit points to its new time */
  rescheduled_to_id?: string | null
  rescheduled_to_starts_at?: string | null
  created_by?: string | null
  created_by_name?: string | null
  created_at?: string | null
  status_changed_at?: string | null
  services: {
    service_id: string
    name_uz: string
    name_ru: string
    duration_min: number
    price: number | null
  }[]
}

export type Slot = {
  starts_at: string
  ends_at: string
  doctor_id: string
  doctor_name: string
  resource_id: string | null
}

export type DoctorDay = {
  doctor_id: string
  doctor_name: string
  color: string | null
  windows: { starts_at: string; ends_at: string }[]
}

export type ScheduleDay = { date: string; doctors: DoctorDay[] }

export type Recommendation = {
  id: string
  patient_id: string
  doctor_id: string | null
  appointment_id: string | null
  due_date: string
  service_id: string | null
  note: string | null
  status: 'open' | 'booked' | 'dismissed'
  created_at: string
  doctor_name?: string | null
  service_name_uz?: string | null
  service_name_ru?: string | null
  /** the current user may edit / withdraw it (their own, still open) */
  can_edit?: boolean
}

export type AbsenceKind = 'vacation' | 'sick' | 'other'
export const ABSENCE_KINDS: AbsenceKind[] = ['vacation', 'sick', 'other']
export type Absence = {
  id: string
  date_from: string
  date_to: string
  kind: AbsenceKind
  reason: string | null
}
export type ScheduleRowIn = { branch_id: string; weekday: number; start_time: string; end_time: string }

export type ServiceCategory = {
  id: string
  name_uz: string
  name_ru: string
  specialty: Specialty | null
}
export type DeviceType = { device_type: string; resources: number; services: number }
export type DoctorServiceLink = { doctor_id: string; service_id: string }

export type SyncRun = {
  started_at: string
  finished_at: string
  trigger: 'manual' | 'auto'
  user_id: string | null
  status: 'ok' | 'aborted' | 'failed'
  counts: Record<string, number | string> | null
  error: string | null
}

export type PatientContext = {
  patient: {
    id: string
    full_name: string
    birth_date: string | null
    gender: 'male' | 'female' | 'unknown'
    kind: string
    tags: string[]
    notes: string | null
    last_visit_at: string | null
  }
  conditions: {
    raw_text: string
    category_code: string | null
    category_name_uz: string | null
    category_name_ru: string | null
    visit_type: string | null
  }[]
  visits: Appointment[]
  recommendations: Recommendation[]
}

// transitions the UI offers (backend enforces the full table)
export const NEXT_ACTIONS: Record<AppointmentStatus, AppointmentStatus[]> = {
  scheduled: ['confirmed', 'arrived', 'no_show'],
  confirmed: ['arrived', 'no_show'],
  arrived: ['completed'],
  no_show: ['arrived'],
  completed: [],
  cancelled: [],
  rescheduled: [],
}
/** why a patient didn't come (TZ 4.3: "kelmadi" is recorded with a reason) */
export const NO_SHOW_REASONS = ['no_answer', 'forgot', 'illness', 'late', 'changed_mind', 'other'] as const

export const CANCEL_REASONS = [
  'patient_request',
  'illness',
  'time',
  'price',
  'doctor_unavailable',
  'duplicate',
  'other',
] as const

export const STATUS_STYLE: Record<AppointmentStatus, string> = {
  scheduled: 'bg-sky-50 border-sky-300 text-sky-900',
  confirmed: 'bg-teal-50 border-teal-400 text-teal-900',
  arrived: 'bg-emerald-100 border-emerald-500 text-emerald-900',
  completed: 'bg-slate-100 border-slate-300 text-slate-600',
  no_show: 'bg-red-50 border-red-300 text-red-800',
  cancelled: 'bg-slate-50 border-slate-200 text-slate-400 line-through',
  rescheduled: 'bg-slate-50 border-slate-200 text-slate-400',
}
export const INACTIVE_STATUSES: AppointmentStatus[] = ['cancelled', 'rescheduled']

// --- API ---

export const getBranches = () => api<Branch[]>('/catalog/branches')
export const getDoctors = (activeOnly = true) => api<Doctor[]>(`/catalog/doctors?active_only=${activeOnly}`)
export const updateDoctor = (
  id: string,
  body: Partial<Pick<Doctor, 'specialties' | 'color' | 'is_active' | 'user_id'>>,
) => api<Doctor>(`/catalog/doctors/${id}`, { method: 'PATCH', body })

export function searchServices(p: {
  q?: string
  offset?: number
  limit?: number
  activeOnly?: boolean
  categoryId?: string
  durationMissing?: boolean
  deviceType?: string
}) {
  const qs = new URLSearchParams({ offset: String(p.offset ?? 0), limit: String(p.limit ?? 20) })
  if (p.q?.trim()) qs.set('q', p.q.trim())
  if (p.activeOnly === false) qs.set('active_only', 'false')
  if (p.categoryId) qs.set('category_id', p.categoryId)
  if (p.durationMissing) qs.set('duration_missing', 'true')
  if (p.deviceType) qs.set('device_type', p.deviceType)
  return api<{ total: number; items: ServiceItem[] }>(`/catalog/services?${qs}`)
}
/** every active service (the doctor <-> service editor groups them by category) */
export const getAllServices = () => searchServices({ limit: 1000 }).then((r) => r.items)
export const getServiceCategories = () => api<ServiceCategory[]>('/catalog/service-categories')
export const updateService = (id: string, body: Partial<ServiceItem>) =>
  api<ServiceItem>(`/catalog/services/${id}`, { method: 'PATCH', body })
export const bulkUpdateServices = (body: {
  service_ids: string[]
  duration_min?: number
  device_type?: string
  clear_device?: boolean
}) => api<{ updated: number }>('/catalog/services/bulk', { method: 'POST', body })
export const getDeviceTypes = () => api<DeviceType[]>('/catalog/device-types')
export const getDoctorServiceLinks = (doctorId?: string) =>
  api<DoctorServiceLink[]>(`/catalog/doctor-services${doctorId ? `?doctor_id=${doctorId}` : ''}`)
export const setDoctorServices = (doctorId: string, serviceIds: string[]) =>
  api<DoctorServiceLink[]>(`/catalog/doctors/${doctorId}/services`, {
    method: 'PUT',
    body: { service_ids: serviceIds },
  })
export const getResources = (branchId?: string) =>
  api<Resource[]>(`/catalog/resources${branchId ? `?branch_id=${branchId}` : ''}`)
export const createResource = (body: Omit<Resource, 'id'>) =>
  api<Resource>('/catalog/resources', { method: 'POST', body })
export const updateResource = (id: string, body: Omit<Resource, 'id'>) =>
  api<Resource>(`/catalog/resources/${id}`, { method: 'PUT', body })
export const syncCatalog = () => api<Record<string, number>>('/catalog/sync', { method: 'POST' })
export const getSyncState = () => api<{ last: SyncRun | null; last_ok: SyncRun | null }>('/catalog/sync')

export const getDay = (date: string, branchId: string) =>
  api<Appointment[]>(`/appointments/day?date=${date}&branch_id=${branchId}`)
export const getDayColumns = (date: string, branchId: string) =>
  api<DoctorDay[]>(`/schedule/day?date=${date}&branch_id=${branchId}`)
export const getMyDay = (date: string) => api<Appointment[]>(`/appointments/my-day?date=${date}`)
export function getRange(p: { dateFrom: string; days?: number; branchId?: string; doctorId?: string }) {
  const qs = new URLSearchParams({ date_from: p.dateFrom, days: String(p.days ?? 7) })
  if (p.branchId) qs.set('branch_id', p.branchId)
  if (p.doctorId) qs.set('doctor_id', p.doctorId)
  return api<Appointment[]>(`/appointments/range?${qs}`)
}
export const getScheduleRange = (dateFrom: string, branchId: string, days = 7) =>
  api<ScheduleDay[]>(`/schedule/range?date_from=${dateFrom}&branch_id=${branchId}&days=${days}`)
export const getPatientAppointments = (patientId: string) =>
  api<Appointment[]>(`/appointments/patient/${patientId}`)
export const getPatientContext = (patientId: string) => api<PatientContext>(`/patient-context/${patientId}`)

export function findSlots(p: {
  serviceIds: string[]
  branchId: string
  doctorId?: string
  patientId?: string
  dateFrom?: string
  part?: string
  limit?: number
  /** reschedule: the appointment being moved doesn't block its own course interval */
  excludeAppointmentId?: string
}) {
  const qs = new URLSearchParams({ branch_id: p.branchId, limit: String(p.limit ?? 3) })
  p.serviceIds.forEach((id) => qs.append('service_ids', id))
  if (p.doctorId) qs.set('doctor_id', p.doctorId)
  if (p.patientId) qs.set('patient_id', p.patientId)
  if (p.dateFrom) qs.set('date_from', p.dateFrom)
  if (p.part) qs.set('part', p.part)
  if (p.excludeAppointmentId) qs.set('exclude_appointment_id', p.excludeAppointmentId)
  return api<Slot[]>(`/appointments/slots?${qs}`)
}

export type BookingInput = {
  patient_id: string
  branch_id: string
  doctor_id: string
  service_ids: string[]
  starts_at: string
  source?: Source | null
  note?: string | null
  allow_outside_hours?: boolean
}
export const book = (body: BookingInput) => api<Appointment>('/appointments', { method: 'POST', body })
export const setAppointmentStatus = (id: string, status: AppointmentStatus, reason?: string) =>
  api<Appointment>(`/appointments/${id}/status`, { method: 'POST', body: { status, reason } })
export const setAppointmentResource = (id: string, resourceId: string | null) =>
  api<Appointment>(`/appointments/${id}/resource`, { method: 'POST', body: { resource_id: resourceId } })
export const rescheduleAppointment = (id: string, starts_at: string, doctor_id?: string) =>
  api<Appointment>(`/appointments/${id}/reschedule`, { method: 'POST', body: { starts_at, doctor_id } })

export const getDoctorSchedule = (doctorId: string) =>
  api<{ rows: ScheduleRowIn[]; absences: Absence[] }>(`/schedule/doctors/${doctorId}`)
export const setWeekly = (doctorId: string, rows: ScheduleRowIn[]) =>
  api(`/schedule/doctors/${doctorId}/weekly`, { method: 'PUT', body: { rows } })
export const copySchedule = (doctorId: string, doctorIds: string[]) =>
  api<{ doctors: number; rows: number }>(`/schedule/doctors/${doctorId}/copy`, {
    method: 'POST',
    body: { doctor_ids: doctorIds },
  })
export const addAbsence = (
  doctorId: string,
  body: { date_from: string; date_to: string; kind: AbsenceKind; reason: string | null },
) => api(`/schedule/doctors/${doctorId}/absences`, { method: 'POST', body })
export const deleteAbsence = (id: string) => api(`/schedule/absences/${id}`, { method: 'DELETE' })

export const createRecommendation = (body: {
  patient_id: string
  appointment_id?: string
  due_date: string
  service_id?: string | null
  note?: string | null
}) => api<Recommendation>('/recommendations', { method: 'POST', body })
export const getPatientRecommendations = (patientId: string) =>
  api<Recommendation[]>(`/recommendations/patient/${patientId}`)
export const updateRecommendation = (
  id: string,
  body: { due_date?: string; service_id?: string | null; note?: string | null },
) => api<Recommendation>(`/recommendations/${id}`, { method: 'PATCH', body })
export const dismissRecommendation = (id: string) =>
  api<Recommendation>(`/recommendations/${id}/dismiss`, { method: 'POST' })

// --- time helpers (clinic time zone, independent of the browser's) ---

const partsFmt = new Intl.DateTimeFormat('en-CA', {
  timeZone: TZ,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})

function parts(iso: string | Date) {
  const p = Object.fromEntries(partsFmt.formatToParts(new Date(iso)).map((x) => [x.type, x.value]))
  return { date: `${p.year}-${p.month}-${p.day}`, time: `${p.hour}:${p.minute}` }
}

export const clinicDate = (iso: string | Date = new Date()) => parts(iso).date
export const clinicTime = (iso: string) => parts(iso).time
/** minutes since clinic-local midnight */
export const clinicMinutes = (iso: string) => {
  const [h, m] = clinicTime(iso).split(':').map(Number)
  return h * 60 + m
}
/** clinic-local date + "HH:MM" -> ISO with the clinic's fixed +05:00 offset (no DST in Uzbekistan) */
export const toClinicIso = (date: string, time: string) => `${date}T${time}:00+05:00`
export const addDays = (date: string, days: number) => {
  const d = new Date(`${date}T12:00:00+05:00`)
  d.setUTCDate(d.getUTCDate() + days)
  return clinicDate(d)
}
/** 0 = Monday … 6 = Sunday */
export const weekdayOf = (date: string) => {
  const [y, m, d] = date.split('-').map(Number)
  return (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7
}
/** Monday of the week the date is in */
export const weekStart = (date: string) => addDays(date, -weekdayOf(date))
/** "HH:MM" <-> minutes since midnight */
export const hhmmToMin = (v: string) => {
  const [h, m] = v.split(':').map(Number)
  return h * 60 + m
}
export const minToHhmm = (minutes: number) =>
  `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`
/** "150 000" style price (UZS) */
export const formatPrice = (v: number | null | undefined) => (v == null ? '—' : v.toLocaleString('ru-RU'))

// Browsers render the uz-UZ locale inconsistently ("M09 26, Sat"), so names come from our own table.
const MONTHS = {
  uz: [
    'yanvar',
    'fevral',
    'mart',
    'aprel',
    'may',
    'iyun',
    'iyul',
    'avgust',
    'sentabr',
    'oktabr',
    'noyabr',
    'dekabr',
  ],
  ru: [
    'января',
    'февраля',
    'марта',
    'апреля',
    'мая',
    'июня',
    'июля',
    'августа',
    'сентября',
    'октября',
    'ноября',
    'декабря',
  ],
}
const WEEKDAYS = {
  uz: ['dushanba', 'seshanba', 'chorshanba', 'payshanba', 'juma', 'shanba', 'yakshanba'],
  ru: ['понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье'],
}
export function formatDay(date: string, lang: string) {
  const l = lang === 'ru' ? 'ru' : 'uz'
  const [, m, d] = date.split('-').map(Number)
  const weekday = weekdayOf(date)
  return l === 'ru'
    ? `${WEEKDAYS.ru[weekday]}, ${d} ${MONTHS.ru[m - 1]}`
    : `${d}-${MONTHS.uz[m - 1]}, ${WEEKDAYS.uz[weekday]}`
}
/** "26-sentabr" / "26 сентября" without the weekday */
export function formatShortDay(date: string, lang: string) {
  const [, m, d] = date.split('-').map(Number)
  return lang === 'ru' ? `${d} ${MONTHS.ru[m - 1]}` : `${d}-${MONTHS.uz[m - 1]}`
}
export const doctorName = (d: { name_uz: string; name_ru: string }, lang: string) =>
  lang === 'ru' ? d.name_ru : d.name_uz
export const serviceName = (s: { name_uz: string; name_ru: string }, lang: string) =>
  lang === 'ru' ? s.name_ru : s.name_uz
export const branchName = (b: { name_uz: string; name_ru: string }, lang: string) =>
  lang === 'ru' ? b.name_ru : b.name_uz
/** the branch a screen starts with: the user's own, else the main one */
export function defaultBranchId(branches: Branch[], userBranchId?: string | null) {
  const active = branches.filter((b) => b.is_active)
  return (
    active.find((b) => b.id === userBranchId)?.id ?? active.find((b) => b.is_main)?.id ?? active[0]?.id ?? ''
  )
}

/** Human label of a cancel / no-show reason code (free text from older records passes through). */
export function useReasonLabel() {
  const { t } = useTranslation()
  return (status: AppointmentStatus, code: string | null) => {
    if (!code) return ''
    const ns = status === 'no_show' ? 'noShowReasons' : 'cancelReasons'
    return t(`${ns}.${code}`, { defaultValue: code })
  }
}
