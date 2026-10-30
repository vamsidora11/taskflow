import { describe, expect, it } from 'vitest'
import type { Role } from '../api/types'
import { can, canAssignTo, canDeleteComment, canEditTask, type Permission } from './permissions'

// PLAN.md section 5, one row per permission: [admin, manager, member].
const MATRIX: [Permission, boolean, boolean, boolean][] = [
  ['org:update', true, false, false],
  ['member:invite', true, false, false],
  ['member:remove', true, false, false],
  ['member:change_role', true, false, false],
  ['member:view', true, true, true],
  ['board:view', true, true, true],
  ['board:manage', true, true, false],
  ['task:view', true, true, true],
  ['task:create', true, true, true],
  ['task:edit_any', true, true, false],
  ['task:delete', true, true, false],
  ['comment:create', true, true, true],
  ['comment:delete_any', true, true, false],
  ['audit:view', true, true, false],
]
const ROLES: Role[] = ['admin', 'manager', 'member']

describe('can()', () => {
  it.each(MATRIX)('%s', (permission, ...expected) => {
    ROLES.forEach((role, i) => expect(can(role, permission)).toBe(expected[i]))
  })

  it('denies everything without a role', () => {
    expect(can(null, 'board:view')).toBe(false)
  })
})

describe('ownership rules', () => {
  const mine = { assignee_id: 'me' }
  const theirs = { assignee_id: 'other' }
  const nobody = { assignee_id: null }

  it('members edit only tasks assigned to them; admin and manager edit any', () => {
    expect(canEditTask('member', 'me', mine)).toBe(true)
    expect(canEditTask('member', 'me', theirs)).toBe(false)
    expect(canEditTask('member', 'me', nobody)).toBe(false)
    expect(canEditTask('manager', 'me', theirs)).toBe(true)
    expect(canEditTask('admin', 'me', nobody)).toBe(true)
  })

  it('members may only assign to themselves or nobody', () => {
    expect(canAssignTo('member', 'me', null)).toBe(true)
    expect(canAssignTo('member', 'me', 'me')).toBe(true)
    expect(canAssignTo('member', 'me', 'other')).toBe(false)
    expect(canAssignTo('manager', 'me', 'other')).toBe(true)
  })

  it('comments: authors delete their own, admin and manager delete any', () => {
    expect(canDeleteComment('member', 'me', { author_id: 'me' })).toBe(true)
    expect(canDeleteComment('member', 'me', { author_id: 'other' })).toBe(false)
    expect(canDeleteComment('manager', 'me', { author_id: 'other' })).toBe(true)
    expect(canDeleteComment('member', 'me', { author_id: null })).toBe(false)
  })
})
