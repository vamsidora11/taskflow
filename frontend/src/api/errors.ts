export class ApiError extends Error {
  readonly code: string
  readonly status: number
  readonly requestId: string | null
  readonly retryAfter: number | null

  constructor(init: {
    code: string
    message: string
    status: number
    requestId?: string | null
    retryAfter?: number | null
  }) {
    super(init.message)
    this.name = 'ApiError'
    this.code = init.code
    this.status = init.status
    this.requestId = init.requestId ?? null
    this.retryAfter = init.retryAfter ?? null
  }
}

const FRIENDLY: Record<string, string> = {
  COLUMN_NOT_EMPTY: 'This column still has tasks. Move or delete them first, then try again.',
  BOARD_ARCHIVED: 'This board is archived and can no longer be changed.',
  LAST_ADMIN: 'An organization must keep at least one admin, so this change was blocked.',
}

/** Human-readable text for any thrown value, with a friendly message for rate limiting. */
export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 429) {
      const wait = error.retryAfter
      return wait !== null
        ? `Slow down: too many requests. Retry in ${wait} s.`
        : 'Slow down: too many requests. Please retry shortly.'
    }
    return FRIENDLY[error.code] ?? error.message
  }
  return 'Something went wrong. Please try again.'
}
