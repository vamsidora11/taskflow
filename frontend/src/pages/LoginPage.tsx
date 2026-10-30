import { useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { FormField } from '../components/FormField'
import { FormError } from '../components/states'
import { btn } from '../components/styles'
import { usePageTitle } from '../components/usePageTitle'
import { AuthCard } from './AuthCard'

interface LocationState {
  from?: { pathname: string; search?: string }
}

export default function LoginPage() {
  usePageTitle('Log in')
  const { status, login } = useAuth()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<{ email?: string; password?: string }>({})
  const [serverError, setServerError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  if (status === 'authenticated') {
    const from = (location.state as LocationState | null)?.from
    return <Navigate to={from ? `${from.pathname}${from.search ?? ''}` : '/'} replace />
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const next = {
      email: email.trim() ? undefined : 'Enter your email address.',
      password: password ? undefined : 'Enter your password.',
    }
    setErrors(next)
    if (next.email || next.password) return
    setBusy(true)
    setServerError(null)
    try {
      await login(email.trim(), password)
    } catch (error) {
      setServerError(error)
      setBusy(false)
    }
  }

  return (
    <AuthCard title="Log in">
      <form onSubmit={(e) => void onSubmit(e)} noValidate className="space-y-4">
        <FormField
          label="Email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          error={errors.email}
        />
        <FormField
          label="Password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={errors.password}
        />
        {serverError !== null && <FormError error={serverError} />}
        <button type="submit" disabled={busy} className={`${btn.primary} w-full`}>
          {busy ? 'Logging in...' : 'Log in'}
        </button>
      </form>
      <p className="mt-4 text-sm text-slate-700">
        New to TaskFlow?{' '}
        <Link to="/signup" className="font-medium text-indigo-800 underline">
          Create an organization
        </Link>
      </p>
    </AuthCard>
  )
}
