import { useState, type FormEvent } from 'react'
import type { ColumnRead } from '../../api/types'
import { FormField } from '../../components/FormField'
import { FormError } from '../../components/states'
import { btn } from '../../components/styles'
import { useColumnMutations } from './hooks'

/** Column title with rename/delete controls (rendered only for admin/manager by the caller). */
export function ColumnHeader({
  column,
  boardId,
  count,
  canManage,
}: {
  column: ColumnRead
  boardId: string
  count: number
  canManage: boolean
}) {
  const { rename, remove } = useColumnMutations(boardId)
  const [editing, setEditing] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [name, setName] = useState(column.name)
  const [error, setError] = useState<string | null>(null)

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    if (!name.trim()) return setError('Enter a column name.')
    setError(null)
    rename.mutate({ id: column.id, name: name.trim() }, { onSuccess: () => setEditing(false) })
  }

  if (editing) {
    return (
      <form onSubmit={onSubmit} noValidate className="space-y-2">
        <FormField
          label={`Rename column ${column.name}`}
          value={name}
          onChange={(e) => setName(e.target.value)}
          error={error}
          maxLength={100}
        />
        {rename.error && <FormError error={rename.error} />}
        <div className="flex gap-2">
          <button type="submit" disabled={rename.isPending} className={btn.primary}>
            Save
          </button>
          <button type="button" className={btn.secondary} onClick={() => setEditing(false)}>
            Cancel
          </button>
        </div>
      </form>
    )
  }

  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-semibold">
          {column.name} <span className="font-normal text-slate-700">({count})</span>
        </h2>
        {canManage && (
          <div className="flex gap-1">
            <button
              type="button"
              className={btn.ghost}
              aria-label={`Rename column ${column.name}`}
              onClick={() => {
                setName(column.name)
                setEditing(true)
              }}
            >
              Rename
            </button>
            {confirming ? (
              <button
                type="button"
                className={btn.danger}
                aria-label={`Confirm delete column ${column.name}`}
                onClick={() => remove.mutate(column.id, { onSettled: () => setConfirming(false) })}
              >
                Confirm delete
              </button>
            ) : (
              <button
                type="button"
                className={btn.ghost}
                aria-label={`Delete column ${column.name}`}
                onClick={() => setConfirming(true)}
              >
                Delete
              </button>
            )}
          </div>
        )}
      </div>
      {remove.error && <FormError error={remove.error} />}
    </div>
  )
}
