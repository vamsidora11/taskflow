import { request } from './client'
import type { InvitationRead, MemberRead, OrganizationRead, Page, Role } from './types'

export const membersApi = {
  list: (cursor?: string | null) =>
    request<Page<MemberRead>>('/org/members', { query: { limit: 100, cursor } }),
  changeRole: (userId: string, role: Role) =>
    request<MemberRead>(`/org/members/${userId}`, { method: 'PATCH', body: { role } }),
  remove: (userId: string) => request<void>(`/org/members/${userId}`, { method: 'DELETE' }),
  invite: (email: string, role: Role) =>
    request<InvitationRead>('/org/invitations', { method: 'POST', body: { email, role } }),
  getOrg: () => request<OrganizationRead>('/org'),
}
