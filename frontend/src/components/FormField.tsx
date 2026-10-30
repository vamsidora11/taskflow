import { useId, type InputHTMLAttributes } from 'react'
import { inputClass } from './styles'

interface Props extends InputHTMLAttributes<HTMLInputElement> {
  label: string
  error?: string | null
  hint?: string
}

export function FormField({ label, error, hint, className, ...input }: Props) {
  const id = useId()
  const hintId = `${id}-hint`
  const errorId = `${id}-error`
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(' ')
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-slate-900">
        {label}
      </label>
      <input
        id={id}
        className={`${inputClass} ${error ? 'border-red-700' : ''} ${className ?? ''}`}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy || undefined}
        {...input}
      />
      {hint && (
        <p id={hintId} className="mt-1 text-xs text-slate-700">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} role="alert" className="mt-1 text-sm font-medium text-red-800">
          {error}
        </p>
      )}
    </div>
  )
}
