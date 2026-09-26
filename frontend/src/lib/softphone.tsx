import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { UA } from 'jssip'
import type { RTCSession } from 'jssip/lib/RTCSession'
import type { RTCSessionEvent, UnRegisteredEvent } from 'jssip/lib/UA'
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { ACTIVITY_EVENT, useAuth } from './auth-context'
import { SoftphoneContext, type ActiveCall, type PhoneStatus, type Softphone } from './softphone-context'
import { dialable, getSoftphone } from './telephony'

const CALL_CENTER = ['operator', 'supervisor', 'admin']
const MEDIA = { mediaConstraints: { audio: true, video: false } }
// the PBX has a public address; no STUN/TURN round trips are needed
const PC_CONFIG = { pcConfig: { iceServers: [] } }
// re-REGISTER after a failure (PBX restart, rotated secret): 5 s, 10 s, 30 s, then every minute
const RETRY_DELAYS_MS = [5_000, 10_000, 30_000, 60_000]
const AUTH_FAILED = [401, 403, 407]

/** Two-tone ring for an incoming call, made with WebAudio (no sound file to ship). */
function startRinging(): () => void {
  const ctx = new AudioContext()
  const beep = () => {
    for (const [freq, at] of [
      [440, 0],
      [480, 0.45],
    ]) {
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.frequency.value = freq
      gain.gain.value = 0.08
      osc.connect(gain).connect(ctx.destination)
      osc.start(ctx.currentTime + at)
      osc.stop(ctx.currentTime + at + 0.4)
    }
  }
  beep()
  const timer = window.setInterval(beep, 2500)
  return () => {
    window.clearInterval(timer)
    void ctx.close()
  }
}

