import { apiRequest, queryString, toJsonBody, uploadRequest } from './client'
import type { CountSlice, Metric, SeriesPoint } from './dashboards'
import type { AccountRow, ClassGroupRow, PageQuery, PageResult, StudentRow, SubjectRow } from './management'
import type { EvaluationNotAssessedEntry } from '@/domain/evaluation'

export type TeacherDashboard = {
  school: { id: number; name: string; code: string }
  metrics: Metric[]
  charts: {
    event_series: SeriesPoint[]
    login_series: SeriesPoint[]
    active_students_7d: SeriesPoint[]
    class_students: SeriesPoint[]
    class_activity: SeriesPoint[]
    student_layers: CountSlice[]
    event_types: CountSlice[]
    decision_status: CountSlice[]
    training_status: CountSlice[]
  }
  class_rows: Array<{
    id: number
    name: string
    grade: string
    student_count: number
    event_count: number
    status_label: string
  }>
  todo_rows: Array<{ label: string; count: number; level: string }>
}

export function getTeacherDashboard() {
  return apiRequest<TeacherDashboard>('/api/v1/teacher/dashboard/')
}

export function getTeacherClasses() {
  return apiRequest<ClassGroupRow[]>('/api/v1/teacher/classes/')
}

export function getTeacherStudents(params: PageQuery = {}) {
  return apiRequest<PageResult<StudentRow>>(`/api/v1/teacher/students/${queryString(params)}`)
}

export function resetTeacherStudentPassword(id: number) {
  return apiRequest<StudentRow>(`/api/v1/teacher/students/${id}/reset-password/`, {
    method: 'POST'
  })
}

export function bulkResetTeacherStudentPasswords(ids: number[]) {
  return apiRequest<{ updated_count: number; results: StudentRow[] }>('/api/v1/teacher/students/bulk-reset-password/', {
    method: 'POST',
    body: JSON.stringify({ ids })
  })
}

export type LessonRow = {
  id: number
  course: number
  course_title: string
  title: string
  content: string
  sort_order: number
  is_active: boolean
  status: 'draft' | 'published'
  status_label: string
  activity_count: number
  session_count: number
  created_at: string
  updated_at: string
}

export type CourseRow = {
  id: number
  subject: SubjectRow | null
  title: string
  introduction: string
  cover_url: string
  cover_name: string
  teaching_model: 'pbl' | 'tbl'
  teaching_model_label: string
  is_active: boolean
  status: 'draft' | 'published'
  status_label: string
  target_classes: ClassGroupRow[]
  class_count: number
  lesson_count: number
  session_count: number
  created_at: string
  updated_at: string
  lessons?: LessonRow[]
}

export type CoursePayload = {
  subject: number | string
  title: string
  introduction: string
  teaching_model: string
  status: string
  class_groups?: Array<number | string>
}

export type LessonPayload = {
  title: string
  content: string
  sort_order: number | string
  status: string
}

export type LessonStepType =
  | 'intro'
  | 'resource'
  | 'question'
  | 'task'
  | 'upload'
  | 'discussion'
  | 'evaluation'
  | 'reflection'
  | 'ai_worksheet'
  | 'document'

export type LessonStepStatus = 'draft' | 'ready'

export type ResourceBinding = {
  id: number | string
  title: string
  attachment_url: string
  attachment_name: string
  file_ext: string
  kind: string
  learning_page_id?: number
  revision_no?: number
}

export type LessonStepQuestionType = 'single' | 'multiple' | 'judge' | 'blank' | 'text' | 'file'

export type LessonFileConfig = {
  allowed_extensions: string[]
  max_size_mb: number
}

export type LessonStepQuestion = {
  id: string
  question_type: LessonStepQuestionType
  question_type_label?: string
  stem: string
  options: string[]
  answer: string[]
  score: number | string
  target_layer: string
  target_layer_label?: string
  use_layer_scores: boolean
  layer_scores: Record<'A' | 'B' | 'C', number | string>
  file_config?: LessonFileConfig
  analysis: string
  is_required: boolean
  sort_order: number | string
}

export type LessonStepRow = {
  id: number
  lesson: number
  title: string
  step_type: LessonStepType
  step_type_label: string
  student_instruction: string
  teacher_note: string
  sort_order: number
  is_required: boolean
  estimated_minutes: number
  target_layer: 'all' | 'A' | 'B' | 'C' | 'A/B' | 'B/C' | 'A/B/C'
  target_layer_label: string
  status: LessonStepStatus
  status_label: string
  resource_items: ResourceBinding[]
  activity_items: string[]
  question_items: LessonStepQuestion[]
  ai_prompt: string
  collect_student_log: boolean
  collect_class_log: boolean
  created_at: string
  updated_at: string
}

