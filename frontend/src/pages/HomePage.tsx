import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { Badge, Card } from '../components/ui'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth-context'
import { getTaskSummary } from '../lib/ops'
import { formatDateTime } from '../lib/patients'

type Readiness = Record<'db' | 'redis', string>

type SystemStatus = {
  today: { missed_calls: number; unread_chats: number }
  qa?: { red_flags_open: number }
  integrations?: {
    telephony: boolean
    trunk: boolean
    last_call_at: string | null
    ai: boolean
    telegram: boolean
    instagram: boolean
    sms: string | null
  }
  attention?: {
    recordings_failed: number
    analyses_failed: number
    messages_failed: number
    messages_queued: number
  }
}

const useSystemStatus = () =>
  useQuery({
    queryKey: ['system', 'status'],
    queryFn: () => api<SystemStatus>('/system/status'),
    refetchInterval: 60_000,
  })

function Tile({ label, value, alert, to }: { label: string; value: number; alert?: boolean; to?: string }) {
  const body = (
    <>
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`text-3xl font-semibold tabular-nums ${alert ? 'text-red-700' : 'text-slate-900'}`}>
        {value}
      </div>
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
  const { data } = useQuery({
    queryKey: ['tasks', 'summary'],
    queryFn: getTaskSummary,
    refetchInterval: 30_000,
  })
  const { data: status } = useSystemStatus()
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
            <Row label={t('health.ai')} ok={i.ai} />
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
  const callCenter = ['operator', 'supervisor', 'admin'].includes(user.role)
  return (
    <div className="max-w-5xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">{t('home.welcome', { name: user.full_name })}</h1>
        <p className="mt-1 text-slate-600">{t('home.role', { role: t(`roles.${user.role}`) })}</p>
      </div>
      {callCenter && <CallCenterToday showQa={user.role !== 'operator'} />}
      {user.role === 'doctor' && (
        <Link to="/my-day" className="inline-block text-sm font-medium text-teal-800 hover:underline">
          {t('nav.myDay')} →
        </Link>
      )}
      {(user.role === 'admin' || user.role === 'owner' || user.role === 'supervisor') && <SystemHealth />}
    </div>
  )
}
