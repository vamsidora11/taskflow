import { request } from './client'
import type {
  AcceptInvitationRequest,
  LoginRequest,
  MeResponse,
  SignupRequest,
  TokenResponse,
} from './types'

export const authApi = {
  login: (body: LoginRequest) =>
    request<TokenResponse>('/auth/login', { method: 'POST', body, auth: false }),
  signup: (body: SignupRequest) =>
    request<TokenResponse>('/auth/signup', { method: 'POST', body, auth: false }),
  logout: () => request<void>('/auth/logout', { method: 'POST', auth: false }),
  switchOrg: (organizationId: string) =>
    request<TokenResponse>('/auth/switch-org', {
      method: 'POST',
      body: { organization_id: organizationId },
    }),
  me: () => request<MeResponse>('/auth/me'),
  acceptInvitation: (token: string, body: AcceptInvitationRequest) =>
    request<TokenResponse>(`/org/invitations/${encodeURIComponent(token)}/accept`, {
      method: 'POST',
      body,
      auth: false,
    }),
}
