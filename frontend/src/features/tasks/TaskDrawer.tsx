import { useState, type FormEvent } from 'react'
import {
  PRIORITIES,
  type MemberRead,
  type Priority,
  type TaskRead,
  type TaskUpdate,
} from '../../api/types'
import { useAuth } from '../../auth/AuthContext'
import { canEditTask } from '../../auth/permissions'
import { FormField } from '../../components/FormField'
import { Modal } from '../../components/Modal'
import { ErrorState, FormError, LoadingState } from '../../components/states'
import { btn, inputClass } from '../../components/styles'
import { useDeleteTask, useTask, useUpdateTask } from '../boards/taskHooks'
import { CommentSection } from './CommentSection'

interface Props {
  taskId: string
  boardId: string
  members: MemberRead[]
  readOnly: boolean
  onClose: () => void
}

export function TaskDrawer({ taskId, boardId, members, readOnly, onClose }: Props) {
  const task = useTask(taskId)
  return (
    <Modal title={task.data?.title ?? 'Task details'} onClose={onClose}>
      {task.isPending && <LoadingState label="Loading task" />}
      {task.isError && <ErrorState error={task.error} onRetry={() => void task.refetch()} />}
      {task.data && (
        <>
          <TaskForm
            task={task.data}
            boardId={boardId}
            members={members}
            readOnly={readOnly}
            onDeleted={onClose}
          />
          <CommentSection taskId={taskId} members={members} readOnly={readOnly} />
        </>
      )}
    </Modal>
  )
}

interface FormProps {
  task: TaskRead
  boardId: string
  members: MemberRead[]
  readOnly: boolean
  onDeleted: () => void
}

function TaskForm({ task, boardId, members, readOnly, onDeleted }: FormProps) {
  const { role, user, can } = useAuth()
  const update = useUpdateTask(boardId)
  const remove = useDeleteTask(boardId)
  const [title, setTitle] = useState(task.title)
  const [description, setDescription] = useState(task.description ?? '')
  const [priority, setPriority] = useState<Priority>(task.priority)
  const [dueDate, setDueDate] = useState(task.due_date ?? '')
  const [assignee, setAssignee] = useState(task.assignee_id ?? '')
  const [titleError, setTitleError] = useState<string | null>(null)
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [saved, setSaved] = useState(false)

  const editable = !readOnly && canEditTask(role, user?.id ?? null, task)
  const canAssign = editable && can('task:edit_any')
  const assigneeName = members.find((m) => m.user_id === task.assignee_id)?.full_name

  /** Only the fields that changed are sent, so members never submit an assignee they cannot set. */
  function buildChanges(): TaskUpdate {
    const changes: TaskUpdate = {}
    if (title.trim() !== task.title) changes.title = title.trim()
    if (description !== (task.description ?? '')) changes.description = description
    if (priority !== task.priority) changes.priority = priority
    if (dueDate !== (task.due_date ?? '')) changes.due_date = dueDate || null
    if (canAssign && assignee !== (task.assignee_id ?? '')) changes.assignee_id = assignee || null
    return changes
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    setSaved(false)
    if (!title.trim()) return setTitleError('Enter a title.')
    setTitleError(null)
    const changes = buildChanges()
    if (Object.keys(changes).length === 0) return setSaved(true)
    update.mutate({ id: task.id, body: changes }, { onSuccess: () => setSaved(true) })
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-3">
      <FormField
        label="Title"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        error={titleError}
        readOnly={!editable}
        maxLength={200}
      />
      <div>
        <label htmlFor="task-description" className="mb-1 block text-sm font-medium">
          Description
        </label>
        <textarea
          id="task-description"
          rows={4}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          readOnly={!editable}
          maxLength={5000}
          className={inputClass}
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label htmlFor="task-priority" className="mb-1 block text-sm font-medium">
            Priority
          </label>
          <select
            id="task-priority"
            value={priority}
            onChange={(e) => setPriority(e.target.value as Priority)}
            disabled={!editable}
            className={inputClass}
          >
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </div>
        <FormField
          label="Due date"
          type="date"
          value={dueDate}
          onChange={(e) => setDueDate(e.target.value)}
          readOnly={!editable}
        />
      </div>
      {canAssign ? (
        <div>
          <label htmlFor="task-assignee" className="mb-1 block text-sm font-medium">
            Assignee
          </label>
          <select
            id="task-assignee"
            value={assignee}
            onChange={(e) => setAssignee(e.target.value)}
            className={inputClass}
          >
            <option value="">Unassigned</option>
            {members.map((m) => (
              <option key={m.user_id} value={m.user_id}>
                {m.full_name}
              </option>
            ))}
          </select>
        </div>
      ) : (
        <p className="text-sm">
          <span className="font-medium">Assignee:</span> {assigneeName ?? 'Unassigned'}
        </p>
      )}
      <p className="text-xs text-slate-700">
        Created {new Date(task.created_at).toLocaleString()}
        {!editable && !readOnly && ' - you can edit only tasks assigned to you.'}
      </p>
      {update.error && <FormError error={update.error} />}
      {saved && !update.isPending && (
        <p role="status" className="text-sm font-medium text-green-800">
          Saved.
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        {editable && (
          <button type="submit" disabled={update.isPending} className={btn.primary}>
            Save changes
          </button>
        )}
        {can('task:delete') && !readOnly && (
          <DeleteControls
            confirming={confirmingDelete}
            setConfirming={setConfirmingDelete}
            onConfirm={() => remove.mutate(task.id, { onSuccess: onDeleted })}
          />
        )}
      </div>
      {remove.error && <FormError error={remove.error} />}
    </form>
  )
}

function DeleteControls(props: {
  confirming: boolean
  setConfirming: (v: boolean) => void
  onConfirm: () => void
}) {
  if (!props.confirming) {
    return (
      <button type="button" className={btn.secondary} onClick={() => props.setConfirming(true)}>
        Delete task
      </button>
    )
  }
  return (
    <>
      <button type="button" className={btn.danger} onClick={props.onConfirm}>
        Confirm delete
      </button>
      <button type="button" className={btn.secondary} onClick={() => props.setConfirming(false)}>
        Cancel
      </button>
    </>
  )
}
