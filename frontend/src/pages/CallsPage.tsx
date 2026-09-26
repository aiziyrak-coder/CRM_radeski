import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import CallAnalysisDialog, { ScoreBadge } from '../components/CallAnalysisDialog'
import PatientName from '../components/PatientName'
import RecordingPlayer from '../components/RecordingPlayer'
import { CallButton } from '../components/Softphone'
import { Badge, Card, ErrorText, Field, Input, Select } from '../components/ui'
import { useAuth } from '../lib/auth-context'
import { canOpen } from '../lib/navigation'
import { formatPhone } from '../lib/patients'
import { clinicDate, clinicTime } from '../lib/scheduling'
import { CALL_STATUSES, formatDuration, getCalls, type CallRecord } from '../lib/telephony'

const TONE: Partial<Record<CallRecord['status'], 'good' | 'bad' | 'info' | 'neutral'>> = {
  answered: 'good',
  missed: 'bad',
  abandoned: 'bad',
  after_hours: 'neutral',
  ringing: 'info',
}

export default function CallsPage() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const [day, setDay] = useState(clinicDate())
  const [direction, setDirection] = useState('')
  const [status, setStatus] = useState('')
  const [who, setWho] = useState<'all' | 'mine'>('all')
  const { data: calls, error } = useQuery({
    queryKey: ['telephony', 'calls', day, direction, status, who],
    queryFn: () => getCalls({ day, direction, status, who }),
    placeholderData: keepPreviousData,
    refetchInterval: 15_000,
  })
  const canListenAll = ['supervisor', 'admin', 'owner'].includes(user?.role ?? '')
  const [analysis, setAnalysis] = useState<string | null>(null)
  const answered = calls?.filter((c) => c.status === 'answered').length ?? 0
  const missed = calls?.filter((c) => ['missed', 'abandoned', 'after_hours'].includes(c.status)).length ?? 0

  return (
    <div className="max-w-6xl space-y-4">
      <h1 className="text-2xl font-semibold">{t('calls.title')}</h1>
      <div className="flex flex-wrap items-end gap-2">
        <Field label={t('calls.day')}>
          <Input
            type="date"
            value={day}
            onChange={(e) => e.target.value && setDay(e.target.value)}
            className="w-44"
          />
        </Field>
        <Field label={t('calls.direction')}>
          <Select value={direction} onChange={(e) => setDirection(e.target.value)} className="w-40">
            <option value="">{t('calls.all')}</option>
            <option value="in">{t('calls.dir.in')}</option>
            <option value="out">{t('calls.dir.out')}</option>
          </Select>
        </Field>
        <Field label={t('calls.status')}>
          <Select value={status} onChange={(e) => setStatus(e.target.value)} className="w-48">
            <option value="">{t('calls.all')}</option>
            {CALL_STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`calls.statuses.${s}`)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t('calls.who')}>
          <Select value={who} onChange={(e) => setWho(e.target.value as 'all' | 'mine')} className="w-40">
            <option value="all">{t('calls.all')}</option>
            <option value="mine">{t('calls.mine')}</option>
          </Select>
        </Field>
      </div>
      {calls && (
        <p className="text-sm text-slate-600">
          {t('calls.summary', { total: calls.length, answered, missed })}
        </p>
      )}
      <ErrorText error={error} />
      <Card>
        {calls && calls.length === 0 && (
          <p className="py-6 text-center text-sm text-slate-500">{t('calls.empty')}</p>
        )}
        {calls && calls.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-left text-sm">
              <thead className="text-xs text-slate-500 uppercase">
                <tr>
                  <th className="pb-2">{t('calls.time')}</th>
                  <th className="pb-2">{t('calls.direction')}</th>
                  <th className="pb-2">{t('calls.caller')}</th>
                  <th className="pb-2">{t('calls.operator')}</th>
                  <th className="pb-2 pl-3 text-right">{t('calls.wait')}</th>
                  <th className="pr-3 pb-2 pl-3 text-right">{t('calls.talk')}</th>
                  <th className="pb-2">{t('calls.status')}</th>
                  <th className="pb-2">AI</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {calls.map((c) => (
                  <tr key={c.id} className="border-t border-slate-100 align-top">
                    <td className="py-2 pr-3 whitespace-nowrap tabular-nums">{clinicTime(c.started_at)}</td>
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
                    <td className="py-2 pr-3 whitespace-nowrap">
                      {c.ai_status === 'ready' && (canListenAll || c.user_id === user?.id) ? (
                        <button
                          onClick={() => setAnalysis(c.id)}
                          className="flex items-center gap-1"
                          title={t('ai.open')}
                        >
                          <ScoreBadge score={c.ai_score} />
                          {c.ai_red_flags && <span className="text-red-600">⚑</span>}
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
                      {c.direction === 'in' && ['missed', 'abandoned', 'after_hours'].includes(c.status) && (
                        <CallButton number={c.phone} />
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
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