export type LessonStepPayload = {
  title: string
  step_type: LessonStepType
  student_instruction: string
  teacher_note: string
  sort_order: number | string
  is_required: boolean
  estimated_minutes: number | string
  target_layer: string
  status: string
  resource_items: Array<ResourceBinding | string>
  activity_items: string[]
  question_items: LessonStepQuestion[]
  ai_prompt: string
  collect_student_log: boolean
  collect_class_log: boolean
}

export type AiQuestionGenerationPayload = {
  direction: string
  question_type: LessonStepQuestionType
  count: number | string
  lesson_title?: string
  step_title?: string
  subject_name?: string
  student_instruction?: string
  requirement?: string
}

export type AiQuestionGenerationResult = {
  questions: LessonStepQuestion[]
  groups: Array<{
    target_layer: string
    target_layer_label: string
    questions: LessonStepQuestion[]
    score_defaults: {
      base_score: number
      layer_scores: Record<'A' | 'B' | 'C', number>
    }
  }>
  score_defaults: {
    base_score: number
    groups: Record<string, {
      base_score: number
      layer_scores: Record<'A' | 'B' | 'C', number>
    }>
    note: string
  }
}

export type ActivityTypeRow = {
  value: string
  label: string
}

export type TeacherCourseOptions = {
  subjects: SubjectRow[]
  classes: ClassGroupRow[]
  courses: CourseRow[]
  activity_types: ActivityTypeRow[]
}

export type ResourceRow = {
  id: number
  public_id: string
  title: string
  content: string
  attachment_url: string
  attachment_name: string
  attachment_size: number
  file_ext: string
  cover_url: string
  resource_type: 'file' | 'article' | 'link' | 'student_project'
  resource_type_label: string
  category: string
  category_label: string
  visibility: 'private' | 'classes' | 'school' | 'external'
  visibility_label: string
  publish_status: 'published' | 'pending' | 'approved' | 'rejected' | 'archived'
  publish_status_label: string
  subject: SubjectRow | null
  target_classes: ClassGroupRow[]
  grade_scope: string
  tags: string[]
  external_url: string
  project_type: '' | 'individual' | 'group'
  project_type_label: string
  project_members: string[]
  project_course: string
  competition_name: string
  competition_year: number | null
  award_level: string
  extra_files: Array<{
    id: number
    name: string
    file_url: string
    file_ext: string
    file_size: number
    role: 'supplement' | 'process'
    role_label: string
    sort_order: number
  }>
  owner: { id: number; username: string; display_name: string; role: string }
  school: { id: number; name: string; code: string } | null
  view_count: number
  is_pinned: boolean
  is_owner: boolean
  review_note: string
  reviewed_at: string | null
  published_at: string | null
  created_at: string
  updated_at: string
}

export type ResourcePayload = {
  title: string
  content?: string
  resource_type?: ResourceRow['resource_type']
  category?: string
  visibility?: ResourceRow['visibility']
  subject?: number | string
  class_ids?: number[]
  grade_scope?: string
  tags?: string[]
  external_url?: string
  project_type?: 'individual' | 'group' | ''
  project_members?: string[]
  project_course?: string
  competition_name?: string
  competition_year?: number | string
  award_level?: string
  is_pinned?: boolean
  file?: File | null
  cover?: File | null
  extra_files?: File[]
}

export type TeacherAIProviderRow = {
  id: number
  provider: 'deepseek'
  provider_label: string
  base_url: string
  model: string
  is_enabled: boolean
  has_api_key: boolean
  api_key_hint: string
  last_tested_at: string | null
  last_error: string
  updated_at: string
}

export type TeacherAIProviderPayload = {
  provider: string
  base_url: string
  model: string
  api_key?: string
  is_enabled: boolean
  clear_api_key?: boolean
}

export type ClassroomActivityRow = {
  id: number
  session: number
  activity_type: string
  activity_type_label: string
  title: string
  content: string
  metadata: Record<string, unknown>
  status: 'draft' | 'open' | 'closed'
  status_label: string
  opened_at: string | null
  closed_at: string | null
  created_at: string
  updated_at: string
}

export type AttendanceStatus = 'not_signed' | 'signed' | 'late' | 'leave' | 'absent'

export type ClassroomAttendanceRow = {
  student_id: number
  profile_id: number
  username: string
  display_name: string
  student_no: string
  current_layer: string
  current_layer_label: string
  status: AttendanceStatus
  status_label: string
  source: string
  note: string
  occurred_at: string | null
  activity_id: number
}

export type ClassroomAttendanceSummary = {
  total: number
  signed: number
  late: number
  leave: number
  absent: number
  not_signed: number
}

export type ClassroomAttendancePayload = {
  activity: ClassroomActivityRow
  summary: ClassroomAttendanceSummary
  rows: ClassroomAttendanceRow[]
}

export type QuickAnswerRow = {
  rank: number
  event_id: number
  student_id: number
  username: string
  display_name: string
  student_no: string
  current_layer: string
  current_layer_label: string
  responded_at: string
  score: number | null
  score_action: 'plus' | 'minus' | ''
  score_note: string
  scored_at: string | null
}

