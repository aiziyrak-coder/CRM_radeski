import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Badge, Card } from '../components/ui'
import { api } from '../lib/api'
import { Link } from 'react-router'
import { useAuth } from '../lib/auth-context'
import { getTaskSummary } from '../lib/ops'

type Readiness = Record<'db' | 'redis', string>

function SystemHealth() {
  const { t } = useTranslation()
  const { data, isPending, isError } = useQuery({
    queryKey: ['health', 'ready'],
    queryFn: () => api<Readiness>('/health/ready'),
    refetchInterval: 30_000,
  })
  return (
    <Card title={t('health.title')}>
      {isPending && <p className="text-sm text-slate-500">{t('health.checking')}</p>}
      {isError && <Badge tone="bad">{t('health.down')}</Badge>}
      {data && (
        <ul className="space-y-2 text-sm">
          {(['db', 'redis'] as const).map((k) => (
            <li key={k} className="flex items-center justify-between">
              <span>{t(`health.${k}`)}</span>
              <Badge tone={data[k] === 'ok' ? 'good' : 'bad'}>{data[k]}</Badge>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function CallCenterToday() {
  const { t } = useTranslation()
  const { data } = useQuery({
    queryKey: ['tasks', 'summary'],
    queryFn: getTaskSummary,
    refetchInterval: 30_000,
  })
  if (!data) return null
  const tiles = [
    { label: t('homeOps.tasks'), value: data.total_due, alert: false },
    { label: t('homeOps.overdue'), value: data.overdue, alert: data.overdue > 0 },
    { label: t('homeOps.sla'), value: data.lead_sla_breached, alert: data.lead_sla_breached > 0 },
  ]
  return (
    <Card>
      <div className="grid gap-3 sm:grid-cols-3">
        {tiles.map((x) => (
          <div key={x.label}>
            <div className="text-xs text-slate-500">{x.label}</div>
            <div
              className={`text-3xl font-semibold tabular-nums ${x.alert ? 'text-red-700' : 'text-slate-900'}`}
            >
              {x.value}
            </div>
          </div>
        ))}
      </div>
      <Link to="/tasks" className="mt-3 inline-block text-sm font-medium text-teal-800 hover:underline">
        {t('homeOps.go')} →
      </Link>
    </Card>
  )
}

export default function HomePage() {
  const { t } = useTranslation()
  const { user } = useAuth()
  if (!user) return null
  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">{t('home.welcome', { name: user.full_name })}</h1>
        <p className="mt-1 text-slate-600">{t('home.role', { role: t(`roles.${user.role}`) })}</p>
        <p className="mt-3 text-sm text-slate-500">{t('home.hint')}</p>
      </div>
      {['operator', 'supervisor', 'admin'].includes(user.role) && <CallCenterToday />}
      {(user.role === 'admin' || user.role === 'owner') && <SystemHealth />}
    </div>
  )
}
