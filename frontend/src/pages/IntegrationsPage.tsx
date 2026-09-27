import { useMutation, useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Badge, Button, Card, ErrorText } from '../components/ui'
import {
  getIntegrations,
  testIntegration,
  type Integration,
  type IntegrationKey,
  type IntegrationState,
  type TestResult,
} from '../lib/integrations'
import { formatDateTime } from '../lib/patients'

const GROUPS: { key: string; items: IntegrationKey[] }[] = [
  { key: 'telephony', items: ['telephony', 'trunk'] },
  { key: 'ai', items: ['openai'] },
  { key: 'channels', items: ['telegram', 'instagram', 'sms'] },
  { key: 'site', items: ['site_webhook', 'site_polling', 'catalog_sync'] },
]

const TONE: Record<IntegrationState, 'good' | 'info' | 'bad' | 'neutral'> = {
  ok: 'good',
  warning: 'info',
  error: 'bad',
  off: 'neutral',
}

const DOT: Record<IntegrationState, string> = {
  ok: 'bg-emerald-500',
  warning: 'bg-amber-500',
  error: 'bg-red-500',
  off: 'bg-slate-300',
}

function useValue() {
  const { t } = useTranslation()
  return (v: string | number | boolean | null | undefined): string => {
    if (v === null || v === undefined || v === '') return '—'
    if (typeof v === 'boolean') return v ? t('integrations.yes') : t('integrations.no')
    if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(v)) return formatDateTime(v)
    return String(v)
  }
}

function TestOutcome({ result }: { result: TestResult }) {
  const { t } = useTranslation()
  const value = useValue()
  if (!result.ok)
    return (
      <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">
        {t(`integrations.errors.${result.error}`, { defaultValue: t('integrations.errors.other') })}
        {result.message && <span className="block text-xs text-red-700">{result.message}</span>}
      </p>
    )
  return (
    <div className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-900">
      <div className="font-medium">{t('integrations.testOk')}</div>
      <dl className="mt-1 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-xs">
        {Object.entries(result.result).map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-emerald-800">{t(`integrations.result.${k}`, { defaultValue: k })}</dt>
            <dd className="break-words">{value(v)}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

function IntegrationCard({ item }: { item: Integration }) {
  const { t } = useTranslation()
  const value = useValue()
  const test = useMutation({ mutationFn: () => testIntegration(item.test!) })
  const facts = Object.entries(item.facts)
  return (
    <section className="flex flex-col rounded-lg border border-slate-200 bg-white p-4">
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="flex items-center gap-2 font-semibold">
            <span
              className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${DOT[item.state]}`}
              aria-hidden
            />
            {t(`integrations.items.${item.key}.name`)}
          </h3>
          <p className="mt-0.5 text-xs text-slate-600">{t(`integrations.items.${item.key}.what`)}</p>
        </div>
        <Badge tone={TONE[item.state]}>{t(`integrations.states.${item.state}`)}</Badge>
      </header>

      {facts.length > 0 && (
        <dl className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-sm">
          {facts.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-slate-500">{t(`integrations.facts.${k}`, { defaultValue: k })}</dt>
              <dd className="min-w-0 font-medium break-words tabular-nums">{value(v)}</dd>
            </div>
          ))}
        </dl>
      )}
      {item.state === 'warning' && item.configured && (
        <p className="mt-2 text-xs text-amber-800">{t(`integrations.items.${item.key}.warning`)}</p>
      )}

      {!item.configured && (
        <div className="mt-3 space-y-2 rounded-md bg-slate-50 p-3 text-sm">
          <div className="font-medium">{t('integrations.howTitle')}</div>
          <p className="text-slate-700">{t(`integrations.items.${item.key}.how`)}</p>
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <span className="text-slate-500">{t('integrations.missing')}</span>
            {item.missing.map((m) => (
              <code key={m} className="rounded bg-white px-1.5 py-0.5 ring-1 ring-slate-200">
                {m}
              </code>
            ))}
          </div>
          <p className="text-xs text-slate-500">
            {t('integrations.docs')} <code>{item.docs}</code>
          </p>
        </div>
      )}

      {item.test && (
        <div className="mt-auto space-y-2 pt-3">
          <Button
            variant="secondary"
            className="px-2 py-1 text-xs"
            disabled={test.isPending}
            onClick={() => test.mutate()}
          >
            {test.isPending ? t('integrations.testing') : t('integrations.test')}
          </Button>
          <p className="text-[11px] text-slate-500">{t(`integrations.testWhat.${item.test}`)}</p>
          <ErrorText error={test.error} />
          {test.data && <TestOutcome result={test.data} />}
        </div>
      )}
    </section>
  )
}

export default function IntegrationsPage() {
  const { t } = useTranslation()
  const { data, error, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['system', 'integrations'],
    queryFn: getIntegrations,
    refetchInterval: 60_000,
  })
  const byKey = new Map(data?.map((i) => [i.key, i]))
  const off = data?.filter((i) => !i.configured).length ?? 0
  const problems = data?.filter((i) => i.state === 'error' || i.state === 'warning').length ?? 0

  return (
    <div className="max-w-6xl space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">{t('integrations.title')}</h1>
          <p className="mt-1 max-w-3xl text-sm text-slate-600">{t('integrations.intro')}</p>
        </div>
        <Button variant="secondary" disabled={isFetching} onClick={() => void refetch()}>
          {t('integrations.refresh')}
        </Button>
      </div>
      <ErrorText error={error} />
      {isLoading && <p className="text-sm text-slate-500">{t('app.loading')}</p>}
      {data && (
        <p className="text-sm">
          {problems === 0 && off === 0
            ? t('integrations.allGood')
            : t('integrations.summary', { problems, off, total: data.length })}
        </p>
      )}
      {data &&
        GROUPS.map((g) => (
          <Card key={g.key} title={t(`integrations.groups.${g.key}`)}>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {g.items.map((k) => {
                const item = byKey.get(k)
                return item ? <IntegrationCard key={k} item={item} /> : null
              })}
            </div>
          </Card>
        ))}
    </div>
  )
}
