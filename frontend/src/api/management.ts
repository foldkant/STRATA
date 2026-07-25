import { apiRequest, queryString, toJsonBody, uploadRequest } from './client'
import type { ResourceRow } from './teacher'

export type PageResult<T> = {
  count: number
  page: number
  page_size: number
  results: T[]
}

export type PageQuery = {
  q?: string
  status?: string
  school?: string
  class?: string | number
  teacher?: string | number
  subject?: string | number
  course?: string | number
  kind?: string
  layer?: string
  page?: number
  page_size?: number
}

export type AccountRow = {
  id: number
  username: string
  display_name: string
  phone: string
  role: string
  role_label: string
  school: null | { id: number; name: string; code: string }
  is_active: boolean
  is_first_login: boolean
  last_login: string | null
  date_joined: string
}

export type SchoolRow = {
  id: number
  name: string
  code: string
  status: 'active' | 'disabled' | 'archived'
  status_label: string
  contact_name: string
  contact_phone: string
  address: string
  note: string
  class_count: number
  user_count: number
  created_at: string
  updated_at: string
}

export type SchoolPayload = {
  name: string
  code: string
  status: string
  contact_name: string
  contact_phone: string
  address: string
  note: string
}

export type AccountPayload = {
  username: string
  display_name: string
  phone: string
  password?: string
  school?: number | string
  is_active: boolean
}

export type ClassGroupRow = {
  id: number
  name: string
  grade: string
  entry_year: number | null
  status: 'active' | 'disabled' | 'archived'
  status_label: string
  student_count: number
  teacher_count: number
  graduated_at: string | null
  created_at: string
}

export type ClassGroupPayload = {
  name: string
  grade: string
  entry_year: number | string | null
  status: string
}

export type ClassGroupBulkPayload = {
  grade: string
  entry_year: number | string
  class_count: number | string
  start_no: number | string
  status: string
}

export type ClassGroupPromotePayload = {
  from_grade: string
  to_grade: string
}

export type BulkIdsPayload = {
  ids: number[]
}

export type BulkOperationResult = {
  requested_count: number
  updated_count?: number
  deleted_count?: number
  graduated_count?: number
  disabled_students?: number
  blocked?: Array<{ id: number; username?: string; display_name?: string; name?: string; reason: string }>
  message?: string
}

export type ImportResult = {
  created_count: number
  updated_count: number
  total_count: number
}

export type TeachingTeacherRow = {
  id: number
  teacher: AccountRow
  classes: ClassGroupRow[]
  class_count: number
}

export type TeachingBulkPayload = {
  teacher: number | string
  class_groups: Array<number | string>
}

export type TeachingBulkResult = {
  created_count: number
  updated_count: number
  deleted_count: number
  total_count: number
}

export type TeachingOptions = {
  classes: ClassGroupRow[]
  teachers: AccountRow[]
}

export type SubjectRow = {
  id: number
  name: string
  code: string
  is_active: boolean
  course_count: number
  pretest_count: number
  created_at: string
  updated_at: string
}

export type SubjectPayload = {
  name: string
  code: string
  is_active: boolean
}

export type PretestOption = {
  label: string
  text: string
}

export type PretestPaperRow = {
  id: number
  subject: SubjectRow
  title: string
  kind: 'literacy' | 'attitude'
  kind_label: string
  version: number
  introduction: string
  status: 'draft' | 'published' | 'archived'
  status_label: string
  question_count: number
  submission_count: number
  published_at: string | null
  published_version: { id: number; version_no: number; content_hash: string } | null
  created_at: string
  updated_at: string
  questions?: PretestQuestionRow[]
}

export type PretestPaperPayload = {
  subject: number | string
  title: string
  kind: string
  version?: number | string
  introduction: string
  status: string
}

