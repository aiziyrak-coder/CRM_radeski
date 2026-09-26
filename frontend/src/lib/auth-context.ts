import { createContext, useContext } from 'react'
import type { TotpChallenge, User } from './api'

export type Status = 'loading' | 'authenticated' | 'anonymous'

/** Window event that counts as user activity for the idle logout (e.g. an ongoing phone call). */
export const ACTIVITY_EVENT = 'crm:activity'
export type LogoutReason = 'manual' | 'expired' | 'idle'

export type AuthContextValue = {
  status: Status
  user: User | null
  logoutReason: LogoutReason | null
  /** resolves with a challenge when an authenticator code is still needed */
  login: (username: string, password: string) => Promise<TotpChallenge | null>
  verifyTotp: (challenge: string, code: string) => Promise<void>
  logout: (reason?: LogoutReason) => Promise<void>
  setUser: (user: User) => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
