import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { createLead } from '../lib/ops'
import { formatDateTime, formatPhone } from '../lib/patients'
import { useSoftphone, type PhoneStatus } from '../lib/softphone-context'
import { formatDuration, lookupCaller } from '../lib/telephony'
import { Button, Input } from './ui'

const DOT: Record<PhoneStatus, string> = {
  disabled: 'bg-slate-300',
  connecting: 'bg-amber-400',
  registered: 'bg-emerald-500',
  offline: 'bg-red-500',
}

function display(number: string): string {
  const digits = number.replace(/\D/g, '')
  if (digits.length === 9) return formatPhone(`+998${digits}`)
  if (digits.length === 12 && digits.startsWith('998')) return formatPhone(`+${digits}`)
  return number
}

/** Header chip: registration state + a small dialer. */
export function SoftphoneStatus() {
  const { t } = useTranslation()
  const phone = useSoftphone()
  const [open, setOpen] = useState(false)
  const [number, setNumber] = useState('')
  if (phone.status === 'disabled') return null
  const dial = (e: FormEvent) => {
    e.preventDefault()
    phone.dial(number)
    setOpen(false)
    setNumber('')
  }
  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 rounded-md border border-slate-200 px-2.5 py-1.5 text-sm hover:bg-slate-50"
        title={t(`phone.status.${phone.status}`)}
      >
        <span className={`h-2.5 w-2.5 rounded-full ${DOT[phone.status]}`} />
        <span className="tabular-nums">{phone.extension}</span>
        <span className="hidden text-slate-500 md:inline">{t(`phone.status.${phone.status}`)}</span>
      </button>
      {open && (
        <div className="absolute right-0 z-30 mt-2 w-72 rounded-md border border-slate-200 bg-white p-3 shadow-lg">
          <form onSubmit={dial} className="flex gap-2">
            <Input
              type="tel"
              autoFocus
              placeholder={t('phone.dialPlaceholder')}
              value={number}
              onChange={(e) => setNumber(e.target.value)}
              className="min-w-0 flex-1"
            />
            <Button type="submit" disabled={phone.status !== 'registered' || !number || Boolean(phone.call)}>
              {t('phone.call')}
            </Button>
          </form>
          {phone.error && (
            <p className="mt-2 text-xs text-red-700">
              {t('phone.failed', { cause: t(`phone.causes.${phone.error}`, { defaultValue: phone.error }) })}
            </p>
          )}
          <button
            className="mt-2 text-xs text-teal-800 hover:underline disabled:text-slate-400"
            disabled={phone.status !== 'registered' || Boolean(phone.call)}
            onClick={() => {
              phone.dial('600')
              setOpen(false)
            }}
          >
            {t('phone.echoTest')}
          </button>
          {phone.status === 'offline' && (
            <p className="mt-2 text-xs text-slate-600">{t('phone.offlineHint')}</p>
          )}
        </div>
      )}
    </div>
  )
}

function Elapsed({ since }: { since: number }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])
  return <span className="tabular-nums">{formatDuration(Math.max(0, Math.round((now - since) / 1000)))}</span>
}

function Caller({ number }: { number: string }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { data } = useQuery({
    queryKey: ['telephony', 'lookup', number],
    queryFn: () => lookupCaller(number),
    enabled: number.replace(/\D/g, '').length >= 9,
  })
  const newLead = useMutation({
    mutationFn: () => createLead({ phone: number, channel: 'call' }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['telephony', 'lookup', number] }),
  })
  if (!data) return null
  if (data.patient) {
    return (
      <div className="text-sm">
        <Link to={`/patients/${data.patient.id}`} className="font-medium text-teal-800 hover:underline">
          {data.patient.full_name}
        </Link>
        <div className="text-xs text-slate-600">
          {t(`kinds.${data.patient.kind}`)}
          {data.patient.district && ` · ${data.patient.district}`}
          {data.open_tasks > 0 && ` · ${t('phone.openTasks', { count: data.open_tasks })}`}
        </div>
        {data.next_visit && (
          <div className="text-xs text-slate-600">
            {t('phone.nextVisit')}: {formatDateTime(data.next_visit)}
          </div>
        )}
        {data.patient.do_not_call && (
          <div className="text-xs font-medium text-red-700">{t('patients.dnc')}</div>
        )}
      </div>
    )
  }
  if (data.lead) {
    return (
      <div className="text-sm">
        <Link to="/leads" className="font-medium text-teal-800 hover:underline">
          {data.lead.name ?? t('phone.lead')}
        </Link>
        {data.lead.interest && <div className="text-xs text-slate-600">{data.lead.interest}</div>}
      </div>
    )
  }
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="text-slate-600">{t('phone.unknownCaller')}</span>
      <Button
        variant="secondary"
        className="px-2 py-1 text-xs"
        disabled={newLead.isPending}
        onClick={() => newLead.mutate()}
      >
        {t('phone.newLead')}
      </Button>
    </div>
  )
}

