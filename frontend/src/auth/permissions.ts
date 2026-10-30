import type { Role } from '../api/types'

/** Single source of truth for the RBAC matrix (PLAN.md section 5). The backend enforces it. */
export type Permission =
  | 'org:update'
  | 'member:view'
  | 'member:invite'
  | 'member:remove'
  | 'member:change_role'
  | 'board:view'
  | 'board:manage'
  | 'task:view'
  | 'task:create'
  | 'task:edit_any'
  | 'task:delete'
  | 'comment:create'
  | 'comment:delete_any'
  | 'audit:view'

const ALL: readonly Role[] = ['admin', 'manager', 'member']
const LEADS: readonly Role[] = ['admin', 'manager']
const ADMIN: readonly Role[] = ['admin']

const MATRIX: Record<Permission, readonly Role[]> = {
  'org:update': ADMIN,
  'member:view': ALL,
  'member:invite': ADMIN,
  'member:remove': ADMIN,
  'member:change_role': ADMIN,
  'board:view': ALL,
  'board:manage': LEADS, // create, edit, archive boards; add, rename, delete columns
  'task:view': ALL,
  'task:create': ALL,
  'task:edit_any': LEADS,
  'task:delete': LEADS,
  'comment:create': ALL,
  'comment:delete_any': LEADS,
  'audit:view': LEADS,
}

export function can(role: Role | null, permission: Permission): boolean {
  return role !== null && MATRIX[permission].includes(role)
}

interface TaskOwnership {
  assignee_id?: string | null
}

/** Edit and move: admin/manager any task; a member only tasks assigned to them. */
export function canEditTask(
  role: Role | null,
  userId: string | null,
  task: TaskOwnership,
): boolean {
  if (can(role, 'task:edit_any')) return true
  return role === 'member' && userId !== null && task.assignee_id === userId
}

/** Only admin/manager may reassign; members may only create tasks unassigned or self-assigned. */
export function canAssignTo(role: Role | null, userId: string | null, assigneeId: string | null) {
  return can(role, 'task:edit_any') || assigneeId === null || assigneeId === userId
}

/** Delete a comment: its author, or admin/manager. */
export function canDeleteComment(
  role: Role | null,
  userId: string | null,
  comment: { author_id: string | null },
): boolean {
  return can(role, 'comment:delete_any') || (userId !== null && comment.author_id === userId)
}
