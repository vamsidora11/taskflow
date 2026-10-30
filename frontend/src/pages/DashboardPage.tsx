import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { FormField } from '../components/FormField'
import { EmptyState, ErrorState, FormError, LoadingState } from '../components/states'
import { btn, cardClass } from '../components/styles'
import { usePageTitle } from '../components/usePageTitle'
import { useBoards, useCreateBoard } from '../features/boards/hooks'

function CreateBoardForm() {
  const create = useCreateBoard()
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    if (!name.trim()) return setError('Enter a board name.')
    setError(null)
    create.mutate({ name: name.trim() }, { onSuccess: () => setName('') })
  }

  return (
    <form onSubmit={onSubmit} noValidate className={`${cardClass} mb-6 space-y-3`}>
      <h2 className="font-semibold">Create a board</h2>
      <FormField
        label="Board name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        error={error}
      />
      {create.error && <FormError error={create.error} />}
      <button type="submit" disabled={create.isPending} className={btn.primary}>
        Create board
      </button>
    </form>
  )
}

export default function DashboardPage() {
  const { activeOrganization, role, can } = useAuth()
  usePageTitle('Boards')
  const boards = useBoards()

  return (
    <>
      <h1 className="text-2xl font-semibold">{activeOrganization?.name}</h1>
      <p className="mb-6 text-slate-700">
        Your role: <strong>{role}</strong>
      </p>
      {can('board:manage') && <CreateBoardForm />}
      <h2 className="mb-3 text-lg font-semibold">Boards</h2>
      {boards.isPending && <LoadingState label="Loading boards" />}
      {boards.isError && <ErrorState error={boards.error} onRetry={() => void boards.refetch()} />}
      {boards.data?.length === 0 && (
        <EmptyState
          title="No boards yet"
          hint={
            can('board:manage') ? 'Create your first board above.' : 'Ask a manager to create one.'
          }
        />
      )}
      {boards.data && boards.data.length > 0 && (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {boards.data.map((board) => (
            <li key={board.id} className={cardClass}>
              <Link to={`/boards/${board.id}`} className="font-semibold text-indigo-800 underline">
                {board.name}
              </Link>
              {board.description && (
                <p className="mt-1 text-sm text-slate-700">{board.description}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </>
  )
}
