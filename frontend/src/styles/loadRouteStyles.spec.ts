import { describe, expect, it } from 'vitest'
import { styleGroupsForPath } from './loadRouteStyles'

describe('styleGroupsForPath', () => {
  it('loads the public page styles for the home, login and error screens', () => {
    expect(styleGroupsForPath('/')).toEqual(['public'])
    expect(styleGroupsForPath('/login')).toEqual(['public'])
    expect(styleGroupsForPath('/404')).toEqual(['public'])
    expect(styleGroupsForPath('/500')).toEqual(['public'])
  })

  it('loads only the domains needed by each role workspace', () => {
    expect(styleGroupsForPath('/super-admin/curriculum-standards')).toEqual([
      'governance',
      'super-admin'
    ])
    expect(styleGroupsForPath('/school-admin/question-reviews')).toEqual([
      'governance',
      'resources',
      'assessments',
      'super-admin',
      'school-admin'
    ])
    expect(styleGroupsForPath('/teacher/classroom/3')).toEqual([
      'resources',
      'learning',
      'assessments',
      'teacher'
    ])
    expect(styleGroupsForPath('/student/courses')).toEqual([
      'resources',
      'learning',
      'assessments',
      'student'
    ])
  })
})
