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

export const useSystemStatus = (enabled = true) =>
  useQuery({
    queryKey: ['system', 'status'],
    queryFn: () => api<SystemStatus>('/system/status'),
    refetchInterval: 60_000,
    enabled,
  })
