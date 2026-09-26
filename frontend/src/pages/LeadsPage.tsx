import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import BookingDialog from '../components/BookingDialog'
import { CallButton } from '../components/Softphone'
import { Badge, Button, Card, ErrorText, Field, Input, Select } from '../components/ui'
import {
  LEAD_CHANNELS,
  LEAD_STAGES,
  REASONS,
  createLead,
  getLeads,
  leadPatient,
  updateLead,
  type Lead,
  type LeadChannel,
} from '../lib/ops'
import { SOURCES, formatDateTime, formatPhone, getPatient, type Source } from '../lib/patients'

const PAGE = 50 // the backend's page size for /leads

function NewLead({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [form, setForm] = useState({
    phone: '',
    name: '',
    channel: 'call' as LeadChannel,
    source: '' as Source | '',
    interest: '',
  })
  const create = useMutation({
    mutationFn: () =>
      createLead({
        phone: form.phone || null,
        name: form.name || null,
        channel: form.channel,
        source: form.source || null,
        interest: form.interest || null,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['leads'] })
      void queryClient.invalidateQueries({ queryKey: ['tasks'] })
      onClose()
    },
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    create.mutate()
  }
  return (
    <Card title={t('leads.new')}>
      <form onSubmit={submit} className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <Field label={t('leads.phone')}>
          <Input
            type="tel"
            placeholder="90 000 22 44"
            value={form.phone}
            onChange={(e) => setForm({ ...form, phone: e.target.value })}
            autoFocus
          />
        </Field>
        <Field label={t('leads.name')}>
          <Input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            maxLength={255}
          />
        </Field>
        <Field label={t('leads.channel')}>
          <Select
            value={form.channel}
            onChange={(e) => setForm({ ...form, channel: e.target.value as LeadChannel })}
          >
            {LEAD_CHANNELS.map((c) => (
              <option key={c} value={c}>
                {t(`leads.channels.${c}`)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t('leads.source')}>
          <Select
            value={form.source}
            onChange={(e) => setForm({ ...form, source: e.target.value as Source | '' })}
          >
            <option value="">—</option>
            {SOURCES.map((s) => (
              <option key={s} value={s}>
                {t(`sources.${s}`)}
              </option>
            ))}
          </Select>
        </Field>
        <div className="md:col-span-2">
          <Field label={t('leads.interest')}>
            <Input
              value={form.interest}
              onChange={(e) => setForm({ ...form, interest: e.target.value })}
              maxLength={2000}
            />
          </Field>
        </div>
        <div className="flex gap-2 md:col-span-3">
          <Button type="submit" disabled={create.isPending || (!form.phone && !form.name)}>
            {t('leads.save')}
          </Button>
          <Button variant="secondary" onClick={onClose}>
            {t('patients.cancel')}
          </Button>
          <ErrorText error={create.error} />
        </div>
      </form>
    </Card>
  )
}

function LeadRow({ lead }: { lead: Lead }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [lost, setLost] = useState(false)
  const [reason, setReason] = useState<string>(REASONS[0])
  const [bookFor, setBookFor] = useState<string | null>(null)
  const patient = useQuery({
    queryKey: ['patient', bookFor],
    queryFn: () => getPatient(bookFor!),
    enabled: Boolean(bookFor),
  })
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['leads'] })
    void queryClient.invalidateQueries({ queryKey: ['tasks'] })
  }
  const markLost = useMutation({
    mutationFn: () => updateLead(lead.id, { stage: 'lost', lost_reason: reason }),
    onSuccess: () => {
      setLost(false)
      refresh()
    },
  })
  const book = useMutation({
    mutationFn: () => leadPatient(lead.id),
    onSuccess: (r) => setBookFor(r.patient_id),
  })
  const open = ['new', 'contacted', 'later'].includes(lead.stage)
  return (
    <>
      <tr className="border-t border-slate-100 align-top">
        <td className="py-2 pr-3 whitespace-nowrap text-xs text-slate-600">
          {formatDateTime(lead.created_at)}
        </td>
        <td className="py-2 pr-3">
          {lead.patient_id ? (
            <Link to={`/patients/${lead.patient_id}`} className="font-medium text-teal-800 hover:underline">
              {lead.name ?? '—'}
            </Link>
          ) : (
            <span className="font-medium">{lead.name ?? '—'}</span>
          )}
          {lead.phone && (
            <a
              href={`tel:${lead.phone}`}
              className="block text-xs whitespace-nowrap text-slate-600 tabular-nums"
            >
              {formatPhone(lead.phone)}
            </a>
          )}
          {open && <CallButton number={lead.phone} />}
        </td>
        <td className="py-2 pr-3">{t(`leads.channels.${lead.channel}`)}</td>
        <td className="py-2 pr-3 text-slate-700">{lead.interest}</td>
        <td className="py-2 pr-3">
          <Badge
            tone={
              lead.stage === 'lost'
                ? 'bad'
                : lead.stage === 'booked' || lead.stage === 'visited'
                  ? 'good'
                  : 'info'
            }
          >
            {t(`leads.stages.${lead.stage}`)}
          </Badge>
          {lead.lost_reason && (
            <div className="text-xs text-slate-500">
              {t(`reasons.${lead.lost_reason}`, { defaultValue: lead.lost_reason })}
            </div>
          )}
        </td>
        <td className="py-2 pr-3 whitespace-nowrap text-xs">
          {lead.sla_breached ? (
            <span className="font-medium text-red-700">{t('leads.slaBreached')}</span>
          ) : lead.first_response_at ? (
            <span className="text-emerald-700">✓ {formatDateTime(lead.first_response_at)}</span>
          ) : (
            formatDateTime(lead.sla_due_at)
          )}
        </td>
        <td className="py-2 text-right whitespace-nowrap">
          {open && (
            <>
              <Button
                variant="secondary"
                className="px-2 py-1 text-xs"
                disabled={book.isPending}
                onClick={() => book.mutate()}
              >
                {t('leads.book')}
              </Button>
              <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => setLost(!lost)}>
                {t('leads.markLost')}
              </Button>
            </>
          )}
        </td>
      </tr>
      {lost && (
        <tr>
          <td colSpan={7} className="pb-2">
            <div className="flex items-end gap-2">
              <Field label={t('leads.lostReason')}>
                <Select value={reason} onChange={(e) => setReason(e.target.value)}>
                  {REASONS.map((r) => (
                    <option key={r} value={r}>
                      {t(`reasons.${r}`)}
                    </option>
                  ))}
                </Select>
              </Field>
              <Button variant="danger" disabled={markLost.isPending} onClick={() => markLost.mutate()}>
                {t('leads.markLost')}
              </Button>
              <ErrorText error={markLost.error} />
            </div>
          </td>
        </tr>
      )}
      {book.error && (
        <tr>
          <td colSpan={7} className="pb-2 text-right">
            <ErrorText error={book.error} />
          </td>
        </tr>
      )}
      {bookFor && patient.data && (
        <tr>
          <td>
            <BookingDialog
              patient={patient.data}
              onClose={() => {
                setBookFor(null)
                refresh()
              }}
            />
          </td>
        </tr>
      )}
    </>
  )
}