export function SoftphoneProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const userId = user?.id
  const allowed = Boolean(user && CALL_CENTER.includes(user.role))
  const { data: creds } = useQuery({
    queryKey: ['softphone', userId],
    queryFn: getSoftphone,
    enabled: allowed,
    staleTime: Infinity,
    retry: false,
  })
  const [status, setStatus] = useState<PhoneStatus>('connecting')
  const [call, setCall] = useState<ActiveCall | null>(null)
  const [error, setError] = useState<string | null>(null)
  const ua = useRef<UA | null>(null)
  const session = useRef<RTCSession | null>(null)
  const audio = useRef<HTMLAudioElement | null>(null)
  const stopRing = useRef<(() => void) | null>(null)
  const enabled = allowed && Boolean(creds?.enabled)
  // fresh credentials (rotated SIP secret, extension changed) restart the SIP agent, which
  // would hang up a call in progress: they are applied only once the line is free
  const fetched =
    enabled && creds?.extension && creds.password
      ? { extension: creds.extension, password: creds.password }
      : null
  const [applied, setApplied] = useState(fetched)
  const fetchedKey = fetched ? `${fetched.extension}:${fetched.password}` : ''
  const appliedKey = applied ? `${applied.extension}:${applied.password}` : ''
  const lineBusy = call !== null
  // derived during render (React's "adjust state on prop change"), not in an effect
  if (!lineBusy && fetchedKey !== appliedKey) setApplied(fetched)
  const extension = applied?.extension ?? null
  const password = applied?.password ?? null

  const attach = useCallback((s: RTCSession, incoming: boolean, taskId: string | null) => {
    session.current = s
    const playRemote = (pc: RTCPeerConnection) =>
      pc.addEventListener('track', (e) => {
        if (audio.current && e.streams[0]) audio.current.srcObject = e.streams[0]
      })
    if (s.connection) playRemote(s.connection as unknown as RTCPeerConnection)
    s.on('peerconnection', (e) => playRemote(e.peerconnection as unknown as RTCPeerConnection))

    const patch = (p: Partial<ActiveCall>) => setCall((c) => (c && c.id === s.id ? { ...c, ...p } : c))
    const finish = () => {
      stopRing.current?.()
      stopRing.current = null
      if (session.current === s) session.current = null
      setCall((c) => (c?.id === s.id ? null : c))
    }
    s.on('accepted', () => {
      stopRing.current?.()
      stopRing.current = null
      patch({ state: 'active', startedAt: Date.now() })
    })
    s.on('ended', finish)
    s.on('failed', (e) => {
      // hanging up / rejecting yourself is not an error; a missing microphone is
      if (e.cause !== 'Canceled' && e.cause !== 'Rejected') setError(e.cause)
      finish()
    })
    s.on('hold', () => patch({ held: true }))
    s.on('unhold', () => patch({ held: false }))
    s.on('muted', () => patch({ muted: true }))
    s.on('unmuted', () => patch({ muted: false }))

    setError(null)
    setCall({
      id: s.id,
      direction: incoming ? 'incoming' : 'outgoing',
      number: s.remote_identity.uri.user,
      state: incoming ? 'ringing' : 'calling',
      startedAt: null,
      muted: false,
      held: false,
      taskId,
    })
    if (incoming) stopRing.current = startRinging()
  }, [])

  useEffect(() => {
    if (!extension || !password) return
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    let agent: UA | null = null
    let cancelled = false
    let retryTimer: number | undefined
    let failures = 0
    // JsSIP is loaded only for users who actually have a softphone
    void import('jssip').then(({ UA, WebSocketInterface }) => {
      if (cancelled) return
      agent = new UA({
        sockets: [new WebSocketInterface(`${proto}://${window.location.host}/ws`)],
        uri: `sip:${extension}@${window.location.hostname}`,
        password,
        register: true,
        register_expires: 120,
        session_timers: false,
        user_agent: 'Radeski CRM',
      })
      // a stopped agent (credentials changed, logout) may still report; only the live one counts
      agent.on('connecting', () => !cancelled && setStatus('connecting'))
      agent.on('registered', () => {
        if (cancelled) return
        failures = 0
        window.clearTimeout(retryTimer)
        setStatus('registered')
      })
      agent.on('unregistered', () => !cancelled && setStatus('offline'))
      agent.on('registrationFailed', (e: UnRegisteredEvent) => {
        if (cancelled) return
        setStatus('offline')
        const code = e.response?.status_code
        if ((code && AUTH_FAILED.includes(code)) || e.cause === 'Authentication Error') {
          // the SIP password may have been rotated: fetch fresh credentials (a new one restarts the UA)
          void queryClient.invalidateQueries({ queryKey: ['softphone', userId] })
        }
        const delay = RETRY_DELAYS_MS[Math.min(failures, RETRY_DELAYS_MS.length - 1)]
        failures += 1
        window.clearTimeout(retryTimer)
        retryTimer = window.setTimeout(() => {
          // while disconnected JsSIP reconnects the socket itself and registers on connect
          if (!cancelled && agent?.isConnected() && !agent.isRegistered()) agent.register()
        }, delay)
      })
      agent.on('disconnected', () => !cancelled && setStatus('offline'))
      agent.on('newRTCSession', (e: RTCSessionEvent) => {
        if (cancelled) return
        if (e.originator !== 'remote') return // outgoing sessions are attached in dial()
        if (session.current) {
          e.session.terminate({ status_code: 486, reason_phrase: 'Busy Here' })
          return
        }
        attach(e.session, true, null)
      })
      agent.start()
      ua.current = agent
    })
    return () => {
      cancelled = true
      window.clearTimeout(retryTimer)
      session.current?.terminate()
      agent?.stop()
      ua.current = null
    }
  }, [extension, password, attach, queryClient, userId])

  // a conversation is activity: the idle logout must not end the session mid-call (a phone
  // ringing at an empty desk is not)
  const inCall = call?.state === 'active' || call?.state === 'calling'
  useEffect(() => {
    if (!inCall) return
    const ping = () => window.dispatchEvent(new Event(ACTIVITY_EVENT))
    ping()
    const timer = window.setInterval(ping, 30_000)
    return () => {
      window.clearInterval(timer)
      ping() // the idle window starts when the call ends
    }
  }, [inCall])

  const value = useMemo<Softphone>(() => {
    const current = () => session.current
    return {
      status: enabled ? status : 'disabled',
      extension,
      call,
      error,
      dial: (number, options) => {
        const target = dialable(number)
        if (!ua.current || session.current || !target) return
        const extraHeaders = options?.taskId ? [`X-CRM-Task: ${options.taskId}`] : []
        const s = ua.current.call(`sip:${target}@${window.location.hostname}`, {
          ...MEDIA,
          ...PC_CONFIG,
          extraHeaders,
        })
        attach(s, false, options?.taskId ?? null)
      },
      answer: () => current()?.answer({ ...MEDIA, ...PC_CONFIG }),
      hangup: () => current()?.terminate(),
      toggleMute: () => {
        const s = current()
        if (s) (s.isMuted().audio ? s.unmute : s.mute).call(s, { audio: true })
      },
      toggleHold: () => {
        const s = current()
        if (s) (s.isOnHold().local ? s.unhold : s.hold).call(s)
      },
      dtmf: (tone) => current()?.sendDTMF(tone),
      clearError: () => setError(null),
    }
  }, [enabled, status, extension, call, error, attach])

  return (
    <SoftphoneContext.Provider value={value}>
      {children}
      <audio ref={audio} autoPlay hidden />
    </SoftphoneContext.Provider>
  )
}
