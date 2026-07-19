import { apiRequest, queryString, toJsonBody, uploadRequest } from './client'

export type SubjectOption = { id: number; name: string; code: string }
export type ClassOption = { id: number; name: string; grade: string }
export type CourseOption = { id: number; title: string; subject: number }

export type AssessmentOptions = {
  subjects: SubjectOption[]
  classes: ClassOption[]
  courses: CourseOption[]
  question_types: Array<{ value: string; label: string }>
  difficulties: Array<{ value: string; label: string }>
  question_statuses: Array<{ value: BankQuestionStatus; label: string }>
  question_sources: Array<{ value: BankQuestionSource; label: string }>
}

export type BankQuestionStatus = 'draft' | 'pending_review' | 'trial' | 'active' | 'disabled'
export type BankQuestionSource = 'manual' | 'xlsx' | 'ai' | 'copy' | 'existing'
export type BankQuestionLibraryScope = 'personal' | 'school'

export type BankQuestion = {
  id: number
  subject: SubjectOption
  creator: { id: number; username: string; display_name: string }
  stem: string
  question_type: string
  question_type_label: string
  options: string[]
  answer: string[]
  analysis: string
  difficulty: string
  difficulty_label: string
  knowledge_point: string
  default_score: number
  status: BankQuestionStatus
  status_label: string
  source: BankQuestionSource
  source_label: string
  library_scope: BankQuestionLibraryScope
  library_scope_label: string
  version_no: number
  content_hash: string
  usage_count: number
  response_count: number
  correct_count: number
  correct_rate: number | null
  trial_usage_count: number
  trial_response_count: number
  trial_correct_count: number
  trial_correct_rate: number | null
  submitted_for_review_at: string | null
  reviewed_by: { id: number; username: string; display_name: string } | null
  reviewed_at: string | null
  review_note: string
  disabled_by: { id: number; username: string; display_name: string } | null
  disabled_at: string | null
  disabled_reason: string
  is_owner: boolean
  created_at: string
  updated_at: string
  option_distribution?: Array<{ option: string; count: number }>
  versions?: Array<{
    id: number
    version_no: number
    content_hash: string
    source: BankQuestionSource
    source_label: string
    status_snapshot: BankQuestionStatus
    status_snapshot_label: string
    created_by: { id: number; username: string; display_name: string }
    created_at: string
  }>
  lifecycle?: Array<{
    id: number
    from_status: string
    to_status: BankQuestionStatus
    to_status_label: string
    action: string
    note: string
    actor: { id: number; username: string; display_name: string }
    created_at: string
  }>
}

export type BankQuestionPayload = {
  subject: number | string
  stem: string
  question_type: string
  options: string[]
  answer: string[]
  analysis: string
  difficulty: string
  knowledge_point: string
  default_score: number
}

export type AiQuestionDraft = BankQuestionPayload & {
  draft_id: string
  selected: boolean
}

export type AiQuestionGenerationPayload = {
  subject: number | string
  direction: string
  knowledge_point: string
  question_type: string
  difficulty: string
  count: number
  requirement: string
}

export type AiQuestionGenerationResult = {
  subject: SubjectOption
  questions: AiQuestionDraft[]
  requested_count: number
  valid_count: number
}

export type AssessmentQuestion = {
  id: number
  source_question?: number | null
  source_version?: number | null
  source_status?: BankQuestionStatus
  question_type: string
  question_type_label: string
  stem: string
  options: string[]
  answer?: string[]
  analysis?: string
  knowledge_point: string
  score: number
  sort_order: number
}

export type TestAttempt = {
  id: number
  student: { id: number; username: string; display_name: string }
  class_group: ClassOption
  status: 'in_progress' | 'submitted' | 'graded'
  status_label: string
  objective_score: number | null
  subjective_score: number | null
  total_score: number | null
  started_at: string
  submitted_at: string | null
  graded_at: string | null
  answers?: Array<{
    id: number
    question: AssessmentQuestion
    answer: string[]
    auto_score: number
    manual_score: number | null
    final_score: number
    is_correct: boolean | null
    feedback: string
  }>
}