const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '*', '0', '#']

/** Floating card for the ringing / ongoing call. */
export function CallPanel() {
  const { t } = useTranslation()
  const phone = useSoftphone()
  const [keypad, setKeypad] = useState(false)
  const call = phone.call
  if (!call && phone.error) {
    return (
      <div
        className="fixed right-4 bottom-4 z-50 w-80 rounded-lg border border-red-200 bg-white p-4 shadow-xl"
        role="alert"
      >
        <p className="text-sm text-red-800">
          {t('phone.failed', { cause: t(`phone.causes.${phone.error}`, { defaultValue: phone.error }) })}
        </p>
        <Button variant="secondary" className="mt-2 px-2 py-1 text-xs" onClick={phone.clearError}>
          {t('phone.dismiss')}
        </Button>
      </div>
    )
  }
  if (!call) return null
  const ringing = call.state === 'ringing'
  return (
    <div
      className={`fixed right-4 bottom-4 z-50 w-80 rounded-lg border bg-white p-4 shadow-xl ${ringing ? 'border-emerald-400 ring-4 ring-emerald-100' : 'border-slate-200'}`}
      role="dialog"
      aria-live="assertive"
    >
      <div className="flex items-center justify-between text-xs text-slate-500">
        <span>
          {t(call.direction === 'incoming' ? 'phone.incoming' : 'phone.outgoing')} ·{' '}
          {t(`phone.state.${call.held ? 'held' : call.state}`)}
        </span>
        {call.startedAt && <Elapsed since={call.startedAt} />}
      </div>
      <div className="mt-1 text-lg font-semibold tabular-nums">{display(call.number)}</div>
      <div className="mt-2">
        <Caller number={call.number} />
      </div>
      {keypad && call.state === 'active' && (
        <div className="mt-3 grid grid-cols-3 gap-1">
          {KEYS.map((k) => (
            <Button key={k} variant="secondary" className="py-1" onClick={() => phone.dtmf(k)}>
              {k}
            </Button>
          ))}
        </div>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        {ringing && call.direction === 'incoming' && (
          <Button className="flex-1" onClick={phone.answer}>
            {t('phone.answer')}
          </Button>
        )}
        {call.state === 'active' && (
          <>
            <Button variant="secondary" onClick={phone.toggleMute}>
              {t(call.muted ? 'phone.unmute' : 'phone.mute')}
            </Button>
            <Button variant="secondary" onClick={phone.toggleHold}>
              {t(call.held ? 'phone.resume' : 'phone.hold')}
            </Button>
            <Button variant="secondary" onClick={() => setKeypad(!keypad)}>
              #
            </Button>
          </>
        )}
        <Button variant="danger" className="flex-1" onClick={phone.hangup}>
          {t(ringing && call.direction === 'incoming' ? 'phone.reject' : 'phone.hangup')}
        </Button>
      </div>
    </div>
  )
}

/** Click-to-call next to a phone number; renders nothing when the softphone isn't ready. */
export function CallButton({ number, taskId }: { number: string | null; taskId?: string }) {
  const { t } = useTranslation()
  const phone = useSoftphone()
  if (!number || phone.status !== 'registered') return null
  return (
    <Button
      variant="secondary"
      className="px-2 py-1 text-xs"
      disabled={Boolean(phone.call)}
      onClick={() => phone.dial(number, { taskId })}
    >
      {t('phone.call')}
    </Button>
  )
}
