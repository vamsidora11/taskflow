import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { OrgSwitcher } from './OrgSwitcher'
import { UserMenu } from './UserMenu'

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 ${
    isActive ? 'bg-slate-700 underline underline-offset-4' : ''
  }`

export function Layout() {
  const { can } = useAuth()
  return (
    <div className="min-h-screen">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-md focus:bg-white focus:px-3 focus:py-2"
      >
        Skip to main content
      </a>
      <header className="bg-slate-900">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-4">
            <span className="text-lg font-bold text-white">TaskFlow</span>
            <nav aria-label="Main">
              <ul className="flex items-center gap-1">
                <li>
                  <NavLink to="/" end className={linkClass}>
                    Boards
                  </NavLink>
                </li>
                <li>
                  <NavLink to="/members" className={linkClass}>
                    Members
                  </NavLink>
                </li>
                {can('audit:view') && (
                  <li>
                    <NavLink to="/activity" className={linkClass}>
                      Activity
                    </NavLink>
                  </li>
                )}
              </ul>
            </nav>
          </div>
          <div className="flex items-center gap-4">
            <OrgSwitcher />
            <UserMenu />
          </div>
        </div>
      </header>
      <main id="main" tabIndex={-1} className="mx-auto max-w-7xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  )
}
