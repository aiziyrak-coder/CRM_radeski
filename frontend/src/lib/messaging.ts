import { api } from './api'

export type Channel = 'telegram' | 'instagram' | 'sms'
export const CHANNELS: Channel[] = ['telegram', 'instagram', 'sms']

export interface ChannelsStatus {
  telegram: boolean
  instagram: boolean
  sms: string | null
  ai: boolean
}

export interface Conversation {
  id: string
  channel: Channel
  title: string | null
  phone: string | null
  patient_id: string | null
  patient_name: string | null
  lead_id: string | null
  last_message_at: string | null
  unread: number
  last_text: string | null
  last_direction: 'in' | 'out' | null
}

export interface ChatMessage {
  id: string
  direction: 'in' | 'out'
  text: string
  status: 'received' | 'queued' | 'sending' | 'sent' | 'delivered' | 'failed'
  template_code: string | null
  ai_draft: boolean
  sent_by_name: string | null
  error: string | null
  created_at: string
  sent_at: string | null
}

export interface MessageTemplate {
  id: string
  code: string
  language: 'uz' | 'ru'
  title: string
  text: string
  active: boolean
}

export const getChannelsStatus = () => api<ChannelsStatus>('/messaging/status')
export const getConversations = (filters: { channel?: string; unread?: boolean; q?: string }) => {
  const q = new URLSearchParams()
  if (filters.channel) q.set('channel', filters.channel)
  if (filters.unread) q.set('unread', 'true')
  // name (any script), @username, a part of the phone number or message text
  if (filters.q?.trim()) q.set('q', filters.q.trim())
  return api<Conversation[]>(`/messaging/conversations?${q}`)
}
export const getUnread = () => api<{ conversations: number }>('/messaging/unread')
export const getThread = (id: string) =>
  api<{ conversation: Conversation; messages: ChatMessage[] }>(`/messaging/conversations/${id}`)
export const sendMessage = (
  id: string,
  body: { text: string; template_code?: string | null; ai_draft?: boolean },
) => api<ChatMessage>(`/messaging/conversations/${id}/messages`, { method: 'POST', body })
export const aiDraft = (id: string) =>
  api<{ text: string }>(`/messaging/conversations/${id}/draft`, { method: 'POST' })
export const renderTemplate = (id: string, code: string) =>
  api<{ text: string }>(`/messaging/conversations/${id}/render`, { method: 'POST', body: { code } })
export const linkPatient = (id: string, patientId: string) =>
  api<Conversation>(`/messaging/conversations/${id}/patient`, {
    method: 'PUT',
    body: { patient_id: patientId },
  })
export const openSms = (patientId: string) =>
  api<Conversation>(`/messaging/patients/${patientId}/sms`, { method: 'POST' })
export const getTemplates = () => api<MessageTemplate[]>('/messaging/templates')
export const updateTemplate = (id: string, body: Pick<MessageTemplate, 'title' | 'text' | 'active'>) =>
  api<MessageTemplate>(`/messaging/templates/${id}`, { method: 'PUT', body })
