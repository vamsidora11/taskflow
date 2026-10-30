import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { boardsApi } from '../../api/boards'
import { fetchAll } from '../../api/pagination'
import type { BoardCreate } from '../../api/types'

export const boardKeys = {
  all: ['boards'] as const,
  detail: (id: string) => ['boards', id] as const,
}

export function useBoards() {
  return useQuery({
    queryKey: boardKeys.all,
    queryFn: () => fetchAll((cursor) => boardsApi.list(cursor)),
  })
}

export function useBoard(id: string) {
  return useQuery({ queryKey: boardKeys.detail(id), queryFn: () => boardsApi.get(id) })
}

export function useCreateBoard() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: BoardCreate) => boardsApi.create(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: boardKeys.all }),
  })
}

export function useArchiveBoard() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => boardsApi.archive(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: boardKeys.all }),
  })
}

export function useColumnMutations(boardId: string) {
  const qc = useQueryClient()
  const refresh = () => qc.invalidateQueries({ queryKey: boardKeys.detail(boardId) })
  return {
    add: useMutation({
      mutationFn: (name: string) => boardsApi.addColumn(boardId, name),
      onSuccess: refresh,
    }),
    rename: useMutation({
      mutationFn: (v: { id: string; name: string }) => boardsApi.renameColumn(v.id, v.name),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: (id: string) => boardsApi.deleteColumn(id),
      onSuccess: refresh,
    }),
  }
}
