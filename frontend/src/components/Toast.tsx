import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'

type Tone = 'error' | 'info'
type Notify = (message: string, tone?: Tone) => void

interface ToastItem {
  id: number
  message: string
  tone: Tone
}

const ToastContext = createContext<Notify | null>(null)
let nextId = 0

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])

  const dismiss = useCallback((id: number) => {
    setItems((current) => current.filter((t) => t.id !== id))
  }, [])

  const notify = useCallback<Notify>(
    (message, tone = 'info') => {
      const id = nextId++
      setItems((current) => [...current, { id, message, tone }])
      window.setTimeout(() => dismiss(id), 8000)
    },
    [dismiss],
  )

  return (
    <ToastContext.Provider value={notify}>
      {children}
      <div
        role="status"
        aria-live="polite"
        className="fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-2"
      >
        {items.map((t) => (
          <div
            key={t.id}
            className={`flex items-start justify-between gap-2 rounded-md border p-3 text-sm shadow ${
              t.tone === 'error'
                ? 'border-red-700 bg-red-50 text-red-900'
                : 'border-slate-400 bg-white text-slate-900'
            }`}
          >
            <span>{t.message}</span>
            <button type="button" onClick={() => dismiss(t.id)} aria-label="Dismiss message">
              &times;
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast(): Notify {
  const notify = useContext(ToastContext)
  if (!notify) throw new Error('useToast must be used inside <ToastProvider>')
  return notify
}
