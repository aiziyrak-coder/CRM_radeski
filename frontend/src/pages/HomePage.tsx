import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { lazy, Suspense, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { Badge, Button, Card, ErrorText } from '../components/ui'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth-context'
import { addShiftNote, getShiftNotes, getTaskSummary, getTasks } from '../lib/ops'
import { formatDateTime } from '../lib/patients'
import { clinicTime } from '../lib/scheduling'
import { getSetup, getTodayVisits, useSystemStatus, type SetupItem, type SetupStatus } from '../lib/system'

// the dashboard brings the chart library: only the owner and the supervisor download it
const KpiDashboard = lazy(() => import('../components/KpiDashboard'))

type Readiness = Record<'db' | 'redis', string>

function Tile({ label, value, alert, to }: { label: string; value: number; alert?: boolean; to?: string }) {
  const body = (
    <>
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`text-3xl font-semibold ${alert ? 'text-red-700' : 'text-slate-900'}`}>{value}</div>
    </>
  )
  return to ? (
    <Link to={to} className="block rounded-md p-1 hover:bg-slate-50">
      {body}
    </Link>
  ) : (
    <div className="p-1">{body}</div>
  )
}

function CallCenterToday({ showQa }: { showQa: boolean }) {
  const { t } = useTranslation()
  const { data, error } = useQuery({
    queryKey: ['tasks', 'summary'],
    queryFn: getTaskSummary,
    refetchInterval: 30_000,
  })
  const { data: status } = useSystemStatus()
  if (error) return <ErrorText error={error} />
  if (!data) return null
  return (
    <Card>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Tile label={t('homeOps.tasks')} value={data.total_due} to="/tasks" />
        <Tile label={t('homeOps.overdue')} value={data.overdue} alert={data.overdue > 0} to="/tasks" />
        <Tile
          label={t('homeOps.sla')}
          value={data.lead_sla_breached}
          alert={data.lead_sla_breached > 0}
          to="/leads"
        />
        {status && (
          <>
            <Tile
              label={t('homeOps.missed')}
              value={status.today.missed_calls}
              alert={status.today.missed_calls > 0}
              to="/calls"
            />
            <Tile
              label={t('homeOps.chats')}
              value={status.today.unread_chats}
              alert={status.today.unread_chats > 0}
              to="/inbox"
            />
            {showQa && status.qa && (
              <Tile
                label={t('homeOps.redFlags')}
                value={status.qa.red_flags_open}
                alert={status.qa.red_flags_open > 0}
                to="/qa"
              />
            )}
          </>
        )}
      </div>
    </Card>
  )
}

