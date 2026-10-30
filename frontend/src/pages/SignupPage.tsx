import { useState, type FormEvent } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { FormField } from '../components/FormField'
import { FormError } from '../components/states'
import { btn } from '../components/styles'
import { usePageTitle } from '../components/usePageTitle'
import { AuthCard } from './AuthCard'
import { MIN_PASSWORD, validatePassword } from './validation'

type Field = 'organization_name' | 'full_name' | 'email' | 'password'

export default function SignupPage() {
  usePageTitle('Sign up')
  const { status, signup } = useAuth()
  const [values, setValues] = useState<Record<Field, string>>({
    organization_name: '',
    full_name: '',
    email: '',
    password: '',
  })
  const [errors, setErrors] = useState<Partial<Record<Field, string>>>({})
  const [serverError, setServerError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  if (status === 'authenticated') return <Navigate to="/" replace />

  const bind = (field: Field) => ({
    value: values[field],
    error: errors[field],
    onChange: (e: { target: { value: string } }) =>
      setValues((v) => ({ ...v, [field]: e.target.value })),
  })

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const next: Partial<Record<Field, string>> = {}
    if (!values.organization_name.trim()) next.organization_name = 'Enter an organization name.'
    if (!values.full_name.trim()) next.full_name = 'Enter your full name.'
    if (!values.email.trim()) next.email = 'Enter your email address.'
    const passwordError = validatePassword(values.password)
    if (passwordError) next.password = passwordError
    setErrors(next)
    if (Object.keys(next).length > 0) return
    setBusy(true)
    setServerError(null)
    try {
      await signup({
        organization_name: values.organization_name.trim(),
        full_name: values.full_name.trim(),
        email: values.email.trim(),
        password: values.password,
      })
    } catch (error) {
      setServerError(error)
      setBusy(false)
    }
  }

  return (
    <AuthCard title="Create your organization">
      <form onSubmit={(e) => void onSubmit(e)} noValidate className="space-y-4">
        <FormField
          label="Organization name"
          autoComplete="organization"
          {...bind('organization_name')}
        />
        <FormField label="Your full name" autoComplete="name" {...bind('full_name')} />
        <FormField label="Email" type="email" autoComplete="email" {...bind('email')} />
        <FormField
          label="Password"
          type="password"
          autoComplete="new-password"
          hint={`At least ${MIN_PASSWORD} characters.`}
          {...bind('password')}
        />
        {serverError !== null && <FormError error={serverError} />}
        <button type="submit" disabled={busy} className={`${btn.primary} w-full`}>
          {busy ? 'Creating...' : 'Create organization'}
        </button>
      </form>
      <p className="mt-4 text-sm text-slate-700">
        Already have an account?{' '}
        <Link to="/login" className="font-medium text-indigo-800 underline">
          Log in
        </Link>
      </p>
    </AuthCard>
  )
}