export type PretestQuestionRow = {
  id: number
  paper: number
  stem: string
  question_type: 'single' | 'multiple' | 'scale' | 'text' | 'performance' | 'operation' | 'short_project'
  question_type_label: string
  options: PretestOption[]
  answer: string[]
  score: number
  dimension: string
  learning_target_code: string
  learning_target_name: string
  learning_target_version: {
    id: number
    version_no: number
    content_hash: string
    logical_key: string
  } | null
  legacy_unmapped: boolean
  material_requirements: string[]
  sort_order: number
  is_required: boolean
  created_at: string
  updated_at: string
}

export type PretestQuestionPayload = {
  stem: string
  question_type: string
  options: string | PretestOption[]
  answer: string | string[]
  score: number | string
  dimension: string
  learning_target_code: string
  learning_target_name: string
  learning_target_version_id?: number | string | null
  material_requirements: string[]
  sort_order: number | string
  is_required: boolean
}

export type DiagnosticLearningTargetVersionOption = {
  id: number
  logical_key: string
  version_no: number
  code: string
  title: string
  description: string
  content_hash: string
  alignment_status: 'complete'
  subject: { id: number; name: string; code: string }
  course: { id: number; title: string }
  plan_version_id: number
  published_at: string
}

export type DiagnosticAdministrationAssignmentRow = {
  id: number
  class_group: { id: number; name: string; grade: string }
  cohort_role: 'experiment' | 'control' | 'unassigned'
  cohort_role_label: string
  opportunity_status: 'offered' | 'not_offered'
  opportunity_status_label: string
  submission_count?: number
  scoring_completed_count?: number
  created_at: string
}

export type DiagnosticAdministrationRow = {
  id: number
  subject: { id: number; name: string; code: string }
  course: { id: number; title: string } | null
  paper_version: {
    id: number
    source_id: number
    title: string
    kind: string
    kind_label: string
    version_no: number
    content_hash: string
    published_at: string
  }
  purpose: 'entry_diagnostic' | 'research_pretest' | 'research_posttest' | 'pilot'
  purpose_label: string
  batch_code: string
  title: string
  open_at: string | null
  close_at: string | null
  status: 'draft' | 'published' | 'closed'
  status_label: string
  availability_status: 'draft' | 'scheduled' | 'open' | 'closed'
  content_hash: string
  assignment_count: number
  submission_count: number
  created_at: string
  updated_at: string
  published_at: string | null
  closed_at: string | null
  assignments?: DiagnosticAdministrationAssignmentRow[] | null
}

export type DiagnosticAdministrationPayload = {
  subject_id: number
  course_id?: number | null
  paper_version_id: number
  purpose: DiagnosticAdministrationRow['purpose']
  batch_code: string
  title: string
  open_at?: string | null
  close_at?: string | null
  expected_updated_at?: string
}

export type PretestMaterialReviewRow = {
  material_id: string
  student: { id: number; username: string; display_name: string }
  class_group: { id: number; name: string; grade: string } | null
  subject: { id: number; name: string }
  learning_target_code: string
  material_type: string
  material_type_label: string
  material_status: string
  material_status_label: string
  question_id: string
  question_type: string
  answer: unknown
  process_explanation: unknown
  attachments: Array<{
    attachment_id: string
    original_name: string
    file_ext: string
    content_type: string
    file_size: number
    file_sha256: string
    download_url: string
  }>
  material_requirements: string[]
  score_max: number | null
  recorded_at: string
}

export type StudentRow = {
  id: number
  user_id: number
  username: string
  display_name: string
  phone: string
  student_no: string
  class_group: null | { id: number; name: string; grade: string; status: string }
  current_layer: '' | 'A' | 'B' | 'C' | null
  current_layer_label: string
  current_group_no: number | null
  score: number
  is_first_use: boolean
  onboarding_status: string
  onboarding_status_label: string
  pretest_completed_at: string | null
  is_active: boolean
  is_first_login: boolean
  last_login: string | null
  updated_at: string
}

