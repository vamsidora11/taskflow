import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { request, setAuthFailureHandler } from './client'
import { ApiError } from './errors'
import { tokenStore } from './tokenStore'
import { errorBody, mockFetch } from '../test/mockFetch'
import { token } from '../test/fixtures'

const unauthorized = () => errorBody('INVALID_TOKEN', 'Token expired', 401)

describe('api client', () => {
  const onAuthFailure = vi.fn()

  beforeEach(() => {
    onAuthFailure.mockReset()
    setAuthFailureHandler(onAuthFailure)
  })
  afterEach(() => setAuthFailureHandler(null))

  it('sends the in-memory token as a bearer header and includes credentials', async () => {
    tokenStore.set('abc')
    const api = mockFetch({ 'GET /api/v1/boards': () => ({ body: { items: [] } }) })
    await request('/boards', { query: { limit: 5, cursor: null } })
    const [url, init] = api.fetchMock.mock.calls[0]
    expect(String(url)).toBe('/api/v1/boards?limit=5')
    expect(api.calls[0].headers.get('Authorization')).toBe('Bearer abc')
    expect(init?.credentials).toBe('include')
  })

  it('shares ONE refresh between 5 concurrent 401s, then retries each request once', async () => {
    tokenStore.set('old')
    const api = mockFetch({
      'GET /api/v1/boards': (req) =>
        req.headers.get('Authorization') === 'Bearer new'
          ? { body: { items: ['ok'] } }
          : unauthorized(),
      'POST /api/v1/auth/refresh': async () => {
        await new Promise((resolve) => setTimeout(resolve, 20))
        return { body: token('admin', 'org-a', 'new') }
      },
    })

    const results = await Promise.all(Array.from({ length: 5 }, () => request('/boards')))

    expect(results).toHaveLength(5)
    expect(api.count('POST', '/api/v1/auth/refresh')).toBe(1)
    expect(api.count('GET', '/api/v1/boards')).toBe(10) // 5 originals + 5 retries
    expect(tokenStore.get()).toBe('new')
    expect(onAuthFailure).not.toHaveBeenCalled()
  })

  it('calls the logout callback once and does not retry when the refresh fails', async () => {
    tokenStore.set('old')
    const api = mockFetch({
      'GET /api/v1/boards': unauthorized,
      'POST /api/v1/auth/refresh': () => errorBody('INVALID_TOKEN', 'Session expired', 401),
    })

    const outcomes = await Promise.allSettled([request('/boards'), request('/boards')])

    expect(outcomes.every((o) => o.status === 'rejected')).toBe(true)
    expect(api.count('POST', '/api/v1/auth/refresh')).toBe(1)
    expect(api.count('GET', '/api/v1/boards')).toBe(2) // no retries
    expect(onAuthFailure).toHaveBeenCalled()
    expect(tokenStore.get()).toBeNull()
  })

  it('does not loop when the retried request is still unauthorized', async () => {
    tokenStore.set('old')
    const api = mockFetch({
      'GET /api/v1/boards': unauthorized,
      'POST /api/v1/auth/refresh': () => ({ body: token('admin', 'org-a', 'new') }),
    })

    await expect(request('/boards')).rejects.toMatchObject({ status: 401, code: 'INVALID_TOKEN' })
    expect(api.count('GET', '/api/v1/boards')).toBe(2)
    expect(api.count('POST', '/api/v1/auth/refresh')).toBe(1)
  })

  it('turns the error envelope into a typed ApiError (with Retry-After on 429)', async () => {
    mockFetch({
      'GET /api/v1/boards': () => ({
        ...errorBody('RATE_LIMITED', 'Too many requests', 429),
        headers: { 'Retry-After': '7' },
      }),
    })
    const error = await request('/boards').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({
      code: 'RATE_LIMITED',
      message: 'Too many requests',
      status: 429,
      requestId: 'req-test',
      retryAfter: 7,
    })
  })

  it('does not try to refresh for public endpoints such as login', async () => {
    const api = mockFetch({
      'POST /api/v1/auth/login': () => errorBody('INVALID_TOKEN', 'Bad credentials', 401),
    })
    await expect(
      request('/auth/login', { method: 'POST', body: {}, auth: false }),
    ).rejects.toBeInstanceOf(ApiError)
    expect(api.count('POST', '/api/v1/auth/refresh')).toBe(0)
    expect(onAuthFailure).not.toHaveBeenCalled()
  })

  it('returns undefined for 204 and wraps network failures as ApiError', async () => {
    mockFetch({ 'DELETE /api/v1/tasks/1': () => ({ status: 204 }) })
    await expect(request('/tasks/1', { method: 'DELETE' })).resolves.toBeUndefined()

    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')))
    await expect(request('/boards')).rejects.toMatchObject({ code: 'NETWORK_ERROR', status: 0 })
  })
})
