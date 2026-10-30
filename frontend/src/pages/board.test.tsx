import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { appRoutes } from '../test/appRoutes'
import { TASKS, makeTask } from '../test/fixtures'
import { errorBody, mockFetch } from '../test/mockFetch'
import { renderApp } from '../test/render'

const titlesIn = (column: string) =>
  within(screen.getByRole('list', { name: `Tasks in ${column}` }))
    .queryAllByRole('button', { name: /^(Alpha|Beta|Gamma|New task)/ })
    .map((b) => b.textContent)

async function openBoard(role: 'admin' | 'manager' | 'member', overrides = {}) {
  const api = mockFetch(appRoutes(role, overrides))
  renderApp('/boards/b1')
  await screen.findByRole('button', { name: 'Alpha' })
  return api
}

describe('kanban moves', () => {
  it('moves with the keyboard buttons: optimistic update, then server call', async () => {
    let release!: () => void
    const gate = new Promise<void>((resolve) => (release = resolve))
    const api = await openBoard('manager', {
      'POST /api/v1/tasks/:id/move': async () => {
        await gate
        return { body: makeTask({ id: 't-alpha', column_id: 'c-todo', position: 1 }) }
      },
    })
    expect(titlesIn('To Do')).toEqual(['Alpha', 'Beta'])

    await userEvent.click(screen.getByRole('button', { name: 'Move Alpha down' }))

    await waitFor(() => expect(titlesIn('To Do')).toEqual(['Beta', 'Alpha'])) // optimistic
    expect(screen.getByText(/Moved Alpha to To Do, position 2 of 2/)).toBeInTheDocument()
    release()
    await waitFor(() => expect(api.count('POST', '/api/v1/tasks/t-alpha/move')).toBe(1))
    const call = api.calls.find((c) => c.path === '/api/v1/tasks/t-alpha/move')
    expect(call?.body).toEqual({ column_id: 'c-todo', position: 1 })
  })

  it('rolls back and shows an error when the server refuses the move', async () => {
    let release!: () => void
    const gate = new Promise<void>((resolve) => (release = resolve))
    await openBoard('manager', {
      'POST /api/v1/tasks/:id/move': async () => {
        await gate
        return errorBody('BOARD_ARCHIVED', 'Board is archived', 409)
      },
    })
    await userEvent.click(screen.getByRole('button', { name: 'Move Alpha to next column' }))
    await waitFor(() => expect(titlesIn('Doing')).toContain('Alpha'))
    expect(titlesIn('To Do')).toEqual(['Beta'])

    release()

    expect(await screen.findByText(/archived.*The move was undone/s)).toBeInTheDocument()
    await waitFor(() => expect(titlesIn('To Do')).toEqual(['Alpha', 'Beta']))
    expect(titlesIn('Doing')).toEqual(['Gamma'])
  })

  it('supports drag and drop between columns', async () => {
    const api = await openBoard('manager', {
      'POST /api/v1/tasks/:id/move': () => ({
        body: makeTask({ id: 't-alpha', column_id: 'c-doing', position: 1 }),
      }),
    })
    const card = screen.getByRole('button', { name: 'Alpha' }).closest('li') as HTMLElement
    expect(card).toHaveAttribute('draggable', 'true')
    const dataTransfer = { setData: vi.fn(), effectAllowed: '' }
    fireEvent.dragStart(card, { dataTransfer })
    const target = screen.getByRole('list', { name: 'Tasks in Doing' })
    fireEvent.dragOver(target, { dataTransfer })
    fireEvent.drop(target, { dataTransfer })

    await waitFor(() => expect(api.count('POST', '/api/v1/tasks/t-alpha/move')).toBe(1))
    const call = api.calls.find((c) => c.path === '/api/v1/tasks/t-alpha/move')
    expect(call?.body).toEqual({ column_id: 'c-doing', position: 1 }) // jsdom has no layout: end of list
  })

  it('does not make tasks draggable when a member may not move them', async () => {
    await openBoard('member')
    expect(screen.getByRole('button', { name: 'Alpha' }).closest('li')).toHaveAttribute(
      'draggable',
      'false',
    )
    expect(screen.getByRole('button', { name: 'Beta' }).closest('li')).toHaveAttribute(
      'draggable',
      'true',
    )
  })

  it('uses the API filters and pauses moving while filters are active', async () => {
    const api = await openBoard('manager')
    await userEvent.selectOptions(screen.getByLabelText('Priority'), 'high')
    await waitFor(() =>
      expect(
        api.calls.some(
          (c) => c.path === '/api/v1/boards/b1/tasks' && c.query.get('priority') === 'high',
        ),
      ).toBe(true),
    )
    expect(await screen.findByText(/Moving tasks is disabled/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Move Alpha/ })).not.toBeInTheDocument()
  })
})

