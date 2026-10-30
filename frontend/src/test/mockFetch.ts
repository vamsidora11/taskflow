import { vi } from 'vitest'

export interface MockRequest {
  method: string
  path: string
  query: URLSearchParams
  headers: Headers
  body: unknown
}

export interface MockResponse {
  status?: number
  body?: unknown
  headers?: Record<string, string>
}

export type Handler = (req: MockRequest) => MockResponse | Promise<MockResponse>
export type Routes = Record<string, Handler>

export function errorBody(code: string, message: string, status: number): MockResponse {
  return { status, body: { error: { code, message, request_id: 'req-test' } } }
}

function toRegExp(pattern: string): RegExp {
  return new RegExp(`^${pattern.replace(/:[a-z_]+/g, '[^/]+')}$`)
}

/**
 * Replaces global fetch with an in-memory router. Keys look like "GET /api/v1/boards/:id".
 * Unmatched requests answer 501 so a missing handler fails loudly instead of hitting the network.
 */
export function mockFetch(routes: Routes) {
  const compiled = Object.entries(routes).map(([key, handler]) => {
    const [method, pattern] = key.split(' ')
    return { method, regexp: toRegExp(pattern), handler }
  })
  const calls: MockRequest[] = []

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost')
    const headers = new Headers(init?.headers)
    const raw = typeof init?.body === 'string' ? init.body : undefined
    const req: MockRequest = {
      method: init?.method ?? 'GET',
      path: url.pathname,
      query: url.searchParams,
      headers,
      body: raw ? JSON.parse(raw) : undefined,
    }
    calls.push(req)
    const route = compiled.find((r) => r.method === req.method && r.regexp.test(req.path))
    const out = route
      ? await route.handler(req)
      : errorBody('NO_MOCK', `No mock for ${req.method} ${req.path}`, 501)
    const status = out.status ?? 200
    return new Response(status === 204 ? null : JSON.stringify(out.body ?? {}), {
      status,
      headers: { 'Content-Type': 'application/json', ...out.headers },
    })
  })

  vi.stubGlobal('fetch', fetchMock)
  const count = (method: string, path: string) =>
    calls.filter((c) => c.method === method && c.path === path).length
  return { fetchMock, calls, count }
}