export type QuickAnswerSummary = {
  total: number
  scored: number
  plus: number
  minus: number
}

export type QuickAnswerPayload = {
  activity: ClassroomActivityRow
  summary: QuickAnswerSummary
  score_defaults: {
    plus: number
    minus: number
  }
  rows: QuickAnswerRow[]
}

export type RandomPickStudentRow = {
  student_id: number
  profile_id: number
  username: string
  display_name: string
  student_no: string
  current_layer: string
  current_layer_label: string
  is_picked: boolean
  score: number | null
  score_action: 'plus' | 'minus' | ''
  score_note: string
  scored_at: string | null
}

export type RandomPickPayload = {
  activity: ClassroomActivityRow
  summary: {
    total: number
    picked: number
    scored: number
  }
  score_defaults: {
    plus: number
    minus: number
  }
  picked_student: RandomPickStudentRow | null
  students: RandomPickStudentRow[]
}

export type RandomPickPreviewPayload = Omit<RandomPickPayload, 'activity'>

export type ClassroomStepProgressAnswer = {
  question_id: string
  question_type: LessonStepQuestionType
  question_type_label: string
  stem: string
  required: boolean
  answer_values: string[]
  answer_text: string
  is_answered: boolean
  auto_gradable: boolean
  is_correct: boolean | null
  score: number | null
  max_score: number | null
  attachment?: StudentWorkAttachmentRow | null
}

export type StudentWorkAttachmentRow = {
  id: number
  student: number
  lesson_step: number
  classroom_session: number | null
  question_id: string
  question_stem: string
  upload_version: number
  title: string
  attachment_url: string
  attachment_name: string
  file_ext: string
  attachment_size: number
  score: number | null
  feedback: string
  evaluated_by: number | null
  evaluated_at: string | null
  created_at: string
  updated_at: string
}

export type ClassroomGroupMemberRow = {
  id: number
  student_id: number
  profile_id: number | null
  username: string
  display_name: string
  student_no: string
  current_layer: string
  current_layer_label: string
  role: 'leader' | 'member'
  role_label: string
  joined_at: string
}

export type ClassroomGroupFileRow = {
  id: number
  public_id: string
  version_no: number
  group: number
  uploader: {
    id: number
    username: string
    display_name: string
    role: string
  } | null
  title: string
  description: string
  attachment_url: string
  attachment_name: string
  file_ext: string
  file_size: number
  created_at: string
}

export type ClassroomGroupDocumentRow = {
  attachment_url: string
  attachment_name: string
  file_ext: 'docx' | 'pptx' | 'xlsx' | string
  file_size: number
  document_version: number
}

export type ClassroomGroupRow = {
  id: number
  collaboration: number
  group_no: number
  name: string
  layer_hint: string
  leader: number | null
  document: ClassroomGroupDocumentRow
  used_storage_bytes: number
  used_storage_mb: number
  members: ClassroomGroupMemberRow[]
  files: ClassroomGroupFileRow[]
  file_count: number
  created_at: string
  updated_at: string
}

export type ClassroomGroupCollaborationRow = {
  id: number
  session: number
  is_enabled: boolean
  status: 'draft' | 'open' | 'closed'
  status_label: string
  group_size: number
  grouping_strategy: 'balanced_layer' | 'same_layer' | 'random' | 'manual' | 'ai_layer'
  grouping_strategy_label: string
  document_type: 'docx' | 'pptx' | 'xlsx'
  document_type_label: string
  storage_quota_mb: number
  allow_student_upload: boolean
  allow_onlyoffice_edit: boolean
  group_count: number
  my_group_id: number | null
  my_group: ClassroomGroupRow | null
  groups: ClassroomGroupRow[]
  opened_at: string | null
  closed_at: string | null
  created_at: string
  updated_at: string
}

export type ClassroomGroupCollaborationPayload = {
  group_size: number | string
  grouping_strategy: string
  document_type: string
  storage_quota_mb: number | string
  allow_student_upload: boolean
  allow_onlyoffice_edit: boolean
  regenerate?: boolean
}

export type ClassroomEvaluationType = 'self' | 'peer' | 'teacher'

export type ClassroomEvaluationCriterion = {
  id: string
  title: string
  description: string
  sort_order: number
  level_descriptions?: string[]
  skip_condition?: string
}

export type ClassroomEvaluationConfig = {
  id: number | null
  course: number | null
  session: number | null
  enable_self: boolean
  enable_peer: boolean
  enable_teacher: boolean
  self_criteria: ClassroomEvaluationCriterion[]
  peer_criteria: ClassroomEvaluationCriterion[]
  teacher_criteria: ClassroomEvaluationCriterion[]
  opened_at: string | null
  created_at: string | null
  updated_at: string | null
}

