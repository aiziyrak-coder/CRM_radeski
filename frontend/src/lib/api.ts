// Thin fetch wrapper: attaches the in-memory access token, refreshes it once on 401
// (refresh token lives in an httpOnly cookie scoped to /api/auth), and reports expiry.

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  /** full error body, e.g. duplicate candidates on 409 */
  readonly data: Record<string, unknown>

  constructor(status: number, code: string, data: Record<string, unknown> = {}) {
    super(code)
    this.status = status
    this.code = code
    this.data = data
  }
}

export type TokenResponse = {
  access_token: string
  token_type: string
  expires_in: number
  user: User
}

/** Admins and the owner get this instead of tokens: the authenticator code is the second step. */
export type TotpChallenge = {
  totp_required: true
  challenge: string
  setup: boolean
  otpauth_uri: string | null
  qr: string | null
  secret: string | null
}

export type Role = 'operator' | 'supervisor' | 'registrar' | 'doctor' | 'owner' | 'admin'
export type Language = 'uz' | 'ru'

export type User = {
  id: string
  username: string
  full_name: string
  role: Role
  language: Language
  branch_id: string | null
  is_active: boolean
  sip_extension: string | null
  totp_enabled: boolean
  last_login_at: string | null
  created_at: string
}

let accessToken: string | null = null
let refreshing: Promise<TokenResponse | null> | null = null
let onSessionExpired: (() => void) | null = null
let onTokenRefreshed: ((t: TokenResponse) => void) | null = null

export function setAccessToken(token: string | null) {
  accessToken = token
}

export const getAccessToken = () => accessToken

export function setSessionHandlers(handlers: { expired: () => void; refreshed: (t: TokenResponse) => void }) {
  onSessionExpired = handlers.expired
  onTokenRefreshed = handlers.refreshed
}

async function parseError(resp: Response): Promise<ApiError> {
  let code = `http_${resp.status}`
  let data: Record<string, unknown> = {}
  try {
    data = await resp.json()
    if (typeof data?.detail === 'string') code = data.detail
    else if (Array.isArray(data?.detail)) {
      // pydantic: "Value error, invalid_phone" -> "invalid_phone"
      const custom = (data.detail as { msg?: string }[])
        .map((d) => d.msg?.match(/^Value error, ([a-z_]+)$/)?.[1])
        .find(Boolean)
      code = custom ?? 'validation_error'
    }
  } catch {
    // non-JSON error body
  }
  return new ApiError(resp.status, code, data)
}

async function doRefresh(): Promise<TokenResponse | null> {
  const attempt = () => fetch('/api/auth/refresh', { method: 'POST', credentials: 'include' })
  let resp = await attempt()
  if (resp.status === 401) {
    // another tab may have rotated the cookie a moment ago — retry once with the new one
    await new Promise((r) => setTimeout(r, 400))
    resp = await attempt()
  }
  if (!resp.ok) return null
  const data = (await resp.json()) as TokenResponse
  accessToken = data.access_token
  onTokenRefreshed?.(data)
  return data
}

/** Single-flight refresh: concurrent 401s share one refresh request. */
export function refreshSession(): Promise<TokenResponse | null> {
  refreshing ??= doRefresh().finally(() => {
    refreshing = null
  })
  return refreshing
}

export async function api<T>(
  path: string,
  options: { method?: string; body?: unknown; retry?: boolean } = {},
): Promise<T> {
  const { method = 'GET', body, retry = true } = options
  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`

  const resp = await fetch(`/api${path}`, {
    method,
    headers,
    credentials: 'include',
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  if (resp.status === 401 && retry && !path.startsWith('/auth/')) {
    const refreshed = await refreshSession()
    if (refreshed) return api<T>(path, { ...options, retry: false })
    onSessionExpired?.()
  }
  if (!resp.ok) throw await parseError(resp)
  if (resp.status === 204) return undefined as T
  return (await resp.json()) as T
}

/** A file download (Excel, audio) with the same session handling and error codes as `api`. */
export async function apiBlob(path: string, retry = true): Promise<Blob> {
  const resp = await fetch(`/api${path}`, {
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
    credentials: 'include',
  })
  if (resp.status === 401 && retry) {
    if (await refreshSession()) return apiBlob(path, false)
    onSessionExpired?.()
  }
  if (!resp.ok) throw await parseError(resp)
  return resp.blob()
}
