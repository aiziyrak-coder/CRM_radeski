import { useQuery } from '@tanstack/react-query'
import { api } from './api'

export type SystemStatus = {
  today: {
    missed_calls: number
    unread_chats: number
    missed_open?: number
    leads_sla_breached?: number
  }
  qa?: { red_flags_open: number }
  integrations?: {
    telephony: boolean
    trunk: boolean
    last_call_at: string | null
    ai: boolean
    ai_spent_today_usd?: number
    ai_daily_budget_usd?: number
    telegram: boolean
    instagram: boolean
    sms: string | null
  }
  attention?: {
    recordings_failed: number
    analyses_failed: number
    messages_failed: number
    messages_queued: number
  }
}

// roles the backend lets read /system/status
export const STATUS_ROLES = ['operator', 'supervisor', 'owner', 'admin']

export type SetupStatus = 'ok' | 'partial' | 'todo' | 'off'
export type SetupItem = {
  key: string
  status: SetupStatus
  /** page where it is fixed; null = only on the server (.env) */
  link: string | null
  done?: number
  total?: number
  [detail: string]: unknown
}
export type SetupChecklist = { items: SetupItem[]; done: number; total: number }
export const getSetup = () => api<SetupChecklist>('/system/setup')

export type TodayVisits = {
  scope: 'all' | 'branch' | 'doctor'
  branch_id: string | null
  /** a doctor account not linked to a doctor of the catalog sees nothing */
  linked: boolean
  counts: Record<
    | 'scheduled'
    | 'confirmed'
    | 'arrived'
    | 'completed'
    | 'no_show'
    | 'cancelled'
    | 'rescheduled'
    | 'expected'
    | 'came'
    | 'total',
    number
  >
  next_at: string | null
}
export const getTodayVisits = () => api<TodayVisits>('/system/today')

export const useSystemStatus = (enabled = true) =>
  useQuery({
    queryKey: ['system', 'status'],
    queryFn: () => api<SystemStatus>('/system/status'),
    refetchInterval: 60_000,
    enabled,
  })
