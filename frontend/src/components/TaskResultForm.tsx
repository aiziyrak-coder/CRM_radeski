import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { User } from '../lib/api'
import {
  NEEDS_REASON,
  OUTCOMES_FOR,
  PRIORITIES,
  REASONS,
  cancelTask,
  getTaskAttempts,
  priorityLevel,
  recordResult,
  suggestedResult,
  updateTask,
  useTaskScriptValues,
  type Outcome,
  type Task,
} from '../lib/ops'
import { formatDateTime } from '../lib/patients'
import { clinicDate, clinicTime } from '../lib/scheduling'
import { ScriptPanel } from './ScriptView'
import { Badge, Button, ErrorText, Field, Input, Select } from './ui'

/** datetime-local value of an ISO time in the clinic zone */
const localValue = (iso: string) => `${clinicDate(iso)}T${clinicTime(iso)}`
const fromLocal = (value: string) => `${value}:00+05:00`

/**
 * The result form of a call. With `script`, the task's script opens with it (TZ 4.6: the script
 * matching the task type opens automatically, the objections below it).
 */
export default function TaskResultForm({
  task,
  user,
  onDone,
  script = true,
}: {
  task: Task
  user: User | null
  onDone: () => void
  script?: boolean
}) {
  const { t } = useTranslation()
  const initial = suggestedResult(task)
  const values = useTaskScriptValues(task, user)
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
        callback_at: callbackAt ? fromLocal(callbackAt) : null,
        analysis_id: task.ai_suggestion?.analysis_id ?? null,
      }),
    onSuccess: onDone,
  })
  const needsReason = NEEDS_REASON.includes(outcome)
  return (
    <div className="space-y-3">
      {script && task.script_code && (
        <ScriptPanel code={task.script_code} language={task.patient_language} values={values} />
      )}
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
        <div className="flex flex-wrap items-center gap-2 md:col-span-4">
          <Button
            disabled={save.isPending || (needsReason && !reason) || (outcome === 'callback' && !callbackAt)}
            onClick={() => save.mutate()}
          >
            {t('tasks.save')}
          </Button>
          <ErrorText error={save.error} />
        </div>
      </div>
    </div>
  )
}

/** Every call made from the task: who, when, what came of it (TZ 4.5 attempts). */
export function AttemptHistory({ task }: { task: Pick<Task, 'id' | 'attempts'> }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const { data, error, isLoading } = useQuery({
    queryKey: ['tasks', 'attempts', task.id, task.attempts],
    queryFn: () => getTaskAttempts(task.id),
    enabled: open,
  })
  if (task.attempts === 0) return null
  return (
    <div className="mt-2">
      <button
        className="text-xs text-teal-800 hover:underline"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        {open ? '▾' : '▸'} {t('taskQueue.attemptHistory', { count: task.attempts })}
      </button>
      {open && (
        <div className="mt-1 rounded-md border border-slate-100 bg-slate-50 p-2">
          {isLoading && <p className="text-xs text-slate-500">{t('app.loading')}</p>}
          <ErrorText error={error} />
          <ol className="space-y-1.5 text-xs">
            {data?.map((a) => (
              <li key={a.id} className="flex flex-wrap items-baseline gap-x-2">
                <span className="text-slate-500 tabular-nums">{formatDateTime(a.created_at)}</span>
                <Badge tone={a.outcome === 'no_answer' ? 'neutral' : 'good'}>
                  {t(`outcomes.${a.outcome}`)}
                </Badge>
                {a.reason && (
                  <span className="text-slate-600">
                    {t(`reasons.${a.reason}`, { defaultValue: a.reason })}
                  </span>
                )}
                <span className="text-slate-700">
                  {a.automatic ? t('taskQueue.bySystem') : (a.user_name ?? '—')}
                </span>
                {a.note && <span className="w-full whitespace-pre-line text-slate-600">{a.note}</span>}
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  )
}

/** Supervisor only (backend checks the role too): move, reprioritise or cancel an open task. */
export function SupervisorActions({ task, onDone }: { task: Task; onDone: () => void }) {
  const { t } = useTranslation()
  const [mode, setMode] = useState<'' | 'move' | 'priority' | 'cancel'>('')
  const [due, setDue] = useState(localValue(task.due_at))
  const [priority, setPriority] = useState(String(task.priority))
  const [reason, setReason] = useState('')
  const done = () => {
    setMode('')
    onDone()
  }
  const move = useMutation({
    mutationFn: () => updateTask(task.id, { due_at: fromLocal(due) }),
    onSuccess: done,
  })
  const prio = useMutation({
    mutationFn: () => updateTask(task.id, { priority: Number(priority) }),
    onSuccess: done,
  })
  const cancel = useMutation({ mutationFn: () => cancelTask(task.id, reason.trim()), onSuccess: done })
  const toggle = (m: typeof mode) => setMode(mode === m ? '' : m)
  return (
    <div className="mt-2 rounded-md border border-dashed border-slate-300 p-2">
      <div className="flex flex-wrap items-center gap-1">
        <span className="mr-1 text-xs font-medium text-slate-500">{t('taskQueue.supervisor')}:</span>
        <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => toggle('move')}>
          {t('taskQueue.move')}
        </Button>
        <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => toggle('priority')}>
          {t('taskQueue.priority')}: {t(`taskQueue.levels.${priorityLevel(task.priority)}`)}
        </Button>
        <Button variant="ghost" className="px-2 py-1 text-xs text-red-700" onClick={() => toggle('cancel')}>
          {t('taskQueue.cancel')}
        </Button>
      </div>
      {mode === 'move' && (
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <Field label={t('taskQueue.newDue')}>
            <Input
              type="datetime-local"
              value={due}
              onChange={(e) => setDue(e.target.value)}
              className="w-56"
            />
          </Field>
          <Button
            className="px-3 py-2 text-xs"
            disabled={!due || move.isPending}
            onClick={() => move.mutate()}
          >
            {t('patients.save')}
          </Button>
          <ErrorText error={move.error} />
        </div>
      )}
      {mode === 'priority' && (
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <Field label={t('taskQueue.priority')}>
            <Select value={priority} onChange={(e) => setPriority(e.target.value)} className="w-56">
              {!PRIORITIES.some((p) => String(p.value) === priority) && (
                <option value={priority}>
                  {t(`taskQueue.levels.${priorityLevel(Number(priority))}`)} ({priority})
                </option>
              )}
              {PRIORITIES.map((p) => (
                <option key={p.value} value={p.value}>
                  {t(`taskQueue.levels.${p.key}`)}
                </option>
              ))}
            </Select>
          </Field>
          <Button className="px-3 py-2 text-xs" disabled={prio.isPending} onClick={() => prio.mutate()}>
            {t('patients.save')}
          </Button>
          <ErrorText error={prio.error} />
        </div>
      )}
      {mode === 'cancel' && (
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <div className="min-w-0 flex-1">
            <Field label={t('taskQueue.cancelReason')}>
              <Input
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                maxLength={255}
                placeholder={t('taskQueue.cancelPlaceholder')}
              />
            </Field>
          </div>
          <Button
            variant="danger"
            className="px-3 py-2 text-xs"
            disabled={reason.trim().length < 3 || cancel.isPending}
            onClick={() => cancel.mutate()}
          >
            {t('taskQueue.cancelConfirm')}
          </Button>
          <ErrorText error={cancel.error} />
        </div>
      )}
    </div>
  )
}
