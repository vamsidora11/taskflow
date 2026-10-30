import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { membersApi } from '../../api/members'
import { fetchAll } from '../../api/pagination'
import type { Role } from '../../api/types'

const KEY = ['members'] as const

export function useMembers() {
  return useQuery({
    queryKey: KEY,
    queryFn: () => fetchAll((cursor) => membersApi.list(cursor)),
  })
}

export function useChangeRole() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { userId: string; role: Role }) => membersApi.changeRole(v.userId, v.role),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}

export function useRemoveMember() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (userId: string) => membersApi.remove(userId),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}

export function useInvite() {
  return useMutation({
    mutationFn: (v: { email: string; role: Role }) => membersApi.invite(v.email, v.role),
  })
}
