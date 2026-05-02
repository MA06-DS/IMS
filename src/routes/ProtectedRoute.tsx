import { Navigate, Outlet, useLocation } from 'react-router-dom'
import type { AppRole } from '@/types/auth'
import { authStore } from '@/store/authStore'

export function ProtectedRoute({ role }: { role?: AppRole }) {
  const location = useLocation()
  const token = authStore((s) => s.token)
  const currentRole = authStore((s) => s.role)

  if (!token) return <Navigate to="/login" replace state={{ from: location }} />
  if (role && currentRole !== role) return <Navigate to="/login" replace />
  return <Outlet />
}
