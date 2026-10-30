import type {
  BoardDetail,
  BoardRead,
  MemberRead,
  OrganizationSummary,
  Role,
  TaskRead,
  TokenResponse,
} from '../api/types'

export const ORG_A: OrganizationSummary = { id: 'org-a', name: 'Acme', slug: 'acme', role: 'admin' }
export const ORG_B: OrganizationSummary = {
  id: 'org-b',
  name: 'Beta',
  slug: 'beta',
  role: 'member',
}

export const USERS = {
  admin: { id: 'u-admin', email: 'ada@acme.test', full_name: 'Ada Admin' },
  manager: { id: 'u-manager', email: 'max@acme.test', full_name: 'Max Manager' },
  member: { id: 'u-member', email: 'mia@acme.test', full_name: 'Mia Member' },
} as const

export function token(role: Role, organizationId = 'org-a', access = 'access-1'): TokenResponse {
  return {
    access_token: access,
    token_type: 'bearer',
    expires_in: 900,
    organization_id: organizationId,
    role,
  }
}

export function meFor(role: Role) {
  return {
    user: USERS[role],
    active_organization: { ...ORG_A, role },
    organizations: [{ ...ORG_A, role }, ORG_B],
  }
}

export const MEMBERS: MemberRead[] = (['admin', 'manager', 'member'] as const).map((role) => ({
  user_id: USERS[role].id,
  email: USERS[role].email,
  full_name: USERS[role].full_name,
  role,
  joined_at: '2026-01-01T00:00:00Z',
}))

export const BOARD_LIST_ITEM: BoardRead = {
  id: 'b1',
  name: 'Roadmap',
  description: null,
  is_archived: false,
  created_by: USERS.admin.id,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

export const BOARD: BoardDetail = {
  ...BOARD_LIST_ITEM,
  columns: [
    {
      id: 'c-todo',
      board_id: 'b1',
      name: 'To Do',
      position: 0,
      created_at: '2026-01-01T00:00:00Z',
    },
    {
      id: 'c-doing',
      board_id: 'b1',
      name: 'Doing',
      position: 1,
      created_at: '2026-01-01T00:00:00Z',
    },
    { id: 'c-done', board_id: 'b1', name: 'Done', position: 2, created_at: '2026-01-01T00:00:00Z' },
  ],
}

export function makeTask(
  overrides: Partial<TaskRead> & Pick<TaskRead, 'id' | 'column_id'>,
): TaskRead {
  return {
    board_id: 'b1',
    title: overrides.id,
    description: null,
    priority: 'medium',
    position: 0,
    assignee_id: null,
    due_date: null,
    created_by: USERS.admin.id,
    created_at: '2026-01-02T00:00:00Z',
    updated_at: '2026-01-02T00:00:00Z',
    ...overrides,
  }
}

/** Alpha (unassigned) and Beta (assigned to the member) in To Do, Gamma in Doing. */
export const TASKS: TaskRead[] = [
  makeTask({ id: 't-alpha', title: 'Alpha', column_id: 'c-todo', position: 0 }),
  makeTask({
    id: 't-beta',
    title: 'Beta',
    column_id: 'c-todo',
    position: 1,
    assignee_id: USERS.member.id,
    priority: 'high',
    due_date: '2026-12-01',
  }),
  makeTask({ id: 't-gamma', title: 'Gamma', column_id: 'c-doing', position: 0 }),
]