/** Operator: the first five tasks of the queue, as the task page orders them. */
function NextTasks() {
  const { t } = useTranslation()
  const { data, error } = useQuery({
    queryKey: ['tasks', 'today', ''],
    queryFn: () => getTasks('today'),
    refetchInterval: 30_000,
  })
  const next = data?.slice(0, 5) ?? []
  return (
    <Card
      title={t('dash.nextTasks')}
      actions={
        <Link to="/tasks" className="text-sm font-medium text-teal-800 hover:underline">
          {t('homeOps.go')} →
        </Link>
      }
    >
      <ErrorText error={error} />
      {data && next.length === 0 && <p className="text-sm text-slate-500">{t('dash.noTasks')}</p>}
      <ul className="divide-y divide-slate-100">
        {next.map((task) => (
          <li key={task.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
            <div className="min-w-0">
              <div className="font-medium">{t(`taskTypes.${task.type}`)}</div>
              <div className="truncate text-xs text-slate-600">
                {task.patient_name ?? task.patient_phone ?? t('calls.lead')}
                {task.appointment_at && ` · ${formatDateTime(task.appointment_at)}`}
              </div>
            </div>
            <span
              className={`text-xs tabular-nums ${task.overdue ? 'font-medium text-red-700' : 'text-slate-500'}`}
            >
              {task.overdue
                ? t('dash.overdueSince', { time: clinicTime(task.due_at) })
                : clinicTime(task.due_at)}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  )
}

/** Operator: the last handover note and a place to leave one (TZ 4.5). */
function ShiftNote() {
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
  const last = notes[0]
  return (
    <Card title={t('tasks.shift')}>
      {last ? (
        <div className="mb-3 rounded-md bg-amber-50 p-3 text-sm">
          <div className="text-xs text-amber-900">
            {last.user_name} · {formatDateTime(last.created_at)}
          </div>
          <div className="whitespace-pre-line text-slate-900">{last.text}</div>
        </div>
      ) : (
        <p className="mb-3 text-sm text-slate-500">{t('tasks.shiftEmpty')}</p>
      )}
      <textarea
        className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
        rows={2}
        aria-label={t('tasks.shiftPlaceholder')}
        placeholder={t('tasks.shiftPlaceholder')}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <ErrorText error={add.error} />
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

/** Registrar and doctor: today's visits at a glance. */
function TodayVisits({ role }: { role: 'registrar' | 'doctor' }) {
  const { t } = useTranslation()
  const { data, error } = useQuery({
    queryKey: ['system', 'today'],
    queryFn: getTodayVisits,
    refetchInterval: 60_000,
  })
  const link = role === 'doctor' ? '/my-day' : '/schedule?mode=today'
  return (
    <Card
      title={t(role === 'doctor' ? 'dash.today.doctorTitle' : 'dash.today.registrarTitle')}
      actions={
        <Link to={link} className="text-sm font-medium text-teal-800 hover:underline">
          {t(role === 'doctor' ? 'nav.myDay' : 'dash.today.openSchedule')} →
        </Link>
      }
    >
      <ErrorText error={error} />
      {data && role === 'doctor' && !data.linked && (
        <p className="mb-3 rounded-md bg-amber-50 p-2 text-sm text-amber-900">{t('dash.today.notLinked')}</p>
      )}
      {data && role === 'registrar' && data.scope === 'all' && (
        <p className="mb-3 text-xs text-slate-500">{t('dash.today.allBranches')}</p>
      )}
      {data && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Tile label={t('dash.today.total')} value={data.counts.total} to={link} />
          <Tile label={t('dash.today.expected')} value={data.counts.expected} to={link} />
          <Tile label={t('dash.today.came')} value={data.counts.came} to={link} />
          <Tile
            label={t('dash.today.noShow')}
            value={data.counts.no_show}
            alert={data.counts.no_show > 0}
            to={link}
          />
        </div>
      )}
      {data?.next_at && (
        <p className="mt-3 text-sm text-slate-600">
          {t('dash.today.next', { time: clinicTime(data.next_at) })}
        </p>
      )}
    </Card>
  )
}

const SETUP_TONE: Record<SetupStatus, 'good' | 'bad' | 'info' | 'neutral'> = {
  ok: 'good',
  partial: 'info',
  todo: 'bad',
  off: 'neutral',
}

function setupDetail(item: SetupItem, t: (k: string, o?: Record<string, unknown>) => string): string {
  const n = (k: string) => (typeof item[k] === 'number' ? (item[k] as number) : 0)
  switch (item.key) {
    case 'catalog':
      return t('setup.detail.catalog', {
        services: n('services'),
        doctors: n('doctors'),
        at: item.last_sync_at ? formatDateTime(String(item.last_sync_at)) : '—',
      })
    case 'resources':
      return t('setup.detail.resources', {
        rooms: n('rooms'),
        devices: n('devices'),
        done: n('done'),
        total: n('total'),
      })
    case 'users': {
      const roles = (item.roles ?? {}) as Record<string, number>
      return Object.entries(roles)
        .map(([r, c]) => `${t(`roles.${r}`)}: ${c}`)
        .join(' · ')
    }
    case 'telephony':
      return item.last_call_at
        ? t('health.lastCall', { at: formatDateTime(String(item.last_call_at)) })
        : t(item.trunk ? 'setup.detail.noCalls' : 'setup.detail.noTrunk')
    case 'sms':
      return item.provider ? String(item.provider) : t('setup.detail.env')
    case 'legacy_import':
      return t('setup.detail.legacy', { legacy: n('legacy'), cold: n('cold'), total: n('patients') })
    case 'diagnoses':
      return t('setup.detail.diagnoses', { waiting: n('waiting'), approved: n('approved') })
    case 'ai':
    case 'telegram':
    case 'instagram':
      return item.status === 'off' ? t('setup.detail.env') : ''
    default:
      return item.total !== undefined
        ? t('setup.detail.progress', { done: n('done'), total: n('total') })
        : ''
  }
}

/** Admin: "Tizimni sozlash" — what is still missing, each row linking to where it's fixed. */
function SetupChecklist() {
  const { t } = useTranslation()
  const { data, error, isPending } = useQuery({ queryKey: ['system', 'setup'], queryFn: getSetup })
  return (
    <Card
      title={t('setup.title')}
      actions={
        data && (
          <span className="text-sm text-slate-600">
            {t('setup.progress', { done: data.done, total: data.total })}
          </span>
        )
      }
    >
      <ErrorText error={error} />
      {isPending && <p className="text-sm text-slate-500">{t('app.loading')}</p>}
      {data && (
        <>
          <div className="mb-3 h-1.5 rounded bg-slate-100" aria-hidden>
            <div
              className="h-1.5 rounded bg-teal-600"
              style={{ width: `${(100 * data.done) / data.total}%` }}
            />
          </div>
          <ul className="divide-y divide-slate-100">
            {data.items.map((item) => {
              const detail = setupDetail(item, t)
              return (
                <li key={item.key} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5 text-sm">
                  <span className="w-5 shrink-0 text-center" aria-hidden>
                    {item.status === 'ok' ? '✓' : item.status === 'off' ? '○' : '!'}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="font-medium">{t(`setup.items.${item.key}`)}</div>
                    {detail && <div className="text-xs text-slate-600">{detail}</div>}
                  </div>
                  <Badge tone={SETUP_TONE[item.status]}>{t(`setup.status.${item.status}`)}</Badge>
                  {item.link && item.status !== 'ok' && (
                    <Link to={item.link} className="text-xs font-medium text-teal-800 hover:underline">
                      {t('setup.fix')} →
                    </Link>
                  )}
                </li>
              )
            })}
          </ul>
        </>
      )}
    </Card>
  )
}

function Row({ label, ok, detail }: { label: string; ok: boolean; detail?: string }) {
  const { t } = useTranslation()
  return (
    <li className="flex items-center justify-between gap-2">
      <span>{label}</span>
      <span className="flex items-center gap-2">
        {detail && <span className="text-xs text-slate-500">{detail}</span>}
        <Badge tone={ok ? 'good' : 'neutral'}>{ok ? t('health.on') : t('health.off')}</Badge>
      </span>
    </li>
  )
}

function SystemHealth() {
  const { t } = useTranslation()
  const { data, isPending, isError } = useQuery({
    queryKey: ['health', 'ready'],
    queryFn: () => api<Readiness>('/health/ready'),
    refetchInterval: 30_000,
  })
  const { data: status } = useSystemStatus()
  const i = status?.integrations
  const a = status?.attention
  const problems = a
    ? (
        [
          ['recordings_failed', a.recordings_failed],
          ['analyses_failed', a.analyses_failed],
          ['messages_failed', a.messages_failed],
        ] as const
      ).filter(([, n]) => n > 0)
    : []
  return (
    <Card title={t('health.title')}>
      {isPending && <p className="text-sm text-slate-500">{t('health.checking')}</p>}
      {isError && <Badge tone="bad">{t('health.down')}</Badge>}
      <ul className="space-y-2 text-sm">
        {data &&
          (['db', 'redis'] as const).map((k) => (
            <li key={k} className="flex items-center justify-between">
              <span>{t(`health.${k}`)}</span>
              <Badge tone={data[k] === 'ok' ? 'good' : 'bad'}>{data[k]}</Badge>
            </li>
          ))}
        {i && (
          <>
            <Row
              label={t('health.telephony')}
              ok={i.telephony}
              detail={
                i.last_call_at ? t('health.lastCall', { at: formatDateTime(i.last_call_at) }) : undefined
              }
            />
            <Row label={t('health.trunk')} ok={i.trunk} />
            <Row
              label={t('health.ai')}
              ok={i.ai}
              detail={
                i.ai && i.ai_spent_today_usd != null && i.ai_daily_budget_usd != null
                  ? t(i.ai_daily_budget_usd > 0 ? 'health.aiSpend' : 'health.aiSpendNoLimit', {
                      spent: i.ai_spent_today_usd.toFixed(3),
                      budget: i.ai_daily_budget_usd,
                    })
                  : undefined
              }
            />
            <Row label="Telegram" ok={i.telegram} />
            <Row label="Instagram" ok={i.instagram} />
            <Row label="SMS" ok={Boolean(i.sms)} detail={i.sms ?? undefined} />
          </>
        )}
      </ul>
      {problems.length > 0 && (
        <div className="mt-3 rounded-md bg-amber-50 p-2 text-sm text-amber-900">
          {problems.map(([k, n]) => (
            <div key={k}>{t(`health.problems.${k}`, { count: n })}</div>
          ))}
        </div>
      )}
      {a && a.messages_queued > 0 && (
        <p className="mt-2 text-xs text-slate-500">{t('health.queued', { count: a.messages_queued })}</p>
      )}
    </Card>
  )
}

export default function HomePage() {
  const { t } = useTranslation()
  const { user } = useAuth()
  if (!user) return null
  const role = user.role
  return (
    <div className="max-w-6xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">{t('home.welcome', { name: user.full_name })}</h1>
        <p className="mt-1 text-slate-600">{t('home.role', { role: t(`roles.${role}`) })}</p>
      </div>
      {(role === 'operator' || role === 'supervisor') && <CallCenterToday showQa={role === 'supervisor'} />}
      {role === 'operator' && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <NextTasks />
          <ShiftNote />
        </div>
      )}
      {(role === 'owner' || role === 'supervisor') && (
        <Suspense fallback={<p className="text-sm text-slate-500">{t('app.loading')}</p>}>
          <KpiDashboard />
        </Suspense>
      )}
      {(role === 'registrar' || role === 'doctor') && <TodayVisits role={role} />}
      {role === 'admin' && <SetupChecklist />}
      {(role === 'admin' || role === 'owner' || role === 'supervisor') && <SystemHealth />}
    </div>
  )
}
