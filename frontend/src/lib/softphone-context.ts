import { createContext, useContext } from 'react'

/** disabled: no extension or telephony off; offline: registration lost (network, PBX restart) */
export type PhoneStatus = 'disabled' | 'connecting' | 'registered' | 'offline'

export interface ActiveCall {
  id: string
  direction: 'incoming' | 'outgoing'
  number: string
  state: 'ringing' | 'calling' | 'active'
  startedAt: number | null
  muted: boolean
  held: boolean
  taskId: string | null
}

export interface Softphone {
  status: PhoneStatus
  extension: string | null
  call: ActiveCall | null
  error: string | null
  dial: (number: string, options?: { taskId?: string }) => void
  answer: () => void
  hangup: () => void
  toggleMute: () => void
  toggleHold: () => void
  dtmf: (tone: string) => void
  clearError: () => void
}

const noop = () => undefined

export const SoftphoneContext = createContext<Softphone>({
  status: 'disabled',
  extension: null,
  call: null,
  error: null,
  dial: noop,
  answer: noop,
  hangup: noop,
  toggleMute: noop,
  toggleHold: noop,
  dtmf: noop,
  clearError: noop,
})

export const useSoftphone = () => useContext(SoftphoneContext)
