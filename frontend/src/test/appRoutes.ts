import type { Role } from '../api/types'
import { BOARD, BOARD_LIST_ITEM, MEMBERS, TASKS, meFor, token } from './fixtures'
import type { Routes } from './mockFetch'

/** Happy-path API for a signed-in user of the given role; tests override single routes. */
export function appRoutes(role: Role, overrides: Routes = {}): Routes {
  return {
    'POST /api/v1/auth/refresh': () => ({ body: token(role) }),
    'GET /api/v1/auth/me': () => ({ body: meFor(role) }),
    'GET /api/v1/boards': () => ({ body: { items: [BOARD_LIST_ITEM], next_cursor: null } }),
    'GET /api/v1/boards/:id': () => ({ body: BOARD }),
    'GET /api/v1/boards/:id/tasks': () => ({ body: { items: TASKS, next_cursor: null } }),
    'GET /api/v1/org/members': () => ({ body: { items: MEMBERS, next_cursor: null } }),
    'GET /api/v1/tasks/:id': (req) => ({
      body: TASKS.find((t) => req.path.endsWith(t.id)),
    }),
    'GET /api/v1/tasks/:id/comments': () => ({ body: { items: [], next_cursor: null } }),
    ...overrides,
  }
}
