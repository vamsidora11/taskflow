import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { LoadingState } from '../components/states'
import { useAuth } from './AuthContext'

export function ProtectedRoute() {
  const { status } = useAuth()
  const location = useLocation()
  if (status === 'loading') return <LoadingState label="Restoring your session" />
  if (status === 'anonymous') return <Navigate to="/login" replace state={{ from: location }} />
  return <Outlet />
}
