import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router'
import CallAnalysisDialog, { ScoreBadge } from '../components/CallAnalysisDialog'
import PatientName from '../components/PatientName'
import RecordingPlayer from '../components/RecordingPlayer'
import { CallButton } from '../components/Softphone'
import { Badge, Button, Card, ErrorText, Field, Input, Select } from '../components/ui'
import { useAuth } from '../lib/auth-context'
import { canOpen } from '../lib/navigation'
import { formatDate, formatPhone } from '../lib/patients'
import { getReportOperators, useFormatKpi } from '../lib/reports'
import { addDays, clinicDate, clinicTime } from '../lib/scheduling'
import {
  CALL_LOG_PAGE,
  CALL_STATUSES,
  formatDuration,
  getCallLog,
  type CallLogItem,
  type CallRecord,
} from '../lib/telephony'

const TONE: Partial<Record<CallRecord['status'], 'good' | 'bad' | 'info' | 'neutral'>> = {
  answered: 'good',
  missed: 'bad',
  abandoned: 'bad',
  after_hours: 'neutral',
  ringing: 'info',
}
const UNANSWERED = ['missed', 'abandoned', 'after_hours']
const MANAGERS = ['supervisor', 'admin', 'owner']
type Range = 'today' | 'yesterday' | '7d' | 'custom'

function Counter({ label, value, tone }: { label: string; value: string | number; tone?: 'bad' }) {
  return (
    <div className="rounded-md border border-slate-200 bg-white px-3 py-2">
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`text-xl font-semibold ${tone === 'bad' ? 'text-red-700' : 'text-slate-900'}`}>
        {value}
      </div>
    </div>
  )
}

/** minutes between two timestamps, for "called back after N min" */
const minutesBetween = (a: string, b: string) =>
  Math.max(0, Math.round((Date.parse(b) - Date.parse(a)) / 60_000))

function Result({ c }: { c: CallLogItem }) {
  const { t } = useTranslation()
  const fmt = useFormatKpi()
  if (c.task_outcome) {
    return (
      <div>
        <Badge tone="good">{t(`outcomes.${c.task_outcome}`)}</Badge>
        {c.task_outcome_reason && (
          <div className="text-xs text-slate-600">
            {t(`reasons.${c.task_outcome_reason}`, { defaultValue: c.task_outcome_reason })}
          </div>
        )}
        {c.task_type && <div className="text-xs text-slate-500">{t(`taskTypes.${c.task_type}`)}</div>}
      </div>
    )
  }
  if (c.ai_outcome) {
    return (
      <div title={t('calls.aiSuggestion')}>
        <Badge tone="info">AI: {t(`outcomes.${c.ai_outcome}`)}</Badge>
      </div>
    )
  }
  if (c.direction === 'in' && UNANSWERED.includes(c.status) && c.phone) {
    return c.called_back_at ? (
      <span className="text-xs text-emerald-700">
        ✓{' '}
        {t('calls.calledBack', {
          after: fmt('missed_callback_avg_min', minutesBetween(c.started_at, c.called_back_at)),
        })}
      </span>
    ) : (
      <span className="text-xs font-medium text-red-700">! {t('calls.notCalledBack')}</span>
    )
  }
  return <span className="text-slate-400">—</span>
}

