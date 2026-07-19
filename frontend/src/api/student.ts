import { apiRequest, queryString, toJsonBody, uploadRequest } from './client'
import type { CurrentUser } from './auth'
import type { ClassGroupRow, PageQuery, PageResult, SubjectRow } from './management'
import type { ResourceRow } from './teacher'
import type { EvaluationNotAssessedEntry } from '@/domain/evaluation'

export type StudentProfile = {
  id: number
  student_no: string
  class_group: ClassGroupRow | null
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
  evaluation_enabled: boolean
  evaluation_opened_at: string | null
  current_step_started_at: string | null
  current_step_closed_at: string | null
  teacher: StudentTeacher
  course: StudentCourse | null
  lesson: StudentLesson | null
  class_group: ClassGroupRow
  started_at: string | null
  finished_at: string | null
  activities: StudentClassroomActivity[]
  created_at: string
  updated_at: string
}

export type StudentClassroomActivity = {
  id: number
  session: number
  activity_type: string
  activity_type_label: string
  title: string
  content: string
  metadata: Record<string, unknown> & {
    my_score_feedback?: StudentClassroomScoreFeedback
  }
  status: 'draft' | 'open' | 'closed'
  status_label: string
  opened_at: string | null
  closed_at: string | null
  created_at: string
  updated_at: string
}

export type StudentClassroomScoreFeedback = {
  event_id: number
  score: number
  score_action: 'plus' | 'minus' | ''
  score_note: string
  command?: string
  activity_title: string
  occurred_at: string
}

export type StudentClassroomActivityResponsePayload = {
  response_type?: string
  content?: string
}

export type StudentStepAnswerResult = {
  attempt_id: string
  attempt_no: number
  answered_count: number
  question_count: number
  auto_score: number
  auto_score_max: number
}