describe('kanban tasks and columns', () => {
  it('creates a task with an Idempotency-Key and reuses it when the same request is retried', async () => {
    let attempts = 0
    const api = await openBoard('member', {
      'POST /api/v1/boards/:id/tasks': () =>
        ++attempts === 1
          ? errorBody('SERVICE_UNAVAILABLE', 'Try again', 503)
          : {
              status: 201,
              body: makeTask({ id: 't-new', title: 'New task', column_id: 'c-done' }),
            },
    })
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Add task to Done' }))
    await user.type(screen.getByLabelText('New task in Done'), 'New task')
    await user.click(screen.getByRole('button', { name: 'Add' }))
    expect(await screen.findByText('Try again')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Add' }))
    await waitFor(() => expect(attempts).toBe(2))

    const posts = api.calls.filter(
      (c) => c.method === 'POST' && c.path === '/api/v1/boards/b1/tasks',
    )
    const keys = posts.map((p) => p.headers.get('Idempotency-Key'))
    expect(keys[0]).toMatch(/^[0-9a-f-]{36}$/)
    expect(keys[1]).toBe(keys[0])
    expect(posts[0].body).toMatchObject({ title: 'New task', column_id: 'c-done' })
  })

  it('shows a clear message when deleting a column that still has tasks', async () => {
    await openBoard('admin', {
      'DELETE /api/v1/columns/:id': () => errorBody('COLUMN_NOT_EMPTY', 'Column has tasks', 409),
    })
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Delete column To Do' }))
    await user.click(screen.getByRole('button', { name: 'Confirm delete column To Do' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/still has tasks/i)
  })

  it('shows a retry-able error when tasks fail to load, and a 429 hint', async () => {
    let calls = 0
    mockFetch(
      appRoutes('admin', {
        'GET /api/v1/boards/:id/tasks': () =>
          ++calls === 1
            ? {
                ...errorBody('RATE_LIMITED', 'Too many requests', 429),
                headers: { 'Retry-After': '12' },
              }
            : { body: { items: TASKS, next_cursor: null } },
      }),
    )
    renderApp('/boards/b1')
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Slow down: too many requests. Retry in 12 s.',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('button', { name: 'Alpha' })).toBeInTheDocument()
  })

  it('shows an empty state on the dashboard when there are no boards', async () => {
    mockFetch(appRoutes('member', { 'GET /api/v1/boards': () => ({ body: { items: [] } }) }))
    renderApp('/')
    expect(await screen.findByText('No boards yet')).toBeInTheDocument()
  })
})

describe('task dialog', () => {
  it('is an accessible modal: labelled, traps focus, closes on Esc and restores focus', async () => {
    await openBoard('admin')
    const user = userEvent.setup()
    const opener = screen.getByRole('button', { name: 'Alpha' })
    await user.click(opener)

    const dialog = await screen.findByRole('dialog', { name: 'Alpha' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    await within(dialog).findByLabelText('Title')
    expect(dialog).toContainElement(document.activeElement as HTMLElement)

    for (let i = 0; i < 25; i++) {
      await user.tab()
      expect(dialog).toContainElement(document.activeElement as HTMLElement)
    }
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(opener).toHaveFocus()
  })

  it('sends only the changed fields when saving', async () => {
    const api = await openBoard('member', {
      'PATCH /api/v1/tasks/:id': () => ({ body: { ...TASKS[1], priority: 'urgent' } }),
    })
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Beta' }))
    const dialog = await screen.findByRole('dialog', { name: 'Beta' })
    await user.selectOptions(await within(dialog).findByLabelText('Priority'), 'urgent')
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }))
    await within(dialog).findByText('Saved.')
    const patch = api.calls.find((c) => c.method === 'PATCH')
    expect(patch?.body).toEqual({ priority: 'urgent' })
  })

  it('lets members delete only their own comments; managers delete any', async () => {
    const comments = [
      {
        id: 'k1',
        task_id: 't-beta',
        author_id: 'u-member',
        body: 'mine',
        created_at: '2026-02-01T10:00:00Z',
        updated_at: '2026-02-01T10:00:00Z',
      },
      {
        id: 'k2',
        task_id: 't-beta',
        author_id: 'u-admin',
        body: 'theirs',
        created_at: '2026-02-01T11:00:00Z',
        updated_at: '2026-02-01T11:00:00Z',
      },
    ]
    const routes = { 'GET /api/v1/tasks/:id/comments': () => ({ body: { items: comments } }) }

    mockFetch(appRoutes('member', routes))
    const first = renderApp('/boards/b1')
    await userEvent.click(await screen.findByRole('button', { name: 'Beta' }))
    await screen.findByText('theirs')
    expect(screen.getAllByRole('button', { name: /^Delete comment by/ })).toHaveLength(1)
    expect(screen.getByRole('button', { name: 'Delete comment by Mia Member' })).toBeInTheDocument()
    first.unmount()

    mockFetch(appRoutes('manager', routes))
    renderApp('/boards/b1')
    await userEvent.click(await screen.findByRole('button', { name: 'Beta' }))
    await screen.findByText('theirs')
    expect(screen.getAllByRole('button', { name: /^Delete comment by/ })).toHaveLength(2)
  })
})