export type ClassroomEvaluationSubmission = {
  id: number
  course: number
  class_group: number | null
  session: number | null
  evaluation_type: ClassroomEvaluationType
  evaluation_type_label: string
  evaluator: AccountRow
  target: AccountRow
  group: number | null
  ratings: Record<string, number>
  not_assessed: Record<string, EvaluationNotAssessedEntry>
  comment: string
  created_at: string
  updated_at: string
}

export type ClassroomEvaluationSummaryItem = {
  label: string
  enabled: boolean
  submitted: number
  total: number
  average: number | null
  rated_item_count: number
  not_assessed_item_count: number
  unanswered_item_count: number
  total_item_count: number
  criteria: Array<{
    id: string
    title: string
    average: number | null
    count: number
    not_assessed_count: number
  }>
}

export type ClassroomEvaluationStudentRow = {
  student: AccountRow
  profile: {
    id: number
    student_no: string
    current_layer: string | null
    current_layer_label: string
    score: number
  } | null
  self_submission: ClassroomEvaluationSubmission | null
  teacher_submission: ClassroomEvaluationSubmission | null
  peer_submission_count: number
  peer_average: number | null
}

export type ClassroomEvaluationPayload = {
  course?: CourseRow
  class_options?: ClassGroupRow[]
  selected_class_group?: ClassGroupRow | null
  runtime_enabled?: boolean
  runtime_opened_at?: string | null
  config: ClassroomEvaluationConfig
  summary: Record<ClassroomEvaluationType, ClassroomEvaluationSummaryItem>
  students: ClassroomEvaluationStudentRow[]
  recent_submissions: ClassroomEvaluationSubmission[]
  peer_available: boolean
}

export type ClassroomEvaluationConfigPayload = Pick<
  ClassroomEvaluationConfig,
  'enable_self' | 'enable_peer' | 'enable_teacher' | 'self_criteria' | 'peer_criteria' | 'teacher_criteria'
>

export type ClassroomEvaluationAiPayload = {
  types: ClassroomEvaluationType[]
  direction?: string
}

export type ClassroomEvaluationAiResult = Partial<Record<ClassroomEvaluationType, ClassroomEvaluationCriterion[]>>

export type ClassroomTeacherEvaluationSubmitPayload = {
  target: number
  ratings: Record<string, number>
  not_assessed?: Record<string, EvaluationNotAssessedEntry>
  comment?: string
}

export type ClassroomStepProgressRow = {
  student_id: number
  profile_id: number
  username: string
  display_name: string
  student_no: string
  current_layer: string
  current_layer_label: string
  submitted: boolean
  submitted_at: string | null
  event_id: number | null
  attempt_id: string | null
  attempt_no: number | null
  text: string
  answered_count: number
  question_count: number
  required_count: number
  auto_score: number | null
  auto_score_max: number
  auto_gradable_count: number
  correct_count: number
  answers: ClassroomStepProgressAnswer[]
}

export type ClassroomStepProgressPayload = {
  step: {
    id: number
    title: string
    step_type: LessonStepType
    step_type_label: string
    is_layered: boolean
  } | null
  summary: {
    total: number
    submitted: number
    not_submitted: number
    question_count: number
    required_count: number
    auto_score_avg: number | null
    auto_score_max: number
  }
  rows: ClassroomStepProgressRow[]
}

export type ClassroomCommandPayload = {
  command: 'sign_in' | 'random_pick' | 'quick_answer' | 'timer' | 'broadcast'
  title?: string
  content?: string
  duration_seconds?: number
  picked_user_id?: number | string
}

export type ClassroomSessionRow = {
  id: number
  title: string
  status: 'draft' | 'running' | 'finished'
  status_label: string
  current_step: LessonStepRow | null
  current_step_status: 'idle' | 'open' | 'locked' | 'closed'
  current_step_status_label: string
  submission_locked: boolean
  is_layered: boolean
  evaluation_enabled: boolean
  evaluation_opened_at: string | null
  current_step_started_at: string | null
  current_step_closed_at: string | null
  school: { id: number; name: string; code: string } | null
  course: CourseRow | null
  lesson: LessonRow | null
  class_group: ClassGroupRow | null
  activity_count: number
  open_activity_count: number
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
  activities?: ClassroomActivityRow[]
}

export type ClassroomSessionPayload = {
  course: number | string
  lesson: number | string
  class_group: number | string
  title: string
}

export type ClassroomActivityPayload = {
  activity_type: string
  title: string
  content: string
}

export function getTeacherCourseOptions() {
  return apiRequest<TeacherCourseOptions>('/api/v1/teacher/course-options/')
}

export function getTeacherResources(params: PageQuery & { scope?: string; resource_type?: string; category?: string } = {}) {
  return apiRequest<PageResult<ResourceRow>>(`/api/v1/teacher/resources/${queryString(params)}`)
}

