// Admin integrations page: status of every external connection and safe read-only tests.
import { api } from './api'

export type IntegrationKey =
  | 'telephony'
  | 'trunk'
  | 'openai'
  | 'telegram'
  | 'instagram'
  | 'sms'
  | 'site_webhook'
  | 'site_polling'
  | 'catalog_sync'

export type IntegrationState = 'ok' | 'warning' | 'error' | 'off'

export type Integration = {
  key: IntegrationKey
  configured: boolean
  state: IntegrationState
  /** .env variables still empty */
  missing: string[]
  facts: Record<string, string | number | boolean | null>
  /** which safe test the "Tekshirish" button runs (null: none) */
  test: string | null
  docs: string
}

export type TestResult =
  | { ok: true; result: Record<string, string | number | boolean | null> }
  | { ok: false; error: string; message: string | null }

export const getIntegrations = () => api<Integration[]>('/system/integrations')
export const testIntegration = (key: string) =>
  api<TestResult>(`/system/integrations/${key}/test`, { method: 'POST' })
