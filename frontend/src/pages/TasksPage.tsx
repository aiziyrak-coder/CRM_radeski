import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import BookingDialog from '../components/BookingDialog'
import PatientName from '../components/PatientName'
import CallAnalysisDialog from '../components/CallAnalysisDialog'
import { CallButton } from '../components/Softphone'
import { getBrief } from '../lib/ai'
import ScriptButton from '../components/ScriptView'
import { Badge, Button, Card, ErrorText, Field, Input, Select } from '../components/ui'
import { useAuth } from '../lib/auth-context'
import {
  NEEDS_REASON,
  OUTCOMES_FOR,
  REASONS,
  addShiftNote,
  getShiftNotes,
  getTaskSummary,
  getTasks,
  leadPatient,
  recordResult,
  type Outcome,
  type Task,
  type TaskType,
} from '../lib/ops'
import { UNKNOWN_NAME, formatDate, formatDateTime, formatPhone, getPatient } from '../lib/patients'
import { clinicTime } from '../lib/scheduling'

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

/** What the AI heard, as a starting point for the result form (the operator decides). */
function suggested(task: Task) {
  const ai = task.ai_suggestion
  const allowed = OUTCOMES_FOR[task.type]
  return {
    outcome: ai?.outcome && allowed.includes(ai.outcome) ? ai.outcome : allowed[0],
    reason: ai?.reason ?? '',
    note: ai ? [ai.summary, ai.next_step].filter(Boolean).join(' ') : '',
  }
}

function ResultForm({ task, onDone }: { task: Task; onDone: () => void }) {
  const { t } = useTranslation()
  const initial = suggested(task)
  const [outcome, setOutcome] = useState<Outcome>(initial.outcome)
  const [reason, setReason] = useState(initial.reason)
  const [note, setNote] = useState(initial.note)
  const [callbackAt, setCallbackAt] = useState('')
  const save = useMutation({
    mutationFn: () =>
      recordResult(task.id, {
        outcome,
        reason: reason || null,
        note: note.trim() || null,
        callback_at: callbackAt ? `${callbackAt}:00+05:00` : null,
        analysis_id: task.ai_suggestion?.analysis_id ?? null,
      }),
    onSuccess: onDone,
  })
  const needsReason = NEEDS_REASON.includes(outcome)
  return (
    <div className="grid grid-cols-1 gap-2 rounded-md bg-slate-50 p-3 md:grid-cols-4">
      <Field label={t('tasks.result')}>
        <Select value={outcome} onChange={(e) => setOutcome(e.target.value as Outcome)}>
          {OUTCOMES_FOR[task.type].map((o) => (
            <option key={o} value={o}>
              {t(`outcomes.${o}`)}
            </option>
          ))}
        </Select>
      </Field>
      {(needsReason || outcome === 'thinking') && (
        <Field label={t('tasks.reason')}>
          <Select value={reason} onChange={(e) => setReason(e.target.value)} required={needsReason}>
            <option value="">—</option>
            {REASONS.map((r) => (
              <option key={r} value={r}>
                {t(`reasons.${r}`)}
              </option>
            ))}
          </Select>
        </Field>
      )}
      {(outcome === 'callback' || outcome === 'thinking') && (
        <Field
          label={t('tasks.callbackAt')}
          hint={outcome === 'thinking' ? t('tasks.thinkingDefault') : undefined}
        >
          <Input type="datetime-local" value={callbackAt} onChange={(e) => setCallbackAt(e.target.value)} />
        </Field>
      )}
      <div className="md:col-span-2">
        <Field label={t('tasks.note')}>
          <Input value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />
        </Field>
      </div>
      <div className="flex items-center gap-2 md:col-span-4">
        <Button
          disabled={save.isPending || (needsReason && !reason) || (outcome === 'callback' && !callbackAt)}
          onClick={() => save.mutate()}
        >
          {t('tasks.save')}
        </Button>
        <ErrorText error={save.error} />
      </div>
    </div>
  )
}

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
  const initial = suggested(task)
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