export type StudentWorkAttachment = {
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

export type StudentGroupMember = {
  id: number
  student_id: number
  username: string
  display_name: string
  student_no: string
  role: 'leader' | 'member'
  role_label: string
  joined_at: string
}

export type StudentGroupFile = {
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

export type StudentGroupDocument = {
  attachment_url: string
  attachment_name: string
  file_ext: string
  file_size: number
  document_version: number
}

export type StudentGroup = {
  id: number
  collaboration: number
  group_no: number
  name: string
  leader: number | null
  document: StudentGroupDocument
  used_storage_bytes: number
  used_storage_mb: number
  members: StudentGroupMember[]
  files: StudentGroupFile[]
  file_count: number
  created_at: string
  updated_at: string
}

export type StudentGroupCollaboration = {
  id: number
  session: number
  is_enabled: boolean
  status: 'draft' | 'open' | 'closed'
  status_label: string
  group_size: number
  document_type: 'docx' | 'pptx' | 'xlsx'
  document_type_label: string
  storage_quota_mb: number
  allow_student_upload: boolean
  allow_onlyoffice_edit: boolean
  group_count: number
  my_group_id: number | null
  my_group: StudentGroup | null
  groups: StudentGroup[]
  opened_at: string | null
  closed_at: string | null
  created_at: string
  updated_at: string
}

export type StudentEvaluationType = 'self' | 'peer'

export type StudentEvaluationCriterion = {
  id: string
  title: string
  description: string
  sort_order: number
  level_descriptions?: string[]
  skip_condition?: string
}

export type StudentEvaluationSubmission = {
  id: number
  course: number
  class_group: number | null
  session: number | null
  evaluation_type: 'self' | 'peer' | 'teacher'
  evaluation_type_label: string
  evaluator: {
    id: number
    username: string
    display_name: string
  }
  target: {
    id: number
    username: string
    display_name: string
  }
  group: number | null
  ratings: Record<string, number>
  not_assessed: Record<string, EvaluationNotAssessedEntry>
  comment: string
  created_at: string
  updated_at: string
}

export type StudentEvaluationConfig = {
  id: number | null
  course: number | null
  session: number | null
  enable_self: boolean
  enable_peer: boolean
  enable_teacher: false
  self_criteria: StudentEvaluationCriterion[]
  peer_criteria: StudentEvaluationCriterion[]
  teacher_criteria: []
  opened_at: string | null
  created_at: string | null
  updated_at: string | null
}

export type StudentPeerEvaluationTarget = {
  student_id: number
  username: string
  display_name: string
  student_no: string
  submission: StudentEvaluationSubmission | null
}

export type StudentEvaluationContext = {
  runtime_enabled: boolean
  runtime_opened_at: string | null
  config: StudentEvaluationConfig
  self_submission: StudentEvaluationSubmission | null
  peer_targets: StudentPeerEvaluationTarget[]
  my_group: StudentGroup | null
}

export type StudentEvaluationSubmitPayload = {
  evaluation_type: StudentEvaluationType
  target?: number
  ratings: Record<string, number>
  not_assessed?: Record<string, EvaluationNotAssessedEntry>
  comment?: string
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

export type StudentArchiveSubject = { id: number; name: string; code: string }

export type StudentArchive = {
  student: {
    id: number
    username: string
    display_name: string
    student_no: string
    school: { id: number; name: string } | null
    class_group: ClassGroupRow | null
  }
  subjects: StudentArchiveSubject[]
  selected_subject: number | null
  metrics: {
    course_count: number
    active_day_count: number
    learning_event_count: number
    completed_test_count: number
    work_count: number
    last_activity_at: string | null
  }
  courses: Array<{
    id: number
    title: string
    subject: StudentArchiveSubject | null
    teacher: StudentTeacher
    lesson_count: number
    visited_lesson_count: number
    step_count: number
    completed_step_count: number
    progress_percent: number
    event_count: number
    last_activity_at: string | null
  }>
  pretests: Array<{
    id: number
    subject: StudentArchiveSubject
    paper_title: string
    kind: 'literacy' | 'attitude'
    kind_label: string
    score: number
    submitted_at: string
  }>
  tests: Array<{
    id: number
    assessment_id: number
    title: string
    subject: StudentArchiveSubject
    course: { id: number; title: string } | null
    status: 'in_progress' | 'submitted' | 'graded'
    status_label: string
    objective_score: number
    subjective_score: number
    total_score: number
    total_possible: number
    started_at: string
    submitted_at: string | null
    graded_at: string | null
  }>
  works: Array<StudentWorkAttachment & {
    course_title: string
    subject: StudentArchiveSubject | null
    lesson_title: string
    step_title: string
    status: 'submitted' | 'evaluated'
    status_label: string
  }>
  evaluations: Array<{
    id: number
    course: { id: number; title: string }
    subject: StudentArchiveSubject | null
    evaluation_type: 'self' | 'peer' | 'teacher'
    evaluation_type_label: string
    average_rating: number | null
    comment: string
    evaluator_label: string
    updated_at: string
  }>
  event_distribution: Array<{
    event_type: string
    label: string
    value: number
    percent: number
  }>
  recent_events: Array<{
    id: number
    event_type: string
    label: string
    course: { id: number; title: string } | null
    lesson: { id: number; title: string } | null
    duration_ms: number
    occurred_at: string
  }>
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
  question_type: 'single' | 'multiple' | 'judge' | 'blank' | 'text' | 'file'
  question_type_label: string
  stem: string
  options: string[]
  score: number
  file_config?: {
    allowed_extensions: string[]
    max_size_mb: number
  }
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
  external_url?: string
  resource_type?: string
  learning_page_id?: number
  revision_no?: number
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

export function getStudentResources(params: PageQuery & { scope?: string } = {}) {
  return apiRequest<PageResult<ResourceRow>>(`/api/v1/student/resources/${queryString(params)}`)
}

export function getStudentResource(id: number) {
  return apiRequest<ResourceRow>(`/api/v1/student/resources/${id}/`)
}

export function recordStudentResourceView(id: number) {
  return apiRequest<ResourceRow>(`/api/v1/student/resources/${id}/`, { method: 'POST' })
}

export function getStudentArchive(subject?: number | string) {
  return apiRequest<StudentArchive>(`/api/v1/student/profile/${queryString({ subject })}`)
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

export function recordClassroomResourceOpened(
  classroomId: number,
  resourceId: number | string,
  presentation: 'embedded' | 'popout' | 'external' | 'download' | 'unknown' = 'embedded'
) {
  return apiRequest<Record<string, never>>(`/api/v1/student/classroom/${classroomId}/resources/${resourceId}/opened/`, {
    method: 'POST',
    body: toJsonBody({ presentation })
  })
}

export function recordClassroomVideoProgress(
  classroomId: number,
  resourceId: number | string,
  payload: { position_seconds: number; media_seconds: number; playback_rate: number; duration_ms: number }
) {
  return apiRequest<Record<string, never>>(`/api/v1/student/classroom/${classroomId}/resources/${resourceId}/video-progress/`, {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function recordClassroomDocumentProgress(
  classroomId: number,
  resourceId: number | string,
  payload: { page: number; page_count: number; visible_seconds: number }
) {
  return apiRequest<Record<string, never>>(`/api/v1/student/classroom/${classroomId}/resources/${resourceId}/document-progress/`, {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function getStudentGroupCollaboration(classroomId: number) {
  return apiRequest<StudentGroupCollaboration | null>(`/api/v1/student/classroom/${classroomId}/group-collaboration/`)
}

export function getStudentClassroomEvaluation(classroomId: number) {
  return apiRequest<StudentEvaluationContext>(`/api/v1/student/classroom/${classroomId}/evaluation/`)
}

export function submitStudentClassroomEvaluation(classroomId: number, payload: StudentEvaluationSubmitPayload) {
  return apiRequest<StudentEvaluationContext>(`/api/v1/student/classroom/${classroomId}/evaluation/submit/`, {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function uploadStudentGroupFile(classroomId: number, file: File, description = '') {
  const formData = new FormData()
  formData.append('attachment', file)
  formData.append('description', description)
  return uploadRequest<StudentGroupFile>(`/api/v1/student/classroom/${classroomId}/group-collaboration/files/`, formData)
}

export function respondClassroomActivity(classroomId: number, activityId: number, payload: StudentClassroomActivityResponsePayload = {}) {
  return apiRequest<StudentClassroomActivity>(`/api/v1/student/classroom/${classroomId}/activities/${activityId}/response/`, {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function acknowledgeClassroomScoreFeedback(classroomId: number, activityId: number, scoreEventId: number) {
  return apiRequest<{ score_event_id: number }>(`/api/v1/student/classroom/${classroomId}/activities/${activityId}/score-feedback/ack/`, {
    method: 'POST',
    body: toJsonBody({ score_event_id: scoreEventId })
  })
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
  return apiRequest<StudentStepAnswerResult>(`/api/v1/student/lesson-steps/${id}/answer/`, {
    method: 'POST',
    body: toJsonBody({ answer })
  })
}

export function uploadStudentStepAttachment(stepId: number, questionId: string, file: File) {
  const formData = new FormData()
  formData.append('question_id', questionId)
  formData.append('attachment', file)
  return uploadRequest<StudentWorkAttachment>(`/api/v1/student/lesson-steps/${stepId}/attachments/`, formData)
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
