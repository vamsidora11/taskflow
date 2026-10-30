import { request } from './client'
import type { AuditLogRead, Page } from './types'

export interface AuditFilters {
  action?: string
  entity_type?: string
  actor_user_id?: string
  created_from?: string
  created_to?: string
}

export const auditApi = {
  list: (filters: AuditFilters, cursor?: string | null) =>
    request<Page<AuditLogRead>>('/audit-logs', { query: { ...filters, limit: 50, cursor } }),
}
