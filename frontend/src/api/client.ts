import { ApiError } from './errors'
import { tokenStore } from './tokenStore'
import type { TokenResponse } from './types'

const BASE = '/api/v1'

type Query = Record<string, string | number | boolean | null | undefined>

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  query?: Query
  body?: unknown
  headers?: Record<string, string>
  /** Public endpoints (login, signup, accept) skip the bearer header and the refresh-retry. */
  auth?: boolean
}

let authFailureHandler: (() => void) | null = null
let refreshInFlight: Promise<TokenResponse | null> | null = null

/** Called once when a refresh fails and the session is gone, so the app can go to /login. */
export function setAuthFailureHandler(handler: (() => void) | null): void {
  authFailureHandler = handler
}

function buildUrl(path: string, query?: Query): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value))
  }
  const qs = params.toString()
  return `${BASE}${path}${qs ? `?${qs}` : ''}`
}

async function toApiError(res: Response): Promise<ApiError> {
  const retryHeader = res.headers.get('Retry-After')
  const retryAfter = retryHeader !== null && /^\d+$/.test(retryHeader) ? Number(retryHeader) : null
  let envelope: { error?: { code?: string; message?: string; request_id?: string } } = {}
  try {
    envelope = await res.json()
  } catch {
    // Non-JSON body (e.g. a proxy error page): fall back to a generic error below.
  }
  return new ApiError({
    code: envelope.error?.code ?? 'HTTP_ERROR',
    message: envelope.error?.message ?? `Request failed with status ${res.status}`,
    status: res.status,
    requestId: envelope.error?.request_id ?? null,
    retryAfter,
  })
}

async function send(path: string, options: RequestOptions, withToken: boolean): Promise<Response> {
  const headers: Record<string, string> = { Accept: 'application/json', ...options.headers }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  const token = tokenStore.get()
  if (withToken && token) headers.Authorization = `Bearer ${token}`
  try {
    return await fetch(buildUrl(path, options.query), {
      method: options.method ?? 'GET',
      headers,
      credentials: 'include',
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    })
  } catch {
    throw new ApiError({
      code: 'NETWORK_ERROR',
      message: 'Could not reach the server. Check your connection and retry.',
      status: 0,
    })
  }
}

/**
 * Exchanges the refresh cookie for a new access token. Concurrent callers share one
 * in-flight request. Resolves to null (never rejects) when there is no valid session.
 */
export function refreshSession(): Promise<TokenResponse | null> {
  refreshInFlight ??= (async () => {
    try {
      const res = await send('/auth/refresh', { method: 'POST' }, false)
      if (!res.ok) return null
      const data = (await res.json()) as TokenResponse
      tokenStore.set(data.access_token)
      return data
    } catch {
      return null
    } finally {
      refreshInFlight = null
    }
  })()
  return refreshInFlight
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const useAuth = options.auth !== false
  let res = await send(path, options, useAuth)

  if (useAuth && res.status === 401) {
    const failure = await toApiError(res.clone())
    if (failure.code === 'INVALID_TOKEN') {
      const refreshed = await refreshSession()
      if (!refreshed) {
        tokenStore.set(null)
        authFailureHandler?.()
        throw failure
      }
      res = await send(path, options, true)
    }
  }

  if (!res.ok) throw await toApiError(res)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}
