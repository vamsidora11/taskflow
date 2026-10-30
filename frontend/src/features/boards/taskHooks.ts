import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchAll } from '../../api/pagination'
import { tasksApi, type TaskFilters } from '../../api/tasks'
import type { TaskCreate, TaskRead, TaskUpdate } from '../../api/types'
import { applyMove } from './moveLogic'

export const taskKeys = {
  board: (boardId: string) => ['boards', boardId, 'tasks'] as const,
  list: (boardId: string, filters: TaskFilters) => ['boards', boardId, 'tasks', filters] as const,
  detail: (id: string) => ['tasks', id] as const,
}

export function useBoardTasks(boardId: string, filters: TaskFilters) {
  return useQuery({
    queryKey: taskKeys.list(boardId, filters),
    queryFn: () => fetchAll((cursor) => tasksApi.list(boardId, filters, cursor)),
  })
}

export function useTask(id: string) {
  return useQuery({ queryKey: taskKeys.detail(id), queryFn: () => tasksApi.get(id) })
}

export function useCreateTask(boardId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { body: TaskCreate; idempotencyKey: string }) =>
      tasksApi.create(boardId, v.body, v.idempotencyKey),
    onSuccess: () => qc.invalidateQueries({ queryKey: taskKeys.board(boardId) }),
  })
}

export function useUpdateTask(boardId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { id: string; body: TaskUpdate }) => tasksApi.update(v.id, v.body),
    onSuccess: (task) => {
      qc.setQueryData(taskKeys.detail(task.id), task)
      return qc.invalidateQueries({ queryKey: taskKeys.board(boardId) })
    },
  })
}

export function useDeleteTask(boardId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => tasksApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: taskKeys.board(boardId) }),
  })
}

interface MoveVars {
  taskId: string
  columnId: string
  position: number
}

/** Moves a task with an optimistic cache update that is rolled back if the server refuses. */
export function useMoveTask(boardId: string, filters: TaskFilters) {
  const qc = useQueryClient()
  const key = taskKeys.list(boardId, filters)
  return useMutation({
    mutationFn: (v: MoveVars) =>
      tasksApi.move(v.taskId, { column_id: v.columnId, position: v.position }),
    onMutate: async (v) => {
      await qc.cancelQueries({ queryKey: taskKeys.board(boardId) })
      const previous = qc.getQueryData<TaskRead[]>(key)
      if (previous) {
        const result = applyMove(previous, v.taskId, v.columnId, v.position)
        if (result) qc.setQueryData(key, result.tasks)
      }
      return { previous }
    },
    onError: (_error, _vars, context) => {
      if (context?.previous) qc.setQueryData(key, context.previous)
    },
    onSettled: () => qc.invalidateQueries({ queryKey: taskKeys.board(boardId) }),
  })
}
