import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router'
import BookingDialog from '../components/BookingDialog'
import CallAnalysisDialog from '../components/CallAnalysisDialog'
import { CallButton } from '../components/Softphone'
import { Badge, Button, Card, ErrorText, Field, Input, Select } from '../components/ui'
import { useAuth } from '../lib/auth-context'
import {
  BOARD,
  FUNNEL,
  LEAD_CHANNELS,
  LEAD_STAGES,
  MANUAL_STAGES,
  OPEN_LEAD_STAGES,
  REASONS,
  conversion,
  createLead,
  getLead,
  getLeads,
  leadPatient,
  slaMinutesLeft,
  updateLead,
  type Lead,
  type LeadChannel,
  type LeadPage,
  type LeadStage,
} from '../lib/ops'
import { SOURCES, formatDateTime, formatPhone, getPatient, type Source } from '../lib/patients'
import { formatDuration } from '../lib/telephony'

const PAGE = 50
const BOARD_LIMIT = 200

/** re-renders every `ms` so SLA countdowns move between refetches */
function useNow(ms = 30_000) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), ms)
    return () => window.clearInterval(id)
  }, [ms])
  return now
}

function Duration({ minutes }: { minutes: number }) {
  const { t } = useTranslation()
  const m = Math.abs(minutes)
  if (m < 60) return <>{t('leadsView.minutes', { count: m })}</>
  if (m < 60 * 24) return <>{t('leadsView.hoursMinutes', { h: Math.floor(m / 60), m: m % 60 })}</>
  return <>{t('leadsView.days', { count: Math.floor(m / (60 * 24)) })}</>
}

/** TZ 4.4 SLA: 15 working minutes for the first answer. */
function SlaBadge({ lead, now }: { lead: Lead; now: number }) {
  const { t } = useTranslation()
  const state = lead.sla_state ?? (lead.sla_breached ? 'overdue' : 'waiting')
  const left = slaMinutesLeft(lead.sla_due_at, now)
  switch (state) {
    case 'overdue':
      return (
        <span className="inline-flex items-center rounded bg-red-600 px-2 py-0.5 text-xs font-semibold whitespace-nowrap text-white">
          {t('leadsView.late')} <Duration minutes={left} />
        </span>
      )
    case 'waiting':
      return (
        <span className="inline-flex items-center rounded bg-amber-100 px-2 py-0.5 text-xs font-medium whitespace-nowrap text-amber-900">
          <Duration minutes={Math.max(left, 0)} /> {t('leadsView.left')}
        </span>
      )
    case 'met':
      return (
        <span
          className="text-xs whitespace-nowrap text-emerald-700"
          title={formatDateTime(lead.first_response_at)}
        >
          ✓ {t('leadsView.answered')}
        </span>
      )
    case 'late':
      return (
        <span
          className="text-xs whitespace-nowrap text-slate-600"
          title={formatDateTime(lead.first_response_at)}
        >
          ✓ {t('leadsView.answeredLate')}
        </span>
      )
    default:
      return <span className="text-xs text-slate-400">—</span>
  }
}

function StageBadge({ stage }: { stage: LeadStage }) {
  const { t } = useTranslation()
  const tone = stage === 'lost' ? 'bad' : ['booked', 'confirmed', 'visited'].includes(stage) ? 'good' : 'info'
  return <Badge tone={tone}>{t(`leads.stages.${stage}`)}</Badge>
}

function SourceText({ source }: { source: Source | null }) {
  const { t } = useTranslation()
  if (!source) return <span className="text-xs font-medium text-red-700">{t('leadsView.noSource')}</span>
  return <>{t(`sources.${source}`)}</>
}

