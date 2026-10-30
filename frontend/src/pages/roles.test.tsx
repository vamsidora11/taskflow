import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { Role } from '../api/types'
import { appRoutes } from '../test/appRoutes'
import { USERS } from '../test/fixtures'
import { mockFetch } from '../test/mockFetch'
import { renderApp } from '../test/render'

const ROLES: Role[] = ['admin', 'manager', 'member']
const isLead = (role: Role) => role !== 'member'

async function open(role: Role, route: string, heading: RegExp | string) {
  mockFetch(appRoutes(role))
  renderApp(route)
  await screen.findByRole('heading', { level: 1, name: heading })
}

describe.each(ROLES)('role-based UI as %s', (role) => {
  it('dashboard: board creation and the Activity nav link follow the matrix', async () => {
    await open(role, '/', 'Acme')
    expect(screen.queryByRole('button', { name: 'Create board' }) !== null).toBe(isLead(role))
    const nav = screen.getByRole('navigation', { name: 'Main' })
    expect(within(nav).queryByRole('link', { name: 'Activity' }) !== null).toBe(isLead(role))
    expect(within(nav).getByRole('link', { name: 'Members' })).toBeInTheDocument()
  })

  it('members page: invite, role change and remove are admin-only', async () => {
    await open(role, '/members', 'Members')
    await screen.findByText(USERS.member.email)
    const admin = role === 'admin'
    expect(screen.queryByRole('button', { name: 'Send invitation' }) !== null).toBe(admin)
    expect(screen.queryByLabelText('Role for Mia Member') !== null).toBe(admin)
    expect(screen.queryByRole('button', { name: 'Remove Mia Member' }) !== null).toBe(admin)
  })

  it('board page: column management, archive and task creation', async () => {
    await open(role, '/boards/b1', 'Roadmap')
    await screen.findByText('Alpha')
    expect(screen.queryByRole('button', { name: 'Archive board' }) !== null).toBe(isLead(role))
    expect(screen.queryByRole('button', { name: 'Add column' }) !== null).toBe(isLead(role))
    expect(screen.queryByRole('button', { name: /Rename column To Do/ }) !== null).toBe(
      isLead(role),
    )
    expect(screen.getAllByRole('button', { name: /^Add task/ })).toHaveLength(3)
  })

  it('board page: move buttons appear only on tasks the user may move', async () => {
    await open(role, '/boards/b1', 'Roadmap')
    await screen.findByText('Alpha')
    // Beta is assigned to the member, so every role may move it; Alpha and Gamma only leads.
    expect(screen.queryByRole('button', { name: 'Move Alpha down' }) !== null).toBe(isLead(role))
    expect(screen.getByRole('button', { name: 'Move Beta up' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Move Gamma to next column' }) !== null).toBe(
      isLead(role),
    )
  })

  it('task dialog: edit-any vs edit-own, assignee select and delete', async () => {
    await open(role, '/boards/b1', 'Roadmap')
    const user = userEvent.setup()
    const lead = isLead(role)
    const asMember = role === 'member'

    // Alpha is unassigned and nobody's: only admin/manager may edit it.
    await user.click(await screen.findByRole('button', { name: 'Alpha' }))
    let dialog = await screen.findByRole('dialog', { name: 'Alpha' })
    await within(dialog).findByLabelText('Title')
    expect(within(dialog).getByLabelText('Title')).toHaveProperty('readOnly', !lead)
    expect(within(dialog).queryByRole('button', { name: 'Save changes' }) !== null).toBe(lead)
    expect(within(dialog).queryByLabelText('Assignee') !== null).toBe(lead)
    expect(within(dialog).queryByRole('button', { name: 'Delete task' }) !== null).toBe(lead)
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())

    // Beta is assigned to the member: editable by everyone, but only leads can reassign/delete.
    await user.click(screen.getByRole('button', { name: 'Beta' }))
    dialog = await screen.findByRole('dialog', { name: 'Beta' })
    await within(dialog).findByLabelText('Title')
    expect(within(dialog).getByLabelText('Title')).toHaveProperty('readOnly', false)
    expect(within(dialog).getByRole('button', { name: 'Save changes' })).toBeInTheDocument()
    expect(within(dialog).queryByLabelText('Assignee') !== null).toBe(lead)
    if (asMember) expect(within(dialog).getByText(USERS.member.full_name)).toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: 'Delete task' }) !== null).toBe(lead)
  })
})

describe('activity page', () => {
  it('shows a friendly no-access state to members without calling the API', async () => {
    const api = mockFetch(appRoutes('member'))
    renderApp('/activity')
    expect(await screen.findByText(/do not have access to the activity log/i)).toBeInTheDocument()
    expect(api.count('GET', '/api/v1/audit-logs')).toBe(0)
  })

  it('shows the log with a Load more button to managers', async () => {
    const entry = (id: string) => ({
      id,
      action: 'task.moved',
      entity_type: 'task',
      entity_id: 'abcdefgh-1',
      actor_user_id: USERS.admin.id,
      metadata: {},
      ip_address: null,
      request_id: null,
      created_at: '2026-02-01T10:00:00Z',
    })
    const api = mockFetch(
      appRoutes('manager', {
        'GET /api/v1/audit-logs': (req) =>
          req.query.get('cursor')
            ? { body: { items: [entry('2')], next_cursor: null } }
            : { body: { items: [entry('1')], next_cursor: 'next' } },
      }),
    )
    renderApp('/activity')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Load more' }))
    await waitFor(() => expect(screen.getAllByText('task.moved')).toHaveLength(2))
    expect(
      api.calls
        .filter((c) => c.path === '/api/v1/audit-logs')
        .at(-1)
        ?.query.get('cursor'),
    ).toBe('next')
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
  })
})
