import { apiRequest, queryString, toJsonBody } from './client'
import type { CurrentUser } from './auth'
import type { ClassGroupRow, PageQuery, PageResult, SubjectRow } from './management'

export type StudentProfile = {
  id: number
  student_no: string
  class_group: ClassGroupRow | null
  current_layer: string | null
  current_layer_label: string
  current_group_no: number | null
  score: number
  is_first_use: boolean
  onboarding_status: string
  onboarding_status_label: string
  password_updated_at: string | null
  class_selected_at: string | null
  pretest_completed_at: string | null
}

export type StudentTeacher = {
  id: number
  username: string
  display_name: string
}

export type StudentMetric = {
  label: string
  value: number
  sub: string
}

export type StudentTodo = {
  label: string
  detail: string
  level: 'live' | 'warn' | 'ok' | 'failed'
  path: string
}

export type StudentLesson = {
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
  step_count?: number
  classroom_session?: {
    id: number
    status: 'draft' | 'running' | 'finished'
    status_label: string
    current_step_status: 'idle' | 'open' | 'locked' | 'closed'
    current_step_status_label: string
    current_step_id: number | null
    submission_locked: boolean
  } | null
  created_at: string
  updated_at: string
}

export type StudentPretestStatus = {
  required: boolean
  completed: boolean
  missing: Array<{ kind: string; kind_label: string; paper_id: number; title: string }>
}

export type StudentCourse = {
  id: number
  subject: SubjectRow | null
  title: string
  introduction: string
  cover_url: string
  teacher: StudentTeacher
  teaching_model: 'pbl' | 'tbl'
  teaching_model_label: string
  lesson_count: number
  step_count: number
  latest_lesson: StudentLesson | null
  pretest_status: StudentPretestStatus
  created_at: string
  updated_at: string
  lessons?: StudentLesson[]
}

export type StudentClassroom = {
  id: number
  title: string
  status: 'draft' | 'running' | 'finished'
  status_label: string
  current_step: StudentLessonStep | null
  current_step_status: 'idle' | 'open' | 'locked' | 'closed'
  current_step_status_label: string
  submission_locked: boolean
  is_layered: boolean
  current_step_started_at: string | null
  current_step_closed_at: string | null
  teacher: StudentTeacher
  course: StudentCourse | null
  lesson: StudentLesson | null
  class_group: ClassGroupRow
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
}

export type StudentDashboard = {
  profile: StudentProfile
  current_classroom: StudentClassroom | null
  metrics: StudentMetric[]
  todo_rows: StudentTodo[]
  course_rows: StudentCourse[]
  notice_rows: StudentNotice[]
  teachers: StudentTeacher[]
}

export type StudentMe = {
  user: CurrentUser
  profile: StudentProfile
  current_classroom: StudentClassroom | null
  teachers: StudentTeacher[]
}

export type StudentLessonStep = {
  id: number
  lesson: number
  title: string
  step_type: string
  step_type_label: string
  student_instruction: string
  sort_order: number
  is_required: boolean
  estimated_minutes: number
  target_layer: string
  target_layer_label: string
  status: string
  status_label: string
  resource_items: StudentResourceBinding[]
  activity_items: string[]
  question_items: StudentLessonQuestion[]
  collect_student_log: boolean
  created_at: string
  updated_at: string
}

export type StudentLessonQuestion = {
  id: string
  question_type: 'single' | 'multiple' | 'judge' | 'blank' | 'text'
  question_type_label: string
  stem: string
  options: string[]
  score: number
  target_layer?: string
  target_layer_label?: string
  use_layer_scores?: boolean
  layer_scores?: Record<'A' | 'B' | 'C', number>
  is_required: boolean
  sort_order: number
}

export type StudentResourceBinding = {
  id: number | string
  title: string
  attachment_url: string
  attachment_name: string
  file_ext: string
  kind: string
}

export type StudentLessonWorkspace = {
  course: StudentCourse
  lesson: StudentLesson
  steps: StudentLessonStep[]
}

export type StudentNotice = {
  id: number
  title: string
  content: string
  is_pinned: boolean
  teacher: StudentTeacher
  published_at: string | null
  created_at: string
  updated_at: string
}

