import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { tokenStore } from '../api/tokenStore'
import { appRoutes } from '../test/appRoutes'
import { ORG_B, USERS, meFor, token } from '../test/fixtures'
import { errorBody, mockFetch } from '../test/mockFetch'
import { renderApp } from '../test/render'

const noSession = () => errorBody('INVALID_TOKEN', 'No session', 401)

describe('session restore', () => {
  it('shows a loading state, restores the session via refresh and renders the app', async () => {
    const api = mockFetch(appRoutes('admin'))
    renderApp('/')
    expect(screen.getByText(/restoring your session/i)).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'Acme' })).toBeInTheDocument()
    expect(api.count('POST', '/api/v1/auth/refresh')).toBe(1)
    expect(tokenStore.get()).toBe('access-1')
    // The /auth/me call carries the refreshed token.
    const me = api.calls.find((c) => c.path === '/api/v1/auth/me')
    expect(me?.headers.get('Authorization')).toBe('Bearer access-1')
  })
})

describe('protected routes', () => {
  it('redirects anonymous visitors to /login', async () => {
    mockFetch(appRoutes('admin', { 'POST /api/v1/auth/refresh': noSession }))
    renderApp('/members')
    expect(await screen.findByRole('heading', { name: 'Log in' })).toBeInTheDocument()
    expect(document.title).toBe('Log in | TaskFlow')
  })

  it('returns to the originally requested page after logging in', async () => {
    mockFetch(
      appRoutes('admin', {
        'POST /api/v1/auth/refresh': noSession,
        'POST /api/v1/auth/login': () => ({ body: token('admin') }),
      }),
    )
    renderApp('/members')
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Email'), USERS.admin.email)
    await user.type(screen.getByLabelText('Password'), 'correct horse battery')
    await user.click(screen.getByRole('button', { name: 'Log in' }))
    expect(await screen.findByRole('heading', { name: 'Members' })).toBeInTheDocument()
  })
})

