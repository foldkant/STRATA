import type { Role } from '@/api/auth'

export type RouteAccessMeta = {
  public?: boolean
  guestOnly?: boolean
  role?: unknown
  roles?: unknown
}

export function homePathForRole(role: Role | null | undefined): string {
  if (role === 'super_admin') return '/super-admin'
  if (role === 'school_admin') return '/school-admin'
  if (role === 'teacher') return '/teacher'
  if (role === 'student') return '/student'
  return '/login'
}

export function resolveRouteAccess(meta: RouteAccessMeta, role: Role | null): true | string {
  const homePath = homePathForRole(role)
  if (meta.public) return meta.guestOnly && role ? homePath : true
  if (!role) return '/login'
  if (typeof meta.role === 'string' && meta.role !== role) return homePath

  const acceptedRoles = Array.isArray(meta.roles)
    ? meta.roles.filter((item): item is string => typeof item === 'string')
    : []
  if (acceptedRoles.length && !acceptedRoles.includes(role)) return homePath
  return true
}
