import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router'
import BookingDialog from '../components/BookingDialog'
import PatientName from '../components/PatientName'
import { PatientPicker } from '../components/Pickers'
import { Badge, Button, Card, ErrorText, Notice, Select } from '../components/ui'
import {
  CHANNELS,
  aiDraft,
  getChannelsStatus,
  getConversations,
  getTemplates,
  getThread,
  linkPatient,
  renderTemplate,
  sendMessage,
  type Channel,
  type Conversation,
} from '../lib/messaging'
import { formatDateTime, formatPhone, getPatient } from '../lib/patients'

const CHANNEL_STYLE: Record<Channel, string> = {
  telegram: 'bg-sky-100 text-sky-800',
  instagram: 'bg-pink-100 text-pink-800',
  sms: 'bg-slate-100 text-slate-700',
}

function ChannelBadge({ channel }: { channel: Channel }) {
  const { t } = useTranslation()
  return (
    <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${CHANNEL_STYLE[channel]}`}>
      {t(`inbox.channels.${channel}`)}
    </span>
  )
}

function who(c: Conversation): string {
  return c.patient_name ?? c.title ?? (c.phone ? formatPhone(c.phone) : '—')
}

function ConversationList({
  selected,
  onSelect,
}: {
  selected: string | null
  onSelect: (id: string) => void
}) {
  const { t } = useTranslation()
  const [channel, setChannel] = useState('')
  const [unread, setUnread] = useState(false)
  const { data, error } = useQuery({
    queryKey: ['inbox', 'list', channel, unread],
    queryFn: () => getConversations({ channel, unread }),
    placeholderData: keepPreviousData,
    refetchInterval: 10_000,
  })
  return (
    <Card>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Select value={channel} onChange={(e) => setChannel(e.target.value)} className="w-36 py-1 text-xs">
          <option value="">{t('inbox.all')}</option>
          {CHANNELS.map((c) => (
            <option key={c} value={c}>
              {t(`inbox.channels.${c}`)}
            </option>
          ))}
        </Select>
        <label className="flex items-center gap-1 text-xs">
          <input type="checkbox" checked={unread} onChange={(e) => setUnread(e.target.checked)} />
          {t('inbox.unreadOnly')}
        </label>
      </div>
      <ErrorText error={error} />
      {data?.length === 0 && <p className="py-6 text-center text-sm text-slate-500">{t('inbox.empty')}</p>}
      <ul className="-mx-2 max-h-[70vh] divide-y divide-slate-100 overflow-y-auto">
        {data?.map((c) => (
          <li key={c.id}>
            <button
              onClick={() => onSelect(c.id)}
              className={`w-full rounded-md px-2 py-2 text-left ${selected === c.id ? 'bg-teal-50' : 'hover:bg-slate-50'}`}
            >
              <div className="flex items-center gap-2">
                <ChannelBadge channel={c.channel} />
                <span className={`min-w-0 flex-1 truncate text-sm ${c.unread ? 'font-semibold' : ''}`}>
                  {who(c)}
                </span>
                {c.unread > 0 && (
                  <span className="rounded-full bg-teal-700 px-1.5 text-[11px] text-white tabular-nums">
                    {c.unread}
                  </span>
                )}
              </div>
              <div className="mt-0.5 flex gap-2 text-xs text-slate-500">
                <span className="min-w-0 flex-1 truncate">
                  {c.last_direction === 'out' && '↪ '}
                  {c.last_text}
                </span>
                {c.last_message_at && (
                  <span className="shrink-0 tabular-nums">{formatDateTime(c.last_message_at)}</span>
                )}
              </div>
            </button>
          </li>
        ))}
      </ul>
    </Card>
  )
}

function Thread({ id }: { id: string }) {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const [text, setText] = useState('')
  const [fromAi, setFromAi] = useState(false)
  const [templateCode, setTemplateCode] = useState<string | null>(null)
  const [linking, setLinking] = useState(false)
  const [booking, setBooking] = useState(false)
  const bottom = useRef<HTMLDivElement | null>(null)
  const { data, error } = useQuery({
    queryKey: ['inbox', 'thread', id],
    queryFn: () => getThread(id),
    refetchInterval: 5_000,
  })
  const { data: status } = useQuery({
    queryKey: ['inbox', 'status'],
    queryFn: getChannelsStatus,
    staleTime: 60_000,
  })
  const { data: templates = [] } = useQuery({
    queryKey: ['inbox', 'templates'],
    queryFn: getTemplates,
    staleTime: 300_000,
  })
  const patient = useQuery({
    queryKey: ['patient', data?.conversation.patient_id],
    queryFn: () => getPatient(data!.conversation.patient_id!),
    enabled: booking && Boolean(data?.conversation.patient_id),
  })
  const count = data?.messages.length ?? 0
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: 'end' })
  }, [count])
  const loaded = Boolean(data)
  useEffect(() => {
    // opening a chat marks it read on the server: refresh the list and the menu badge
    if (loaded) void queryClient.invalidateQueries({ queryKey: ['inbox', 'list'] })
    if (loaded) void queryClient.invalidateQueries({ queryKey: ['inbox', 'unread'] })
  }, [loaded, id, queryClient])
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['inbox'] })
  }
  const send = useMutation({
    mutationFn: () => sendMessage(id, { text, template_code: templateCode, ai_draft: fromAi }),
    onSuccess: () => {
      setText('')
      setFromAi(false)
      setTemplateCode(null)
      refresh()
    },
  })
  const draft = useMutation({
    mutationFn: () => aiDraft(id),
    onSuccess: (r) => {
      setText(r.text)
      setFromAi(true)
    },
  })
  const applyTemplate = useMutation({
    mutationFn: (code: string) => renderTemplate(id, code),
    onSuccess: (r, code) => {
      setText(r.text)
      setTemplateCode(code)
    },
  })
  const link = useMutation({
    mutationFn: (patientId: string) => linkPatient(id, patientId),
    onSuccess: () => {
      setLinking(false)
      refresh()
    },
  })
  if (error) return <ErrorText error={error} />
  if (!data) return null
  const c = data.conversation
  const lang = i18n.language === 'ru' ? 'ru' : 'uz'
  const channelOff =
    (c.channel === 'telegram' && status && !status.telegram) ||
    (c.channel === 'instagram' && status && !status.instagram) ||
    (c.channel === 'sms' && status && !status.sms)
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && text.trim() && !send.isPending) send.mutate()
  }
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-2 border-b border-slate-100 pb-3">
        <div>
          <div className="flex items-center gap-2">
            <ChannelBadge channel={c.channel} />
            <span className="font-medium">{c.title ?? who(c)}</span>
          </div>
          <div className="mt-1 text-xs text-slate-600">
            {c.phone && <span className="tabular-nums">{formatPhone(c.phone)} · </span>}
            {c.patient_id ? (
              <Link to={`/patients/${c.patient_id}`} className="text-teal-800 hover:underline">
                <PatientName name={c.patient_name ?? '—'} />
              </Link>
            ) : (
              <span>{t('inbox.notLinked')}</span>
            )}
            {c.lead_id && (
              <Link to="/leads" className="ml-2 text-teal-800 hover:underline">
                {t('inbox.lead')}
              </Link>
            )}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {!c.patient_id && (
            <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => setLinking(!linking)}>
              {t('inbox.link')}
            </Button>
          )}
          {c.patient_id && (
            <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => setBooking(true)}>
              {t('tasks.book')}
            </Button>
          )}
        </div>
      </div>
      {linking && (
        <div className="mt-3">
          <PatientPicker value={null} onChange={(p) => p && link.mutate(p.id)} />
          <ErrorText error={link.error} />
        </div>
      )}
      {channelOff && <Notice>{t('inbox.channelOff')}</Notice>}

      <div className="my-3 max-h-[55vh] space-y-2 overflow-y-auto">
        {data.messages.map((m) => (
          <div key={m.id} className={m.direction === 'in' ? 'flex' : 'flex justify-end'}>
            <div
              className={`max-w-[80%] rounded-lg px-3 py-2 text-sm whitespace-pre-line ${m.direction === 'in' ? 'bg-slate-100' : m.status === 'failed' ? 'bg-red-50 text-red-900' : 'bg-teal-50'}`}
            >
              {m.text}
              <div className="mt-1 text-[11px] text-slate-500">
                {formatDateTime(m.created_at)}
                {m.direction === 'out' && ` · ${t(`inbox.status.${m.status}`)}`}
                {m.sent_by_name && ` · ${m.sent_by_name}`}
                {m.template_code && ` · ${t('inbox.template')}`}
                {m.ai_draft && ' · AI'}
                {m.error && (
                  <div className="text-red-700" title={m.error}>
                    {/* "unexpected: <provider text>" -> the translated "unexpected" */}
                    {t(`inbox.errors.${m.error.split(':')[0]}`, { defaultValue: m.error })}
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}
        <div ref={bottom} />
      </div>

      <div className="space-y-2 border-t border-slate-100 pt-3">
        <div className="flex flex-wrap gap-2">
          <Select
            value=""
            onChange={(e) => e.target.value && applyTemplate.mutate(e.target.value)}
            className="w-56 py-1 text-xs"
          >
            <option value="">{t('inbox.templates')}</option>
            {templates
              .filter((tpl) => tpl.language === lang && tpl.active)
              .map((tpl) => (
                <option key={tpl.id} value={tpl.code}>
                  {tpl.title}
                </option>
              ))}
          </Select>
          {status?.ai && c.channel !== 'sms' && (
            <Button
              variant="secondary"
              className="px-2 py-1 text-xs"
              disabled={draft.isPending}
              onClick={() => draft.mutate()}
            >
              {draft.isPending ? t('app.loading') : t('inbox.aiDraft')}
            </Button>
          )}
        </div>
        {fromAi && <p className="text-xs text-violet-800">{t('inbox.aiHint')}</p>}
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKey}
          rows={3}
          maxLength={c.channel === 'sms' ? 480 : 4000}
          placeholder={t('inbox.placeholder')}
          className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-600/20"
        />
        <div className="flex items-center gap-2">
          <Button disabled={!text.trim() || send.isPending} onClick={() => send.mutate()}>
            {t('inbox.send')}
          </Button>
          {c.channel === 'sms' && (
            <span className="text-xs text-slate-500">{t('inbox.smsNote', { n: text.length })}</span>
          )}
          <ErrorText error={send.error ?? draft.error ?? applyTemplate.error} />
        </div>
      </div>
      {booking && patient.data && <BookingDialog patient={patient.data} onClose={() => setBooking(false)} />}
    </Card>
  )
}

export default function InboxPage() {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const selected = params.get('c')
  const { data: status } = useQuery({
    queryKey: ['inbox', 'status'],
    queryFn: getChannelsStatus,
    staleTime: 60_000,
  })
  const nothing = status && !status.telegram && !status.instagram && !status.sms
  return (
    <div className="max-w-7xl space-y-4">
      <h1 className="text-2xl font-semibold">{t('inbox.title')}</h1>
      {nothing && <Notice>{t('inbox.noChannels')}</Notice>}
      {status && (
        <div className="flex flex-wrap gap-2 text-xs">
          <Badge tone={status.telegram ? 'good' : 'neutral'}>Telegram</Badge>
          <Badge tone={status.instagram ? 'good' : 'neutral'}>Instagram</Badge>
          <Badge tone={status.sms ? 'good' : 'neutral'}>SMS{status.sms ? ` (${status.sms})` : ''}</Badge>
        </div>
      )}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[22rem_1fr]">
        <ConversationList selected={selected} onSelect={(id) => setParams({ c: id })} />
        {selected ? (
          <Thread key={selected} id={selected} />
        ) : (
          <Card>
            <p className="py-10 text-center text-sm text-slate-500">{t('inbox.pick')}</p>
          </Card>
        )}
      </div>
    </div>
  )
}
