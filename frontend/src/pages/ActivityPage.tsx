import { useMemo, useState, type FormEvent } from 'react'
import type { AuditFilters } from '../api/audit'
import { describeError } from '../api/errors'
import { useAuth } from '../auth/AuthContext'
import { FormField } from '../components/FormField'
import { EmptyState, ErrorState, LoadingState } from '../components/states'
import { btn, cardClass, inputClass } from '../components/styles'
import { usePageTitle } from '../components/usePageTitle'
import { useAuditLogs } from '../features/audit/hooks'
import { useMembers } from '../features/members/hooks'

interface FormValues {
  action: string
  entity_type: string
  actor_user_id: string
  created_from: string
  created_to: string
}

const EMPTY: FormValues = {
  action: '',
  entity_type: '',
  actor_user_id: '',
  created_from: '',
  created_to: '',
}

/** datetime-local gives local wall-clock time; the API expects an absolute ISO timestamp. */
function toIso(local: string): string | undefined {
  return local ? new Date(local).toISOString() : undefined
}

function toFilters(v: FormValues): AuditFilters {
  return {
    action: v.action.trim() || undefined,
    entity_type: v.entity_type.trim() || undefined,
    actor_user_id: v.actor_user_id || undefined,
    created_from: toIso(v.created_from),
    created_to: toIso(v.created_to),
  }
}

function FilterForm({ onApply }: { onApply: (filters: AuditFilters) => void }) {
  const members = useMembers()
  const [values, setValues] = useState<FormValues>(EMPTY)
  const set = (key: keyof FormValues) => (e: { target: { value: string } }) =>
    setValues((v) => ({ ...v, [key]: e.target.value }))

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    onApply(toFilters(values))
  }

  return (
    <form
      onSubmit={onSubmit}
      className={`${cardClass} mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3`}
    >
      <FormField
        label="Action"
        placeholder="e.g. task.moved"
        value={values.action}
        onChange={set('action')}
      />
      <FormField
        label="Entity type"
        placeholder="e.g. task"
        value={values.entity_type}
        onChange={set('entity_type')}
      />
      <div>
        <label htmlFor="audit-actor" className="mb-1 block text-sm font-medium">
          Actor
        </label>
        <select
          id="audit-actor"
          value={values.actor_user_id}
          onChange={set('actor_user_id')}
          className={inputClass}
        >
          <option value="">Anyone</option>
          {members.data?.map((m) => (
            <option key={m.user_id} value={m.user_id}>
              {m.full_name}
            </option>
          ))}
        </select>
      </div>
      <FormField
        label="From"
        type="datetime-local"
        value={values.created_from}
        onChange={set('created_from')}
      />
      <FormField
        label="To"
        type="datetime-local"
        value={values.created_to}
        onChange={set('created_to')}
      />
      <div className="flex items-end gap-2">
        <button type="submit" className={btn.primary}>
          Apply filters
        </button>
        <button
          type="button"
          className={btn.secondary}
          onClick={() => {
            setValues(EMPTY)
            onApply({})
          }}
        >
          Clear
        </button>
      </div>
    </form>
  )
}

function AuditTable({ filters }: { filters: AuditFilters }) {
  const logs = useAuditLogs(filters)
  const members = useMembers()
  const names = useMemo(
    () => new Map((members.data ?? []).map((m) => [m.user_id, m.full_name])),
    [members.data],
  )
  const rows = logs.data?.pages.flatMap((p) => p.items) ?? []

  if (logs.isPending) return <LoadingState label="Loading activity" />
  if (logs.isError && !logs.data)
    return <ErrorState error={logs.error} onRetry={() => void logs.refetch()} />
  if (rows.length === 0) return <EmptyState title="No activity matches these filters" />

  return (
    <>
      <div className="overflow-x-auto rounded-lg border border-slate-300 bg-white">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">Audit log entries, newest first</caption>
          <thead className="bg-slate-100">
            <tr>
              <th scope="col" className="px-3 py-2">
                When
              </th>
              <th scope="col" className="px-3 py-2">
                Actor
              </th>
              <th scope="col" className="px-3 py-2">
                Action
              </th>
              <th scope="col" className="px-3 py-2">
                Entity
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className="border-t border-slate-300">
                <td className="whitespace-nowrap px-3 py-2">
                  {new Date(row.created_at).toLocaleString()}
                </td>
                <td className="px-3 py-2">
                  {row.actor_user_id
                    ? (names.get(row.actor_user_id) ?? row.actor_user_id)
                    : 'System'}
                </td>
                <td className="px-3 py-2 font-mono">{row.action}</td>
                <td className="px-3 py-2">
                  {row.entity_type}
                  {row.entity_id ? (
                    <span className="text-slate-700"> {row.entity_id.slice(0, 8)}</span>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {logs.isFetchNextPageError && (
        <p role="alert" className="mt-3 text-sm font-medium text-red-800">
          {describeError(logs.error)}
        </p>
      )}
      {logs.hasNextPage && (
        <button
          type="button"
          className={`${btn.secondary} mt-4`}
          disabled={logs.isFetchingNextPage}
          onClick={() => void logs.fetchNextPage()}
        >
          {logs.isFetchingNextPage ? 'Loading...' : 'Load more'}
        </button>
      )}
    </>
  )
}

export default function ActivityPage() {
  usePageTitle('Activity')
  const { can } = useAuth()
  const [filters, setFilters] = useState<AuditFilters>({})

  if (!can('audit:view')) {
    return (
      <>
        <h1 className="mb-4 text-2xl font-semibold">Activity</h1>
        <EmptyState
          title="You do not have access to the activity log"
          hint="Only admins and managers can view it."
        />
      </>
    )
  }

  return (
    <>
      <h1 className="mb-4 text-2xl font-semibold">Activity</h1>
      <FilterForm onApply={setFilters} />
      <AuditTable filters={filters} />
    </>
  )
}
