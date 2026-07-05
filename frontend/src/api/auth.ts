import { apiRequest, toJsonBody } from './client'

export type Role = 'super_admin' | 'school_admin' | 'teacher' | 'student'

export type CurrentUser = {
  id: number
  username: string
  display_name: string
  role: Role
  role_label: string
  school: null | { id: number; name: string; code: string }
  is_active: boolean
  is_first_login: boolean
}

export function getCsrf() {
  return apiRequest<{ csrf_token: string }>('/api/v1/auth/csrf/')
}

export function login(username: string, password: string) {
  return apiRequest<CurrentUser>('/api/v1/auth/login/', {
    method: 'POST',
    body: toJsonBody({ username, password })
  })
}

export function logout() {
  return apiRequest<Record<string, never>>('/api/v1/auth/logout/', { method: 'POST' })
}

export function me() {
  return apiRequest<CurrentUser>('/api/v1/auth/me/')
}