export type TestAssessment = {
  id: number
  title: string
  instruction: string
  subject: SubjectOption
  course: { id: number; title: string } | null
  teacher: { id: number; username: string; display_name: string }
  target_classes: ClassOption[]
  duration_minutes: number
  status: 'draft' | 'published' | 'open' | 'closed'
  status_label: string
  start_at: string | null
  end_at: string | null
  opened_at: string | null
  closed_at: string | null
  show_score_after_submit: boolean
  randomize_question_order: boolean
  randomize_option_order: boolean
  question_count: number
  attempt_count: number
  submitted_count: number
  total_score: number
  questions?: AssessmentQuestion[]
  available?: boolean
  attempt?: TestAttempt | null
  created_at: string
  updated_at: string
}

export type TestPayload = {
  title: string
  subject: number | string
  course: number | string
  class_ids: number[]
  instruction: string
  duration_minutes: number
  start_at: string
  end_at: string
  show_score_after_submit: boolean
  randomize_question_order: boolean
  randomize_option_order: boolean
}

export function getAssessmentOptions() {
  return apiRequest<AssessmentOptions>('/api/v1/teacher/assessment-options/')
}

export function getQuestionBank(params: Record<string, string | number> = {}) {
  return apiRequest<BankQuestion[]>(`/api/v1/teacher/question-bank/${queryString(params)}`)
}

export function createBankQuestion(payload: BankQuestionPayload) {
  return apiRequest<BankQuestion>('/api/v1/teacher/question-bank/', { method: 'POST', body: toJsonBody(payload) })
}

export function updateBankQuestion(id: number, payload: Partial<BankQuestionPayload>) {
  return apiRequest<BankQuestion>(`/api/v1/teacher/question-bank/${id}/`, { method: 'PATCH', body: toJsonBody(payload) })
}

export function actionBankQuestion(
  id: number,
  action: 'submit_review' | 'withdraw' | 'disable' | 'copy',
  note = ''
) {
  return apiRequest<BankQuestion>(`/api/v1/teacher/question-bank/${id}/action/`, {
    method: 'POST',
    body: toJsonBody({ action, note })
  })
}

export function deleteBankQuestion(id: number) {
  return apiRequest<Record<string, never>>(`/api/v1/teacher/question-bank/${id}/`, { method: 'DELETE' })
}

export function importQuestionBank(file: File) {
  const form = new FormData()
  form.append('file', file)
  return uploadRequest<{ created: number; failed: number; errors: Array<{ row: number; message: string }> }>('/api/v1/teacher/question-bank/import/', form)
}

export const questionBankTemplateUrl = '/api/v1/teacher/question-bank/template/'
export const questionBankExportUrl = '/api/v1/teacher/question-bank/export/'

export type QuestionReviewPage = {
  count: number
  page: number
  page_size: number
  results: BankQuestion[]
}

export function getQuestionReviews(params: Record<string, string | number> = {}) {
  return apiRequest<QuestionReviewPage>(`/api/v1/school-admin/question-reviews/${queryString(params)}`)
}

export function getQuestionReviewDetail(id: number) {
  return apiRequest<BankQuestion>(`/api/v1/school-admin/question-reviews/${id}/`)
}

export function reviewQuestion(
  id: number,
  action: 'approve_trial' | 'return' | 'activate' | 'disable',
  note = ''
) {
  return apiRequest<BankQuestion>(`/api/v1/school-admin/question-reviews/${id}/action/`, {
    method: 'POST',
    body: toJsonBody({ action, note })
  })
}

export const questionReviewsExportUrl = '/api/v1/school-admin/question-reviews/export/'