function resourceFormData(payload: ResourcePayload) {
  const formData = new FormData()
  formData.append('title', payload.title)
  formData.append('content', payload.content || '')
  formData.append('resource_type', payload.resource_type || 'file')
  formData.append('category', payload.category || 'courseware')
  formData.append('visibility', payload.visibility || 'private')
  formData.append('subject', payload.subject ? String(payload.subject) : '')
  formData.append('class_ids', JSON.stringify(payload.class_ids || []))
  formData.append('grade_scope', payload.grade_scope || '')
  formData.append('tags', JSON.stringify(payload.tags || []))
  formData.append('external_url', payload.external_url || '')
  formData.append('project_type', payload.project_type || '')
  formData.append('project_members', JSON.stringify(payload.project_members || []))
  formData.append('project_course', payload.project_course || '')
  formData.append('competition_name', payload.competition_name || '')
  formData.append('competition_year', payload.competition_year ? String(payload.competition_year) : '')
  formData.append('award_level', payload.award_level || '')
  formData.append('is_pinned', payload.is_pinned ? 'true' : 'false')
  if (payload.file) formData.append('attachment', payload.file)
  if (payload.cover) formData.append('cover', payload.cover)
  for (const file of payload.extra_files || []) {
    formData.append('extra_files', file)
  }
  return formData
}

export function uploadTeacherResource(payload: ResourcePayload) {
  const formData = resourceFormData(payload)
  return uploadRequest<ResourceRow>('/api/v1/teacher/resources/', formData)
}

export function updateTeacherResource(id: number, payload: ResourcePayload) {
  return uploadRequest<ResourceRow>(`/api/v1/teacher/resources/${id}/`, resourceFormData(payload), 'PATCH')
}

export function deleteTeacherResource(id: number) {
  return apiRequest<Record<string, never>>(`/api/v1/teacher/resources/${id}/`, { method: 'DELETE' })
}

export function deleteTeacherResourceFile(resourceId: number, fileId: number) {
  return apiRequest<Record<string, never>>(`/api/v1/teacher/resources/${resourceId}/files/${fileId}/`, { method: 'DELETE' })
}

export function getTeacherCourses(params: PageQuery = {}) {
  return apiRequest<PageResult<CourseRow>>(`/api/v1/teacher/courses/${queryString(params)}`)
}

export function getTeacherCourse(id: number) {
  return apiRequest<CourseRow>(`/api/v1/teacher/courses/${id}/`)
}

export function getTeacherAIProvider() {
  return apiRequest<TeacherAIProviderRow>('/api/v1/teacher/ai-provider/')
}

export function saveTeacherAIProvider(payload: TeacherAIProviderPayload) {
  return apiRequest<TeacherAIProviderRow>('/api/v1/teacher/ai-provider/', {
    method: 'PATCH',
    body: toJsonBody(payload)
  })
}

export function testTeacherAIProvider() {
  return apiRequest<TeacherAIProviderRow>('/api/v1/teacher/ai-provider/test/', {
    method: 'POST'
  })
}

