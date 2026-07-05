import { apiRequest, queryString, toJsonBody, uploadRequest } from './client'

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
  question_type: 'single' | 'multiple' | 'scale' | 'text'
  question_type_label: string
  options: PretestOption[]
  answer: string[]
  score: number
  dimension: string
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
  sort_order: number | string
  is_required: boolean
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
  current_layer: string
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
