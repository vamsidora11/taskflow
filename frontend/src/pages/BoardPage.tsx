import { useMemo, useState, type DragEvent, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { describeError } from '../api/errors'
import type { TaskFilters } from '../api/tasks'
import type { TaskRead } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { canEditTask } from '../auth/permissions'
import { FormField } from '../components/FormField'
import { ErrorState, FormError, LoadingState } from '../components/states'
import { btn } from '../components/styles'
import { useToast } from '../components/Toast'
import { usePageTitle } from '../components/usePageTitle'
import { BoardColumn, type DropTarget } from '../features/boards/BoardColumn'
import { FilterBar } from '../features/boards/FilterBar'
import { useArchiveBoard, useBoard, useColumnMutations } from '../features/boards/hooks'
import {
  applyMove,
  dropSlotToPosition,
  neighborTarget,
  tasksInColumn,
  type Direction,
} from '../features/boards/moveLogic'
import { useBoardTasks, useMoveTask } from '../features/boards/taskHooks'
import { useMembers } from '../features/members/hooks'
import { TaskDrawer } from '../features/tasks/TaskDrawer'

function AddColumnForm({ boardId }: { boardId: string }) {
  const { add } = useColumnMutations(boardId)
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    if (!name.trim()) return setError('Enter a column name.')
    setError(null)
    add.mutate(name.trim(), { onSuccess: () => setName('') })
  }

  return (
    <form onSubmit={onSubmit} noValidate className="w-72 shrink-0 space-y-2">
      <FormField
        label="New column name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        error={error}
        maxLength={100}
      />
      {add.error && <FormError error={add.error} />}
      <button type="submit" disabled={add.isPending} className={btn.secondary}>
        Add column
      </button>
    </form>
  )
}

function ArchiveButton({ boardId }: { boardId: string }) {
  const archive = useArchiveBoard()
  const navigate = useNavigate()
  const [confirming, setConfirming] = useState(false)
  return (
    <div className="flex flex-wrap items-center gap-2">
      {confirming ? (
        <>
          <button
            type="button"
            className={btn.danger}
            onClick={() => archive.mutate(boardId, { onSuccess: () => navigate('/') })}
          >
            Confirm archive
          </button>
          <button type="button" className={btn.secondary} onClick={() => setConfirming(false)}>
            Cancel
          </button>
        </>
      ) : (
        <button type="button" className={btn.secondary} onClick={() => setConfirming(true)}>
          Archive board
        </button>
      )}
      {archive.error && <FormError error={archive.error} />}
    </div>
  )
}

