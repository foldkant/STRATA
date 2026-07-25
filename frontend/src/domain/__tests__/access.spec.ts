import { describe, expect, it } from 'vitest'
import { homePathForRole, resolveRouteAccess } from '../access'

describe('login and route permissions', () => {
  it.each([
    ['super_admin', '/super-admin'],
    ['school_admin', '/school-admin'],
    ['teacher', '/teacher'],
    ['student', '/student']
  ] as const)('maps %s to its own home', (role, path) => {
    expect(homePathForRole(role)).toBe(path)
  })

  it('sends anonymous users to login for protected routes', () => {
    expect(resolveRouteAccess({ role: 'teacher' }, null)).toBe('/login')
  })

  it('prevents a student from opening teacher routes', () => {
    expect(resolveRouteAccess({ role: 'teacher' }, 'student')).toBe('/student')
  })

  it('allows shared learning pages only to accepted roles', () => {
    expect(resolveRouteAccess({ roles: ['teacher', 'student'] }, 'teacher')).toBe(true)
    expect(resolveRouteAccess({ roles: ['teacher', 'student'] }, 'school_admin')).toBe('/school-admin')
  })

  it('keeps general public pages available and redirects authenticated users away from login', () => {
    expect(resolveRouteAccess({ public: true }, 'teacher')).toBe(true)
    expect(resolveRouteAccess({ public: true, guestOnly: true }, 'teacher')).toBe('/teacher')
  })
})
