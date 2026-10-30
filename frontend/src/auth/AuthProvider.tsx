import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { authApi } from '../api/auth'
import { refreshSession, setAuthFailureHandler } from '../api/client'
import { tokenStore } from '../api/tokenStore'
import type { MeResponse, TokenResponse } from '../api/types'
import { AuthContext, type AuthContextValue, type AuthStatus } from './AuthContext'
import { can as roleCan } from './permissions'

interface Session {
  me: MeResponse
  accessToken: string
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<AuthStatus>('loading')
  const [session, setSession] = useState<Session | null>(null)

  const clearSession = useCallback(() => {
    tokenStore.set(null)
    queryClient.clear()
    setSession(null)
    setStatus('anonymous')
  }, [queryClient])

  /** Loads the profile for a freshly issued token and marks the user as signed in. */
  const establish = useCallback(async (token: TokenResponse) => {
    tokenStore.set(token.access_token)
    try {
      const me = await authApi.me()
      setSession({ me, accessToken: token.access_token })
      setStatus('authenticated')
    } catch (error) {
      tokenStore.set(null)
      throw error
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    setAuthFailureHandler(clearSession)
    void (async () => {
      const token = await refreshSession()
      if (cancelled) return
      if (!token) return setStatus('anonymous')
      try {
        await establish(token)
      } catch {
        if (!cancelled) setStatus('anonymous')
      }
    })()
    return () => {
      cancelled = true
      setAuthFailureHandler(null)
    }
  }, [clearSession, establish])

  const value = useMemo<AuthContextValue>(() => {
    const role = session?.me.active_organization.role ?? null
    return {
      status,
      user: session?.me.user ?? null,
      activeOrganization: session?.me.active_organization ?? null,
      organizations: session?.me.organizations ?? [],
      role,
      accessToken: session?.accessToken ?? null,
      can: (permission) => roleCan(role, permission),
      login: async (email, password) => establish(await authApi.login({ email, password })),
      signup: async (input) => establish(await authApi.signup(input)),
      acceptInvitation: async (token, input) =>
        establish(await authApi.acceptInvitation(token, input)),
      logout: async () => {
        try {
          await authApi.logout()
        } catch {
          // The local session is dropped regardless of whether the server call succeeded.
        }
        clearSession()
      },
      switchOrganization: async (organizationId) => {
        const token = await authApi.switchOrg(organizationId)
        queryClient.clear()
        await establish(token)
      },
    }
  }, [status, session, establish, clearSession, queryClient])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