export function createTeacherCourse(payload: CoursePayload) {
  return apiRequest<CourseRow>('/api/v1/teacher/courses/', {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function updateTeacherCourse(id: number, payload: CoursePayload) {
  return apiRequest<CourseRow>(`/api/v1/teacher/courses/${id}/`, {
    method: 'PATCH',
    body: toJsonBody(payload)
  })
}

export function uploadTeacherCourseCover(id: number, file: File) {
  const formData = new FormData()
  formData.append('cover', file)
  return uploadRequest<CourseRow>(`/api/v1/teacher/courses/${id}/cover/`, formData)
}

export function deleteTeacherCourseCover(id: number) {
  return apiRequest<CourseRow>(`/api/v1/teacher/courses/${id}/cover/`, { method: 'DELETE' })
}

export function deleteTeacherCourse(id: number) {
  return apiRequest<Record<string, never>>(`/api/v1/teacher/courses/${id}/`, { method: 'DELETE' })
}

export function publishTeacherCourse(id: number) {
  return apiRequest<CourseRow>(`/api/v1/teacher/courses/${id}/publish/`, { method: 'POST' })
}

export function archiveTeacherCourse(id: number) {
  return apiRequest<CourseRow>(`/api/v1/teacher/courses/${id}/archive/`, { method: 'POST' })
}

export function saveTeacherCourseClasses(id: number, classGroups: Array<number | string>) {
  return apiRequest<CourseRow>(`/api/v1/teacher/courses/${id}/classes/`, {
    method: 'POST',
    body: toJsonBody({ class_groups: classGroups })
  })
}

export function getCourseEvaluation(courseId: number, classGroup?: number | string) {
  return apiRequest<ClassroomEvaluationPayload>(
    `/api/v1/teacher/courses/${courseId}/evaluation/${queryString({ class_group: classGroup || '' })}`
  )
}

export function saveCourseEvaluation(courseId: number, payload: ClassroomEvaluationConfigPayload & { class_group?: number | string }) {
  return apiRequest<ClassroomEvaluationPayload>(`/api/v1/teacher/courses/${courseId}/evaluation/`, {
    method: 'PATCH',
    body: toJsonBody(payload)
  })
}

export function generateCourseEvaluationCriteria(courseId: number, payload: ClassroomEvaluationAiPayload) {
  return apiRequest<ClassroomEvaluationAiResult>(`/api/v1/teacher/courses/${courseId}/evaluation/ai-generate/`, {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function submitCourseTeacherEvaluation(courseId: number, payload: ClassroomTeacherEvaluationSubmitPayload & { class_group?: number | string }) {
  return apiRequest<ClassroomEvaluationPayload>(`/api/v1/teacher/courses/${courseId}/evaluation/teacher-submit/`, {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function getTeacherLessons(courseId: number) {
  return apiRequest<LessonRow[]>(`/api/v1/teacher/courses/${courseId}/lessons/`)
}

export function createTeacherLesson(courseId: number, payload: LessonPayload) {
  return apiRequest<LessonRow>(`/api/v1/teacher/courses/${courseId}/lessons/`, {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function updateTeacherLesson(id: number, payload: LessonPayload) {
  return apiRequest<LessonRow>(`/api/v1/teacher/lessons/${id}/`, {
    method: 'PATCH',
    body: toJsonBody(payload)
  })
}

export function getTeacherLesson(id: number) {
  return apiRequest<LessonRow>(`/api/v1/teacher/lessons/${id}/`)
}

export function deleteTeacherLesson(id: number) {
  return apiRequest<Record<string, never>>(`/api/v1/teacher/lessons/${id}/`, { method: 'DELETE' })
}

export function publishTeacherLesson(id: number) {
  return apiRequest<LessonRow>(`/api/v1/teacher/lessons/${id}/publish/`, { method: 'POST' })
}

export function archiveTeacherLesson(id: number) {
  return apiRequest<LessonRow>(`/api/v1/teacher/lessons/${id}/archive/`, { method: 'POST' })
}

export function getTeacherLessonSteps(lessonId: number) {
  return apiRequest<LessonStepRow[]>(`/api/v1/teacher/lessons/${lessonId}/steps/`)
}

export function createTeacherLessonStep(lessonId: number, payload: LessonStepPayload) {
  return apiRequest<LessonStepRow>(`/api/v1/teacher/lessons/${lessonId}/steps/`, {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function updateTeacherLessonStep(id: number, payload: LessonStepPayload) {
  return apiRequest<LessonStepRow>(`/api/v1/teacher/lesson-steps/${id}/`, {
    method: 'PATCH',
    body: toJsonBody(payload)
  })
}

export function deleteTeacherLessonStep(id: number) {
  return apiRequest<Record<string, never>>(`/api/v1/teacher/lesson-steps/${id}/`, { method: 'DELETE' })
}

export function reorderTeacherLessonSteps(lessonId: number, ids: number[]) {
  return apiRequest<LessonStepRow[]>(`/api/v1/teacher/lessons/${lessonId}/steps/reorder/`, {
    method: 'POST',
    body: toJsonBody({ ids })
  })
}

export function generateTeacherLessonStepQuestions(payload: AiQuestionGenerationPayload) {
  return apiRequest<AiQuestionGenerationResult>('/api/v1/teacher/lesson-steps/ai-generate-questions/', {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function getClassroomSessions(params: PageQuery = {}) {
  return apiRequest<PageResult<ClassroomSessionRow>>(`/api/v1/teacher/classroom/sessions/${queryString(params)}`)
}

export function getClassroomSession(id: number) {
  return apiRequest<ClassroomSessionRow>(`/api/v1/teacher/classroom/sessions/${id}/`)
}

export function createClassroomSession(payload: ClassroomSessionPayload) {
  return apiRequest<ClassroomSessionRow>('/api/v1/teacher/classroom/sessions/', {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function updateClassroomSession(id: number, payload: ClassroomSessionPayload) {
  return apiRequest<ClassroomSessionRow>(`/api/v1/teacher/classroom/sessions/${id}/`, {
    method: 'PATCH',
    body: toJsonBody(payload)
  })
}

export function deleteClassroomSession(id: number) {
  return apiRequest<Record<string, never>>(`/api/v1/teacher/classroom/sessions/${id}/`, { method: 'DELETE' })
}

export function startClassroomSession(id: number) {
  return apiRequest<ClassroomSessionRow>(`/api/v1/teacher/classroom/sessions/${id}/start/`, { method: 'POST' })
}

export function restartClassroomSession(id: number) {
  return apiRequest<ClassroomSessionRow>(`/api/v1/teacher/classroom/sessions/${id}/restart/`, { method: 'POST' })
}

export function finishClassroomSession(id: number) {
  return apiRequest<ClassroomSessionRow>(`/api/v1/teacher/classroom/sessions/${id}/finish/`, { method: 'POST' })
}

export function openClassroomStep(id: number, stepId: number) {
  return apiRequest<ClassroomSessionRow>(`/api/v1/teacher/classroom/sessions/${id}/step/open/`, {
    method: 'POST',
    body: toJsonBody({ step_id: stepId })
  })
}

export function lockClassroomStep(id: number) {
  return apiRequest<ClassroomSessionRow>(`/api/v1/teacher/classroom/sessions/${id}/step/lock/`, { method: 'POST' })
}

export function closeClassroomStep(id: number) {
  return apiRequest<ClassroomSessionRow>(`/api/v1/teacher/classroom/sessions/${id}/step/close/`, { method: 'POST' })
}

export function getClassroomStepProgress(id: number) {
  return apiRequest<ClassroomStepProgressPayload>(`/api/v1/teacher/classroom/sessions/${id}/step-progress/`)
}

export function scoreClassroomAttachment(sessionId: number, attachmentId: number, payload: { score: number | string; feedback?: string }) {
  return apiRequest<StudentWorkAttachmentRow>(`/api/v1/teacher/classroom/sessions/${sessionId}/attachments/${attachmentId}/score/`, {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function getClassroomGroupCollaboration(sessionId: number) {
  return apiRequest<ClassroomGroupCollaborationRow | null>(`/api/v1/teacher/classroom/sessions/${sessionId}/group-collaboration/`)
}

export function setupClassroomGroupCollaboration(sessionId: number, payload: ClassroomGroupCollaborationPayload) {
  return apiRequest<ClassroomGroupCollaborationRow>(`/api/v1/teacher/classroom/sessions/${sessionId}/group-collaboration/setup/`, {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function closeClassroomGroupCollaboration(sessionId: number) {
  return apiRequest<ClassroomGroupCollaborationRow>(`/api/v1/teacher/classroom/sessions/${sessionId}/group-collaboration/close/`, {
    method: 'POST'
  })
}

export function uploadTeacherClassroomGroupFile(sessionId: number, groupId: number, payload: { file: File; description?: string }) {
  const formData = new FormData()
  formData.append('attachment', payload.file)
  formData.append('description', payload.description || '')
  return uploadRequest<ClassroomGroupFileRow>(`/api/v1/teacher/classroom/sessions/${sessionId}/groups/${groupId}/files/`, formData)
}

export function getClassroomEvaluation(sessionId: number) {
  return apiRequest<ClassroomEvaluationPayload>(`/api/v1/teacher/classroom/sessions/${sessionId}/evaluation/`)
}

export function saveClassroomEvaluation(sessionId: number, payload: ClassroomEvaluationConfigPayload) {
  return apiRequest<ClassroomEvaluationPayload>(`/api/v1/teacher/classroom/sessions/${sessionId}/evaluation/`, {
    method: 'PATCH',
    body: toJsonBody(payload)
  })
}

export function setClassroomEvaluationRuntime(sessionId: number, evaluationEnabled: boolean) {
  return apiRequest<ClassroomEvaluationPayload>(`/api/v1/teacher/classroom/sessions/${sessionId}/evaluation/`, {
    method: 'PATCH',
    body: toJsonBody({ evaluation_enabled: evaluationEnabled })
  })
}

export function generateClassroomEvaluationCriteria(sessionId: number, payload: ClassroomEvaluationAiPayload) {
  return apiRequest<ClassroomEvaluationAiResult>(`/api/v1/teacher/classroom/sessions/${sessionId}/evaluation/ai-generate/`, {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function submitClassroomTeacherEvaluation(sessionId: number, payload: ClassroomTeacherEvaluationSubmitPayload) {
  return apiRequest<ClassroomEvaluationPayload>(`/api/v1/teacher/classroom/sessions/${sessionId}/evaluation/teacher-submit/`, {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function runClassroomCommand(id: number, payload: ClassroomCommandPayload) {
  return apiRequest<ClassroomActivityRow>(`/api/v1/teacher/classroom/sessions/${id}/command/`, {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function getClassroomAttendance(sessionId: number, activityId: number) {
  return apiRequest<ClassroomAttendancePayload>(`/api/v1/teacher/classroom/sessions/${sessionId}/attendance/${activityId}/`)
}

export function markClassroomAttendance(
  sessionId: number,
  activityId: number,
  payload: { student_id: number; status: Exclude<AttendanceStatus, 'not_signed'>; note?: string }
) {
  return apiRequest<ClassroomAttendancePayload>(`/api/v1/teacher/classroom/sessions/${sessionId}/attendance/${activityId}/mark/`, {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function getClassroomQuickAnswer(sessionId: number, activityId: number) {
  return apiRequest<QuickAnswerPayload>(`/api/v1/teacher/classroom/sessions/${sessionId}/quick-answer/${activityId}/`)
}

export function scoreClassroomQuickAnswer(
  sessionId: number,
  activityId: number,
  payload: { student_id: number; action: 'plus' | 'minus'; score?: number; note?: string }
) {
  return apiRequest<QuickAnswerPayload>(`/api/v1/teacher/classroom/sessions/${sessionId}/quick-answer/${activityId}/score/`, {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function getClassroomRandomPickPreview(sessionId: number) {
  return apiRequest<RandomPickPreviewPayload>(`/api/v1/teacher/classroom/sessions/${sessionId}/random-pick/preview/`)
}

export function getClassroomRandomPick(sessionId: number, activityId: number) {
  return apiRequest<RandomPickPayload>(`/api/v1/teacher/classroom/sessions/${sessionId}/random-pick/${activityId}/`)
}

export function scoreClassroomRandomPick(
  sessionId: number,
  activityId: number,
  payload: { student_id: number; action: 'plus' | 'minus'; score?: number; note?: string }
) {
  return apiRequest<RandomPickPayload>(`/api/v1/teacher/classroom/sessions/${sessionId}/random-pick/${activityId}/score/`, {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function getClassroomActivities(sessionId: number) {
  return apiRequest<ClassroomActivityRow[]>(`/api/v1/teacher/classroom/sessions/${sessionId}/activities/`)
}

export function createClassroomActivity(sessionId: number, payload: ClassroomActivityPayload) {
  return apiRequest<ClassroomActivityRow>(`/api/v1/teacher/classroom/sessions/${sessionId}/activities/`, {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function updateClassroomActivity(id: number, payload: ClassroomActivityPayload) {
  return apiRequest<ClassroomActivityRow>(`/api/v1/teacher/classroom/activities/${id}/`, {
    method: 'PATCH',
    body: toJsonBody(payload)
  })
}

export function deleteClassroomActivity(id: number) {
  return apiRequest<Record<string, never>>(`/api/v1/teacher/classroom/activities/${id}/`, { method: 'DELETE' })
}

export function openClassroomActivity(id: number) {
  return apiRequest<ClassroomActivityRow>(`/api/v1/teacher/classroom/activities/${id}/open/`, { method: 'POST' })
}

export function closeClassroomActivity(id: number) {
  return apiRequest<ClassroomActivityRow>(`/api/v1/teacher/classroom/activities/${id}/close/`, { method: 'POST' })
}

export type NoticeRow = {
  id: number
  title: string
  content: string
  status: 'draft' | 'published' | 'archived'
  status_label: string
  is_pinned: boolean
  target_classes: ClassGroupRow[]
  published_at: string | null
  archived_at: string | null
  created_at: string
  updated_at: string
}

export type NoticePayload = {
  title: string
  content: string
  status: string
  is_pinned: boolean
  target_classes: Array<number | string>
}

export type FeedbackRow = {
  id: number
  student: AccountRow
  class_group: ClassGroupRow
  category: 'study' | 'account' | 'resource' | 'suggestion' | 'other'
  category_label: string
  title: string
  content: string
  status: 'pending' | 'replied' | 'closed'
  status_label: string
  reply_content: string
  replied_at: string | null
  closed_at: string | null
  created_at: string
  updated_at: string
}

export function getTeacherNotices(params: PageQuery = {}) {
  return apiRequest<PageResult<NoticeRow>>(`/api/v1/teacher/notices/${queryString(params)}`)
}

export function createTeacherNotice(payload: NoticePayload) {
  return apiRequest<NoticeRow>('/api/v1/teacher/notices/', {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function updateTeacherNotice(id: number, payload: NoticePayload) {
  return apiRequest<NoticeRow>(`/api/v1/teacher/notices/${id}/`, {
    method: 'PATCH',
    body: toJsonBody(payload)
  })
}

export function deleteTeacherNotice(id: number) {
  return apiRequest<Record<string, never>>(`/api/v1/teacher/notices/${id}/`, { method: 'DELETE' })
}

export function publishTeacherNotice(id: number) {
  return apiRequest<NoticeRow>(`/api/v1/teacher/notices/${id}/publish/`, { method: 'POST' })
}

export function archiveTeacherNotice(id: number) {
  return apiRequest<NoticeRow>(`/api/v1/teacher/notices/${id}/archive/`, { method: 'POST' })
}

export function getTeacherFeedback(params: PageQuery & { category?: string } = {}) {
  return apiRequest<PageResult<FeedbackRow>>(`/api/v1/teacher/feedback/${queryString(params)}`)
}

export function replyTeacherFeedback(id: number, replyContent: string) {
  return apiRequest<FeedbackRow>(`/api/v1/teacher/feedback/${id}/reply/`, {
    method: 'POST',
    body: toJsonBody({ reply_content: replyContent })
  })
}

export function closeTeacherFeedback(id: number) {
  return apiRequest<FeedbackRow>(`/api/v1/teacher/feedback/${id}/close/`, { method: 'POST' })
}
