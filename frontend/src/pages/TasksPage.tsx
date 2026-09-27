import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router'
import BookingDialog from '../components/BookingDialog'
import CallAnalysisDialog from '../components/CallAnalysisDialog'
import PatientName from '../components/PatientName'
import ScriptButton from '../components/ScriptView'
import { CallButton } from '../components/Softphone'
import TaskResultForm, { AttemptHistory, SupervisorActions } from '../components/TaskResultForm'
import { Badge, Button, Card, ErrorText, Select } from '../components/ui'
import { getBrief } from '../lib/ai'
import { useAuth } from '../lib/auth-context'
import {
  NEEDS_REASON,
  SUPERVISOR_ROLES,
  addShiftNote,
  getDoneTasks,
  getShiftNotes,
  getTaskSummary,
  getTasks,
  leadPatient,
  recordResult,
  suggestedResult,
  useTaskScriptValues,
  type Task,
  type TaskType,
} from '../lib/ops'
import { formatDate, formatDateTime, formatPhone, getPatient } from '../lib/patients'

const TYPES: TaskType[] = [
  'missed_call',
  'new_lead',
  'confirm_visit',
  'no_show',
  'callback',
  'repeat_visit',
  'post_procedure',
  'course_continue',
  'lost_lead',
  'reactivation',
  'campaign',
]

function Brief({ patientId }: { patientId: string }) {
  const { t, i18n } = useTranslation()
  const [open, setOpen] = useState(false)
  const lang = i18n.language === 'ru' ? 'ru' : 'uz'
  const { data, error, isFetching } = useQuery({
    queryKey: ['ai', 'brief', patientId, lang],
    queryFn: () => getBrief(patientId, lang),
    enabled: open,
    staleTime: 600_000,
  })
  return (
    <div className="mt-1">
      <button className="text-xs text-teal-800 hover:underline" onClick={() => setOpen(!open)}>
        {t(open ? 'ai.hideBrief' : 'ai.brief')}
      </button>
      {open && (
        <div className="mt-1 rounded-md bg-slate-50 p-2 text-sm whitespace-pre-line text-slate-700">
          {isFetching && !data ? t('app.loading') : data?.text}
          <ErrorText error={error} />
        </div>
      )}
    </div>
  )
}

/** Plan 4.4: the AI filled in the result from the recording; one click confirms it. */
function AiSuggestionBox({ task, onEdit, onDone }: { task: Task; onEdit: () => void; onDone: () => void }) {
  const { t } = useTranslation()
  const [details, setDetails] = useState(false)
  const s = task.ai_suggestion!
  const initial = suggestedResult(task)
  const confirm = useMutation({
    mutationFn: () =>
      recordResult(task.id, {
        outcome: initial.outcome,
        reason: initial.reason || null,
        note: initial.note || null,
        analysis_id: s.analysis_id,
      }),
    onSuccess: onDone,
  })
  const needsInput = NEEDS_REASON.includes(initial.outcome) && !initial.reason
  const canConfirm =
    s.outcome !== null && initial.outcome === s.outcome && initial.outcome !== 'callback' && !needsInput
  return (
    <div className="mt-3 rounded-md border border-violet-200 bg-violet-50 p-3 text-sm">
      <div className="text-xs font-medium text-violet-800">{t('ai.suggestion')}</div>
      <p className="mt-1 text-slate-800">{s.summary}</p>
      <div className="mt-1 text-xs text-slate-600">
        {s.outcome ? t(`outcomes.${s.outcome}`) : t('ai.noOutcome')}
        {s.reason && ` · ${t(`reasons.${s.reason}`, { defaultValue: s.reason })}`}
        {s.next_step && ` · ${s.next_step}`}
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        {canConfirm && (
          <Button className="px-2 py-1 text-xs" disabled={confirm.isPending} onClick={() => confirm.mutate()}>
            {t('ai.confirm')}
          </Button>
        )}
        <Button variant="secondary" className="px-2 py-1 text-xs" onClick={onEdit}>
          {t('ai.edit')}
        </Button>
        <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => setDetails(true)}>
          {t('ai.open')}
        </Button>
        <ErrorText error={confirm.error} />
      </div>
      {details && <CallAnalysisDialog callId={s.call_id} onClose={() => setDetails(false)} />}
    </div>
  )
}

