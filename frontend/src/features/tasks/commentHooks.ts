import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchAll } from '../../api/pagination'
import { tasksApi } from '../../api/tasks'

const key = (taskId: string) => ['tasks', taskId, 'comments'] as const

export function useComments(taskId: string) {
  return useQuery({
    queryKey: key(taskId),
    queryFn: () => fetchAll((cursor) => tasksApi.listComments(taskId, cursor)),
  })
}

export function useAddComment(taskId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: string) => tasksApi.addComment(taskId, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: key(taskId) }),
  })
}

export function useDeleteComment(taskId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => tasksApi.deleteComment(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: key(taskId) }),
  })
}
