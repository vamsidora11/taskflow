import type { TaskRead } from '../../api/types'

/**
 * Pure move/reorder logic mirroring the backend (`TaskService.move_task`):
 * - positions are 0-based and dense within a column;
 * - the requested position is the task's FINAL index in the target column, i.e. an index into
 *   the target column with the moved task removed, clamped to [0, count];
 * - so moving down inside a column accounts for the slot the task vacates.
 */

type Positioned = Pick<TaskRead, 'id' | 'column_id' | 'position'>

export interface MoveTarget {
  columnId: string
  position: number
}

export interface MoveResult<T extends Positioned> extends MoveTarget {
  /** True when the task ends up somewhere other than where it started. */
  changed: boolean
  /** The whole task list with the move applied and positions renumbered densely. */
  tasks: T[]
}

export function tasksInColumn<T extends Positioned>(tasks: T[], columnId: string): T[] {
  return tasks.filter((t) => t.column_id === columnId).sort((a, b) => a.position - b.position)
}

function renumber<T extends Positioned>(ordered: T[], columnId: string): T[] {
  return ordered.map((t, index) => ({ ...t, column_id: columnId, position: index }))
}

export function applyMove<T extends Positioned>(
  tasks: T[],
  taskId: string,
  columnId: string,
  requestedPosition: number,
): MoveResult<T> | null {
  const moving = tasks.find((t) => t.id === taskId)
  if (!moving) return null

  const sourceId = moving.column_id
  const targetOthers = tasksInColumn(tasks, columnId).filter((t) => t.id !== taskId)
  const position = Math.max(0, Math.min(Math.trunc(requestedPosition), targetOthers.length))

  const newTarget = [...targetOthers]
  newTarget.splice(position, 0, moving)
  const updatedTarget = renumber(newTarget, columnId)
  const updatedSource =
    sourceId === columnId
      ? []
      : renumber(
          tasksInColumn(tasks, sourceId).filter((t) => t.id !== taskId),
          sourceId,
        )

  const touched = new Map([...updatedTarget, ...updatedSource].map((t) => [t.id, t]))
  return {
    columnId,
    position,
    changed: sourceId !== columnId || moving.position !== position,
    tasks: tasks.map((t) => touched.get(t.id) ?? t),
  }
}

/** Converts a drop slot in the visible list (0..length, "before item i") into a final index. */
export function dropSlotToPosition(
  tasks: Positioned[],
  taskId: string,
  columnId: string,
  slot: number,
): number {
  const moving = tasks.find((t) => t.id === taskId)
  const sameColumn = moving?.column_id === columnId
  return sameColumn && moving && slot > moving.position ? slot - 1 : slot
}

export type Direction = 'up' | 'down' | 'left' | 'right'

/**
 * Target for the keyboard/button alternative to dragging. Up/down swap within the column;
 * left/right go to the adjacent column, keeping the same row where possible.
 * Returns null when the move is impossible (already at an edge).
 */
export function neighborTarget(
  tasks: Positioned[],
  columnIds: string[],
  taskId: string,
  direction: Direction,
): MoveTarget | null {
  const task = tasks.find((t) => t.id === taskId)
  if (!task) return null
  if (direction === 'up') {
    return task.position > 0 ? { columnId: task.column_id, position: task.position - 1 } : null
  }
  if (direction === 'down') {
    const last = tasksInColumn(tasks, task.column_id).length - 1
    return task.position < last ? { columnId: task.column_id, position: task.position + 1 } : null
  }
  const index = columnIds.indexOf(task.column_id)
  const next = columnIds[direction === 'left' ? index - 1 : index + 1]
  return next === undefined || index < 0 ? null : { columnId: next, position: task.position }
}