/** Who / why line: the visit, the recommendation or the campaign the call is about. */
function TaskContext({ task }: { task: Task }) {
  const { t, i18n } = useTranslation()
  const ru = i18n.language === 'ru'
  const c = task.context
  const doctor = ru ? (c?.doctor_ru ?? c?.doctor_uz) : (c?.doctor_uz ?? c?.doctor_ru)
  const services = ru ? (c?.services_ru ?? c?.services_uz) : (c?.services_uz ?? c?.services_ru)
  const branch = ru ? (c?.branch_ru ?? c?.branch_uz) : (c?.branch_uz ?? c?.branch_ru)
  const parts = [
    task.appointment_at && `${t('tasks.appointment')}: ${formatDateTime(task.appointment_at)}`,
    task.recommendation_due && `${t('taskQueue.recDue')}: ${formatDate(task.recommendation_due)}`,
    doctor,
    services,
    branch,
    task.campaign_name && `${t('taskQueue.campaign')}: ${task.campaign_name}`,
    task.lead_channel && t(`leads.channels.${task.lead_channel}`),
    task.patient_language && task.patient_language.toUpperCase(),
  ].filter(Boolean)
  return (
    <div className="mt-0.5 text-xs text-slate-500">
      {t('tasks.due')}: <span className="tabular-nums">{formatDateTime(task.due_at)}</span>
      {parts.map((p, i) => (
        <span key={i}> · {p}</span>
      ))}
    </div>
  )
}

function TaskHead({ task }: { task: Task }) {
  const { t } = useTranslation()
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={task.priority <= 10 ? 'bad' : task.priority <= 20 ? 'info' : 'neutral'}>
          {t(`taskTypes.${task.type}`)}
        </Badge>
        {task.overdue && <Badge tone="bad">{t('tasks.overdue')}</Badge>}
        {task.do_not_call && <Badge tone="bad">{t('tasks.dnc')}</Badge>}
        {task.attempts > 0 && (
          <span className="text-xs text-slate-500">{t('tasks.attempts', { count: task.attempts })}</span>
        )}
      </div>
      <div className="mt-1 text-base font-medium break-words">
        {task.patient_id ? (
          <Link to={`/patients/${task.patient_id}`} className="text-teal-800 hover:underline">
            <PatientName name={task.patient_name ?? '—'} />
          </Link>
        ) : (
          (task.patient_name ?? '—')
        )}
        {task.patient_phone && (
          <a
            href={`tel:${task.patient_phone}`}
            className="ml-3 font-normal whitespace-nowrap text-slate-700 tabular-nums hover:underline"
          >
            {formatPhone(task.patient_phone)}
          </a>
        )}
      </div>
    </>
  )
}