export default function CallsPage() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const [params] = useSearchParams()
  const today = clinicDate()
  const [range, setRange] = useState<Range>('today')
  const [from, setFromRaw] = useState(today)
  const [to, setToRaw] = useState(today)
  const [direction, setDirectionRaw] = useState('')
  const [status, setStatusRaw] = useState(params.get('status') ?? '')
  const [who, setWhoRaw] = useState<'all' | 'mine'>('all')
  const [userId, setUserIdRaw] = useState('')
  const [search, setSearch] = useState('')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(0)
  const isManager = MANAGERS.includes(user?.role ?? '')
  const canListenAll = isManager
  const [analysis, setAnalysis] = useState<string | null>(null)

  useEffect(() => {
    const id = setTimeout(() => {
      setQ(search.trim())
      setPage(0)
    }, 350)
    return () => clearTimeout(id)
  }, [search])
  // any filter change starts from the first page
  const filter =
    <T,>(set: (v: T) => void) =>
    (v: T) => {
      set(v)
      setPage(0)
    }
  const setFrom = filter(setFromRaw)
  const setTo = filter(setToRaw)
  const setDirection = filter(setDirectionRaw)
  const setStatus = filter(setStatusRaw)
  const setWho = filter(setWhoRaw)
  const setUserId = filter(setUserIdRaw)

  const pickRange = (r: Range) => {
    setRange(r)
    if (r === 'today') [setFrom, setTo].forEach((f) => f(today))
    if (r === 'yesterday') [setFrom, setTo].forEach((f) => f(addDays(today, -1)))
    if (r === '7d') {
      setFrom(addDays(today, -6))
      setTo(today)
    }
  }

  const { data: operators = [] } = useQuery({
    queryKey: ['reports', 'operators'],
    queryFn: getReportOperators,
    enabled: isManager,
    staleTime: 300_000,
  })
  const { data, error, isFetching } = useQuery({
    queryKey: ['telephony', 'call-log', from, to, direction, status, who, userId, q, page],
    queryFn: () =>
      getCallLog({
        from,
        to,
        direction,
        status,
        who,
        user_id: who === 'all' ? userId : undefined,
        q,
        offset: page * CALL_LOG_PAGE,
      }),
    placeholderData: keepPreviousData,
    refetchInterval: 15_000,
  })
  const s = data?.summary
  const pages = data ? Math.max(1, Math.ceil(data.total / CALL_LOG_PAGE)) : 1
  const multiDay = from !== to

  return (
    <div className="max-w-6xl space-y-4">
      <h1 className="text-2xl font-semibold">{t('calls.title')}</h1>
      <div className="flex flex-wrap gap-1" role="radiogroup" aria-label={t('calls.period')}>
        {(['today', 'yesterday', '7d', 'custom'] as const).map((r) => (
          <Button
            key={r}
            role="radio"
            aria-checked={range === r}
            variant={range === r ? 'primary' : 'secondary'}
            className="px-3 py-1.5 text-xs"
            onClick={() => pickRange(r)}
          >
            {t(`calls.ranges.${r}`)}
          </Button>
        ))}
      </div>
      <div className="grid grid-cols-2 items-end gap-2 sm:flex sm:flex-wrap">
        {range === 'custom' && (
          <>
            <Field label={t('reports.from')}>
              <Input
                type="date"
                value={from}
                max={to}
                onChange={(e) => e.target.value && setFrom(e.target.value)}
                className="w-full sm:w-40"
              />
            </Field>
            <Field label={t('reports.to')}>
              <Input
                type="date"
                value={to}
                min={from}
                max={today}
                onChange={(e) => e.target.value && setTo(e.target.value)}
                className="w-full sm:w-40"
              />
            </Field>
          </>
        )}
        <div className="col-span-2 sm:w-64">
          <Field label={t('calls.search')}>
            <Input
              type="search"
              value={search}
              placeholder={t('calls.searchPlaceholder')}
              onChange={(e) => setSearch(e.target.value)}
            />
          </Field>
        </div>
        <Field label={t('calls.direction')}>
          <Select value={direction} onChange={(e) => setDirection(e.target.value)} className="w-full sm:w-36">
            <option value="">{t('calls.all')}</option>
            <option value="in">{t('calls.dir.in')}</option>
            <option value="out">{t('calls.dir.out')}</option>
          </Select>
        </Field>
        <Field label={t('calls.status')}>
          <Select value={status} onChange={(e) => setStatus(e.target.value)} className="w-full sm:w-48">
            <option value="">{t('calls.all')}</option>
            <option value="unanswered">{t('calls.unansweredAll')}</option>
            {CALL_STATUSES.map((st) => (
              <option key={st} value={st}>
                {t(`calls.statuses.${st}`)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t('calls.who')}>
          <Select
            value={who}
            onChange={(e) => setWho(e.target.value as 'all' | 'mine')}
            className="w-full sm:w-32"
          >
            <option value="all">{t('calls.all')}</option>
            <option value="mine">{t('calls.mine')}</option>
          </Select>
        </Field>
        {isManager && who === 'all' && operators.length > 0 && (
          <Field label={t('calls.operator')}>
            <Select value={userId} onChange={(e) => setUserId(e.target.value)} className="w-full sm:w-48">
              <option value="">{t('reports.allOperators')}</option>
              {operators.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.full_name}
                </option>
              ))}
            </Select>
          </Field>
        )}
      </div>

      {s && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
          <Counter label={t('calls.sum.total')} value={s.total} />
          <Counter label={t('calls.sum.inbound')} value={`${s.inbound} / ${s.answered}`} />
          <Counter label={t('calls.sum.missed')} value={s.missed} tone={s.missed ? 'bad' : undefined} />
          <Counter
            label={t('calls.sum.notCalledBack')}
            value={s.missed_not_called_back}
            tone={s.missed_not_called_back ? 'bad' : undefined}
          />
          <Counter label={t('calls.sum.outbound')} value={`${s.outbound} / ${s.outbound_answered}`} />
          <Counter
            label={t('calls.sum.waitTalk')}
            value={`${s.avg_wait_sec === null ? '—' : t('reports.seconds', { n: s.avg_wait_sec })} · ${t('reports.minutes', { n: s.talk_minutes })}`}
          />
        </div>
      )}
      <ErrorText error={error} />
      <Card>
        {!data && !error && <p className="py-6 text-center text-sm text-slate-500">{t('app.loading')}</p>}
        {data && data.items.length === 0 && (
          <div className="py-6 text-center text-sm text-slate-500">
            <p>
              {q || direction || status || userId || who === 'mine'
                ? t('calls.emptyFiltered')
                : t('calls.empty')}
            </p>
            {s && s.total === 0 && !q && <p className="mt-1 text-xs">{t('calls.emptyHint')}</p>}
          </div>
        )}
        {data && data.items.length > 0 && (
          <div className={`overflow-x-auto ${isFetching ? 'opacity-70' : ''}`}>
            <table className="w-full min-w-[960px] text-left text-sm">
              <thead className="text-xs text-slate-500 uppercase">
                <tr>
                  <th className="pb-2">{t('calls.time')}</th>
                  <th className="pb-2">{t('calls.direction')}</th>
                  <th className="pb-2">{t('calls.caller')}</th>
                  <th className="pb-2">{t('calls.operator')}</th>
                  <th className="pb-2 pl-3 text-right">{t('calls.wait')}</th>
                  <th className="pr-3 pb-2 pl-3 text-right">{t('calls.talk')}</th>
                  <th className="pb-2">{t('calls.status')}</th>
                  <th className="pb-2">{t('calls.result')}</th>
                  <th className="pb-2">AI</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.items.map((c) => (
                  <tr key={c.id} className="border-t border-slate-100 align-top">
                    <td className="py-2 pr-3 whitespace-nowrap tabular-nums">
                      {clinicTime(c.started_at)}
                      {multiDay && <div className="text-xs text-slate-500">{formatDate(c.started_at)}</div>}
                    </td>
                    <td className="py-2 pr-3">{t(`calls.dir.${c.direction}`)}</td>
                    <td className="py-2 pr-3">
                      {c.patient_id ? (
                        canOpen(user?.role, '/patients') ? (
                          <Link
                            to={`/patients/${c.patient_id}`}
                            className="font-medium text-teal-800 hover:underline"
                          >
                            <PatientName name={c.patient_name ?? '—'} />
                          </Link>
                        ) : (
                          <span className="font-medium">
                            <PatientName name={c.patient_name ?? '—'} />
                          </span>
                        )
                      ) : c.lead_id ? (
                        canOpen(user?.role, '/leads') ? (
                          <Link to="/leads" className="text-teal-800 hover:underline">
                            {t('calls.lead')}
                          </Link>
                        ) : (
                          <span>{t('calls.lead')}</span>
                        )
                      ) : null}
                      <div className="text-xs whitespace-nowrap text-slate-600 tabular-nums">
                        {c.phone ? formatPhone(c.phone) : (c.caller_raw ?? '—')}
                      </div>
                    </td>
                    <td className="py-2 pr-3 text-slate-700">{c.user_name ?? c.extension ?? '—'}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">{formatDuration(c.wait_seconds)}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">{formatDuration(c.talk_seconds)}</td>
                    <td className="py-2 pr-3">
                      <Badge tone={TONE[c.status] ?? 'neutral'}>{t(`calls.statuses.${c.status}`)}</Badge>
                      {c.callback_requested && (
                        <div className="text-xs text-amber-700">{t('calls.callbackRequested')}</div>
                      )}
                    </td>
                    <td className="py-2 pr-3">
                      <Result c={c} />
                    </td>
                    <td className="py-2 pr-3 whitespace-nowrap">
                      {c.ai_status === 'ready' && (canListenAll || c.user_id === user?.id) ? (
                        <button
                          onClick={() => setAnalysis(c.id)}
                          className="flex items-center gap-1"
                          title={t('ai.open')}
                        >
                          <ScoreBadge score={c.ai_score} />
                          {c.ai_red_flags && (
                            <span className="text-red-600" aria-label={t('ai.redFlags')}>
                              ⚑
                            </span>
                          )}
                        </button>
                      ) : c.ai_status && c.ai_status !== 'ready' ? (
                        <span className="text-xs text-slate-500">{t(`ai.status.${c.ai_status}`)}</span>
                      ) : null}
                    </td>
                    <td className="py-2 text-right whitespace-nowrap">
                      {c.recording_status === 'ready' && (canListenAll || c.user_id === user?.id) && (
                        <RecordingPlayer callId={c.id} />
                      )}
                      {c.recording_status === 'pending' && (
                        <span className="text-xs text-slate-500">{t('calls.processing')}</span>
                      )}
                      {c.direction === 'in' && UNANSWERED.includes(c.status) && !c.called_back_at && (
                        <CallButton number={c.phone} />
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && data.total > CALL_LOG_PAGE && (
          <div className="mt-3 flex items-center justify-between gap-2 text-sm">
            <span className="text-slate-600">
              {t('calls.pageInfo', {
                from: page * CALL_LOG_PAGE + 1,
                to: Math.min(data.total, (page + 1) * CALL_LOG_PAGE),
                total: data.total,
              })}
            </span>
            <div className="flex gap-2">
              <Button variant="secondary" disabled={page === 0} onClick={() => setPage(page - 1)}>
                ← {t('app.prev')}
              </Button>
              <Button variant="secondary" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>
                {t('app.next')} →
              </Button>
            </div>
          </div>
        )}
      </Card>
      {analysis && (
        <CallAnalysisDialog
          callId={analysis}
          onClose={() => setAnalysis(null)}
          canAck={user?.role === 'supervisor' || user?.role === 'admin'}
        />
      )}
    </div>
  )
}
