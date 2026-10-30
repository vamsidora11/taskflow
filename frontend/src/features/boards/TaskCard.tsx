import type { DragEvent } from 'react'
import type { Priority, TaskRead } from '../../api/types'
import type { Direction } from './moveLogic'

const PRIORITY_STYLE: Record<Priority, string> = {
  low: 'bg-slate-200 text-slate-900',
  medium: 'bg-blue-100 text-blue-900',
  high: 'bg-amber-100 text-amber-900',
  urgent: 'bg-red-100 text-red-900',
}

export function PriorityBadge({ priority }: { priority: Priority }) {
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${PRIORITY_STYLE[priority]}`}>
      Priority: {priority}
    </span>
  )
}

interface MoveButton {
  direction: Direction
  glyph: string
  label: string
}

const MOVE_BUTTONS: MoveButton[] = [
  { direction: 'up', glyph: '↑', label: 'up' },
  { direction: 'down', glyph: '↓', label: 'down' },
  { direction: 'left', glyph: '←', label: 'to previous column' },
  { direction: 'right', glyph: '→', label: 'to next column' },
]

interface Props {
  task: TaskRead
  assigneeName: string | null
  /** Whether the current user may move this task (drag and the Move buttons). */
  movable: boolean
  isDragging: boolean
  isMoveAvailable: (direction: Direction) => boolean
  onOpen: () => void
  onMove: (direction: Direction) => void
  onDragStart: (event: DragEvent<HTMLLIElement>) => void
  onDragEnd: () => void
}

export function TaskCard(props: Props) {
  const { task, assigneeName, movable, isDragging } = props
  return (
    <li
      draggable={movable}
      onDragStart={props.onDragStart}
      onDragEnd={props.onDragEnd}
      data-task-id={task.id}
      className={`rounded-md border border-slate-300 bg-white p-3 shadow-sm ${
        isDragging ? 'opacity-50' : ''
      } ${movable ? 'cursor-grab' : ''}`}
    >
      <button
        type="button"
        onClick={props.onOpen}
        className="text-left text-sm font-medium text-slate-900 underline-offset-2 hover:underline"
      >
        {task.title}
      </button>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-700">
        <PriorityBadge priority={task.priority} />
        <span>{assigneeName ? `Assignee: ${assigneeName}` : 'Unassigned'}</span>
        {task.due_date && <span>Due {task.due_date}</span>}
      </div>
      {movable && (
        <div role="group" aria-label={`Move ${task.title}`} className="mt-2 flex gap-1">
          {MOVE_BUTTONS.map((b) => (
            <button
              key={b.direction}
              type="button"
              disabled={!props.isMoveAvailable(b.direction)}
              onClick={() => props.onMove(b.direction)}
              aria-label={`Move ${task.title} ${b.label}`}
              className="rounded border border-slate-400 px-2 text-sm text-slate-900 hover:bg-slate-100 disabled:opacity-40"
            >
              <span aria-hidden="true">{b.glyph}</span>
            </button>
          ))}
        </div>
      )}
    </li>
  )
}