export default function BoardPage() {
  const { boardId = '' } = useParams()
  const { role, user, can } = useAuth()
  const notify = useToast()
  const [filters, setFilters] = useState<TaskFilters>({})
  const [draggingId, setDraggingId] = useState<string | null>(null)
  const [dropTarget, setDropTarget] = useState<DropTarget | null>(null)
  const [openTaskId, setOpenTaskId] = useState<string | null>(null)
  const [announcement, setAnnouncement] = useState('')

  const board = useBoard(boardId)
  const taskQuery = useBoardTasks(boardId, filters)
  const members = useMembers()
  const move = useMoveTask(boardId, filters)
  usePageTitle(board.data?.name ?? 'Board')

  const memberNames = useMemo(
    () => new Map((members.data ?? []).map((m) => [m.user_id, m.full_name])),
    [members.data],
  )
  const columns = useMemo(
    () => [...(board.data?.columns ?? [])].sort((a, b) => a.position - b.position),
    [board.data],
  )
  const tasks = useMemo(() => taskQuery.data ?? [], [taskQuery.data])
  const columnIds = useMemo(() => columns.map((c) => c.id), [columns])

  if (board.isPending) return <LoadingState label="Loading board" />
  if (board.isError) return <ErrorState error={board.error} onRetry={() => void board.refetch()} />

  const archived = board.data.is_archived
  const filtersActive = Boolean(filters.assignee_id || filters.priority)
  const userId = user?.id ?? null
  const canMove = (task: TaskRead) => !archived && !filtersActive && canEditTask(role, userId, task)
  const canManage = can('board:manage') && !archived

  function performMove(taskId: string, columnId: string, requestedPosition: number) {
    const result = applyMove(tasks, taskId, columnId, requestedPosition)
    if (!result?.changed) return
    const task = tasks.find((t) => t.id === taskId)
    const column = columns.find((c) => c.id === columnId)
    const total = tasksInColumn(tasks, columnId).length + (task?.column_id === columnId ? 0 : 1)
    setAnnouncement(
      `Moved ${task?.title} to ${column?.name}, position ${result.position + 1} of ${total}.`,
    )
    move.mutate(
      { taskId, columnId: result.columnId, position: result.position },
      { onError: (e) => notify(`${describeError(e)} The move was undone.`, 'error') },
    )
  }

  function onDragStart(taskId: string, event: DragEvent) {
    event.dataTransfer.setData('text/plain', taskId)
    event.dataTransfer.effectAllowed = 'move'
    setDraggingId(taskId)
  }

  function endDrag() {
    setDraggingId(null)
    setDropTarget(null)
  }

  function onDrop(columnId: string, slot: number) {
    if (draggingId)
      performMove(draggingId, columnId, dropSlotToPosition(tasks, draggingId, columnId, slot))
    endDrag()
  }

  function onKeyboardMove(task: TaskRead, direction: Direction) {
    const target = neighborTarget(tasks, columnIds, task.id, direction)
    if (target) performMove(task.id, target.columnId, target.position)
  }

  return (
    <>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">{board.data.name}</h1>
          {board.data.description && <p className="text-slate-700">{board.data.description}</p>}
        </div>
        {canManage && <ArchiveButton boardId={boardId} />}
      </div>
      {archived && (
        <p
          role="status"
          className="mb-4 rounded-md border border-amber-700 bg-amber-50 p-3 text-amber-900"
        >
          This board is archived and read-only.
        </p>
      )}
      <FilterBar filters={filters} members={members.data ?? []} onChange={setFilters} />
      {filtersActive && (
        <p className="mb-3 text-sm text-slate-700">
          Moving tasks is disabled while filters are active.
        </p>
      )}
      <p role="status" aria-live="polite" className="sr-only">
        {announcement}
      </p>
      {taskQuery.isPending && <LoadingState label="Loading tasks" />}
      {taskQuery.isError && (
        <ErrorState error={taskQuery.error} onRetry={() => void taskQuery.refetch()} />
      )}
      {taskQuery.isSuccess && (
        <div className="flex items-start gap-4 overflow-x-auto pb-4">
          {columns.map((column) => (
            <BoardColumn
              key={column.id}
              boardId={boardId}
              column={column}
              tasks={tasksInColumn(tasks, column.id)}
              assigneeName={(t) =>
                t.assignee_id ? (memberNames.get(t.assignee_id) ?? 'Unknown member') : null
              }
              canManageColumns={canManage}
              canCreateTasks={!archived && can('task:create')}
              canMove={canMove}
              isMoveAvailable={(t, d) => neighborTarget(tasks, columnIds, t.id, d) !== null}
              draggingId={draggingId}
              dropTarget={dropTarget}
              onDragStart={onDragStart}
              onDragEnd={endDrag}
              onDropTarget={setDropTarget}
              onDrop={onDrop}
              onMove={onKeyboardMove}
              onOpenTask={(t) => setOpenTaskId(t.id)}
            />
          ))}
          {canManage && <AddColumnForm boardId={boardId} />}
        </div>
      )}
      {openTaskId && (
        <TaskDrawer
          taskId={openTaskId}
          boardId={boardId}
          members={members.data ?? []}
          readOnly={archived}
          onClose={() => setOpenTaskId(null)}
        />
      )}
    </>
  )
}