function TaskCard({ task }: { task: Task }) {
  const { t } = useTranslation()
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [booking, setBooking] = useState<{ patientId: string } | null>(null)
  const values = useTaskScriptValues(task, user)
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['tasks'] })
    void queryClient.invalidateQueries({ queryKey: ['leads'] })
  }
  const patientForBooking = useQuery({
    queryKey: ['patient', booking?.patientId],
    queryFn: () => getPatient(booking!.patientId),
    enabled: Boolean(booking),
  })
  const startBooking = useMutation({
    mutationFn: async () =>
      task.patient_id ?? (task.lead_id ? (await leadPatient(task.lead_id)).patient_id : null),
    onSuccess: (patientId) => {
      if (patientId) setBooking({ patientId })
    },
  })
  const supervisor = SUPERVISOR_ROLES.includes(user?.role ?? '')

  return (
    <div className={`rounded-lg border bg-white p-4 ${task.overdue ? 'border-red-300' : 'border-slate-200'}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <TaskHead task={task} />
          <TaskContext task={task} />
          {task.note && <div className="mt-1 text-sm whitespace-pre-line text-slate-700">{task.note}</div>}
          {task.patient_id && <Brief patientId={task.patient_id} />}
          <AttemptHistory task={task} />
        </div>
        <div className="flex flex-wrap gap-1">
          <CallButton number={task.patient_phone} taskId={task.id} />
          {!open && <ScriptButton code={task.script_code} language={task.patient_language} values={values} />}
          {task.type !== 'confirm_visit' && task.type !== 'post_procedure' && (
            <Button
              variant="secondary"
              className="px-2 py-1 text-xs"
              disabled={startBooking.isPending}
              onClick={() => startBooking.mutate()}
            >
              {t('tasks.book')}
            </Button>
          )}
          <Button className="px-2 py-1 text-xs" aria-expanded={open} onClick={() => setOpen(!open)}>
            {open ? t('taskQueue.closeResult') : t('tasks.result')}
          </Button>
        </div>
      </div>
      <ErrorText error={startBooking.error} />
      {task.ai_suggestion && !open && (
        <AiSuggestionBox task={task} onEdit={() => setOpen(true)} onDone={refresh} />
      )}
      {open && (
        <div className="mt-3">
          <TaskResultForm
            task={task}
            user={user}
            onDone={() => {
              // a second click must not record a second attempt
              setOpen(false)
              refresh()
            }}
          />
        </div>
      )}
      {supervisor && <SupervisorActions task={task} onDone={refresh} />}
      {booking && patientForBooking.data && (
        <BookingDialog
          patient={patientForBooking.data}
          onClose={() => {
            setBooking(null)
            refresh()
          }}
        />
      )}
    </div>
  )
}

function ShiftNotes() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [text, setText] = useState('')
  const { data: notes = [] } = useQuery({ queryKey: ['tasks', 'shift-notes'], queryFn: getShiftNotes })
  const add = useMutation({
    mutationFn: () => addShiftNote(text.trim()),
    onSuccess: () => {
      setText('')
      void queryClient.invalidateQueries({ queryKey: ['tasks', 'shift-notes'] })
    },
  })
  return (
    <Card title={t('tasks.shift')}>
      <ul className="mb-3 space-y-2 text-sm">
        {notes.length === 0 && <li className="text-slate-500">{t('tasks.shiftEmpty')}</li>}
        {notes.slice(0, 3).map((n) => (
          <li key={n.id}>
            <div className="text-xs text-slate-500">
              {n.user_name} · {formatDateTime(n.created_at)}
            </div>
            <div className="whitespace-pre-line">{n.text}</div>
          </li>
        ))}
      </ul>
      <textarea
        className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
        rows={3}
        placeholder={t('tasks.shiftPlaceholder')}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <Button
        className="mt-2"
        variant="secondary"
        disabled={!text.trim() || add.isPending}
        onClick={() => add.mutate()}
      >
        {t('tasks.shiftSave')}
      </Button>
    </Card>
  )
}

function SkeletonCards() {
  return (
    <div className="space-y-3" aria-hidden>
      {[0, 1, 2].map((i) => (
        <div key={i} className="animate-pulse rounded-lg border border-slate-200 bg-white p-4">
          <div className="h-4 w-32 rounded bg-slate-200" />
          <div className="mt-3 h-5 w-64 max-w-full rounded bg-slate-200" />
          <div className="mt-2 h-3 w-80 max-w-full rounded bg-slate-100" />
        </div>
      ))}
    </div>
  )
}

function Queue() {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const view = (params.get('view') ?? 'today') as 'today' | 'all'
  const type = (params.get('type') ?? '') as TaskType | ''
  const campaign = params.get('campaign') ?? ''
  const setParam = (key: string, value: string) =>
    setParams((prev) => {
      const next = new URLSearchParams(prev)
      if (value) next.set(key, value)
      else next.delete(key)
      return next
    })
  const { data: summary } = useQuery({
    queryKey: ['tasks', 'summary'],
    queryFn: getTaskSummary,
    refetchInterval: 30_000,
  })
  const {
    data: tasks,
    error,
    isLoading,
  } = useQuery({
    queryKey: ['tasks', view, type, campaign],
    queryFn: () => getTasks(view, type ? [type] : [], campaign),
    refetchInterval: 30_000,
    placeholderData: keepPreviousData,
  })
  const filtered = Boolean(type || campaign)
  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
        <Select
          value={type}
          onChange={(e) => setParam('type', e.target.value)}
          className="sm:w-56"
          aria-label={t('taskQueue.type')}
        >
          <option value="">{t('tasks.filterAll')}</option>
          {TYPES.map((x) => (
            <option key={x} value={x}>
              {t(`taskTypes.${x}`)} {summary?.by_type[x] ? `(${summary.by_type[x]})` : ''}
            </option>
          ))}
        </Select>
        {(summary?.campaigns?.length ?? 0) > 0 && (
          <Select
            value={campaign}
            onChange={(e) => setParam('campaign', e.target.value)}
            className="sm:w-56"
            aria-label={t('taskQueue.campaign')}
          >
            <option value="">{t('taskQueue.allCampaigns')}</option>
            {summary!.campaigns!.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} ({c.open})
              </option>
            ))}
          </Select>
        )}
        <Select
          value={view}
          onChange={(e) => setParam('view', e.target.value === 'today' ? '' : e.target.value)}
          className="sm:w-48"
          aria-label={t('taskQueue.period')}
        >
          <option value="today">{t('tasks.today')}</option>
          <option value="all">{t('tasks.all')}</option>
        </Select>
      </div>
      {summary && (
        <p className="text-sm text-slate-600">
          {t('tasks.summary', { total: summary.total_due, overdue: summary.overdue })}
          {summary.lead_sla_breached > 0 && (
            <Link
              to="/leads?overdue=1"
              className="ml-3 font-medium text-red-700 underline-offset-2 hover:underline"
            >
              {t('tasks.slaBreached', { count: summary.lead_sla_breached })}
            </Link>
          )}
        </p>
      )}
      <ErrorText error={error} />
      {isLoading && <SkeletonCards />}
      {tasks && tasks.length === 0 && (
        <Card>
          <div className="py-4 text-center">
            <p className="text-sm font-medium text-slate-700">
              {filtered ? t('taskQueue.emptyFiltered') : t('tasks.empty')}
            </p>
            <p className="mt-1 text-sm text-slate-500">
              {filtered ? t('taskQueue.emptyFilteredHint') : t('taskQueue.emptyHint')}
            </p>
            {filtered ? (
              <Button
                variant="secondary"
                className="mt-3"
                onClick={() =>
                  setParams((prev) => {
                    const next = new URLSearchParams(prev)
                    next.delete('type')
                    next.delete('campaign')
                    return next
                  })
                }
              >
                {t('taskQueue.clearFilters')}
              </Button>
            ) : (
              <div className="mt-3 flex flex-wrap justify-center gap-2">
                <Link to="/leads" className="text-sm text-teal-800 hover:underline">
                  {t('taskQueue.goLeads')}
                </Link>
                {view === 'today' && (
                  <button
                    className="text-sm text-teal-800 hover:underline"
                    onClick={() => setParam('view', 'all')}
                  >
                    {t('taskQueue.showFuture')}
                  </button>
                )}
              </div>
            )}
          </div>
        </Card>
      )}
      <div className="space-y-3">
        {tasks?.map((task) => (
          <TaskCard key={task.id} task={task} />
        ))}
      </div>
    </div>
  )
}

function DoneRow({ task }: { task: Task }) {
  const { t } = useTranslation()
  const [details, setDetails] = useState(false)
  return (
    <li className="border-t border-slate-100 py-3 first:border-t-0">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <TaskHead task={task} />
          <div className="mt-1 flex flex-wrap items-center gap-2 text-sm">
            {task.status === 'cancelled' ? (
              <Badge tone="bad">{t('taskQueue.cancelled')}</Badge>
            ) : (
              task.outcome && (
                <Badge tone={task.outcome === 'booked' || task.outcome === 'confirmed' ? 'good' : 'neutral'}>
                  {t(`outcomes.${task.outcome}`)}
                </Badge>
              )
            )}
            {task.outcome_reason && (
              <span className="text-slate-600">
                {t(`reasons.${task.outcome_reason}`, { defaultValue: task.outcome_reason })}
              </span>
            )}
            {task.cancel_reason && <span className="text-slate-600">{task.cancel_reason}</span>}
          </div>
          <div className="mt-0.5 text-xs text-slate-500">
            <span className="tabular-nums">{formatDateTime(task.completed_at ?? null)}</span>
            {' · '}
            {task.completed_by_name ?? t('taskQueue.bySystem')}
            {task.campaign_name && ` · ${task.campaign_name}`}
          </div>
          {task.note && (
            <button
              className="mt-1 text-xs text-teal-800 hover:underline"
              onClick={() => setDetails(!details)}
            >
              {details ? '▾' : '▸'} {t('tasks.note')}
            </button>
          )}
          {details && task.note && (
            <p className="mt-1 text-sm whitespace-pre-line text-slate-700">{task.note}</p>
          )}
          <AttemptHistory task={task} />
        </div>
      </div>
    </li>
  )
}

/** "Bajarilganlar": what was closed today / this week, by whom. */
function Done() {
  const { t } = useTranslation()
  const [period, setPeriod] = useState<'today' | 'week'>('today')
  const [userId, setUserId] = useState('')
  const [offset, setOffset] = useState(0)
  const { data, error, isLoading } = useQuery({
    queryKey: ['tasks', 'done', period, userId, offset],
    queryFn: () => getDoneTasks(period, userId, offset),
    placeholderData: keepPreviousData,
  })
  const everyone = data?.by_user.reduce((sum, b) => sum + b.count, 0) ?? 0
  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="flex gap-1" role="group" aria-label={t('taskQueue.period')}>
          {(['today', 'week'] as const).map((p) => (
            <Button
              key={p}
              variant={period === p ? 'primary' : 'secondary'}
              aria-pressed={period === p}
              onClick={() => {
                setPeriod(p)
                setOffset(0)
              }}
            >
              {t(`taskQueue.periods.${p}`)}
            </Button>
          ))}
        </div>
        <Select
          value={userId}
          onChange={(e) => {
            setUserId(e.target.value)
            setOffset(0)
          }}
          className="sm:w-64"
          aria-label={t('taskQueue.operator')}
        >
          <option value="">
            {t('taskQueue.allOperators')} ({everyone})
          </option>
          {data?.by_user
            .filter((b) => b.user_id)
            .map((b) => (
              <option key={b.user_id} value={b.user_id!}>
                {b.name} ({b.count})
              </option>
            ))}
        </Select>
      </div>
      {data && data.by_user.length > 0 && (
        <div className="flex flex-wrap gap-2 text-xs">
          {data.by_user.map((b) => (
            <span key={b.user_id ?? 'system'} className="rounded-full bg-slate-100 px-3 py-1 text-slate-700">
              {b.name ?? t('taskQueue.bySystem')}: <strong className="tabular-nums">{b.count}</strong>
            </span>
          ))}
        </div>
      )}
      <ErrorText error={error} />
      {isLoading && <SkeletonCards />}
      <Card>
        {data && data.items.length === 0 ? (
          <div className="py-4 text-center text-sm text-slate-500">{t('taskQueue.doneEmpty')}</div>
        ) : (
          <ul>
            {data?.items.map((task) => (
              <DoneRow key={task.id} task={task} />
            ))}
          </ul>
        )}
        {data && data.total > 100 && (
          <div className="mt-3 flex items-center justify-between text-sm text-slate-600">
            <span>{t('audit.total', { count: data.total })}</span>
            <div className="flex gap-2">
              <Button
                variant="secondary"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - 100))}
              >
                {t('audit.prev')}
              </Button>
              <Button
                variant="secondary"
                disabled={offset + 100 >= data.total}
                onClick={() => setOffset(offset + 100)}
              >
                {t('audit.next')}
              </Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  )
}

export default function TasksPage() {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') === 'done' ? 'done' : 'queue'
  return (
    <div className="grid max-w-6xl gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="min-w-0 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="text-2xl font-semibold">{t('tasks.title')}</h1>
          <div className="flex rounded-md border border-slate-300 bg-white p-0.5" role="tablist">
            {(['queue', 'done'] as const).map((x) => (
              <button
                key={x}
                role="tab"
                aria-selected={tab === x}
                className={`rounded px-3 py-1.5 text-sm font-medium ${
                  tab === x ? 'bg-teal-700 text-white' : 'text-slate-700 hover:bg-slate-50'
                }`}
                onClick={() => setParams(x === 'done' ? { tab: 'done' } : {})}
              >
                {t(`taskQueue.tabs.${x}`)}
              </button>
            ))}
          </div>
        </div>
        {tab === 'queue' ? <Queue /> : <Done />}
      </div>
      <div>
        <ShiftNotes />
      </div>
    </div>
  )
}
