import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, Card, ErrorText, Field, Input, Select } from '../components/ui'
import { api, type User } from '../lib/api'
import { useAuth } from '../lib/auth-context'
import { downloadKpi, getDaily, getKpi, type CallStats } from '../lib/ops'
import { addDays, clinicDate } from '../lib/scheduling'

function Stat({ label, value, hint }: { label: string; value: string | number | null; hint?: string }) {
  return (
    <div className="rounded-md border border-slate-200 bg-white px-4 py-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value ?? '—'}</div>
      {hint && <div className="text-xs text-slate-400">{hint}</div>}
    </div>
  )
}

const pct = (v: number | null) => (v === null ? null : `${v}%`)

function CallStatsRow({ data }: { data: CallStats }) {
  const { t } = useTranslation()
  if (data.inbound_calls === null) {
    return <p className="text-sm text-slate-500">{t('reports.telephonyNote')}</p>
  }
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Stat
        label={t('reports.inbound')}
        value={data.inbound_calls}
        hint={t('reports.inboundHint', { answered: data.inbound_answered, missed: data.inbound_missed })}
      />
      <Stat
        label={t('reports.answerRate')}
        value={pct(data.inbound_answer_rate)}
        hint={t('reports.callbacks', { count: data.callbacks_requested ?? 0 })}
      />
      <Stat
        label={t('reports.avgWait')}
        value={data.avg_wait_sec === null ? null : t('reports.seconds', { n: data.avg_wait_sec })}
      />
      <Stat
        label={t('reports.outboundCalls')}
        value={data.outbound_calls}
        hint={t('reports.talk', { n: data.talk_minutes })}
      />
    </div>
  )
}

function Daily() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const [date, setDate] = useState(clinicDate())
  const [userId, setUserId] = useState('')
  const isManager = user?.role !== 'operator'
  const { data: users = [] } = useQuery({
    queryKey: ['users'],
    queryFn: () => api<User[]>('/users'),
    enabled: user?.role === 'admin',
  })
  const { data, error } = useQuery({
    queryKey: ['reports', 'daily', date, userId],
    queryFn: () => getDaily(date, userId || undefined),
  })
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-2">
        <Field label={t('reports.daily')}>
          <Input
            type="date"
            value={date}
            onChange={(e) => e.target.value && setDate(e.target.value)}
            className="w-44"
          />
        </Field>
        {isManager && users.length > 0 && (
          <Field label={t('reports.operator')}>
            <Select value={userId} onChange={(e) => setUserId(e.target.value)} className="w-64">
              <option value="">{t('reports.allOperators')}</option>
              {users
                .filter((u) => u.role === 'operator' || u.role === 'supervisor')
                .map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.full_name}
                  </option>
                ))}
            </Select>
          </Field>
        )}
      </div>
      <ErrorText error={error} />
      {data && (
        <>
          <CallStatsRow data={data} />
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label={t('reports.outbound')} value={data.outbound_attempts} />
            <Stat label={t('reports.dialRate')} value={pct(data.dial_rate)} />
            <Stat label={t('reports.newLeads')} value={data.new_leads} />
            <Stat label={t('reports.booked')} value={data.booked} />
            <Stat label={t('reports.repeat')} value={data.repeat_bookings} />
            <Stat label={t('reports.notBooked')} value={data.not_booked} />
            <Stat label={t('reports.noShows')} value={data.no_shows} />
            <Stat label={t('reports.cancellations')} value={data.cancellations} />
            <Stat label={t('reports.reschedules')} value={data.reschedules} />
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <Card title={t('reports.reasons')}>
              <ul className="space-y-1 text-sm">
                {Object.entries(data.reasons).length === 0 && <li className="text-slate-500">—</li>}
                {Object.entries(data.reasons).map(([k, n]) => (
                  <li key={k} className="flex justify-between">
                    <span>{t(`reasons.${k}`, { defaultValue: k })}</span>
                    <span className="tabular-nums">{n}</span>
                  </li>
                ))}
              </ul>
            </Card>
            <Card title={t('reports.campaign')}>
              <ul className="space-y-1 text-sm">
                {Object.entries(data.campaign_outcomes).length === 0 && <li className="text-slate-500">—</li>}
                {Object.entries(data.campaign_outcomes).map(([k, n]) => (
                  <li key={k} className="flex justify-between">
                    <span>{t(`outcomes.${k}`, { defaultValue: k })}</span>
                    <span className="tabular-nums">{n}</span>
                  </li>
                ))}
              </ul>
            </Card>
          </div>
        </>
      )}
    </div>
  )
}

