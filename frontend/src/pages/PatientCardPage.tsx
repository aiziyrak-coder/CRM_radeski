import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, useLocation, useNavigate, useParams } from 'react-router'
import AppointmentPanel, { StatusPill } from '../components/AppointmentPanel'
import BookingDialog from '../components/BookingDialog'
import CallAnalysisDialog from '../components/CallAnalysisDialog'
import PatientForm from '../components/PatientForm'
import PatientName from '../components/PatientName'
import PatientRow from '../components/PatientRow'
import { TagEditor } from '../components/PatientTags'
import RecordingPlayer from '../components/RecordingPlayer'
import ScriptButton from '../components/ScriptView'
import { CallButton } from '../components/Softphone'
import TaskResultForm, { AttemptHistory } from '../components/TaskResultForm'
import { Badge, Button, Card, ErrorText, Field, Input, Modal, Notice, Select } from '../components/ui'
import type { Language, User } from '../lib/api'
import { getBrief } from '../lib/ai'
import { useAuth } from '../lib/auth-context'
import { categoryName, getCategories } from '../lib/diagnoses'
import { openSms } from '../lib/messaging'
import {
  OPEN_LEAD_STAGES,
  createCallback,
  getLeads,
  getPatientTasks,
  useTaskScriptValues,
  type Task,
} from '../lib/ops'
import {
  addCategory,
  addPhone,
  ageOf,
  deletePhone,
  formatDate,
  formatDateTime,
  getPatient,
  getTimeline,
  mergePatients,
  removeCategory,
  searchPatients,
  setDoNotCall,
  updatePatient,
  updatePhone,
  type Patient,
  type TimelineEvent,
  type TimelineKind,
} from '../lib/patients'
import {
  addDays,
  clinicDate,
  clinicTime,
  getPatientAppointments,
  toClinicIso,
  type Appointment,
  type AppointmentStatus,
} from '../lib/scheduling'
import { formatDuration } from '../lib/telephony'

// backend tasks/router.py CALL_CENTER; ai/router.py Agent
const CALL_CENTER = ['operator', 'supervisor', 'admin']
const BRIEF_ROLES = ['operator', 'supervisor', 'owner', 'admin']
const BOOKERS = ['operator', 'supervisor', 'registrar', 'admin']
const UPCOMING: AppointmentStatus[] = ['scheduled', 'confirmed']

function useSetPatient(id: string) {
  const queryClient = useQueryClient()
  return (p: Patient) => {
    queryClient.setQueryData(['patient', id], p)
    void queryClient.invalidateQueries({ queryKey: ['patients'] })
  }
}

// the card's side data, fetched in parallel with the patient itself (same keys as the panels)
const appointmentsQuery = (id: string) => ({
  queryKey: ['appointments', 'patient', id],
  queryFn: () => getPatientAppointments(id),
})
const tasksQuery = (id: string) => ({
  queryKey: ['tasks', 'patient', id],
  queryFn: () => getPatientTasks(id),
})
const leadsQuery = (id: string) => ({
  queryKey: ['leads', 'patient', id],
  queryFn: () => getLeads({ patientId: id }),
})
const timelineQuery = (id: string, lang: Language) => ({
  queryKey: ['appointments', 'timeline', id, lang],
  queryFn: () => getTimeline(id, lang),
})

function Skeleton({ className }: { className: string }) {
  return <div className={`animate-pulse rounded bg-slate-100 ${className}`} aria-hidden />
}

function PanelSkeleton() {
  return (
    <div className="space-y-2">
      <Skeleton className="h-4 w-3/4" />
      <Skeleton className="h-4 w-1/2" />
    </div>
  )
}

function Info({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="text-sm">{value || '—'}</dd>
    </div>
  )
}

function Details({ patient }: { patient: Patient }) {
  const { t } = useTranslation()
  const [editing, setEditing] = useState(false)
  const setPatient = useSetPatient(patient.id)
  const save = useMutation({
    mutationFn: (data: Parameters<typeof updatePatient>[1]) => updatePatient(patient.id, data),
    onSuccess: (p) => {
      setPatient(p)
      setEditing(false)
    },
  })
  const age = ageOf(patient.birth_date)

  if (editing) {
    return (
      <Card title={t('patients.edit')}>
        <PatientForm
          initial={patient}
          busy={save.isPending}
          error={save.error}
          onSubmit={({ phones: _phones, ...data }) => save.mutate(data)}
          onCancel={() => setEditing(false)}
        />
      </Card>
    )
  }
  return (
    <Card
      actions={
        <Button variant="secondary" onClick={() => setEditing(true)}>
          {t('patients.edit')}
        </Button>
      }
      title={t('patients.details')}
    >
      <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Info
          label={t('patients.birthDate')}
          value={
            patient.birth_date &&
            `${formatDate(patient.birth_date)}${age !== null ? ` (${t('patientList.years', { count: age })})` : ''}`
          }
        />
        <Info label={t('patients.gender')} value={t(`genders.${patient.gender}`)} />
        <Info label={t('patients.language')} value={t(`lang.${patient.language}`)} />
        <Info label={t('patients.district')} value={patient.district} />
        <Info label={t('patients.source')} value={patient.source && t(`sources.${patient.source}`)} />
        <Info
          label={t('patients.lastVisit')}
          value={patient.last_visit_at && formatDate(patient.last_visit_at)}
        />
        <div className="sm:col-span-2 lg:col-span-3">
          <Info label={t('patients.address')} value={patient.address} />
        </div>
        {patient.notes && (
          <div className="sm:col-span-2 lg:col-span-3">
            <dt className="text-xs text-slate-500">{t('patients.notes')}</dt>
            <dd className="text-sm whitespace-pre-line">{patient.notes}</dd>
          </div>
        )}
      </dl>
    </Card>
  )
}

