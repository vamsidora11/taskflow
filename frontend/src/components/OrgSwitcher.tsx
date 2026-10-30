import { useId } from 'react'
import { useNavigate } from 'react-router-dom'
import { describeError } from '../api/errors'
import { useAuth } from '../auth/AuthContext'
import { useToast } from './Toast'

export function OrgSwitcher() {
  const { organizations, activeOrganization, switchOrganization } = useAuth()
  const navigate = useNavigate()
  const notify = useToast()
  const id = useId()

  async function onChange(organizationId: string) {
    if (organizationId === activeOrganization?.id) return
    try {
      await switchOrganization(organizationId)
      navigate('/')
    } catch (error) {
      notify(describeError(error), 'error')
    }
  }

  return (
    <div className="flex items-center gap-2">
      <label htmlFor={id} className="text-sm text-slate-200">
        Organization
      </label>
      <select
        id={id}
        value={activeOrganization?.id ?? ''}
        onChange={(e) => void onChange(e.target.value)}
        className="rounded-md border border-slate-400 bg-white px-2 py-1 text-sm text-slate-900"
      >
        {organizations.map((org) => (
          <option key={org.id} value={org.id}>
            {org.name} ({org.role})
          </option>
        ))}
      </select>
    </div>
  )
}