function KpiView() {
  const { t } = useTranslation()
  const [from, setFrom] = useState(addDays(clinicDate(), -30))
  const [to, setTo] = useState(clinicDate())
  const { data, error } = useQuery({
    queryKey: ['reports', 'kpi', from, to],
    queryFn: () => getKpi(from, to),
  })
  const download = useMutation({ mutationFn: () => downloadKpi(from, to) })
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-2">
        <Field label={t('reports.from')}>
          <Input
            type="date"
            value={from}
            onChange={(e) => e.target.value && setFrom(e.target.value)}
            className="w-44"
          />
        </Field>
        <Field label={t('reports.to')}>
          <Input
            type="date"
            value={to}
            onChange={(e) => e.target.value && setTo(e.target.value)}
            className="w-44"
          />
        </Field>
        <Button variant="secondary" disabled={download.isPending} onClick={() => download.mutate()}>
          {t('reports.download')}
        </Button>
      </div>
      <ErrorText error={error ?? download.error} />
      {data && (
        <>
          <CallStatsRow data={data} />
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label={t('reports.leadsTotal')} value={data.leads_total} />
            <Stat label={t('reports.leadToBooking')} value={pct(data.lead_to_booking)} />
            <Stat
              label={t('reports.firstResponse')}
              value={
                data.first_response_median_min === null
                  ? null
                  : t('reports.minutes', { n: data.first_response_median_min })
              }
            />
            <Stat label={t('reports.slaBreached')} value={data.sla_breached} />
            <Stat label={t('reports.attempts')} value={data.attempts} />
            <Stat label={t('reports.dialRate')} value={pct(data.dial_rate)} />
            <Stat label={t('reports.confirmation')} value={pct(data.confirmation_rate)} />
            <Stat label={t('reports.bookingToVisit')} value={pct(data.booking_to_visit)} />
            <Stat label={t('reports.noShowRate')} value={pct(data.no_show_rate)} />
            <Stat label={t('reports.repeatRate')} value={pct(data.repeat_rate)} />
            <Stat label={t('reports.returned')} value={data.returned_patients} />
          </div>
          <Card title={t('reports.operators')}>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-left text-sm">
                <thead className="text-xs text-slate-500 uppercase">
                  <tr>
                    <th className="pb-2">{t('reports.operator')}</th>
                    <th className="pb-2 pl-3 text-right">{t('reports.attempts')}</th>
                    <th className="pb-2 pl-3 text-right">{t('reports.reached')}</th>
                    <th className="pb-2 pl-3 text-right">{t('reports.dialRate')}</th>
                    <th className="pb-2 pl-3 text-right">{t('reports.bookedByPhone')}</th>
                    <th className="pb-2 pl-3 text-right">{t('reports.created')}</th>
                    <th className="pb-2 pl-3 text-right">{t('reports.talkMin')}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.operators.map((o) => (
                    <tr key={o.user_id} className="border-t border-slate-100">
                      <td className="py-2">{o.name}</td>
                      <td className="py-2 text-right tabular-nums">{o.attempts}</td>
                      <td className="py-2 text-right tabular-nums">{o.reached}</td>
                      <td className="py-2 text-right tabular-nums">{pct(o.dial_rate) ?? '—'}</td>
                      <td className="py-2 text-right tabular-nums">{o.booked_by_phone}</td>
                      <td className="py-2 text-right tabular-nums">{o.appointments_created}</td>
                      <td className="py-2 text-right tabular-nums">{o.talk_minutes}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </div>
  )
}

export default function ReportsPage() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const canKpi = user?.role !== 'operator'
  const [tab, setTab] = useState<'daily' | 'kpi'>(canKpi ? 'kpi' : 'daily')
  return (
    <div className="max-w-6xl space-y-4">
      <h1 className="text-2xl font-semibold">{t('reports.title')}</h1>
      <div className="flex gap-1 border-b border-slate-200">
        {(canKpi ? (['kpi', 'daily'] as const) : (['daily'] as const)).map((k) => (
          <button
            key={k}
            onClick={() => setTab(k)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${tab === k ? 'border-teal-700 font-medium text-teal-800' : 'border-transparent text-slate-600'}`}
          >
            {t(`reports.${k}`)}
          </button>
        ))}
      </div>
      {tab === 'kpi' ? <KpiView /> : <Daily />}
    </div>
  )
}
