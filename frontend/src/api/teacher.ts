import { apiRequest, queryString, toJsonBody, uploadRequest } from './client'
import type { CountSlice, Metric, SeriesPoint } from './dashboards'
import type { AccountRow, ClassGroupRow, PageQuery, PageResult, StudentRow, SubjectRow } from './management'

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
}

export type LessonStepQuestionType = 'single' | 'multiple' | 'judge' | 'blank' | 'text'

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
  title: string
  content: string
  attachment_url: string
  attachment_name: string
  attachment_size: number
  file_ext: string
  view_count: number
  is_pinned: boolean
  created_at: string
  updated_at: string
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
  status: 'draft' | 'open' | 'closed'
  status_label: string
  opened_at: string | null
  closed_at: string | null
  created_at: string
  updated_at: string
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
  is_layered: boolean
}

export type ClassroomActivityPayload = {
  activity_type: string
  title: string
  content: string
}

export function getTeacherCourseOptions() {
  return apiRequest<TeacherCourseOptions>('/api/v1/teacher/course-options/')
}

export function getTeacherResources(params: PageQuery = {}) {
  return apiRequest<PageResult<ResourceRow>>(`/api/v1/teacher/resources/${queryString(params)}`)
}

export function uploadTeacherResource(payload: { title: string; content?: string; file: File; is_pinned?: boolean }) {
  const formData = new FormData()
  formData.append('title', payload.title)
  formData.append('content', payload.content || '')
  formData.append('is_pinned', payload.is_pinned ? 'true' : 'false')
  formData.append('attachment', payload.file)
  return uploadRequest<ResourceRow>('/api/v1/teacher/resources/', formData)
}

export function deleteTeacherResource(id: number) {
  return apiRequest<Record<string, never>>(`/api/v1/teacher/resources/${id}/`, { method: 'DELETE' })
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
