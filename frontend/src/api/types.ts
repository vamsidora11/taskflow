import type { components } from './schema'

type S = components['schemas']

export type Role = S['Role']
export type Priority = S['Priority']
export type TokenResponse = S['TokenResponse']
export type MeResponse = S['MeResponse']
export type UserRead = S['UserRead']
export type OrganizationSummary = S['OrganizationSummary']
export type OrganizationRead = S['OrganizationRead']
export type BoardRead = S['BoardRead']
export type BoardDetail = S['BoardDetail']
export type BoardCreate = S['BoardCreate']
export type ColumnRead = S['ColumnRead']
export type TaskRead = S['TaskRead']
export type TaskCreate = S['TaskCreate']
export type TaskUpdate = S['TaskUpdate']
export type TaskMove = S['TaskMove']
export type CommentRead = S['CommentRead']
export type MemberRead = S['MemberRead']
export type InvitationRead = S['InvitationRead']
export type AuditLogRead = S['AuditLogRead']
export type SignupRequest = S['SignupRequest']
export type LoginRequest = S['LoginRequest']
export type AcceptInvitationRequest = S['AcceptInvitationRequest']

export interface Page<T> {
  items: T[]
  next_cursor?: string | null
}

export const ROLES: readonly Role[] = ['admin', 'manager', 'member']
export const PRIORITIES: readonly Priority[] = ['low', 'medium', 'high', 'urgent']
