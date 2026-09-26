import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import i18n from '../i18n'
import {
  api,
  refreshSession,
  setAccessToken,
  setSessionHandlers,
  type TokenResponse,
  type User,
} from './api'
import { AuthContext, type LogoutReason, type Status } from './auth-context'

// TZ 5: the session closes after 30 minutes without user activity
const IDLE_LIMIT_MS = 30 * 60 * 1000
const ACTIVITY_EVENTS = ['mousedown', 'keydown', 'touchstart', 'wheel'] as const

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<Status>('loading')
  const [user, setUserState] = useState<User | null>(null)
  const [logoutReason, setLogoutReason] = useState<LogoutReason | null>(null)
  const lastActivity = useRef(0)

  const applyUser = useCallback((u: User) => {
    setUserState(u)
    if (i18n.language !== u.language) void i18n.changeLanguage(u.language)
  }, [])

  const applyToken = useCallback(
    (t: TokenResponse) => {
      setAccessToken(t.access_token)
      applyUser(t.user)
      setStatus('authenticated')
    },
    [applyUser],
  )

  const clearSession = useCallback(
    (reason: LogoutReason) => {
      setAccessToken(null)
      setUserState(null)
      setLogoutReason(reason)
      setStatus('anonymous')
      queryClient.clear()
    },
    [queryClient],
  )

  const logout = useCallback(
    async (reason: LogoutReason = 'manual') => {
      try {
        await api('/auth/logout', { method: 'POST' })
      } catch {
        // server unreachable — still drop the local session
      }
      clearSession(reason)
    },
    [clearSession],
  )

  const login = useCallback(
    async (username: string, password: string) => {
      const t = await api<TokenResponse>('/auth/login', {
        method: 'POST',
        body: { username, password },
      })
      setLogoutReason(null)
      applyToken(t)
    },
    [applyToken],
  )

  // restore the session from the refresh cookie on page load
  useEffect(() => {
    setSessionHandlers({ expired: () => clearSession('expired'), refreshed: applyToken })
    void refreshSession().then((t) => {
      if (!t) setStatus('anonymous')
    })
  }, [applyToken, clearSession])

  // idle logout
  useEffect(() => {
    if (status !== 'authenticated') return
    lastActivity.current = Date.now()
    const touch = () => {
      lastActivity.current = Date.now()
    }
    ACTIVITY_EVENTS.forEach((e) => window.addEventListener(e, touch, { passive: true }))
    const timer = window.setInterval(() => {
      if (Date.now() - lastActivity.current > IDLE_LIMIT_MS) void logout('idle')
    }, 30_000)
    return () => {
      ACTIVITY_EVENTS.forEach((e) => window.removeEventListener(e, touch))
      window.clearInterval(timer)
    }
  }, [status, logout])

  const value = useMemo(
    () => ({ status, user, logoutReason, login, logout, setUser: applyUser }),
    [status, user, logoutReason, login, logout, applyUser],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
