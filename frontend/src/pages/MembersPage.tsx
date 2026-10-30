import { useState, type FormEvent } from 'react'
import { ROLES, type MemberRead, type Role } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { FormField } from '../components/FormField'
import { EmptyState, ErrorState, FormError, LoadingState } from '../components/states'
import { btn, cardClass, inputClass } from '../components/styles'
import { usePageTitle } from '../components/usePageTitle'
import { useChangeRole, useInvite, useMembers, useRemoveMember } from '../features/members/hooks'

function InviteForm() {
  const invite = useInvite()
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<Role>('member')
  const [error, setError] = useState<string | null>(null)
  const [sentTo, setSentTo] = useState<string | null>(null)

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    setSentTo(null)
    if (!email.trim()) return setError('Enter an email address.')
    setError(null)
    invite.mutate(
      { email: email.trim(), role },
      {
        onSuccess: () => {
          setSentTo(email.trim())
          setEmail('')
        },
      },
    )
  }

  return (
    <form onSubmit={onSubmit} noValidate className={`${cardClass} mb-6 space-y-3`}>
      <h2 className="font-semibold">Invite a teammate</h2>
      <FormField
        label="Email"
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        error={error}
      />
      <div>
        <label htmlFor="invite-role" className="mb-1 block text-sm font-medium">
          Role
        </label>
        <select
          id="invite-role"
          value={role}
          onChange={(e) => setRole(e.target.value as Role)}
          className={inputClass}
        >
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </div>
      {invite.error && <FormError error={invite.error} />}
      {sentTo && (
        <p role="status" className="text-sm font-medium text-green-800">
          Invitation created for {sentTo}.
        </p>
      )}
      <button type="submit" disabled={invite.isPending} className={btn.primary}>
        Send invitation
      </button>
    </form>
  )
}

function MemberRow({ member, canManage }: { member: MemberRead; canManage: boolean }) {
  const changeRole = useChangeRole()
  const remove = useRemoveMember()
  const [confirming, setConfirming] = useState(false)
  const error = changeRole.error ?? remove.error

  return (
    <tr className="border-t border-slate-300">
      <td className="px-3 py-2">{member.full_name}</td>
      <td className="px-3 py-2">{member.email}</td>
      <td className="px-3 py-2">
        {canManage ? (
          <select
            aria-label={`Role for ${member.full_name}`}
            value={member.role}
            disabled={changeRole.isPending}
            onChange={(e) =>
              changeRole.mutate({ userId: member.user_id, role: e.target.value as Role })
            }
            className="rounded-md border border-slate-500 bg-white px-2 py-1 text-sm"
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        ) : (
          member.role
        )}
        {error && <FormError error={error} />}
      </td>
      {canManage && (
        <td className="px-3 py-2">
          {confirming ? (
            <span className="flex gap-2">
              <button
                type="button"
                className={btn.danger}
                onClick={() =>
                  remove.mutate(member.user_id, { onSettled: () => setConfirming(false) })
                }
              >
                Confirm remove {member.full_name}
              </button>
              <button type="button" className={btn.secondary} onClick={() => setConfirming(false)}>
                Cancel
              </button>
            </span>
          ) : (
            <button type="button" className={btn.secondary} onClick={() => setConfirming(true)}>
              Remove {member.full_name}
            </button>
          )}
        </td>
      )}
    </tr>
  )
}

export default function MembersPage() {
  usePageTitle('Members')
  const { can } = useAuth()
  const members = useMembers()
  const canManage = can('member:remove')

  return (
    <>
      <h1 className="mb-4 text-2xl font-semibold">Members</h1>
      {can('member:invite') && <InviteForm />}
      {members.isPending && <LoadingState label="Loading members" />}
      {members.isError && (
        <ErrorState error={members.error} onRetry={() => void members.refetch()} />
      )}
      {members.data?.length === 0 && <EmptyState title="No members found" />}
      {members.data && members.data.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-slate-300 bg-white">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Organization members</caption>
            <thead className="bg-slate-100">
              <tr>
                <th scope="col" className="px-3 py-2">
                  Name
                </th>
                <th scope="col" className="px-3 py-2">
                  Email
                </th>
                <th scope="col" className="px-3 py-2">
                  Role
                </th>
                {canManage && (
                  <th scope="col" className="px-3 py-2">
                    Actions
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {members.data.map((m) => (
                <MemberRow key={m.user_id} member={m} canManage={canManage} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