export default function LeadsPage() {
  const { t } = useTranslation()
  const [adding, setAdding] = useState(false)
  const [stage, setStage] = useState('')
  const [channel, setChannel] = useState('')
  const [q, setQ] = useState('')
  const [offset, setOffset] = useState(0)
  // a new filter starts from the first page
  const filter = (set: (v: string) => void) => (v: string) => {
    set(v)
    setOffset(0)
  }
  const { data, error } = useQuery({
    queryKey: ['leads', stage, channel, q, offset],
    queryFn: () => getLeads({ stage, channel, q, offset }),
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
  })
  return (
    <div className="max-w-6xl space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">{t('leads.title')}</h1>
        {!adding && <Button onClick={() => setAdding(true)}>{t('leads.new')}</Button>}
      </div>
      {adding && <NewLead onClose={() => setAdding(false)} />}
      <Card>
        <div className="mb-3 flex flex-col gap-2 md:flex-row">
          <Input
            type="search"
            placeholder={t('leads.search')}
            value={q}
            onChange={(e) => filter(setQ)(e.target.value)}
            className="md:flex-1"
          />
          <Select value={stage} onChange={(e) => filter(setStage)(e.target.value)} className="md:w-52">
            <option value="">{t('leads.allStages')}</option>
            {LEAD_STAGES.map((s) => (
              <option key={s} value={s}>
                {t(`leads.stages.${s}`)} {data?.by_stage[s] ? `(${data.by_stage[s]})` : ''}
              </option>
            ))}
          </Select>
          <Select value={channel} onChange={(e) => filter(setChannel)(e.target.value)} className="md:w-52">
            <option value="">{t('leads.allChannels')}</option>
            {LEAD_CHANNELS.map((c) => (
              <option key={c} value={c}>
                {t(`leads.channels.${c}`)}
              </option>
            ))}
          </Select>
        </div>
        <ErrorText error={error} />
        {data && data.items.length === 0 && (
          <p className="py-6 text-center text-sm text-slate-500">{t('leads.empty')}</p>
        )}
        {data && data.items.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] text-left text-sm">
              <thead className="text-xs text-slate-500 uppercase">
                <tr>
                  <th className="pb-2">{t('leads.created')}</th>
                  <th className="pb-2">{t('leads.name')}</th>
                  <th className="pb-2">{t('leads.channel')}</th>
                  <th className="pb-2">{t('leads.interest')}</th>
                  <th className="pb-2">{t('leads.stage')}</th>
                  <th className="pb-2">{t('leads.sla')}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.items.map((lead) => (
                  <LeadRow key={lead.id} lead={lead} />
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && data.total > 0 && (
          <div className="mt-4 flex items-center justify-between text-sm text-slate-600">
            <span>{t('audit.total', { count: data.total })}</span>
            <div className="flex gap-2">
              <Button
                variant="secondary"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE))}
              >
                {t('audit.prev')}
              </Button>
              <Button
                variant="secondary"
                disabled={offset + PAGE >= data.total}
                onClick={() => setOffset(offset + PAGE)}
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
