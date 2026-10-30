import { useInfiniteQuery } from '@tanstack/react-query'
import { auditApi, type AuditFilters } from '../../api/audit'

export function useAuditLogs(filters: AuditFilters) {
  return useInfiniteQuery({
    queryKey: ['audit', filters],
    queryFn: ({ pageParam }) => auditApi.list(filters, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? null,
  })
}
