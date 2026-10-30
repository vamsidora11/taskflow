import { useState, type FormEvent } from 'react'
import type { MemberRead } from '../../api/types'
import { useAuth } from '../../auth/AuthContext'
import { canDeleteComment } from '../../auth/permissions'
import { EmptyState, ErrorState, FormError, LoadingState } from '../../components/states'
import { btn, inputClass } from '../../components/styles'
import { useAddComment, useComments, useDeleteComment } from './commentHooks'

interface Props {
  taskId: string
  members: MemberRead[]
  readOnly: boolean
}

export function CommentSection({ taskId, members, readOnly }: Props) {
  const { role, user, can } = useAuth()
  const comments = useComments(taskId)
  const add = useAddComment(taskId)
  const remove = useDeleteComment(taskId)
  const [body, setBody] = useState('')
  const [error, setError] = useState<string | null>(null)

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    if (!body.trim()) return setError('Write a comment first.')
    setError(null)
    add.mutate(body.trim(), { onSuccess: () => setBody('') })
  }

  const authorName = (id: string | null) =>
    members.find((m) => m.user_id === id)?.full_name ?? 'Former member'

  return (
    <section aria-labelledby="comments-heading" className="mt-6 border-t border-slate-300 pt-4">
      <h3 id="comments-heading" className="mb-3 font-semibold">
        Comments
      </h3>
      {comments.isPending && <LoadingState label="Loading comments" />}
      {comments.isError && (
        <ErrorState error={comments.error} onRetry={() => void comments.refetch()} />
      )}
      {comments.data?.length === 0 && <EmptyState title="No comments yet" />}
      <ul className="space-y-3">
        {comments.data?.map((c) => (
          <li key={c.id} className="rounded-md border border-slate-300 p-3">
            <p className="text-xs text-slate-700">
              <span className="font-medium">{authorName(c.author_id)}</span> on{' '}
              <time dateTime={c.created_at}>{new Date(c.created_at).toLocaleString()}</time>
            </p>
            <p className="mt-1 whitespace-pre-wrap text-sm">{c.body}</p>
            {!readOnly && canDeleteComment(role, user?.id ?? null, c) && (
              <button
                type="button"
                className={`${btn.ghost} mt-1`}
                aria-label={`Delete comment by ${authorName(c.author_id)}`}
                onClick={() => remove.mutate(c.id)}
              >
                Delete
              </button>
            )}
          </li>
        ))}
      </ul>
      {remove.error && <FormError error={remove.error} />}
      {can('comment:create') && !readOnly && (
        <form onSubmit={onSubmit} noValidate className="mt-4 space-y-2">
          <label htmlFor="comment-body" className="block text-sm font-medium">
            Add a comment
          </label>
          <textarea
            id="comment-body"
            rows={3}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? 'comment-error' : undefined}
            className={inputClass}
          />
          {error && (
            <p id="comment-error" role="alert" className="text-sm font-medium text-red-800">
              {error}
            </p>
          )}
          {add.error && <FormError error={add.error} />}
          <button type="submit" disabled={add.isPending} className={btn.primary}>
            Post comment
          </button>
        </form>
      )}
    </section>
  )
}
