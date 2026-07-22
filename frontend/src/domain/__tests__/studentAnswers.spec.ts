import { describe, expect, it } from 'vitest'
import { buildStudentStepAnswer } from '../studentAnswers'

describe('student answer payloads', () => {
  it('trims a plain text answer', () => {
    expect(buildStudentStepAnswer(false, null, '  我的反思  ')).toBe('我的反思')
  })

  it('keeps question answers and normalized supporting text', () => {
    const questions = { q1: ['B'], q2: { text: '过程' } }
    expect(buildStudentStepAnswer(true, questions, '  补充说明  ')).toEqual({
      questions,
      text: '补充说明'
    })
  })

  it('returns an empty structured payload without sharing the source object', () => {
    const source = {}
    const result = buildStudentStepAnswer(true, source, '')
    expect(result).toEqual({ questions: {}, text: '' })
    expect((result as { questions: object }).questions).not.toBe(source)
  })
})