export function generateQuestionBankDrafts(payload: AiQuestionGenerationPayload) {
  return apiRequest<AiQuestionGenerationResult>('/api/v1/teacher/question-bank/ai-generate/', {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function confirmQuestionBankDrafts(subject: number | string, questions: AiQuestionDraft[]) {
  return apiRequest<{ created_count: number; questions: BankQuestion[] }>('/api/v1/teacher/question-bank/ai-confirm/', {
    method: 'POST',
    body: toJsonBody({ subject, questions })
  })
}

export function getTeacherAssessments(status = '') {
  return apiRequest<TestAssessment[]>(`/api/v1/teacher/assessments/${queryString({ status })}`)
}

export function createAssessment(payload: TestPayload) {
  return apiRequest<TestAssessment>('/api/v1/teacher/assessments/', { method: 'POST', body: toJsonBody(payload) })
}

export function getTeacherAssessment(id: number) {
  return apiRequest<TestAssessment>(`/api/v1/teacher/assessments/${id}/`)
}

export function updateAssessment(id: number, payload: TestPayload) {
  return apiRequest<TestAssessment>(`/api/v1/teacher/assessments/${id}/`, { method: 'PATCH', body: toJsonBody(payload) })
}

export function deleteAssessment(id: number) {
  return apiRequest<Record<string, never>>(`/api/v1/teacher/assessments/${id}/`, { method: 'DELETE' })
}

export function saveAssessmentQuestions(
  id: number,
  questions: Array<{ question_id: number; score: number }>,
  settings: { randomize_question_order: boolean; randomize_option_order: boolean }
) {
  return apiRequest<TestAssessment>(`/api/v1/teacher/assessments/${id}/questions/`, {
    method: 'PUT',
    body: toJsonBody({ questions, ...settings })
  })
}

export function publishAssessment(id: number) {
  return apiRequest<TestAssessment>(`/api/v1/teacher/assessments/${id}/publish/`, { method: 'POST' })
}

export function openAssessment(id: number) {
  return apiRequest<TestAssessment>(`/api/v1/teacher/assessments/${id}/open/`, { method: 'POST' })
}

export function closeAssessment(id: number) {
  return apiRequest<TestAssessment>(`/api/v1/teacher/assessments/${id}/close/`, { method: 'POST' })
}

export type AssessmentResults = {
  assessment: TestAssessment
  summary: { assigned_count: number; started_count: number; submitted_count: number; pending_grade_count: number; average_score: number }
  attempts: TestAttempt[]
  question_stats: Array<{ question: AssessmentQuestion; answered_count: number; correct_count: number; correct_rate: number; average_score: number }>
}

export function getAssessmentResults(id: number) {
  return apiRequest<AssessmentResults>(`/api/v1/teacher/assessments/${id}/results/`)
}

export function assessmentResultsExportUrl(id: number) {
  return `/api/v1/teacher/assessments/${id}/results/export/`
}

export function getAttemptForGrade(id: number) {
  return apiRequest<TestAttempt>(`/api/v1/teacher/test-attempts/${id}/grade/`)
}

export function saveAttemptGrade(id: number, answers: Array<{ answer_id: number; score: number; feedback: string }>) {
  return apiRequest<TestAttempt>(`/api/v1/teacher/test-attempts/${id}/grade/`, { method: 'PATCH', body: toJsonBody({ answers }) })
}

export function getStudentAssessments() {
  return apiRequest<TestAssessment[]>('/api/v1/student/assessments/')
}

export type StudentAssessmentWorkspace = {
  assessment: TestAssessment
  attempt: TestAttempt | null
  questions: AssessmentQuestion[]
  answers?: Record<string, string[]>
  deadline?: string
  server_time?: string
  result?: { score: number; total_score: number; status: string } | null
}

export function getStudentAssessment(id: number) {
  return apiRequest<StudentAssessmentWorkspace>(`/api/v1/student/assessments/${id}/`)
}

export function startStudentAssessment(id: number) {
  return apiRequest<{ attempt: TestAttempt; deadline: string }>(`/api/v1/student/assessments/${id}/start/`, { method: 'POST' })
}

export function saveStudentAssessmentAnswer(id: number, questionId: number, answer: string[]) {
  return apiRequest<{ question_id: number; answer: string[]; saved_at: string }>(`/api/v1/student/assessments/${id}/answer/`, {
    method: 'PATCH',
    body: toJsonBody({ question_id: questionId, answer })
  })
}

export function submitStudentAssessment(id: number) {
  return apiRequest<TestAttempt>(`/api/v1/student/assessments/${id}/submit/`, { method: 'POST' })
}