function SourceSelect({
  value,
  onChange,
  id,
}: {
  value: Source | ''
  onChange: (s: Source | '') => void
  id?: string
}) {
  const { t } = useTranslation()
  return (
    <Select id={id} value={value} onChange={(e) => onChange(e.target.value as Source | '')} required>
      <option value="" disabled>
        {t('leadsView.pickSource')}
      </option>
      {SOURCES.map((s) => (
        <option key={s} value={s}>
          {t(`sources.${s}`)}
        </option>
      ))}
    </Select>
  )
}

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
            inputMode="tel"
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
        <Field label={`${t('leadsView.adSource')} *`} hint={t('leadsView.adSourceHint')}>
          <SourceSelect value={form.source} onChange={(source) => setForm({ ...form, source })} />
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
        <div className="flex flex-wrap items-center gap-2 md:col-span-3">
          <Button type="submit" disabled={create.isPending || (!form.phone && !form.name) || !form.source}>
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

/** yangi → aloqa → yozildi → tasdiqlandi → keldi, with the step-to-step conversion. */
function FunnelStrip({ page }: { page: LeadPage | undefined }) {
  const { t } = useTranslation()
  const f = page?.funnel
  return (
    <div className="overflow-x-auto">
      <ol className="flex min-w-max items-stretch gap-1 text-sm" aria-label={t('leadsView.funnel')}>
        {FUNNEL.map((stage, i) => {
          const prev = i > 0 ? f?.[FUNNEL[i - 1]] : undefined
          const rate = i > 0 ? conversion(prev, f?.[stage]) : null
          return (
            <li key={stage} className="flex items-center gap-1">
              {i > 0 && (
                <span
                  className="flex flex-col items-center px-1 text-xs text-slate-500"
                  aria-hidden={rate === null}
                >
                  <span>→</span>
                  <span className="tabular-nums">{rate === null ? '' : `${rate}%`}</span>
                </span>
              )}
              <div className="min-w-24 rounded-md border border-slate-200 bg-white px-3 py-2">
                <div className="text-xs text-slate-500">{t(`leads.stages.${stage}`)}</div>
                <div className="text-lg font-semibold tabular-nums">{f ? (f[stage] ?? 0) : '…'}</div>
              </div>
            </li>
          )
        })}
        <li className="ml-3 flex items-center gap-1">
          <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
            <div className="text-xs text-slate-500">{t('leads.stages.later')}</div>
            <div className="text-lg font-semibold tabular-nums">{page?.by_stage.later ?? 0}</div>
          </div>
          <div className="rounded-md border border-red-100 bg-red-50 px-3 py-2">
            <div className="text-xs text-red-700">{t('leads.stages.lost')}</div>
            <div className="text-lg font-semibold text-red-800 tabular-nums">{page?.by_stage.lost ?? 0}</div>
          </div>
          {f && f.new > 0 && (
            <div className="rounded-md bg-teal-50 px-3 py-2 text-teal-900">
              <div className="text-xs">{t('leadsView.overall')}</div>
              <div className="text-lg font-semibold tabular-nums">{conversion(f.new, f.visited)}%</div>
            </div>
          )}
        </li>
      </ol>
    </div>
  )
}

function LeadRow({ lead, now, onOpen }: { lead: Lead; now: number; onOpen: () => void }) {
  const { t } = useTranslation()
  const overdue = lead.sla_state === 'overdue'
  const open = OPEN_LEAD_STAGES.includes(lead.stage)
  return (
    <tr
      className={`cursor-pointer border-t align-top ${
        overdue
          ? 'border-red-200 bg-red-50 text-red-950 hover:bg-red-100'
          : 'border-slate-100 hover:bg-slate-50'
      }`}
      onClick={onOpen}
    >
      <td
        className={`py-2 pr-3 pl-2 text-xs whitespace-nowrap ${overdue ? 'border-l-4 border-red-600' : ''}`}
      >
        {formatDateTime(lead.created_at)}
      </td>
      <td className="py-2 pr-3">
        <button
          className="text-left font-medium text-teal-800 hover:underline"
          onClick={(e) => {
            e.stopPropagation()
            onOpen()
          }}
        >
          {lead.name ?? t('phone.lead')}
        </button>
        {lead.phone && (
          <div className="text-xs whitespace-nowrap tabular-nums">{formatPhone(lead.phone)}</div>
        )}
      </td>
      <td className="py-2 pr-3">{t(`leads.channels.${lead.channel}`)}</td>
      <td className="py-2 pr-3">
        <SourceText source={lead.source} />
      </td>
      <td className="max-w-56 py-2 pr-3">
        <span className="line-clamp-2">{lead.interest}</span>
      </td>
      <td className="py-2 pr-3">
        <StageBadge stage={lead.stage} />
        {lead.lost_reason && (
          <div className="text-xs text-slate-500">
            {t(`reasons.${lead.lost_reason}`, { defaultValue: lead.lost_reason })}
          </div>
        )}
      </td>
      <td className="py-2 pr-3">
        <SlaBadge lead={lead} now={now} />
      </td>
      <td className="py-2 pr-2 text-right" onClick={(e) => e.stopPropagation()}>
        {open && <CallButton number={lead.phone} />}
      </td>
    </tr>
  )
}