export type StudentFeedback = {
  id: number
  teacher: StudentTeacher
  category: string
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

export type StudentFeedbackPayload = {
  teacher: number | string
  category: string
  title: string
  content: string
}

export type StudentPretestQuestion = {
  id: number
  paper: number
  stem: string
  question_type: 'single' | 'multiple' | 'scale' | 'text'
  question_type_label: string
  options: Array<string | { label?: string; text?: string }>
  answer?: string[]
  score: number
  dimension: string
  sort_order: number
  is_required: boolean
}

export type StudentPretestPaper = {
  id: number
  subject: SubjectRow
  title: string
  kind: 'literacy' | 'attitude'
  kind_label: string
  version: number
  introduction: string
  status: string
  status_label: string
  question_count: number
  submission_count: number
  published_at: string | null
  created_at: string
  updated_at: string
  questions?: StudentPretestQuestion[]
}

export type StudentSubjectPretests = {
  subject: SubjectRow
  pretest_status: StudentPretestStatus
  papers: StudentPretestPaper[]
}

export type StudentRequiredPretest = {
  subject: SubjectRow
  pretest_status: StudentPretestStatus
}

export function getStudentMe() {
  return apiRequest<StudentMe>('/api/v1/student/me/')
}

export function getStudentDashboard() {
  return apiRequest<StudentDashboard>('/api/v1/student/dashboard/')
}

export function getStudentOnboarding() {
  return apiRequest<StudentDashboard>('/api/v1/student/onboarding/')
}

export function getStudentOnboardingClasses() {
  return apiRequest<ClassGroupRow[]>('/api/v1/student/onboarding/classes/')
}

export function saveStudentPassword(password: string) {
  return apiRequest<StudentProfile>('/api/v1/student/onboarding/password/', {
    method: 'POST',
    body: toJsonBody({ password })
  })
}

export function saveStudentClass(classGroup: number | string) {
  return apiRequest<StudentProfile>('/api/v1/student/onboarding/class/', {
    method: 'POST',
    body: toJsonBody({ class_group: classGroup })
  })
}

export function getStudentCourses() {
  return apiRequest<StudentCourse[]>('/api/v1/student/courses/')
}

export function getStudentCourse(id: number) {
  return apiRequest<StudentCourse>(`/api/v1/student/courses/${id}/`)
}

export function getStudentLessonWorkspace(id: number) {
  return apiRequest<StudentLessonWorkspace>(`/api/v1/student/lessons/${id}/workspace/`)
}

export function getStudentClassroom(id: number) {
  return apiRequest<StudentClassroom>(`/api/v1/student/classroom/${id}/`)
}

export function getStudentCurrentClassroom() {
  return apiRequest<StudentClassroom | null>('/api/v1/student/classroom/current/')
}

export function enterStudentLesson(id: number) {
  return apiRequest<Record<string, never>>(`/api/v1/student/lessons/${id}/enter/`, { method: 'POST' })
}

export function enterStudentLessonStep(id: number) {
  return apiRequest<Record<string, never>>(`/api/v1/student/lesson-steps/${id}/enter/`, { method: 'POST' })
}

export function completeStudentLessonStep(id: number, durationMs = 0) {
  return apiRequest<Record<string, never>>(`/api/v1/student/lesson-steps/${id}/complete/`, {
    method: 'POST',
    body: toJsonBody({ duration_ms: durationMs })
  })
}

export function submitStudentStepAnswer(id: number, answer: unknown) {
  return apiRequest<Record<string, never>>(`/api/v1/student/lesson-steps/${id}/answer/`, {
    method: 'POST',
    body: toJsonBody({ answer })
  })
}

export function getStudentNotices(params: PageQuery = {}) {
  return apiRequest<PageResult<StudentNotice>>(`/api/v1/student/notices/${queryString(params)}`)
}

export function getStudentFeedback(params: PageQuery = {}) {
  return apiRequest<PageResult<StudentFeedback>>(`/api/v1/student/feedback/${queryString(params)}`)
}

export function createStudentFeedback(payload: StudentFeedbackPayload) {
  return apiRequest<StudentFeedback>('/api/v1/student/feedback/', {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function getStudentSubjectPretests(subjectId: number) {
  return apiRequest<StudentSubjectPretests>(`/api/v1/student/pretests/${subjectId}/`)
}

export function getStudentRequiredPretests() {
  return apiRequest<StudentRequiredPretest[]>('/api/v1/student/pretests/required/')
}

export function getStudentPretestPaper(paperId: number) {
  return apiRequest<StudentPretestPaper>(`/api/v1/student/pretests/papers/${paperId}/`)
}

export function submitStudentPretestPaper(paperId: number, answers: Record<string, unknown>) {
  return apiRequest<{ id: number; score: number; submitted_at: string }>(`/api/v1/student/pretests/papers/${paperId}/`, {
    method: 'POST',
    body: toJsonBody({ answers })
  })
}
