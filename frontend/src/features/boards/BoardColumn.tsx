import type { DragEvent } from 'react'
import type { ColumnRead, TaskRead } from '../../api/types'
import { AddTaskForm } from './AddTaskForm'
import { ColumnHeader } from './ColumnHeader'
import type { Direction } from './moveLogic'
import { TaskCard } from './TaskCard'

export interface DropTarget {
  columnId: string
  slot: number
}

interface Props {
  boardId: string
  column: ColumnRead
  tasks: TaskRead[]
  assigneeName: (task: TaskRead) => string | null
  canManageColumns: boolean
  canCreateTasks: boolean
  canMove: (task: TaskRead) => boolean
  isMoveAvailable: (task: TaskRead, direction: Direction) => boolean
  draggingId: string | null
  dropTarget: DropTarget | null
  onDragStart: (taskId: string, event: DragEvent) => void
  onDragEnd: () => void
  onDropTarget: (target: DropTarget | null) => void
  onDrop: (columnId: string, slot: number) => void
  onMove: (task: TaskRead, direction: Direction) => void
  onOpenTask: (task: TaskRead) => void
}

/** Index (0..n) of the card the pointer is above, derived from the cards' vertical midpoints. */
function slotFromPointer(list: HTMLElement, clientY: number): number {
  const cards = [...list.querySelectorAll<HTMLElement>('[data-task-id]')]
  const index = cards.findIndex((card) => {
    const rect = card.getBoundingClientRect()
    return clientY < rect.top + rect.height / 2
  })
  return index === -1 ? cards.length : index
}

export function BoardColumn(props: Props) {
  const { column, tasks, dropTarget } = props
  const showMarker = (slot: number) =>
    dropTarget?.columnId === column.id && dropTarget.slot === slot

  function onDragOver(event: DragEvent<HTMLUListElement>) {
    if (!props.draggingId) return
    event.preventDefault()
    props.onDropTarget({
      columnId: column.id,
      slot: slotFromPointer(event.currentTarget, event.clientY),
    })
  }

  function onDrop(event: DragEvent<HTMLUListElement>) {
    event.preventDefault()
    props.onDrop(column.id, slotFromPointer(event.currentTarget, event.clientY))
  }

  return (
    <section
      aria-label={column.name}
      className="w-72 shrink-0 rounded-lg border border-slate-300 bg-slate-100 p-3"
    >
      <ColumnHeader
        column={column}
        boardId={props.boardId}
        count={tasks.length}
        canManage={props.canManageColumns}
      />
      {/* Drag and drop is a pointer enhancement; the Move buttons on each card are the accessible path. */}
      <ul
        aria-label={`Tasks in ${column.name}`}
        onDragOver={onDragOver}
        onDragLeave={() => props.onDropTarget(null)}
        onDrop={onDrop}
        className="my-3 min-h-12 space-y-2"
      >
        {tasks.map((task, index) => (
          <TaskSlot key={task.id} marked={showMarker(index)}>
            <TaskCard
              task={task}
              assigneeName={props.assigneeName(task)}
              movable={props.canMove(task)}
              isDragging={props.draggingId === task.id}
              isMoveAvailable={(d) => props.isMoveAvailable(task, d)}
              onOpen={() => props.onOpenTask(task)}
              onMove={(d) => props.onMove(task, d)}
              onDragStart={(e) => props.onDragStart(task.id, e)}
              onDragEnd={props.onDragEnd}
            />
          </TaskSlot>
        ))}
        {tasks.length === 0 && !showMarker(0) && (
          <li className="px-1 text-sm text-slate-700">No tasks</li>
        )}
        {showMarker(tasks.length) && (
          <li aria-hidden="true" className="h-1 rounded bg-indigo-700" />
        )}
      </ul>
      {props.canCreateTasks && (
        <AddTaskForm boardId={props.boardId} columnId={column.id} columnName={column.name} />
      )}
    </section>
  )
}

function TaskSlot({ marked, children }: { marked: boolean; children: React.ReactNode }) {
  return (
    <>
      {marked && <li aria-hidden="true" className="h-1 rounded bg-indigo-700" />}
      {children}
    </>
  )
}