function LeadCard({ lead, now, onOpen }: { lead: Lead; now: number; onOpen: () => void }) {
  const { t } = useTranslation()
  const overdue = lead.sla_state === 'overdue'
  return (
    <button
      onClick={onOpen}
      className={`block w-full rounded-md border p-2 text-left text-sm shadow-sm hover:shadow ${
        overdue ? 'border-red-300 bg-red-50' : 'border-slate-200 bg-white'
      }`}
    >
      <div className="font-medium break-words">{lead.name ?? t('phone.lead')}</div>
      {lead.phone && <div className="text-xs text-slate-600 tabular-nums">{formatPhone(lead.phone)}</div>}
      <div className="mt-1 text-xs text-slate-500">
        {t(`leads.channels.${lead.channel}`)} · <SourceText source={lead.source} />
      </div>
      {lead.interest && <div className="mt-1 line-clamp-2 text-xs text-slate-700">{lead.interest}</div>}
      <div className="mt-1 flex items-center justify-between gap-2">
        <span className="text-xs text-slate-400 tabular-nums">{formatDateTime(lead.created_at)}</span>
        {OPEN_LEAD_STAGES.includes(lead.stage) && <SlaBadge lead={lead} now={now} />}
      </div>
    </button>
  )
}

/** Kanban: one column per stage with its count and the conversion from the previous step. */
function Board({ page, now, onOpen }: { page: LeadPage; now: number; onOpen: (id: string) => void }) {
  const { t } = useTranslation()
  return (
    <div className="-mx-4 overflow-x-auto px-4 pb-2 sm:mx-0 sm:px-0">
      <div className="grid min-w-max auto-cols-[15rem] grid-flow-col gap-3">
        {BOARD.map((stage) => {
          const items = page.items.filter((l) => l.stage === stage)
          const count = page.by_stage[stage] ?? 0
          const idx = FUNNEL.indexOf(stage)
          const rate = idx > 0 ? conversion(page.funnel?.[FUNNEL[idx - 1]], page.funnel?.[stage]) : null
          return (
            <section
              key={stage}
              className="flex max-h-[70vh] flex-col rounded-lg bg-slate-100"
              aria-label={t(`leads.stages.${stage}`)}
            >
              <header className="flex items-center justify-between gap-2 px-3 py-2">
                <span className="text-sm font-semibold">{t(`leads.stages.${stage}`)}</span>
                <span className="flex items-center gap-1 text-xs text-slate-600">
                  {rate !== null && <span title={t('leadsView.conversion')}>{rate}%</span>}
                  <span className="rounded-full bg-white px-2 py-0.5 font-medium tabular-nums">{count}</span>
                </span>
              </header>
              <div className="flex-1 space-y-2 overflow-y-auto px-2 pb-2">
                {items.length === 0 && <p className="px-1 py-3 text-center text-xs text-slate-400">—</p>}
                {items.map((lead) => (
                  <LeadCard key={lead.id} lead={lead} now={now} onOpen={() => onOpen(lead.id)} />
                ))}
                {count > items.length && (
                  <p className="px-1 text-center text-xs text-slate-500">
                    {t('leadsView.more', { count: count - items.length })}
                  </p>
                )}
              </div>
            </section>
          )
        })}
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-xs font-semibold tracking-wide text-slate-500 uppercase">{title}</h3>
      {children}
    </section>
  )
}