describe('login', () => {
  it('logs in and lands on the dashboard', async () => {
    const api = mockFetch(
      appRoutes('admin', {
        'POST /api/v1/auth/refresh': noSession,
        'POST /api/v1/auth/login': () => ({ body: token('admin') }),
      }),
    )
    renderApp('/login')
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Email'), 'ada@acme.test')
    await user.type(screen.getByLabelText('Password'), 'correct horse battery')
    await user.click(screen.getByRole('button', { name: 'Log in' }))
    expect(await screen.findByRole('heading', { name: 'Acme' })).toBeInTheDocument()
    const login = api.calls.find((c) => c.path === '/api/v1/auth/login')
    expect(login?.body).toEqual({ email: 'ada@acme.test', password: 'correct horse battery' })
  })

  it('shows the server error inline and accessibly on failure', async () => {
    mockFetch(
      appRoutes('admin', {
        'POST /api/v1/auth/refresh': noSession,
        'POST /api/v1/auth/login': () =>
          errorBody('INVALID_CREDENTIALS', 'Invalid email or password', 401),
      }),
    )
    renderApp('/login')
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Email'), 'ada@acme.test')
    await user.type(screen.getByLabelText('Password'), 'wrong')
    await user.click(screen.getByRole('button', { name: 'Log in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password')
    expect(screen.getByRole('heading', { name: 'Log in' })).toBeInTheDocument()
    expect(tokenStore.get()).toBeNull()
  })

  it('validates required fields client-side without calling the API', async () => {
    const api = mockFetch(appRoutes('admin', { 'POST /api/v1/auth/refresh': noSession }))
    renderApp('/login')
    await userEvent.click(await screen.findByRole('button', { name: 'Log in' }))
    expect(screen.getByLabelText('Email')).toHaveAccessibleDescription('Enter your email address.')
    expect(screen.getByLabelText('Password')).toHaveAttribute('aria-invalid', 'true')
    expect(api.count('POST', '/api/v1/auth/login')).toBe(0)
  })
})

describe('signup', () => {
  it('enforces a 12 character password before submitting', async () => {
    const api = mockFetch(appRoutes('admin', { 'POST /api/v1/auth/refresh': noSession }))
    renderApp('/signup')
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Organization name'), 'Acme')
    await user.type(screen.getByLabelText('Your full name'), 'Ada')
    await user.type(screen.getByLabelText('Email'), 'ada@acme.test')
    await user.type(screen.getByLabelText('Password'), 'short')
    await user.click(screen.getByRole('button', { name: 'Create organization' }))
    expect(await screen.findByText('Use at least 12 characters.')).toBeInTheDocument()
    expect(api.count('POST', '/api/v1/auth/signup')).toBe(0)
  })

  it('signs up and lands on the dashboard', async () => {
    mockFetch(
      appRoutes('admin', {
        'POST /api/v1/auth/refresh': noSession,
        'POST /api/v1/auth/signup': () => ({ status: 201, body: token('admin') }),
      }),
    )
    renderApp('/signup')
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Organization name'), 'Acme')
    await user.type(screen.getByLabelText('Your full name'), 'Ada Admin')
    await user.type(screen.getByLabelText('Email'), 'ada@acme.test')
    await user.type(screen.getByLabelText('Password'), 'long enough password')
    await user.click(screen.getByRole('button', { name: 'Create organization' }))
    expect(await screen.findByRole('heading', { name: 'Acme' })).toBeInTheDocument()
  })
})

describe('accept invite', () => {
  it('reads the token from the URL and posts it with the password', async () => {
    const api = mockFetch(
      appRoutes('member', {
        'POST /api/v1/auth/refresh': noSession,
        'POST /api/v1/org/invitations/:token/accept': () => ({ body: token('member') }),
      }),
    )
    renderApp('/accept-invite?token=abc123')
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Full name'), 'Mia Member')
    await user.type(screen.getByLabelText('Password'), 'long enough password')
    await user.click(screen.getByRole('button', { name: 'Join organization' }))
    await screen.findByRole('heading', { name: 'Acme' })
    const accept = api.calls.find((c) => c.path === '/api/v1/org/invitations/abc123/accept')
    expect(accept?.body).toEqual({ password: 'long enough password', full_name: 'Mia Member' })
  })

  it('explains a missing token', async () => {
    mockFetch(appRoutes('member', { 'POST /api/v1/auth/refresh': noSession }))
    renderApp('/accept-invite')
    expect(await screen.findByRole('alert')).toHaveTextContent(/missing its token/i)
  })
})

describe('logout and org switching', () => {
  it('logs out: calls the API, clears the token and returns to /login', async () => {
    const api = mockFetch(
      appRoutes('admin', { 'POST /api/v1/auth/logout': () => ({ status: 204 }) }),
    )
    renderApp('/')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: USERS.admin.full_name }))
    await user.click(screen.getByRole('button', { name: 'Log out' }))
    expect(await screen.findByRole('heading', { name: 'Log in' })).toBeInTheDocument()
    expect(api.count('POST', '/api/v1/auth/logout')).toBe(1)
    expect(tokenStore.get()).toBeNull()
  })

  it('switching organization calls switch-org, clears the query cache and refetches', async () => {
    let activeOrg = 'org-a'
    const api = mockFetch(
      appRoutes('admin', {
        'POST /api/v1/auth/switch-org': (req) => {
          activeOrg = (req.body as { organization_id: string }).organization_id
          return { body: token('member', activeOrg, 'access-2') }
        },
        'GET /api/v1/auth/me': () => ({
          body:
            activeOrg === 'org-a'
              ? meFor('admin')
              : { ...meFor('member'), active_organization: ORG_B },
        }),
        'GET /api/v1/boards': () => ({
          body: {
            items: [
              {
                id: 'b1',
                name: activeOrg === 'org-a' ? 'Acme board' : 'Beta board',
                description: null,
                is_archived: false,
                created_by: 'x',
                created_at: '2026-01-01T00:00:00Z',
                updated_at: '2026-01-01T00:00:00Z',
              },
            ],
          },
        }),
      }),
    )
    const { queryClient } = renderApp('/')
    const clear = vi.spyOn(queryClient, 'clear')
    expect(await screen.findByRole('link', { name: 'Acme board' })).toBeInTheDocument()

    await userEvent.selectOptions(screen.getByLabelText('Organization'), 'org-b')

    expect(await screen.findByRole('link', { name: 'Beta board' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Acme board' })).not.toBeInTheDocument()
    expect(clear).toHaveBeenCalled()
    expect(tokenStore.get()).toBe('access-2')
    expect(api.count('POST', '/api/v1/auth/switch-org')).toBe(1)
    // Role now comes from the new organization: members get no create-board form.
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Create board' })).not.toBeInTheDocument(),
    )
  })
})
