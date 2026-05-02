import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { jwtDecode } from 'jwt-decode'
import type { AppRole, AuthSession, JwtPayload } from '@/types/auth'
import * as authApi from '@/api/auth.api'

interface AuthState {
  token: string | null
  refreshTokenValue: string | null
  role: AppRole | null
  adminRole: string | null
  user: AuthSession['user'] | null
  refreshTokenStub: boolean
  login: (args: { username: string; password: string; role: AppRole }) => Promise<void>
  registerCustomer: (args: authApi.RegisterCustomerDTO) => Promise<authApi.AuthSession>
  logout: () => void
  refreshToken: () => Promise<void>
}

function readRoleFromToken(token: string): AppRole | null {
  try {
    const payload = jwtDecode<JwtPayload>(token)
    return payload.role ?? null
  } catch {
    return null
  }
}

function readAdminRoleFromToken(token: string): string | null {
  try {
    const payload = jwtDecode<JwtPayload>(token)
    return payload.db_role ?? null
  } catch {
    return null
  }
}

export const authStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      refreshTokenValue: null,
      role: null,
      adminRole: null,
      user: null,
      refreshTokenStub: false,
      login: async ({ username, password, role }) => {
        const session = await authApi.login({ username, password, role })
        set({
          token: session.token,
          refreshTokenValue: session.refreshToken,
          role: readRoleFromToken(session.token) ?? session.role,
          adminRole: readAdminRoleFromToken(session.token),
          user: session.user,
        })
      },
      registerCustomer: async (args) => {
        const session = await authApi.register(args)
        set({
          token: session.token,
          refreshTokenValue: session.refreshToken,
          role: readRoleFromToken(session.token) ?? session.role,
          adminRole: readAdminRoleFromToken(session.token),
          user: session.user,
        })
        return session
      },
      logout: () => {
        set({ token: null, refreshTokenValue: null, role: null, adminRole: null, user: null })
        void authApi.logout().catch(() => undefined)
      },
      refreshToken: async () => {
        const rt = get().refreshTokenValue
        if (!rt) throw new Error('No refresh token')
        const session = await authApi.refresh()
        set({
          token: session.token,
          refreshTokenValue: session.refreshToken,
          role: readRoleFromToken(session.token) ?? session.role,
          adminRole: readAdminRoleFromToken(session.token),
          user: session.user,
        })
      },
    }),
    {
      name: 'iims-auth',
      partialize: (s) => ({ token: s.token, refreshTokenValue: s.refreshTokenValue, role: s.role, adminRole: s.adminRole, user: s.user }),
    },
  ),
)