function TaskCard({ task }: { task: Task }) {
  const { t } = useTranslation()
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [booking, setBooking] = useState<{ patientId: string } | null>(null)
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

  const scriptValues = {
    Ism: user?.full_name.split(' ')[0],
    Bemor: task.patient_name === UNKNOWN_NAME ? t('patients.tagNoName') : task.patient_name,
    sana: task.appointment_at ? formatDate(task.appointment_at) : undefined,
    vaqt: task.appointment_at ? clinicTime(task.appointment_at) : undefined,
  }
  return (
    <div className={`rounded-lg border bg-white p-4 ${task.overdue ? 'border-red-300' : 'border-slate-200'}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
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
          <div className="mt-1 text-base font-medium">
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
                className="ml-3 font-normal text-slate-700 tabular-nums hover:underline"
              >
                {formatPhone(task.patient_phone)}
              </a>
            )}
          </div>
          <div className="mt-0.5 text-xs text-slate-500">
            {t('tasks.due')}: {formatDateTime(task.due_at)}
            {task.appointment_at && ` · ${t('tasks.appointment')}: ${formatDateTime(task.appointment_at)}`}
            {task.lead_channel && ` · ${t(`leads.channels.${task.lead_channel}`)}`}
            {task.patient_language && ` · ${task.patient_language.toUpperCase()}`}
          </div>
          {task.note && <div className="mt-1 text-sm whitespace-pre-line text-slate-700">{task.note}</div>}
          {task.patient_id && <Brief patientId={task.patient_id} />}
        </div>
        <div className="flex flex-wrap gap-1">
          <CallButton number={task.patient_phone} taskId={task.id} />
          <ScriptButton code={task.script_code} language={task.patient_language} values={scriptValues} />
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
          <Button className="px-2 py-1 text-xs" onClick={() => setOpen(!open)}>
            {t('tasks.result')}
          </Button>
        </div>
      </div>
      <ErrorText error={startBooking.error} />
      {task.ai_suggestion && !open && (
        <AiSuggestionBox task={task} onEdit={() => setOpen(true)} onDone={refresh} />
      )}
      {open && (
        <div className="mt-3">
          <ResultForm
            task={task}
            onDone={() => {
              // a second click must not record a second attempt
              setOpen(false)
              refresh()
            }}
          />
        </div>
      )}
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

export default function TasksPage() {
  const { t } = useTranslation()
  const [view, setView] = useState<'today' | 'all'>('today')
  const [type, setType] = useState<TaskType | ''>('')
  const { data: summary } = useQuery({
    queryKey: ['tasks', 'summary'],
    queryFn: getTaskSummary,
    refetchInterval: 30_000,
  })
  const { data: tasks, error } = useQuery({
    queryKey: ['tasks', view, type],
    queryFn: () => getTasks(view, type ? [type] : []),
    refetchInterval: 30_000,
  })

  return (
    <div className="grid max-w-6xl gap-6 xl:grid-cols-[1fr_20rem]">
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="text-2xl font-semibold">{t('tasks.title')}</h1>
          <div className="flex flex-wrap gap-2">
            <Select value={type} onChange={(e) => setType(e.target.value as TaskType | '')} className="w-56">
              <option value="">{t('tasks.filterAll')}</option>
              {TYPES.map((x) => (
                <option key={x} value={x}>
                  {t(`taskTypes.${x}`)} {summary?.by_type[x] ? `(${summary.by_type[x]})` : ''}
                </option>
              ))}
            </Select>
            <Select
              value={view}
              onChange={(e) => setView(e.target.value as 'today' | 'all')}
              className="w-48"
            >
              <option value="today">{t('tasks.today')}</option>
              <option value="all">{t('tasks.all')}</option>
            </Select>
          </div>
        </div>
        {summary && (
          <p className="text-sm text-slate-600">
            {t('tasks.summary', { total: summary.total_due, overdue: summary.overdue })}
            {summary.lead_sla_breached > 0 && (
              <span className="ml-3 font-medium text-red-700">
                {t('tasks.slaBreached', { count: summary.lead_sla_breached })}
              </span>
            )}
          </p>
        )}
        <ErrorText error={error} />
        {tasks && tasks.length === 0 && (
          <Card>
            <p className="text-sm text-slate-500">{t('tasks.empty')}</p>
          </Card>
        )}
        <div className="space-y-3">
          {tasks?.map((task) => (
            <TaskCard key={task.id} task={task} />
          ))}
        </div>
      </div>
      <div>
        <ShiftNotes />
      </div>
    </div>
  )
}
