import { createContext, useContext } from 'react'
import type { MeResponse, OrganizationSummary, Role } from '../api/types'
import type { Permission } from './permissions'

export type AuthStatus = 'loading' | 'authenticated' | 'anonymous'

export interface AuthContextValue {
  status: AuthStatus
  user: MeResponse['user'] | null
  activeOrganization: OrganizationSummary | null
  organizations: OrganizationSummary[]
  role: Role | null
  accessToken: string | null
  can: (permission: Permission) => boolean
  login: (email: string, password: string) => Promise<void>
  signup: (input: {
    organization_name: string
    email: string
    password: string
    full_name: string
  }) => Promise<void>
  acceptInvitation: (
    token: string,
    input: { password: string; full_name?: string },
  ) => Promise<void>
  logout: () => Promise<void>
  switchOrganization: (organizationId: string) => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>')
  return value
}
