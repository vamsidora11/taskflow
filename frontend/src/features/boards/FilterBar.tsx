import type { TaskFilters } from '../../api/tasks'
import { PRIORITIES, type MemberRead, type Priority } from '../../api/types'
import { btn, inputClass } from '../../components/styles'

interface Props {
  filters: TaskFilters
  members: MemberRead[]
  onChange: (filters: TaskFilters) => void
}

export function FilterBar({ filters, members, onChange }: Props) {
  const active = Boolean(filters.assignee_id || filters.priority)
  return (
    <form
      aria-label="Filter tasks"
      onSubmit={(e) => e.preventDefault()}
      className="mb-4 flex flex-wrap items-end gap-3"
    >
      <div>
        <label htmlFor="filter-assignee" className="mb-1 block text-sm font-medium">
          Assignee
        </label>
        <select
          id="filter-assignee"
          value={filters.assignee_id ?? ''}
          onChange={(e) => onChange({ ...filters, assignee_id: e.target.value || undefined })}
          className={inputClass}
        >
          <option value="">Anyone</option>
          {members.map((m) => (
            <option key={m.user_id} value={m.user_id}>
              {m.full_name}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label htmlFor="filter-priority" className="mb-1 block text-sm font-medium">
          Priority
        </label>
        <select
          id="filter-priority"
          value={filters.priority ?? ''}
          onChange={(e) =>
            onChange({
              ...filters,
              priority: (e.target.value || undefined) as Priority | undefined,
            })
          }
          className={inputClass}
        >
          <option value="">Any</option>
          {PRIORITIES.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </div>
      {active && (
        <button type="button" className={btn.secondary} onClick={() => onChange({})}>
          Clear filters
        </button>
      )}
    </form>
  )
}