export type StudentPayload = {
  username: string
  display_name: string
  phone: string
  password?: string
  student_no: string
  class_group: number | string
  current_group_no: number | string | null
  score: number | string
  is_active: boolean
}

export function getSchools(params: PageQuery = {}) {
  return apiRequest<PageResult<SchoolRow>>(`/api/v1/super-admin/schools/${queryString(params)}`)
}

export function createSchool(payload: SchoolPayload) {
  return apiRequest<SchoolRow>('/api/v1/super-admin/schools/', {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function updateSchool(id: number, payload: SchoolPayload) {
  return apiRequest<SchoolRow>(`/api/v1/super-admin/schools/${id}/`, {
    method: 'PATCH',
    body: toJsonBody(payload)
  })
}

export function deleteSchool(id: number) {
  return apiRequest<Record<string, never>>(`/api/v1/super-admin/schools/${id}/`, { method: 'DELETE' })
}

export function bulkDisableSchools(ids: number[]) {
  return apiRequest<BulkOperationResult>('/api/v1/super-admin/schools/bulk-disable/', {
    method: 'POST',
    body: toJsonBody({ ids })
  })
}

export function bulkDeleteSchools(ids: number[]) {
  return apiRequest<BulkOperationResult>('/api/v1/super-admin/schools/bulk-delete/', {
    method: 'POST',
    body: toJsonBody({ ids })
  })
}

export function getSchoolAdmins(params: PageQuery = {}) {
  return apiRequest<PageResult<AccountRow>>(`/api/v1/super-admin/school-admins/${queryString(params)}`)
}

export function createSchoolAdmin(payload: AccountPayload) {
  return apiRequest<AccountRow>('/api/v1/super-admin/school-admins/', {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function updateSchoolAdmin(id: number, payload: AccountPayload) {
  return apiRequest<AccountRow>(`/api/v1/super-admin/school-admins/${id}/`, {
    method: 'PATCH',
    body: toJsonBody(payload)
  })
}

export function setSchoolAdminActive(id: number, isActive: boolean) {
  return apiRequest<AccountRow>(`/api/v1/super-admin/school-admins/${id}/active/`, {
    method: 'POST',
    body: toJsonBody({ is_active: isActive })
  })
}

export function resetSchoolAdminPassword(id: number, password: string) {
  return apiRequest<AccountRow>(`/api/v1/super-admin/school-admins/${id}/reset-password/`, {
    method: 'POST',
    body: toJsonBody({ password })
  })
}

export function deleteSchoolAdmin(id: number) {
  return apiRequest<Record<string, never>>(`/api/v1/super-admin/school-admins/${id}/`, { method: 'DELETE' })
}

export function bulkDisableSchoolAdmins(ids: number[]) {
  return apiRequest<BulkOperationResult>('/api/v1/super-admin/school-admins/bulk-disable/', {
    method: 'POST',
    body: toJsonBody({ ids })
  })
}

export function bulkDeleteSchoolAdmins(ids: number[]) {
  return apiRequest<BulkOperationResult>('/api/v1/super-admin/school-admins/bulk-delete/', {
    method: 'POST',
    body: toJsonBody({ ids })
  })
}

export function getTeachers(params: PageQuery = {}) {
  return apiRequest<PageResult<AccountRow>>(`/api/v1/school-admin/teachers/${queryString(params)}`)
}

export function createTeacher(payload: AccountPayload) {
  return apiRequest<AccountRow>('/api/v1/school-admin/teachers/', {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function updateTeacher(id: number, payload: AccountPayload) {
  return apiRequest<AccountRow>(`/api/v1/school-admin/teachers/${id}/`, {
    method: 'PATCH',
    body: toJsonBody(payload)
  })
}

export function setTeacherActive(id: number, isActive: boolean) {
  return apiRequest<AccountRow>(`/api/v1/school-admin/teachers/${id}/active/`, {
    method: 'POST',
    body: toJsonBody({ is_active: isActive })
  })
}

export function resetTeacherPassword(id: number, password: string) {
  return apiRequest<AccountRow>(`/api/v1/school-admin/teachers/${id}/reset-password/`, {
    method: 'POST',
    body: toJsonBody({ password })
  })
}

export function deleteTeacher(id: number) {
  return apiRequest<Record<string, never>>(`/api/v1/school-admin/teachers/${id}/`, { method: 'DELETE' })
}

export function bulkDisableTeachers(ids: number[]) {
  return apiRequest<BulkOperationResult>('/api/v1/school-admin/teachers/bulk-disable/', {
    method: 'POST',
    body: toJsonBody({ ids })
  })
}

export function bulkDeleteTeachers(ids: number[]) {
  return apiRequest<BulkOperationResult>('/api/v1/school-admin/teachers/bulk-delete/', {
    method: 'POST',
    body: toJsonBody({ ids })
  })
}

export function importTeachers(file: File) {
  const formData = new FormData()
  formData.append('file', file)
  return uploadRequest<ImportResult>('/api/v1/school-admin/teachers/import/', formData)
}

export function getClasses(params: PageQuery = {}) {
  return apiRequest<PageResult<ClassGroupRow>>(`/api/v1/school-admin/classes/${queryString(params)}`)
}

export function createClass(payload: ClassGroupPayload) {
  return apiRequest<ClassGroupRow>('/api/v1/school-admin/classes/', {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function bulkCreateClasses(payload: ClassGroupBulkPayload) {
  return apiRequest<{ created_count: number; results: ClassGroupRow[] }>('/api/v1/school-admin/classes/bulk-create/', {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function promoteClasses(payload: ClassGroupPromotePayload) {
  return apiRequest<{ promoted_count: number; results: ClassGroupRow[] }>('/api/v1/school-admin/classes/promote/', {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function bulkDisableClasses(ids: number[]) {
  return apiRequest<BulkOperationResult>('/api/v1/school-admin/classes/bulk-disable/', {
    method: 'POST',
    body: toJsonBody({ ids })
  })
}

export function bulkDeleteClasses(ids: number[]) {
  return apiRequest<BulkOperationResult>('/api/v1/school-admin/classes/bulk-delete/', {
    method: 'POST',
    body: toJsonBody({ ids })
  })
}

export function graduateClasses(ids: number[]) {
  return apiRequest<BulkOperationResult>('/api/v1/school-admin/classes/graduate/', {
    method: 'POST',
    body: toJsonBody({ ids })
  })
}

export function updateClass(id: number, payload: ClassGroupPayload) {
  return apiRequest<ClassGroupRow>(`/api/v1/school-admin/classes/${id}/`, {
    method: 'PATCH',
    body: toJsonBody(payload)
  })
}

export function deleteClass(id: number) {
  return apiRequest<Record<string, never>>(`/api/v1/school-admin/classes/${id}/`, { method: 'DELETE' })
}

export function getTeachingOptions() {
  return apiRequest<TeachingOptions>('/api/v1/school-admin/teaching/options/')
}

export function getTeachingAssignments(params: PageQuery = {}) {
  return apiRequest<PageResult<TeachingTeacherRow>>(`/api/v1/school-admin/teaching/${queryString(params)}`)
}

export function deleteTeachingAssignment(id: number) {
  return apiRequest<Record<string, never>>(`/api/v1/school-admin/teaching/${id}/`, { method: 'DELETE' })
}

export function bulkSaveTeachingAssignments(payload: TeachingBulkPayload) {
  return apiRequest<TeachingBulkResult>('/api/v1/school-admin/teaching/bulk-save/', {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function getStudents(params: PageQuery = {}) {
  return apiRequest<PageResult<StudentRow>>(`/api/v1/school-admin/students/${queryString(params)}`)
}

export function createStudent(payload: StudentPayload) {
  return apiRequest<StudentRow>('/api/v1/school-admin/students/', {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function updateStudent(id: number, payload: StudentPayload) {
  return apiRequest<StudentRow>(`/api/v1/school-admin/students/${id}/`, {
    method: 'PATCH',
    body: toJsonBody(payload)
  })
}

export function setStudentActive(id: number, isActive: boolean) {
  return apiRequest<StudentRow>(`/api/v1/school-admin/students/${id}/active/`, {
    method: 'POST',
    body: toJsonBody({ is_active: isActive })
  })
}

export function resetStudentPassword(id: number, password: string) {
  return apiRequest<StudentRow>(`/api/v1/school-admin/students/${id}/reset-password/`, {
    method: 'POST',
    body: toJsonBody({ password })
  })
}

export function deleteStudent(id: number) {
  return apiRequest<Record<string, never>>(`/api/v1/school-admin/students/${id}/`, { method: 'DELETE' })
}

export function bulkDisableStudents(ids: number[]) {
  return apiRequest<BulkOperationResult>('/api/v1/school-admin/students/bulk-disable/', {
    method: 'POST',
    body: toJsonBody({ ids })
  })
}

export function bulkDeleteStudents(ids: number[]) {
  return apiRequest<BulkOperationResult>('/api/v1/school-admin/students/bulk-delete/', {
    method: 'POST',
    body: toJsonBody({ ids })
  })
}

export function importStudents(file: File) {
  const formData = new FormData()
  formData.append('file', file)
  return uploadRequest<ImportResult>('/api/v1/school-admin/students/import/', formData)
}

export function getSubjects(params: PageQuery = {}) {
  return apiRequest<SubjectRow[]>(`/api/v1/school-admin/subjects/${queryString(params)}`)
}

export function createSubject(payload: SubjectPayload) {
  return apiRequest<SubjectRow>('/api/v1/school-admin/subjects/', {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function updateSubject(id: number, payload: SubjectPayload) {
  return apiRequest<SubjectRow>(`/api/v1/school-admin/subjects/${id}/`, {
    method: 'PATCH',
    body: toJsonBody(payload)
  })
}

export function deleteSubject(id: number) {
  return apiRequest<Record<string, never>>(`/api/v1/school-admin/subjects/${id}/`, { method: 'DELETE' })
}

export function getPretestPapers(params: PageQuery = {}) {
  return apiRequest<PageResult<PretestPaperRow>>(`/api/v1/school-admin/pretests/${queryString(params)}`)
}

export function getDiagnosticLearningTargetVersions(params: PageQuery = {}) {
  return apiRequest<DiagnosticLearningTargetVersionOption[]>(
    `/api/v1/school-admin/pretests/learning-target-versions/${queryString(params)}`
  )
}

export function getPretestPaper(id: number) {
  return apiRequest<PretestPaperRow>(`/api/v1/school-admin/pretests/${id}/`)
}

export function createPretestPaper(payload: PretestPaperPayload) {
  return apiRequest<PretestPaperRow>('/api/v1/school-admin/pretests/', {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function updatePretestPaper(id: number, payload: PretestPaperPayload) {
  return apiRequest<PretestPaperRow>(`/api/v1/school-admin/pretests/${id}/`, {
    method: 'PATCH',
    body: toJsonBody(payload)
  })
}

export function deletePretestPaper(id: number) {
  return apiRequest<Record<string, never>>(`/api/v1/school-admin/pretests/${id}/`, { method: 'DELETE' })
}

export function publishPretestPaper(id: number) {
  return apiRequest<PretestPaperRow>(`/api/v1/school-admin/pretests/${id}/publish/`, { method: 'POST' })
}

export function archivePretestPaper(id: number) {
  return apiRequest<PretestPaperRow>(`/api/v1/school-admin/pretests/${id}/archive/`, { method: 'POST' })
}

export function getDiagnosticAdministrations(params: PageQuery = {}) {
  return apiRequest<DiagnosticAdministrationRow[]>(`/api/v1/school-admin/diagnostic-administrations/${queryString(params)}`)
}

export function getDiagnosticAdministration(id: number) {
  return apiRequest<DiagnosticAdministrationRow>(`/api/v1/school-admin/diagnostic-administrations/${id}/`)
}

export function createDiagnosticAdministration(payload: DiagnosticAdministrationPayload) {
  return apiRequest<DiagnosticAdministrationRow>('/api/v1/school-admin/diagnostic-administrations/', {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function updateDiagnosticAdministration(id: number, payload: DiagnosticAdministrationPayload) {
  return apiRequest<DiagnosticAdministrationRow>(`/api/v1/school-admin/diagnostic-administrations/${id}/`, {
    method: 'PATCH',
    body: toJsonBody(payload)
  })
}

export function replaceDiagnosticAdministrationAssignments(
  id: number,
  assignments: Array<{
    class_group_id: number
    cohort_role: DiagnosticAdministrationAssignmentRow['cohort_role']
    opportunity_status: DiagnosticAdministrationAssignmentRow['opportunity_status']
  }>,
  expectedUpdatedAt?: string
) {
  return apiRequest<DiagnosticAdministrationRow>(`/api/v1/school-admin/diagnostic-administrations/${id}/assignments/`, {
    method: 'PUT',
    body: toJsonBody({ assignments, expected_updated_at: expectedUpdatedAt })
  })
}

export function publishDiagnosticAdministration(id: number) {
  return apiRequest<DiagnosticAdministrationRow>(`/api/v1/school-admin/diagnostic-administrations/${id}/publish/`, { method: 'POST' })
}

export function closeDiagnosticAdministration(id: number) {
  return apiRequest<DiagnosticAdministrationRow>(`/api/v1/school-admin/diagnostic-administrations/${id}/close/`, { method: 'POST' })
}

export function getPretestQuestions(paperId: number) {
  return apiRequest<PretestQuestionRow[]>(`/api/v1/school-admin/pretests/${paperId}/questions/`)
}

export function createPretestQuestion(paperId: number, payload: PretestQuestionPayload) {
  return apiRequest<PretestQuestionRow>(`/api/v1/school-admin/pretests/${paperId}/questions/`, {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function updatePretestQuestion(paperId: number, questionId: number, payload: PretestQuestionPayload) {
  return apiRequest<PretestQuestionRow>(`/api/v1/school-admin/pretests/${paperId}/questions/${questionId}/`, {
    method: 'PATCH',
    body: toJsonBody(payload)
  })
}

export function deletePretestQuestion(paperId: number, questionId: number) {
  return apiRequest<Record<string, never>>(`/api/v1/school-admin/pretests/${paperId}/questions/${questionId}/`, {
    method: 'DELETE'
  })
}

export function getPendingPretestMaterials(params: { subject?: number | string; class_group?: number | string } = {}) {
  return apiRequest<PretestMaterialReviewRow[]>(`/api/v1/school-admin/pretest-materials/pending/${queryString(params)}`)
}

export function reviewPretestMaterial(materialId: string, payload: { score: number; score_max?: number; feedback: string }) {
  return apiRequest<{
    score_material_id: string
    target_state_id: number
    evidence_status: string
    evidence_coverage: number
    estimate: number | null
  }>(`/api/v1/school-admin/pretest-materials/${materialId}/review/`, {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function getResourceReviews(params: PageQuery = {}) {
  return apiRequest<PageResult<ResourceRow>>(`/api/v1/school-admin/resource-reviews/${queryString(params)}`)
}

export function reviewResource(id: number, action: 'approve' | 'reject', note = '') {
  return apiRequest<ResourceRow>(`/api/v1/school-admin/resource-reviews/${id}/`, {
    method: 'PATCH',
    body: toJsonBody({ action, note })
  })
}
