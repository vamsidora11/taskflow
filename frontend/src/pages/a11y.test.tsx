import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'vitest-axe'
import { describe, expect, it } from 'vitest'
import { appRoutes } from '../test/appRoutes'
import { errorBody, mockFetch } from '../test/mockFetch'
import { renderApp } from '../test/render'

// jsdom has no layout engine, so axe's colour-contrast rule cannot run here; contrast is covered
// by choosing Tailwind palette pairs that meet WCAG AA, not by these tests.
describe('accessibility (axe)', () => {
  it('login page has no violations', async () => {
    mockFetch(
      appRoutes('admin', {
        'POST /api/v1/auth/refresh': () => errorBody('INVALID_TOKEN', 'x', 401),
      }),
    )
    const { container } = renderApp('/login')
    await screen.findByRole('heading', { name: 'Log in' })
    expect(await axe(container)).toHaveNoViolations()
  })

  it('login page with validation errors has no violations', async () => {
    mockFetch(
      appRoutes('admin', {
        'POST /api/v1/auth/refresh': () => errorBody('INVALID_TOKEN', 'x', 401),
      }),
    )
    const { container } = renderApp('/login')
    await userEvent.click(await screen.findByRole('button', { name: 'Log in' }))
    expect(await axe(container)).toHaveNoViolations()
  })

  it('board page has no violations', async () => {
    mockFetch(appRoutes('admin'))
    const { container } = renderApp('/boards/b1')
    await screen.findByRole('button', { name: 'Alpha' })
    expect(await axe(container)).toHaveNoViolations()
  })

  it('board page with the task dialog open has no violations', async () => {
    mockFetch(appRoutes('manager'))
    const { container } = renderApp('/boards/b1')
    await userEvent.click(await screen.findByRole('button', { name: 'Beta' }))
    await screen.findByLabelText('Title')
    expect(await axe(container)).toHaveNoViolations()
  })

  it('members page has no violations (admin view)', async () => {
    mockFetch(appRoutes('admin'))
    const { container } = renderApp('/members')
    await screen.findByText('mia@acme.test')
    expect(await axe(container)).toHaveNoViolations()
  })

  it('members page has no violations (member view)', async () => {
    mockFetch(appRoutes('member'))
    const { container } = renderApp('/members')
    await screen.findByText('mia@acme.test')
    expect(await axe(container)).toHaveNoViolations()
  })

  it('dashboard has a skip link, landmarks and a page title', async () => {
    mockFetch(appRoutes('admin'))
    const { container } = renderApp('/')
    await screen.findByRole('link', { name: 'Roadmap' })
    expect(screen.getByRole('link', { name: 'Skip to main content' })).toHaveAttribute(
      'href',
      '#main',
    )
    expect(screen.getByRole('banner')).toBeInTheDocument()
    expect(screen.getByRole('main')).toBeInTheDocument()
    expect(document.title).toBe('Boards | TaskFlow')
    expect(await axe(container)).toHaveNoViolations()
  })
})
