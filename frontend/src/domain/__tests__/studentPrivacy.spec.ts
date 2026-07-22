import { describe, expect, it } from 'vitest'
import { findStudentPrivacyViolations, isStudentApiUrl, sanitizeStudentPayload } from '../studentPrivacy'

describe('student internal-layer privacy boundary', () => {
  it('finds nested inference fields and ability labels', () => {
    const payload = {
      course: { title: '数学 A层任务', current_layer: 'A' },
      rows: [{ display_name: '学生甲', risk_probability: 0.8 }]
    }
    expect(findStudentPrivacyViolations(payload)).toEqual([
      'course.title',
      'course.current_layer',
      'rows[0].risk_probability'
    ])
  })

  it('removes hidden fields without mutating safe student data', () => {
    const payload = { title: '课堂任务', grouping_strategy: 'balanced_layer', nested: { score: 88, confidence: 0.9 } }
    expect(sanitizeStudentPayload(payload)).toEqual({ title: '课堂任务', nested: { score: 88 } })
    expect(payload.grouping_strategy).toBe('balanced_layer')
  })

  it('applies only to the student API namespace', () => {
    expect(isStudentApiUrl('/api/v1/student/classroom/3/')).toBe(true)
    expect(isStudentApiUrl('/api/v1/teacher/students/')).toBe(false)
  })
})
