import { request } from './client'
import type { BoardCreate, BoardDetail, BoardRead, ColumnRead, Page } from './types'

export const boardsApi = {
  list: (cursor?: string | null) =>
    request<Page<BoardRead>>('/boards', { query: { limit: 100, cursor } }),
  get: (id: string) => request<BoardDetail>(`/boards/${id}`),
  create: (body: BoardCreate) => request<BoardRead>('/boards', { method: 'POST', body }),
  archive: (id: string) => request<void>(`/boards/${id}`, { method: 'DELETE' }),
  addColumn: (boardId: string, name: string) =>
    request<ColumnRead>(`/boards/${boardId}/columns`, { method: 'POST', body: { name } }),
  renameColumn: (id: string, name: string) =>
    request<ColumnRead>(`/columns/${id}`, { method: 'PATCH', body: { name } }),
  deleteColumn: (id: string) => request<void>(`/columns/${id}`, { method: 'DELETE' }),
}
