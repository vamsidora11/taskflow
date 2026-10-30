import { request } from './client'
import type {
  CommentRead,
  Page,
  Priority,
  TaskCreate,
  TaskMove,
  TaskRead,
  TaskUpdate,
} from './types'

export interface TaskFilters {
  assignee_id?: string
  priority?: Priority
}

export const tasksApi = {
  list: (boardId: string, filters: TaskFilters, cursor?: string | null) =>
    request<Page<TaskRead>>(`/boards/${boardId}/tasks`, {
      query: { ...filters, limit: 100, cursor },
    }),
  get: (id: string) => request<TaskRead>(`/tasks/${id}`),
  create: (boardId: string, body: TaskCreate, idempotencyKey: string) =>
    request<TaskRead>(`/boards/${boardId}/tasks`, {
      method: 'POST',
      body,
      headers: { 'Idempotency-Key': idempotencyKey },
    }),
  update: (id: string, body: TaskUpdate) =>
    request<TaskRead>(`/tasks/${id}`, { method: 'PATCH', body }),
  remove: (id: string) => request<void>(`/tasks/${id}`, { method: 'DELETE' }),
  move: (id: string, body: TaskMove) =>
    request<TaskRead>(`/tasks/${id}/move`, { method: 'POST', body }),
  listComments: (taskId: string, cursor?: string | null) =>
    request<Page<CommentRead>>(`/tasks/${taskId}/comments`, { query: { limit: 100, cursor } }),
  addComment: (taskId: string, body: string) =>
    request<CommentRead>(`/tasks/${taskId}/comments`, { method: 'POST', body: { body } }),
  deleteComment: (id: string) => request<void>(`/comments/${id}`, { method: 'DELETE' }),
}