const CAN_OPEN_ANALYSIS = ['operator', 'supervisor', 'owner', 'admin']

/** Everything about one inquiry, editable: source, name, interest, stage. */
function LeadDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const { t } = useTranslation()
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const now = useNow()
  const {
    data: lead,
    error,
    isLoading,
  } = useQuery({ queryKey: ['leads', 'detail', id], queryFn: () => getLead(id) })
  const [form, setForm] = useState<{
    name: string
    source: Source | ''
    interest: string
    note: string
  } | null>(null)
  const [lostReason, setLostReason] = useState('')
  const [askLost, setAskLost] = useState(false)
  const [bookFor, setBookFor] = useState<string | null>(null)
  const [analysis, setAnalysis] = useState<string | null>(null)
  const values = form ?? {
    name: lead?.name ?? '',
    source: (lead?.source ?? '') as Source | '',
    interest: lead?.interest ?? '',
    note: lead?.note ?? '',
  }
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['leads'] })
    void queryClient.invalidateQueries({ queryKey: ['tasks'] })
  }
  const save = useMutation({
    mutationFn: () =>
      updateLead(id, {
        name: values.name.trim() || null,
        source: values.source || null,
        interest: values.interest.trim() || null,
        note: values.note.trim() || null,
      }),
    onSuccess: () => {
      setForm(null)
      refresh()
    },
  })
  const stage = useMutation({
    mutationFn: (s: LeadStage) =>
      updateLead(id, { stage: s, ...(s === 'lost' ? { lost_reason: lostReason } : {}) }),
    onSuccess: () => {
      setAskLost(false)
      refresh()
    },
  })
  const book = useMutation({ mutationFn: () => leadPatient(id), onSuccess: (r) => setBookFor(r.patient_id) })
  const patient = useQuery({
    queryKey: ['patient', bookFor],
    queryFn: () => getPatient(bookFor!),
    enabled: Boolean(bookFor),
  })
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  const dirty = form !== null
  const open = lead ? OPEN_LEAD_STAGES.includes(lead.stage) : false

  return (
    <div className="fixed inset-0 z-40" role="dialog" aria-modal="true" aria-label={t('leadsView.details')}>
      <button className="absolute inset-0 bg-slate-900/30" aria-label={t('app.close')} onClick={onClose} />
      <aside className="absolute inset-y-0 right-0 flex w-full max-w-xl flex-col bg-white shadow-xl">
        <header className="flex items-start justify-between gap-3 border-b border-slate-200 px-5 py-3">
          <div className="min-w-0">
            <h2 className="text-base font-semibold break-words">{lead?.name ?? t('phone.lead')}</h2>
            {lead && (
              <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-600">
                <StageBadge stage={lead.stage} />
                <SlaBadge lead={lead} now={now} />
                <span>{t(`leads.channels.${lead.channel}`)}</span>
                <span className="tabular-nums">{formatDateTime(lead.created_at)}</span>
              </div>
            )}
          </div>
          <button
            className="rounded p-1 text-slate-500 hover:bg-slate-100"
            aria-label={t('app.close')}
            onClick={onClose}
          >
            ✕
          </button>
        </header>
        <div className="flex-1 space-y-6 overflow-y-auto px-5 py-4">
          <ErrorText error={error} />
          {isLoading && <div className="h-40 animate-pulse rounded-md bg-slate-100" />}
          {lead && (
            <>
              <div className="flex flex-wrap items-center gap-2">
                {lead.phone && (
                  <a
                    href={`tel:${lead.phone}`}
                    className="font-medium text-teal-800 tabular-nums hover:underline"
                  >
                    {formatPhone(lead.phone)}
                  </a>
                )}
                <CallButton number={lead.phone} />
                {lead.patient_id && (
                  <Link to={`/patients/${lead.patient_id}`} className="text-sm text-teal-800 hover:underline">
                    {t('leadsView.openCard')} →
                  </Link>
                )}
                {open && (
                  <Button
                    className="px-2 py-1 text-xs"
                    disabled={book.isPending}
                    onClick={() => book.mutate()}
                  >
                    {t('leads.book')}
                  </Button>
                )}
              </div>
              <ErrorText error={book.error} />

              <Section title={t('leadsView.stage')}>
                <div className="flex flex-wrap gap-1">
                  {MANUAL_STAGES.filter((s) => s !== lead.stage).map((s) => (
                    <Button
                      key={s}
                      variant={s === 'lost' ? 'danger' : 'secondary'}
                      className="px-2 py-1 text-xs"
                      disabled={stage.isPending}
                      onClick={() => (s === 'lost' ? setAskLost(!askLost) : stage.mutate(s))}
                    >
                      {t(`leadsView.moveTo.${s}`)}
                    </Button>
                  ))}
                </div>
                {askLost && (
                  <div className="flex flex-wrap items-end gap-2">
                    <Field label={t('leads.lostReason')}>
                      <Select
                        value={lostReason}
                        onChange={(e) => setLostReason(e.target.value)}
                        className="w-56"
                      >
                        <option value="" disabled>
                          —
                        </option>
                        {REASONS.map((r) => (
                          <option key={r} value={r}>
                            {t(`reasons.${r}`)}
                          </option>
                        ))}
                      </Select>
                    </Field>
                    <Button
                      variant="danger"
                      disabled={!lostReason || stage.isPending}
                      onClick={() => stage.mutate('lost')}
                    >
                      {t('leads.markLost')}
                    </Button>
                  </div>
                )}
                <ErrorText error={stage.error} />
              </Section>

              <Section title={t('leadsView.edit')}>
                <form
                  className="grid grid-cols-1 gap-3 sm:grid-cols-2"
                  onSubmit={(e) => {
                    e.preventDefault()
                    save.mutate()
                  }}
                >
                  <Field label={t('leads.name')}>
                    <Input
                      value={values.name}
                      maxLength={255}
                      onChange={(e) => setForm({ ...values, name: e.target.value })}
                    />
                  </Field>
                  <Field label={`${t('leadsView.adSource')} *`}>
                    <SourceSelect
                      value={values.source}
                      onChange={(source) => setForm({ ...values, source })}
                    />
                  </Field>
                  <div className="sm:col-span-2">
                    <Field label={t('leads.interest')}>
                      <Input
                        value={values.interest}
                        maxLength={2000}
                        onChange={(e) => setForm({ ...values, interest: e.target.value })}
                      />
                    </Field>
                  </div>
                  <div className="sm:col-span-2">
                    <Field label={t('tasks.note')}>
                      <textarea
                        className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-600/20"
                        rows={2}
                        maxLength={2000}
                        value={values.note}
                        onChange={(e) => setForm({ ...values, note: e.target.value })}
                      />
                    </Field>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 sm:col-span-2">
                    <Button type="submit" disabled={!dirty || !values.source || save.isPending}>
                      {t('patients.save')}
                    </Button>
                    {dirty && (
                      <Button variant="ghost" onClick={() => setForm(null)}>
                        {t('patients.cancel')}
                      </Button>
                    )}
                    <ErrorText error={save.error} />
                  </div>
                </form>
              </Section>

              {lead.messages.length > 0 && (
                <Section title={t('leadsView.messages')}>
                  <ol className="space-y-2">
                    {lead.messages.map((m, i) => (
                      <li key={i} className={`flex ${m.direction === 'in' ? '' : 'justify-end'}`}>
                        <div
                          className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
                            m.direction === 'in' ? 'bg-slate-100' : 'bg-teal-50 text-teal-950'
                          }`}
                        >
                          <div className="whitespace-pre-line">{m.text}</div>
                          <div className="mt-1 text-[11px] text-slate-500 tabular-nums">
                            {t(`inbox.channels.${m.channel}`, { defaultValue: m.channel })} ·{' '}
                            {formatDateTime(m.created_at)}
                          </div>
                        </div>
                      </li>
                    ))}
                  </ol>
                </Section>
              )}

              <Section title={t('leadsView.calls')}>
                {lead.calls.length === 0 ? (
                  <p className="text-sm text-slate-500">{t('leadsView.noCalls')}</p>
                ) : (
                  <ul className="divide-y divide-slate-100 text-sm">
                    {lead.calls.map((c) => (
                      <li key={c.id} className="py-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium">{t(`calls.dir.${c.direction}`)}</span>
                          <Badge tone={c.status === 'answered' ? 'good' : 'neutral'}>
                            {t(`calls.statuses.${c.status}`, { defaultValue: c.status })}
                          </Badge>
                          <span className="text-xs text-slate-500 tabular-nums">
                            {formatDateTime(c.started_at)}
                          </span>
                          {c.talk_seconds ? (
                            <span className="text-xs text-slate-500">{formatDuration(c.talk_seconds)}</span>
                          ) : null}
                          {c.user_name && <span className="text-xs text-slate-500">{c.user_name}</span>}
                          {(c.summary || c.has_recording) && CAN_OPEN_ANALYSIS.includes(user?.role ?? '') && (
                            <button
                              className="text-xs text-teal-800 hover:underline"
                              onClick={() => setAnalysis(c.id)}
                            >
                              {t('ai.open')}
                            </button>
                          )}
                        </div>
                        {c.summary && <p className="mt-1 text-slate-600">{c.summary}</p>}
                      </li>
                    ))}
                  </ul>
                )}
              </Section>

              <Section title={t('leadsView.tasks')}>
                {lead.tasks.length === 0 ? (
                  <p className="text-sm text-slate-500">{t('leadsView.noTasks')}</p>
                ) : (
                  <ul className="space-y-2 text-sm">
                    {lead.tasks.map((task) => (
                      <li key={task.id} className="rounded-md border border-slate-100 p-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium">{t(`taskTypes.${task.type}`)}</span>
                          <Badge
                            tone={
                              task.status === 'open' ? 'info' : task.status === 'done' ? 'good' : 'neutral'
                            }
                          >
                            {t(`leadsView.taskStatus.${task.status}`)}
                          </Badge>
                          {task.outcome && <span className="text-xs">{t(`outcomes.${task.outcome}`)}</span>}
                          <span className="text-xs text-slate-500 tabular-nums">
                            {formatDateTime(task.due_at)}
                          </span>
                        </div>
                        {task.attempts.length > 0 && (
                          <ol className="mt-1 space-y-0.5 text-xs text-slate-600">
                            {task.attempts.map((a, i) => (
                              <li key={i}>
                                <span className="tabular-nums">{formatDateTime(a.created_at)}</span> ·{' '}
                                {t(`outcomes.${a.outcome}`)} ·{' '}
                                {a.automatic ? t('taskQueue.bySystem') : (a.user_name ?? '—')}
                                {a.note && ` · ${a.note}`}
                              </li>
                            ))}
                          </ol>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </Section>

              <Section title={t('leadsView.history')}>
                <ol className="relative space-y-2 border-l border-slate-200 pl-4 text-sm">
                  {lead.history.map((h, i) => (
                    <li key={i}>
                      <span
                        className="absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full bg-teal-600"
                        aria-hidden
                      />
                      <div className="text-xs text-slate-500 tabular-nums">
                        {formatDateTime(h.created_at)}
                        {h.user_name && ` · ${h.user_name}`}
                      </div>
                      <div>
                        {h.old_stage && `${t(`leads.stages.${h.old_stage}`)} → `}
                        <strong>{t(`leads.stages.${h.new_stage}`)}</strong>
                        {h.reason && ` · ${t(`reasons.${h.reason}`, { defaultValue: h.reason })}`}
                      </div>
                    </li>
                  ))}
                </ol>
              </Section>
            </>
          )}
        </div>
      </aside>
      {bookFor && patient.data && (
        <BookingDialog
          patient={patient.data}
          onClose={() => {
            setBookFor(null)
            refresh()
          }}
        />
      )}
      {analysis && <CallAnalysisDialog callId={analysis} onClose={() => setAnalysis(null)} />}
    </div>
  )
}

function SkeletonRows() {
  return (
    <div className="space-y-2" aria-hidden>
      {[0, 1, 2, 3, 4].map((i) => (
        <div key={i} className="h-10 animate-pulse rounded bg-slate-100" />
      ))}
    </div>
  )
}

const FILTER_KEYS = ['q', 'stage', 'channel', 'source', 'since', 'until', 'overdue'] as const

export default function LeadsPage() {
  const { t } = useTranslation()
  const now = useNow()
  const [params, setParams] = useSearchParams()
  const [adding, setAdding] = useState(false)
  const get = (k: string) => params.get(k) ?? ''
  const board = get('view') === 'board'
  const offset = board ? 0 : Number(get('offset') || 0)
  const [q, setQ] = useState(get('q'))
  const filters = {
    stage: get('stage'),
    channel: get('channel'),
    source: get('source'),
    since: get('since'),
    until: get('until'),
    overdue: get('overdue') === '1',
  }
  const setParam = (key: string, value: string) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (value) next.set(key, value)
        else next.delete(key)
        if (key !== 'offset' && key !== 'lead') next.delete('offset')
        return next
      },
      { replace: key === 'q' },
    )
  // debounce the search box into the URL
  useEffect(() => {
    const id = window.setTimeout(() => {
      setParams(
        (prev) => {
          if ((prev.get('q') ?? '') === q.trim()) return prev
          const next = new URLSearchParams(prev)
          if (q.trim()) next.set('q', q.trim())
          else next.delete('q')
          next.delete('offset')
          return next
        },
        { replace: true },
      )
    }, 300)
    return () => window.clearTimeout(id)
  }, [q, setParams])

  const { data, error, isLoading, isFetching } = useQuery({
    queryKey: ['leads', filters, get('q'), offset, board],
    queryFn: () =>
      getLeads({
        ...filters,
        stage: board ? '' : filters.stage,
        q: get('q'),
        offset,
        limit: board ? BOARD_LIMIT : PAGE,
      }),
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
  })
  const active = FILTER_KEYS.some((k) => params.get(k))
  const leadId = get('lead')

  return (
    <div className="max-w-7xl space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">{t('leads.title')}</h1>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex rounded-md border border-slate-300 bg-white p-0.5" role="group">
            {(['table', 'board'] as const).map((v) => (
              <button
                key={v}
                aria-pressed={(v === 'board') === board}
                className={`rounded px-3 py-1.5 text-sm font-medium ${
                  (v === 'board') === board ? 'bg-teal-700 text-white' : 'text-slate-700 hover:bg-slate-50'
                }`}
                onClick={() => setParam('view', v === 'board' ? 'board' : '')}
              >
                {t(`leadsView.views.${v}`)}
              </button>
            ))}
          </div>
          {!adding && <Button onClick={() => setAdding(true)}>{t('leads.new')}</Button>}
        </div>
      </div>
      {adding && <NewLead onClose={() => setAdding(false)} />}

      <FunnelStrip page={data} />

      <Card>
        <div className="mb-3 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <Input
            type="search"
            placeholder={t('leads.search')}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="sm:col-span-2"
          />
          {!board && (
            <Select
              value={filters.stage}
              onChange={(e) => setParam('stage', e.target.value)}
              aria-label={t('leads.stage')}
            >
              <option value="">{t('leads.allStages')}</option>
              {LEAD_STAGES.map((s) => (
                <option key={s} value={s}>
                  {t(`leads.stages.${s}`)} {data?.by_stage[s] ? `(${data.by_stage[s]})` : ''}
                </option>
              ))}
            </Select>
          )}
          <Select
            value={filters.channel}
            onChange={(e) => setParam('channel', e.target.value)}
            aria-label={t('leads.channel')}
          >
            <option value="">{t('leads.allChannels')}</option>
            {LEAD_CHANNELS.map((c) => (
              <option key={c} value={c}>
                {t(`leads.channels.${c}`)}
              </option>
            ))}
          </Select>
          <Select
            value={filters.source}
            onChange={(e) => setParam('source', e.target.value)}
            aria-label={t('leadsView.adSource')}
          >
            <option value="">{t('leadsView.allSources')}</option>
            {SOURCES.map((s) => (
              <option key={s} value={s}>
                {t(`sources.${s}`)}
              </option>
            ))}
          </Select>
          <Field label={t('leadsView.from')}>
            <Input
              type="date"
              value={filters.since}
              max={filters.until || undefined}
              onChange={(e) => setParam('since', e.target.value)}
            />
          </Field>
          <Field label={t('leadsView.to')}>
            <Input
              type="date"
              value={filters.until}
              min={filters.since || undefined}
              onChange={(e) => setParam('until', e.target.value)}
            />
          </Field>
          <label className="flex items-center gap-2 self-end pb-2 text-sm">
            <input
              type="checkbox"
              className="h-4 w-4 accent-red-600"
              checked={filters.overdue}
              onChange={(e) => setParam('overdue', e.target.checked ? '1' : '')}
            />
            <span className="font-medium text-red-700">{t('leadsView.onlyOverdue')}</span>
          </label>
        </div>
        {active && (
          <button
            className="mb-3 text-sm text-teal-800 hover:underline"
            onClick={() => {
              setQ('')
              setParams(board ? { view: 'board' } : {})
            }}
          >
            {t('leadsView.clearFilters')}
          </button>
        )}
        <ErrorText error={error} />
        {isLoading && <SkeletonRows />}
        {data && data.items.length === 0 && (
          <div className="py-8 text-center">
            <p className="text-sm font-medium text-slate-700">
              {active ? t('leadsView.emptyFiltered') : t('leads.empty')}
            </p>
            <p className="mt-1 text-sm text-slate-500">
              {active ? t('leadsView.emptyFilteredHint') : t('leadsView.emptyHint')}
            </p>
          </div>
        )}
        {data && data.items.length > 0 && board && (
          <Board page={data} now={now} onOpen={(id) => setParam('lead', id)} />
        )}
        {data && data.items.length > 0 && !board && (
          <div className={`-mx-5 overflow-x-auto px-5 ${isFetching ? 'opacity-70' : ''}`}>
            <table className="w-full min-w-[900px] text-left text-sm">
              <thead className="text-xs text-slate-500 uppercase">
                <tr>
                  <th className="pb-2 pl-2">{t('leads.created')}</th>
                  <th className="pb-2">{t('leads.name')}</th>
                  <th className="pb-2">{t('leads.channel')}</th>
                  <th className="pb-2">{t('leadsView.adSource')}</th>
                  <th className="pb-2">{t('leads.interest')}</th>
                  <th className="pb-2">{t('leads.stage')}</th>
                  <th className="pb-2">{t('leads.sla')}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.items.map((lead) => (
                  <LeadRow key={lead.id} lead={lead} now={now} onOpen={() => setParam('lead', lead.id)} />
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && data.total > 0 && !board && (
          <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-sm text-slate-600">
            <span>{t('audit.total', { count: data.total })}</span>
            <div className="flex gap-2">
              <Button
                variant="secondary"
                disabled={offset === 0}
                onClick={() => setParam('offset', String(Math.max(0, offset - PAGE)))}
              >
                {t('audit.prev')}
              </Button>
              <Button
                variant="secondary"
                disabled={offset + PAGE >= data.total}
                onClick={() => setParam('offset', String(offset + PAGE))}
              >
                {t('audit.next')}
              </Button>
            </div>
          </div>
        )}
      </Card>
      {leadId && <LeadDrawer key={leadId} id={leadId} onClose={() => setParam('lead', '')} />}
    </div>
  )
}
