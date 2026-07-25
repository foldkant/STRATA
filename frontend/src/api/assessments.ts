import { apiRequest, queryString, toJsonBody, uploadRequest } from './client'

export type SubjectOption = { id: number; name: string; code: string }
export type ClassOption = { id: number; name: string; grade: string }
export type CourseOption = { id: number; title: string; subject: number }
export type LearningTargetVersionOption = {
  id: number
  code: string
  title: string
  subject: number
  course: number
  course_title: string
  content_hash: string
}

export type AssessmentOptions = {
  subjects: SubjectOption[]
  classes: ClassOption[]
  courses: CourseOption[]
  question_types: Array<{ value: string; label: string }>
  difficulties: Array<{ value: string; label: string }>
  question_statuses: Array<{ value: BankQuestionStatus; label: string }>
  question_sources: Array<{ value: BankQuestionSource; label: string }>
  item_roles: Array<{ value: string; label: string }>
  layer_scopes: Array<{ value: string; label: string }>
  learning_target_versions: LearningTargetVersionOption[]
  common_question_sets: Array<{
    id: number
    title: string
    subject: number
    grade_scope: string
    term: string
    version_no: number
    question_count: number
    items: Array<{ question_id: number; comparison_code: string; required: boolean }>
  }>
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
  item_role: 'regular' | 'common' | 'layered'
  item_role_label: string
  layer_scope: string
  layer_scope_label: string
  comparison_code: string
  learning_target_version: {
    id: number
    code: string
    title: string
    content_hash: string
    course_id: number
    alignment_status: string
  } | null
  legacy_unmapped: boolean
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
  item_role?: 'regular' | 'layered'
  layer_scope?: string
  learning_target_version_id?: number | string
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

export type AiQuestionGenerationJob = {
  id: number
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
  status_label: string
  subject: SubjectOption
  result: AiQuestionGenerationResult | Record<string, never>
  error_message: string
  error_fields: Record<string, string[]>
  attempt_count: number
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export type AssessmentQuestion = {
  id: number
  source_question?: number | null
  source_version?: number | null
  source_status?: BankQuestionStatus
  item_role?: 'regular' | 'common' | 'layered'
  layer_scope?: string
  comparison_code?: string
  learning_target_version_id?: number | null
  legacy_unmapped?: boolean
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
  common_question_set: { id: number; title: string; version_no: number; content_hash: string } | null
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
  common_question_set: number | string
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

export type CommonQuestionSetRow = {
  id: number
  subject: SubjectOption
  title: string
  grade_scope: string
  term: string
  version_no: number
  measurement_series: string
  version_purpose: 'baseline' | 'follow_up' | 'parallel'
  version_purpose_label: string
  previous_version_id: number | null
  readiness: {
    item_count?: number
    anchor_count?: number
    anchor_ratio?: number
    knowledge_mapped_count?: number
    ve_collection_ready?: boolean
    irt_collection_ready?: boolean
    bkt_collection_ready?: boolean
    requires_real_responses?: boolean
    blockers?: string[]
  }
  content_hash: string
  status: string
  status_label: string
  question_count: number
  items: Array<{
    id: number
    question_id: number
    question_version: number
    question_version_no: number
    stem: string
    comparison_code: string
    required: boolean
    sort_order: number
    anchor_source_id: number | null
    knowledge_components: Array<{
      code: string
      name: string
      weight: number
      is_primary: boolean
    }>
  }>
  published_at: string | null
  created_at: string
  updated_at: string
}

export function getCommonQuestionSets() {
  return apiRequest<CommonQuestionSetRow[]>('/api/v1/school-admin/common-question-sets/')
}

export function createCommonQuestionSet(payload: {
  subject: number | string
  title: string
  grade_scope: string
  term: string
  previous_version?: number | null
  items: Array<{
    question_id: number
    comparison_code: string
    required: boolean
    anchor_source_id?: number | null
  }>
}) {
  return apiRequest<CommonQuestionSetRow>('/api/v1/school-admin/common-question-sets/', {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function archiveCommonQuestionSet(id: number) {
  return apiRequest<Record<string, never>>(`/api/v1/school-admin/common-question-sets/${id}/archive/`, { method: 'POST' })
}

export const commonQuestionSetsExportUrl = '/api/v1/school-admin/common-question-sets/export/'

export function generateQuestionBankDrafts(payload: AiQuestionGenerationPayload) {
  return apiRequest<AiQuestionGenerationJob>('/api/v1/teacher/question-bank/ai-generate/', {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function getLatestQuestionBankDraftJob() {
  return apiRequest<AiQuestionGenerationJob | null>('/api/v1/teacher/question-bank/ai-jobs/latest/')
}

export function getQuestionBankDraftJob(id: number) {
  return apiRequest<AiQuestionGenerationJob>(`/api/v1/teacher/question-bank/ai-jobs/${id}/`)
}

export function retryQuestionBankDraftJob(id: number) {
  return apiRequest<AiQuestionGenerationJob>(`/api/v1/teacher/question-bank/ai-jobs/${id}/retry/`, {
    method: 'POST'
  })
}

export function cancelQuestionBankDraftJob(id: number) {
  return apiRequest<AiQuestionGenerationJob>(`/api/v1/teacher/question-bank/ai-jobs/${id}/cancel/`, {
    method: 'POST'
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
  question_stats: Array<{
    question: AssessmentQuestion
    sample_size: number
    answered_count: number
    correct_count: number
    correct_rate: number | null
    difficulty: number | null
    discrimination: number | null
    option_distribution: Array<{ option: string; count: number }>
    data_status: string
    data_status_label: string
    average_score: number
  }>
  comparisons: Array<{
    id: number
    assessment: number
    status: string
    status_label: string
    common_question_count: number
    exact_version_match_count: number
    left_sample_size: number
    right_sample_size: number
    reasons: string[]
  }>
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
