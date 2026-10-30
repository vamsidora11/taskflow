import { useState, type FormEvent } from 'react'
import { Link, Navigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { FormField } from '../components/FormField'
import { FormError } from '../components/states'
import { btn } from '../components/styles'
import { usePageTitle } from '../components/usePageTitle'
import { AuthCard } from './AuthCard'
import { MIN_PASSWORD, validatePassword } from './validation'

export default function AcceptInvitePage() {
  usePageTitle('Accept invitation')
  const [params] = useSearchParams()
  const token = params.get('token')
  const { status, acceptInvitation } = useAuth()
  const [fullName, setFullName] = useState('')
  const [password, setPassword] = useState('')
  const [passwordError, setPasswordError] = useState<string | null>(null)
  const [serverError, setServerError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  if (status === 'authenticated') return <Navigate to="/" replace />

  if (!token) {
    return (
      <AuthCard title="Invitation link problem">
        <p role="alert" className="text-sm text-red-800">
          This invitation link is missing its token. Open the link from your email again.
        </p>
        <Link to="/login" className="mt-4 inline-block font-medium text-indigo-800 underline">
          Go to log in
        </Link>
      </AuthCard>
    )
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const error = validatePassword(password)
    setPasswordError(error)
    if (error || !token) return
    setBusy(true)
    setServerError(null)
    try {
      await acceptInvitation(token, {
        password,
        full_name: fullName.trim() || undefined,
      })
    } catch (err) {
      setServerError(err)
      setBusy(false)
    }
  }

  return (
    <AuthCard title="Accept your invitation">
      <form onSubmit={(e) => void onSubmit(e)} noValidate className="space-y-4">
        <FormField
          label="Full name"
          autoComplete="name"
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          hint="Required if you are new to TaskFlow."
        />
        <FormField
          label="Password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={passwordError}
          hint={`New here: choose a password of at least ${MIN_PASSWORD} characters. Already have an account: enter your current password.`}
        />
        {serverError !== null && <FormError error={serverError} />}
        <button type="submit" disabled={busy} className={`${btn.primary} w-full`}>
          {busy ? 'Joining...' : 'Join organization'}
        </button>
      </form>
    </AuthCard>
  )
}