/** AI pre-call brief (TZ 4.8.2). Made on request: every brief is a paid model call. */
function AiBrief({ patient }: { patient: Patient }) {
  const { t, i18n } = useTranslation()
  const [asked, setAsked] = useState(false)
  const lang = i18n.language === 'ru' ? 'ru' : 'uz'
  const { data, error, isFetching, refetch } = useQuery({
    queryKey: ['ai', 'brief', patient.id, lang],
    queryFn: () => getBrief(patient.id, lang),
    enabled: asked,
    staleTime: 600_000,
  })
  return (
    <section className="rounded-lg border border-violet-200 bg-violet-50/60 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-violet-900">{t('patientCard.brief')}</h2>
        {!asked ? (
          <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => setAsked(true)}>
            {t('patientCard.makeBrief')}
          </Button>
        ) : (
          data && (
            <Button
              variant="ghost"
              className="px-2 py-1 text-xs"
              disabled={isFetching}
              onClick={() => void refetch()}
            >
              {t('patientCard.refresh')}
            </Button>
          )
        )}
      </div>
      {!asked && <p className="mt-1 text-xs text-violet-800/80">{t('patientCard.briefHint')}</p>}
      {asked && isFetching && !data && (
        <div className="mt-2 space-y-2">
          <Skeleton className="h-3 w-full bg-violet-100" />
          <Skeleton className="h-3 w-5/6 bg-violet-100" />
        </div>
      )}
      {data && (
        <div className="mt-2 text-sm whitespace-pre-line text-slate-800">
          {data.text}
          {!data.ai && <div className="mt-1 text-xs text-slate-500">{t('patientCard.briefNoAi')}</div>}
        </div>
      )}
      <ErrorText error={error} />
    </section>
  )
}

