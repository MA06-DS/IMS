import { apiClient } from '@/api'
import type { AdminAccount } from '@/types/entities'
import type { ListQueryParams, PaginatedResponse } from '@/types/pagination'

export interface AdminsQueryParams extends ListQueryParams {
  isActive?: boolean
  role?: AdminAccount['role']
}

export interface CreateAdminDTO {
  firstName: string
  lastName: string
  email: string
  phone?: string
  password: string
  role: AdminAccount['role']
}

export interface CreateAdminResponse extends AdminAccount {
  warning?: string
}

export const getAdmins = (params: AdminsQueryParams): Promise<PaginatedResponse<AdminAccount>> =>
  apiClient.get('/admins', { params }).then((r) => r.data)

export const getAdminById = (id: string): Promise<AdminAccount> =>
  apiClient.get(`/admins/${id}`).then((r) => r.data)

export const updateAdmin = (id: string, body: Partial<AdminAccount>): Promise<AdminAccount> =>
  apiClient.put(`/admins/${id}`, body).then((r) => r.data)

export const createAdmin = (body: CreateAdminDTO): Promise<CreateAdminResponse> =>
  apiClient.post('/admins', body).then((r) => r.data)

