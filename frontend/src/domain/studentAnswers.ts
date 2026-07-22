export type StudentQuestionAnswers = Record<string, unknown>

export function buildStudentStepAnswer(
  hasStructuredQuestions: boolean,
  questions: StudentQuestionAnswers | null | undefined,
  text: string
): string | { questions: StudentQuestionAnswers; text: string } {
  const normalizedText = String(text || '').trim()
  if (!hasStructuredQuestions) return normalizedText
  return {
    questions: { ...(questions || {}) },
    text: normalizedText
  }
}
