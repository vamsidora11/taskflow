import type { ReactNode } from 'react'

/** Centered card used by the unauthenticated pages (login, signup, accept invite). */
export function AuthCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <main id="main" className="mx-auto flex min-h-screen max-w-md items-center px-4">
      <div className="w-full rounded-lg border border-slate-300 bg-white p-6 shadow-sm">
        <p className="text-sm font-bold text-indigo-800">TaskFlow</p>
        <h1 className="mb-4 text-2xl font-semibold">{title}</h1>
        {children}
      </div>
    </main>
  )
}
