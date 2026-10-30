import { useRef, useState, type FormEvent } from 'react'
import type { TaskCreate } from '../../api/types'
import { FormField } from '../../components/FormField'
import { FormError } from '../../components/states'
import { btn } from '../../components/styles'
import { useCreateTask } from './taskHooks'

/**
 * Inline create-task form for one column. The Idempotency-Key is generated once per submission
 * attempt and reused if the user retries the identical request, so a retry cannot duplicate it.
 */
export function AddTaskForm({ boardId, columnId, columnName }: Props) {
  const create = useCreateTask(boardId)
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [error, setError] = useState<string | null>(null)
  const attempt = useRef<{ key: string; signature: string } | null>(null)

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    const trimmed = title.trim()
    if (!trimmed) return setError('Enter a task title.')
    setError(null)
    const body: TaskCreate = { title: trimmed, column_id: columnId, priority: 'medium' }
    const signature = JSON.stringify(body)
    if (attempt.current?.signature !== signature) {
      attempt.current = { key: crypto.randomUUID(), signature }
    }
    create.mutate(
      { body, idempotencyKey: attempt.current.key },
      {
        onSuccess: () => {
          attempt.current = null
          setTitle('')
          setOpen(false)
        },
      },
    )
  }

  if (!open) {
    return (
      <button
        type="button"
        className={btn.ghost}
        aria-label={`Add task to ${columnName}`}
        onClick={() => setOpen(true)}
      >
        Add task
      </button>
    )
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-2">
      <FormField
        label={`New task in ${columnName}`}
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        error={error}
        maxLength={200}
      />
      {create.error && <FormError error={create.error} />}
      <div className="flex gap-2">
        <button type="submit" disabled={create.isPending} className={btn.primary}>
          Add
        </button>
        <button type="button" className={btn.secondary} onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
    </form>
  )
}

interface Props {
  boardId: string
  columnId: string
  columnName: string
}