/** Diagnosis categories: from the import mapping (fixed here) and set by staff (removable). */
function Categories({ patient }: { patient: Patient }) {
  const { t, i18n } = useTranslation()
  const setPatient = useSetPatient(patient.id)
  const [code, setCode] = useState('')
  const { data: categories = [] } = useQuery({
    queryKey: ['diagnoses', 'categories'],
    queryFn: getCategories,
    staleTime: 60_000,
  })
  const add = useMutation({
    mutationFn: () => addCategory(patient.id, code),
    onSuccess: (p) => {
      setPatient(p)
      setCode('')
    },
  })
  const remove = useMutation({
    mutationFn: (c: string) => removeCategory(patient.id, c),
    onSuccess: setPatient,
  })
  const nameOf = (c: string | null) => {
    const found = categories.find((x) => x.code === c)
    return found ? categoryName(found, i18n.language) : (c ?? '')
  }
  const manual = new Set(patient.conditions.filter((c) => c.source === 'manual').map((c) => c.category_code))
  const imported = patient.conditions.filter((c) => c.source !== 'manual')
  const current = patient.categories ?? []
  return (
    <Card title={t('patientCard.categories')}>
      <div className="flex flex-wrap gap-1">
        {current.length === 0 && (
          <span className="text-sm text-slate-500">{t('patientCard.noCategories')}</span>
        )}
        {current.map((c) => (
          <span
            key={c}
            className="inline-flex items-center gap-1 rounded-full bg-emerald-50 py-0.5 pr-1 pl-2.5 text-xs font-medium text-emerald-800"
          >
            {nameOf(c)}
            {manual.has(c) ? (
              <button
                className="rounded-full px-1 text-emerald-700 hover:bg-white hover:text-red-700"
                aria-label={t('patientCard.removeCategory', { name: nameOf(c) })}
                disabled={remove.isPending}
                onClick={() => remove.mutate(c)}
              >
                ×
              </button>
            ) : (
              <span className="px-1 text-emerald-600" title={t('patientCard.fromImport')}>
                ⓘ
              </span>
            )}
          </span>
        ))}
      </div>
      <form
        className="mt-3 flex flex-col gap-2 sm:flex-row"
        onSubmit={(e: FormEvent) => {
          e.preventDefault()
          if (code) add.mutate()
        }}
      >
        <Select value={code} onChange={(e) => setCode(e.target.value)} className="sm:flex-1">
          <option value="">{t('patientCard.pickCategory')}</option>
          {categories
            .filter((c) => !current.includes(c.code))
            .map((c) => (
              <option key={c.code} value={c.code}>
                {categoryName(c, i18n.language)}
              </option>
            ))}
        </Select>
        <Button type="submit" variant="secondary" disabled={!code || add.isPending}>
          {t('patientCard.addCategory')}
        </Button>
      </form>
      <ErrorText error={add.error ?? remove.error} />
      {imported.length > 0 && (
        <details className="mt-3 text-sm">
          <summary className="cursor-pointer text-xs text-slate-600">
            {t('patientCard.rawDiagnoses', { count: imported.length })}
          </summary>
          <ul className="mt-2 space-y-1">
            {imported.map((c) => (
              <li key={c.id}>
                {c.category_code && (
                  <span className="mr-2">
                    <Badge tone="good">{nameOf(c.category_code)}</Badge>
                  </span>
                )}
                {c.raw_text}
                {c.visit_type && (
                  <span className="ml-2 text-xs text-slate-500">
                    ({t(c.visit_type === 'first' ? 'patients.visitFirst' : 'patients.visitRepeat')})
                  </span>
                )}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-slate-500">
            {t('patientCard.fromImportHint')}{' '}
            <Link to="/diagnoses" className="text-teal-800 hover:underline">
              {t('patientCard.toDiagnoses')}
            </Link>
          </p>
        </details>
      )}
    </Card>
  )
}

const KIND_STYLE: Record<TimelineKind, string> = {
  registered: 'bg-slate-400',
  legacy_visit: 'bg-slate-400',
  lead: 'bg-sky-500',
  appointment: 'bg-teal-600',
  call: 'bg-amber-500',
  phone: 'bg-orange-500',
  message: 'bg-sky-400',
  planned_call: 'bg-amber-300',
  recommendation: 'bg-violet-500',
}

// backend telephony/router.py: managers hear every recording, an operator only their own calls
const LISTENERS = ['supervisor', 'owner', 'admin']
const ANALYSIS_READERS = ['operator', 'supervisor', 'owner', 'admin']

function canListen(e: TimelineEvent, me: User | null): boolean {
  if (!me) return false
  if (LISTENERS.includes(me.role)) return true
  if (me.role !== 'operator') return false
  return e.user_id ? e.user_id === me.id : Boolean(e.user) && e.user === me.full_name
}

function EventLine({ e }: { e: TimelineEvent }) {
  const { t } = useTranslation()
  const { user } = useAuth()
  switch (e.kind) {
    case 'appointment':
      return (
        <>
          <span className="font-medium">{t('timeline.appointment')}</span>
          {e.title && ` · ${e.title}`}
          {e.detail && <span className="text-slate-600"> · {e.detail}</span>}{' '}
          <StatusPill status={e.status as AppointmentStatus} />
          {e.reason && (
            <span className="text-xs text-slate-500">
              {' '}
              {t(`cancelReasons.${e.reason}`, { defaultValue: e.reason })}
            </span>
          )}
        </>
      )
    case 'call':
    case 'planned_call':
      return (
        <>
          <span className="font-medium">
            {t(e.kind === 'call' ? 'timeline.call' : 'timeline.plannedCall')}
          </span>
          {e.title && ` · ${t(`taskTypes.${e.title}`, { defaultValue: e.title })}`}
          {e.status && (
            <Badge tone={e.status === 'booked' || e.status === 'confirmed' ? 'good' : 'neutral'}>
              {t(`outcomes.${e.status}`, { defaultValue: e.status })}
            </Badge>
          )}
          {e.reason && (
            <span className="text-slate-600"> · {t(`reasons.${e.reason}`, { defaultValue: e.reason })}</span>
          )}
          {e.detail && <div className="whitespace-pre-line text-slate-600">{e.detail}</div>}
          {e.user && <div className="text-xs text-slate-500">{e.user}</div>}
        </>
      )
    case 'phone':
      return (
        <>
          <span className="font-medium">{t(`calls.dir.${e.title}`)}</span>{' '}
          <Badge tone={e.status === 'answered' ? 'good' : 'neutral'}>{t(`calls.statuses.${e.status}`)}</Badge>
          {e.seconds ? <span className="text-slate-600"> · {formatDuration(e.seconds)}</span> : null}
          {e.user && <span className="text-xs text-slate-500"> · {e.user}</span>}
          {e.detail && <div className="text-slate-600">{e.detail}</div>}
          {e.ref && canListen(e, user) && (
            <div className="mt-1" onClick={(ev) => ev.stopPropagation()}>
              <RecordingPlayer callId={e.ref} />
            </div>
          )}
        </>
      )
    case 'message':
      return (
        <>
          <span className="font-medium">
            {t(e.status === 'in' ? 'timeline.messageIn' : 'timeline.messageOut')} ·{' '}
            {t(`inbox.channels.${e.title}`, { defaultValue: e.title ?? '' })}
          </span>
          {e.detail && <div className="whitespace-pre-line text-slate-600">{e.detail}</div>}
        </>
      )
    case 'lead':
      return (
        <>
          <span className="font-medium">{t('timeline.lead')}</span>
          {e.title && ` · ${t(`leads.channels.${e.title}`, { defaultValue: e.title })}`}{' '}
          {e.status && <Badge tone="info">{t(`leads.stages.${e.status}`)}</Badge>}
          {e.detail && <div className="text-slate-600">{e.detail}</div>}
        </>
      )
    case 'recommendation':
      return (
        <>
          <span className="font-medium">{t('recommendations.title')}</span>
          {e.title && ` · ${e.title}`}
          {e.reason && (
            <span>
              {' '}
              · {t('recommendations.due')}: <span className="tabular-nums">{formatDate(e.reason)}</span>
            </span>
          )}{' '}
          {e.status && (
            <Badge tone={e.status === 'open' ? 'info' : 'neutral'}>{t(`recommendations.${e.status}`)}</Badge>
          )}
          {e.detail && <div className="text-slate-600">{e.detail}</div>}
        </>
      )
    case 'registered':
      return (
        <span className="text-slate-600">
          {t('timeline.registered')}
          {e.title && ` · ${t(`sources.${e.title}`, { defaultValue: e.title })}`}
        </span>
      )
    case 'legacy_visit':
      return <span className="text-slate-600">{t('timeline.legacyVisit')}</span>
  }
}

function Timeline({
  patient,
  onAppointment,
  onCall,
}: {
  patient: Patient
  onAppointment: (id: string) => void
  onCall: (id: string) => void
}) {
  const { t, i18n } = useTranslation()
  const { user } = useAuth()
  const navigate = useNavigate()
  const lang = i18n.language === 'ru' ? 'ru' : 'uz'
  const { data: events, error, isLoading } = useQuery(timelineQuery(patient.id, lang))
  const now = new Date().toISOString()
  const action = (e: TimelineEvent): (() => void) | null => {
    if (e.kind === 'appointment' && e.appointment_id) return () => onAppointment(e.appointment_id!)
    if (e.kind === 'phone' && e.call_id && e.has_analysis && ANALYSIS_READERS.includes(user?.role ?? ''))
      return () => onCall(e.call_id!)
    if (e.kind === 'lead' && e.lead_id) return () => void navigate(`/leads?lead=${e.lead_id}`)
    return null
  }
  return (
    <Card title={t('patients.history')}>
      <ErrorText error={error} />
      {isLoading && <PanelSkeleton />}
      {events && events.length === 0 && <p className="text-sm text-slate-500">{t('timeline.empty')}</p>}
      <ol className="relative space-y-1 border-l border-slate-200 pl-4 text-sm">
        {events?.map((e, i) => {
          const open = action(e)
          const body = (
            <>
              <div className="text-xs text-slate-500 tabular-nums">
                {e.kind === 'legacy_visit' ? formatDate(e.at) : formatDateTime(e.at)}
                {e.at > now && ` · ${t('timeline.upcoming')}`}
                {open && <span className="ml-2 text-teal-700">{t('patientCard.openItem')} →</span>}
              </div>
              <div className="space-x-1">
                <EventLine e={e} />
              </div>
            </>
          )
          return (
            <li key={i} className={e.at > now ? 'opacity-90' : undefined}>
              <span
                className={`absolute -left-[5px] mt-2.5 h-2.5 w-2.5 rounded-full ${KIND_STYLE[e.kind]}`}
                aria-hidden
              />
              {open ? (
                <div
                  role="button"
                  tabIndex={0}
                  className="-mx-2 cursor-pointer rounded-md px-2 py-1 hover:bg-slate-50 focus:bg-slate-50 focus:outline-none"
                  onClick={open}
                  onKeyDown={(ev) => (ev.key === 'Enter' || ev.key === ' ') && open()}
                >
                  {body}
                </div>
              ) : (
                <div className="py-1">{body}</div>
              )}
            </li>
          )
        })}
      </ol>
    </Card>
  )
}

/** Booked visits ahead, one click to the panel (reschedule / cancel / status). */
function Upcoming({ patient, onOpen }: { patient: Patient; onOpen: (a: Appointment) => void }) {
  const { t, i18n } = useTranslation()
  const { data, error, isLoading } = useQuery(appointmentsQuery(patient.id))
  const now = new Date().toISOString()
  const upcoming = (data ?? [])
    .filter((a) => UPCOMING.includes(a.status) && a.ends_at >= now)
    .sort((a, b) => a.starts_at.localeCompare(b.starts_at))
  const past = (data ?? []).filter((a) => a.starts_at < now).length
  return (
    <Card title={t('patientCard.upcoming')}>
      <ErrorText error={error} />
      {isLoading && <PanelSkeleton />}
      {data && upcoming.length === 0 && (
        <p className="text-sm text-slate-500">{t('patientCard.noUpcoming')}</p>
      )}
      <ul className="space-y-2">
        {upcoming.map((a) => (
          <li key={a.id}>
            <button
              className="w-full rounded-md border border-slate-200 p-2 text-left text-sm hover:border-teal-600 hover:bg-teal-50/40"
              onClick={() => onOpen(a)}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium tabular-nums">
                  {formatDate(a.starts_at)} {clinicTime(a.starts_at)}
                </span>
                <StatusPill status={a.status} />
              </div>
              <div className="text-xs text-slate-600">
                {a.doctor_name} ·{' '}
                {a.services.map((s) => (i18n.language === 'ru' ? s.name_ru : s.name_uz)).join(', ')}
              </div>
            </button>
          </li>
        ))}
      </ul>
      {past > 0 && (
        <p className="mt-2 text-xs text-slate-500">{t('patientCard.pastVisits', { count: past })}</p>
      )}
    </Card>
  )
}

function OpenTask({ task }: { task: Task }) {
  const { t } = useTranslation()
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const values = useTaskScriptValues(task, user)
  return (
    <li
      className={`rounded-md border p-2 ${task.overdue ? 'border-red-200 bg-red-50/40' : 'border-slate-200'}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="text-sm font-medium">{t(`taskTypes.${task.type}`)}</div>
          <div className="text-xs text-slate-500 tabular-nums">
            {formatDateTime(task.due_at)}
            {task.overdue && <span className="ml-1 font-medium text-red-700">· {t('tasks.overdue')}</span>}
          </div>
        </div>
        <div className="flex gap-1">
          <ScriptButton code={task.script_code} language={task.patient_language} values={values} />
          <Button className="px-2 py-1 text-xs" aria-expanded={open} onClick={() => setOpen(!open)}>
            {open ? t('taskQueue.closeResult') : t('tasks.result')}
          </Button>
        </div>
      </div>
      {task.note && <p className="mt-1 text-xs whitespace-pre-line text-slate-600">{task.note}</p>}
      <AttemptHistory task={task} />
      {open && (
        <div className="mt-2">
          <TaskResultForm
            task={task}
            user={user}
            script={false}
            onDone={() => {
              setOpen(false)
              void queryClient.invalidateQueries({ queryKey: ['tasks'] })
              void queryClient.invalidateQueries({ queryKey: ['appointments'] })
              void queryClient.invalidateQueries({ queryKey: ['leads'] })
            }}
          />
        </div>
      )}
    </li>
  )
}

function OpenTasks({ patient }: { patient: Patient }) {
  const { t } = useTranslation()
  const { data, error, isLoading } = useQuery(tasksQuery(patient.id))
  const open = (data ?? [])
    .filter((x) => x.status === 'open')
    .sort((a, b) => a.due_at.localeCompare(b.due_at))
  return (
    <Card title={t('patientCard.openTasks')}>
      <ErrorText error={error} />
      {isLoading && <PanelSkeleton />}
      {data && open.length === 0 && <p className="text-sm text-slate-500">{t('patientCard.noTasks')}</p>}
      <ul className="space-y-2">
        {open.map((task) => (
          <OpenTask key={task.id} task={task} />
        ))}
      </ul>
    </Card>
  )
}

function Recommendations({ patient }: { patient: Patient }) {
  const { t, i18n } = useTranslation()
  const lang = i18n.language === 'ru' ? 'ru' : 'uz'
  const { data, isLoading } = useQuery(timelineQuery(patient.id, lang))
  const recs = (data ?? []).filter((e) => e.kind === 'recommendation')
  const today = clinicDate()
  const soon = addDays(today, 7)
  return (
    <Card title={t('recommendations.title')}>
      {isLoading && <PanelSkeleton />}
      {data && recs.length === 0 && <p className="text-sm text-slate-500">{t('recommendations.none')}</p>}
      <ul className="space-y-2 text-sm">
        {recs.map((r, i) => {
          const due = r.reason ?? ''
          const overdue = r.status === 'open' && due < today
          const near = r.status === 'open' && !overdue && due <= soon
          return (
            <li key={i} className="rounded-md border border-slate-100 p-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span
                  className={`tabular-nums ${overdue ? 'font-medium text-red-700' : near ? 'text-amber-800' : ''}`}
                >
                  {t('recommendations.due')}: {formatDate(due || null)}
                </span>
                <Badge
                  tone={
                    r.status === 'open'
                      ? overdue
                        ? 'bad'
                        : 'info'
                      : r.status === 'booked'
                        ? 'good'
                        : 'neutral'
                  }
                >
                  {t(`recommendations.${r.status}`)}
                </Badge>
              </div>
              {r.title && <div className="text-xs text-slate-600">{r.title}</div>}
              {r.detail && <div className="text-xs text-slate-700">{r.detail}</div>}
            </li>
          )
        })}
      </ul>
    </Card>
  )
}

function Leads({ patient }: { patient: Patient }) {
  const { t } = useTranslation()
  const { data, error, isLoading } = useQuery(leadsQuery(patient.id))
  return (
    <Card title={t('patientCard.leads')}>
      <ErrorText error={error} />
      {isLoading && <PanelSkeleton />}
      {data && data.items.length === 0 && (
        <p className="text-sm text-slate-500">{t('patientCard.noLeads')}</p>
      )}
      <ul className="space-y-2 text-sm">
        {data?.items.map((lead) => (
          <li key={lead.id}>
            <Link
              to={`/leads?lead=${lead.id}`}
              className={`block rounded-md border p-2 hover:border-teal-600 ${
                lead.sla_state === 'overdue' ? 'border-red-300 bg-red-50' : 'border-slate-200'
              }`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs text-slate-500 tabular-nums">{formatDateTime(lead.created_at)}</span>
                <Badge
                  tone={
                    lead.stage === 'lost' ? 'bad' : OPEN_LEAD_STAGES.includes(lead.stage) ? 'info' : 'good'
                  }
                >
                  {t(`leads.stages.${lead.stage}`)}
                </Badge>
              </div>
              <div className="text-xs text-slate-600">
                {t(`leads.channels.${lead.channel}`)}
                {lead.source && ` · ${t(`sources.${lead.source}`)}`}
              </div>
              {lead.interest && (
                <div className="mt-0.5 line-clamp-2 text-xs text-slate-700">{lead.interest}</div>
              )}
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  )
}

function SmsButton({ patient }: { patient: Patient }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const open = useMutation({
    mutationFn: () => openSms(patient.id),
    onSuccess: (conv) => void navigate(`/inbox?c=${conv.id}`),
  })
  return (
    <div className="mt-3">
      <Button
        variant="secondary"
        className="px-2 py-1 text-xs"
        disabled={open.isPending}
        onClick={() => open.mutate()}
      >
        {t('inbox.writeSms')}
      </Button>
      <ErrorText error={open.error} />
    </div>
  )
}

function Phones({ patient }: { patient: Patient }) {
  const { t } = useTranslation()
  const { user } = useAuth()
  const setPatient = useSetPatient(patient.id)
  const [number, setNumber] = useState('')
  const [note, setNote] = useState('')
  const opts = { onSuccess: setPatient }
  const add = useMutation({
    mutationFn: () => addPhone(patient.id, { number, note: note.trim() || null }),
    onSuccess: (p) => {
      setPatient(p)
      setNumber('')
      setNote('')
    },
  })
  const primary = useMutation({
    mutationFn: (phoneId: string) => updatePhone(patient.id, phoneId, { is_primary: true }),
    ...opts,
  })
  const remove = useMutation({ mutationFn: (phoneId: string) => deletePhone(patient.id, phoneId), ...opts })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    add.mutate()
  }

  return (
    <Card title={t('patients.phones')}>
      {patient.phones.length === 0 && <p className="text-sm text-red-700">{t('patientList.noPhone')}</p>}
      <ul className="divide-y divide-slate-100">
        {patient.phones.map((ph) => (
          <li key={ph.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <div>
              <a href={`tel:${ph.number}`} className="font-medium text-teal-800 hover:underline">
                {ph.display}
              </a>{' '}
              <CallButton number={ph.number} />
              {ph.note && <span className="ml-2 text-sm text-slate-500">{ph.note}</span>}
              {ph.is_primary && (
                <span className="ml-2">
                  <Badge tone="good">{t('patients.primary')}</Badge>
                </span>
              )}
              {ph.wrong_number_at && (
                <span className="ml-2" title={formatDateTime(ph.wrong_number_at)}>
                  <Badge tone="bad">{t('patients.wrongNumber')}</Badge>
                </span>
              )}
            </div>
            <div className="flex gap-1">
              {!ph.is_primary && (
                <Button variant="ghost" onClick={() => primary.mutate(ph.id)} disabled={primary.isPending}>
                  {t('patients.makePrimary')}
                </Button>
              )}
              {patient.phones.length > 1 && (
                <Button variant="ghost" onClick={() => remove.mutate(ph.id)} disabled={remove.isPending}>
                  {t('patients.remove')}
                </Button>
              )}
            </div>
          </li>
        ))}
      </ul>
      {/* the card sits in a narrow column, so fields always stack */}
      <form onSubmit={submit} className="mt-3 space-y-2">
        <Input
          type="tel"
          inputMode="tel"
          placeholder="90 000 22 44"
          value={number}
          onChange={(e) => setNumber(e.target.value)}
          required
        />
        <Input
          placeholder={t('patients.phoneNote')}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={100}
        />
        <Button type="submit" variant="secondary" disabled={add.isPending} className="w-full">
          {t('patients.addPhone')}
        </Button>
      </form>
      <div className="mt-2">
        <ErrorText error={add.error ?? primary.error ?? remove.error} />
      </div>
      {BOOKERS.includes(user?.role ?? '') && <SmsButton patient={patient} />}
    </Card>
  )
}

function DoNotCall({ patient }: { patient: Patient }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const setPatient = useSetPatient(patient.id)
  const [reason, setReason] = useState('')
  const toggle = useMutation({
    mutationFn: () =>
      setDoNotCall(patient.id, !patient.do_not_call, patient.do_not_call ? null : reason.trim() || null),
    onSuccess: (p) => {
      setPatient(p)
      setReason('')
      void queryClient.invalidateQueries({ queryKey: ['tasks'] }) // outbound calls were cancelled
    },
  })

  return (
    <Card title={t('patients.dnc')}>
      {patient.do_not_call ? (
        <div className="space-y-3">
          <p className="text-sm">
            <Badge tone="bad">{t('patients.dnc')}</Badge>
            {patient.do_not_call_reason && (
              <span className="ml-2 text-slate-600">{patient.do_not_call_reason}</span>
            )}
          </p>
          <Button variant="secondary" onClick={() => toggle.mutate()} disabled={toggle.isPending}>
            {t('patients.dncClear')}
          </Button>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-slate-600">{t('patients.dncHint')}</p>
          <Field label={t('patients.dncReason')}>
            <Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={255} />
          </Field>
          <Button variant="danger" onClick={() => toggle.mutate()} disabled={toggle.isPending}>
            {t('patients.dncSet')}
          </Button>
        </div>
      )}
      <ErrorText error={toggle.error} />
    </Card>
  )
}

function Merge({ patient }: { patient: Patient }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const setPatient = useSetPatient(patient.id)
  const [q, setQ] = useState('')
  const { data } = useQuery({
    queryKey: ['patients', 'merge-search', q],
    queryFn: () => searchPatients({ q, offset: 0, limit: 10 }),
    enabled: q.trim().length >= 3,
  })
  const merge = useMutation({
    mutationFn: (sourceId: string) => mergePatients(patient.id, sourceId),
    onSuccess: (p) => {
      setPatient(p)
      setQ('')
      // the merged card's visits, calls, tasks and messages now belong to this one
      // (the ['appointments'] prefix covers this patient's timeline too)
      void queryClient.invalidateQueries({ queryKey: ['appointments'] })
      void queryClient.invalidateQueries({ queryKey: ['tasks'] })
      void queryClient.invalidateQueries({ queryKey: ['leads'] })
    },
  })
  const candidates = data?.items.filter((p) => p.id !== patient.id) ?? []

  return (
    <Card title={t('patients.merge')}>
      <p className="mb-3 text-sm text-slate-600">{t('patients.mergeHint')}</p>
      <Input
        type="search"
        placeholder={t('patients.mergeSearch')}
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      {candidates.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-sm">
            <tbody>
              {candidates.map((c) => (
                <PatientRow
                  key={c.id}
                  p={c}
                  action={
                    <Button
                      variant="danger"
                      disabled={merge.isPending}
                      onClick={() => {
                        if (window.confirm(t('patients.mergeConfirm', { name: c.full_name })))
                          merge.mutate(c.id)
                      }}
                    >
                      {t('patients.merge')}
                    </Button>
                  }
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {merge.isSuccess && (
        <div className="mt-3">
          <Notice>{t('patients.merged')}</Notice>
        </div>
      )}
      <ErrorText error={merge.error} />
    </Card>
  )
}

/** "Qayta qo'ng'iroq belgilash": a callback task in the shared queue at the chosen time. */
function CallbackDialog({ patient, onClose }: { patient: Patient; onClose: () => void }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [day, setDay] = useState(addDays(clinicDate(), 1))
  const [time, setTime] = useState('10:00')
  const [note, setNote] = useState('')
  const save = useMutation({
    mutationFn: () => createCallback(patient.id, toClinicIso(day, time), note.trim() || undefined),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['tasks'] })
      void queryClient.invalidateQueries({ queryKey: ['appointments', 'timeline', patient.id] })
      onClose()
    },
  })
  return (
    <Modal title={t('patientCard.callback')} onClose={onClose}>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate()
        }}
      >
        <p className="text-sm text-slate-600">{t('patientCard.callbackHint')}</p>
        <div className="grid grid-cols-2 gap-3">
          <Field label={t('patientCard.callbackDay')}>
            <Input
              type="date"
              value={day}
              min={clinicDate()}
              onChange={(e) => setDay(e.target.value)}
              required
            />
          </Field>
          <Field label={t('patientCard.callbackTime')}>
            <Input type="time" value={time} onChange={(e) => setTime(e.target.value)} required />
          </Field>
        </div>
        <Field label={t('tasks.note')}>
          <Input value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />
        </Field>
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" disabled={!day || !time || save.isPending}>
            {t('patientCard.callbackSave')}
          </Button>
          <Button variant="secondary" onClick={onClose}>
            {t('patients.cancel')}
          </Button>
          <ErrorText error={save.error} />
        </div>
      </form>
    </Modal>
  )
}

function FirstContact({ patient }: { patient: Patient }) {
  const { t } = useTranslation()
  const channel = patient.first_contact_channel
  const how =
    channel === 'registered'
      ? t('patientCard.viaRegistration')
      : channel === 'call'
        ? t('patientCard.viaCall')
        : channel
          ? t(`leads.channels.${channel}`, { defaultValue: channel })
          : null
  return (
    <p className="mt-1 text-sm text-slate-600">
      {patient.first_contact_at ? (
        <>
          {t('patientCard.firstContact')}:{' '}
          <span className="font-medium tabular-nums">{formatDate(patient.first_contact_at)}</span>
          {how && ` · ${how}`}
        </>
      ) : patient.kind === 'legacy' || patient.kind === 'cold' ? (
        // the import date is not a contact: the old export has no dates
        t('patientCard.firstContactUnknown')
      ) : (
        <>
          {t('patients.created')}: <span className="tabular-nums">{formatDate(patient.created_at)}</span>
        </>
      )}
      {' · '}
      {t('patients.source')}:{' '}
      {patient.source ? (
        <span className="font-medium">{t(`sources.${patient.source}`)}</span>
      ) : (
        <span className="text-red-700">{t('patientCard.noSource')}</span>
      )}
    </p>
  )
}

function CardSkeleton() {
  return (
    <div className="max-w-6xl space-y-6" aria-busy>
      <Skeleton className="h-4 w-32" />
      <Skeleton className="h-8 w-72 max-w-full" />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
        <div className="space-y-6">
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-32 w-full" />
        </div>
      </div>
    </div>
  )
}

export default function PatientCardPage() {
  const { t, i18n } = useTranslation()
  const { id = '' } = useParams()
  const { user } = useAuth()
  const location = useLocation()
  const redirectedFromMerge = Boolean((location.state as { mergedFrom?: string } | null)?.mergedFrom)
  const [booking, setBooking] = useState(false)
  const [callback, setCallback] = useState(false)
  const [appointment, setAppointment] = useState<Appointment | null>(null)
  const [analysis, setAnalysis] = useState<string | null>(null)
  const role = user?.role ?? ''
  const callCenter = CALL_CENTER.includes(role)
  const lang = i18n.language === 'ru' ? 'ru' : 'uz'
  const queryClient = useQueryClient()
  const setPatient = useSetPatient(id)

  // TZ 5 "1 second": everything the card shows starts loading at once, not panel after panel
  const { data: patient, error } = useQuery({ queryKey: ['patient', id], queryFn: () => getPatient(id) })
  const appointments = useQuery(appointmentsQuery(id))
  useQuery({ ...timelineQuery(id, lang) })
  useQuery({ ...leadsQuery(id) })
  useQuery({ ...tasksQuery(id), enabled: callCenter })

  if (error) return <ErrorText error={error} />
  if (!patient) return <CardSkeleton />
  if (patient.merged_into_id) {
    return <Navigate to={`/patients/${patient.merged_into_id}`} replace state={{ mergedFrom: patient.id }} />
  }
  const canMerge = role === 'supervisor' || role === 'admin'
  const canBook = BOOKERS.includes(role)
  const primary = patient.phones.find((p) => p.is_primary) ?? patient.phones[0]
  const openAppointment = (appointmentId: string) => {
    const found = appointments.data?.find((a) => a.id === appointmentId)
    if (found) setAppointment(found)
  }

  return (
    <div className="max-w-6xl space-y-6">
      <div>
        <Link to="/patients" className="text-sm text-teal-800 hover:underline">
          ← {t('patients.back')}
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold break-words">
            <PatientName name={patient.full_name} />
          </h1>
          <Badge tone={patient.kind === 'active' ? 'good' : 'neutral'}>{t(`kinds.${patient.kind}`)}</Badge>
          {patient.do_not_call && <Badge tone="bad">{t('patients.dnc')}</Badge>}
        </div>
        <FirstContact patient={patient} />
        <div className="mt-2">
          <TagEditor patient={patient} onSaved={setPatient} />
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {canBook && <Button onClick={() => setBooking(true)}>{t('booking.title')}</Button>}
          {callCenter && (
            <Button variant="secondary" onClick={() => setCallback(true)} disabled={patient.do_not_call}>
              {t('patientCard.callback')}
            </Button>
          )}
          {primary && <CallButton number={primary.number} />}
        </div>
      </div>

      {booking && <BookingDialog patient={patient} onClose={() => setBooking(false)} />}
      {callback && <CallbackDialog patient={patient} onClose={() => setCallback(false)} />}
      {appointment && (
        <AppointmentPanel
          a={appointment}
          onClose={() => {
            setAppointment(null)
            void queryClient.invalidateQueries({ queryKey: ['appointments'] })
            void queryClient.invalidateQueries({ queryKey: ['tasks'] })
          }}
        />
      )}
      {analysis && <CallAnalysisDialog callId={analysis} onClose={() => setAnalysis(null)} />}
      {redirectedFromMerge && <Notice>{t('patients.mergedRedirect')}</Notice>}
      {patient.kind === 'legacy' && (
        <p className="rounded-md bg-slate-100 px-3 py-2 text-sm text-slate-700">{t('patients.legacyNote')}</p>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="min-w-0 space-y-6 lg:col-span-2">
          {BRIEF_ROLES.includes(role) && <AiBrief patient={patient} />}
          <Details patient={patient} />
          <Categories patient={patient} />
          <Timeline patient={patient} onAppointment={openAppointment} onCall={setAnalysis} />
        </div>
        <div className="min-w-0 space-y-6">
          <Upcoming patient={patient} onOpen={setAppointment} />
          {callCenter && <OpenTasks patient={patient} />}
          <Recommendations patient={patient} />
          <Leads patient={patient} />
          <Phones patient={patient} />
          <DoNotCall patient={patient} />
          {canMerge && <Merge patient={patient} />}
        </div>
      </div>
    </div>
  )
}
