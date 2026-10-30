import { describeError } from '../api/errors'
import { btn } from './styles'

export function LoadingState({ label = 'Loading' }: { label?: string }) {
  return (
    <div role="status" className="p-6 text-center text-slate-700">
      {label}...
    </div>
  )
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-400 p-8 text-center">
      <p className="font-medium text-slate-900">{title}</p>
      {hint && <p className="mt-1 text-sm text-slate-700">{hint}</p>}
    </div>
  )
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div role="alert" className="rounded-lg border border-red-700 bg-red-50 p-4 text-red-900">
      <p className="font-medium">Could not load this data.</p>
      <p className="mt-1 text-sm">{describeError(error)}</p>
      {onRetry && (
        <button type="button" onClick={onRetry} className={`${btn.secondary} mt-3`}>
          Retry
        </button>
      )}
    </div>
  )
}

/** Inline form/server error, announced to screen readers. */
export function FormError({ id, error }: { id?: string; error: unknown }) {
  return (
    <p id={id} role="alert" className="text-sm font-medium text-red-800">
      {describeError(error)}
    </p>
  )
}
