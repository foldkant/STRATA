import { apiRequest, toJsonBody } from './client'

export type LearningPageFieldType =
  | 'single'
  | 'multiple'
  | 'select'
  | 'short_text'
  | 'long_text'
  | 'number'
  | 'scale'

export type LearningPageField = {
  id: string
  type: LearningPageFieldType
  label: string
  required: boolean
  placeholder?: string
  options?: string[]
  min?: number | null
  max?: number | null
}

export type LearningPageVisualizationItem = {
  label: string
  detail: string
  code: string
  value: number | null
  tone: 'blue' | 'green' | 'cyan' | 'amber' | 'red' | 'indigo'
}

export type LearningPageBlock = {
  id: string
  type: 'content' | 'callout' | 'list' | 'steps' | 'cards' | 'table' | 'code' | 'visualization' | 'interactive' | 'form'
  title?: string
  body?: string
  tone?: 'info' | 'success' | 'warning' | 'danger'
  items?: Array<string | { title: string; body: string } | LearningPageVisualizationItem>
  headers?: string[]
  rows?: string[][]
  language?: string
  code?: string
  visualization_type?: 'process' | 'timeline' | 'bars' | 'binary'
  description?: string
  duration_ms?: number
  autoplay?: boolean
  loop?: boolean
  html?: string
  css?: string
  javascript?: string
  height?: number
  form_id?: string
  submit_label?: string
  fields?: LearningPageField[]
}

export type LearningPageSchema = {
  schema_version: 1
  title: string
  subtitle: string
  accent: 'blue' | 'green' | 'cyan' | 'amber' | 'red' | 'indigo'
  blocks: LearningPageBlock[]
}

export type LearningPageGenerationMode = 'auto' | 'interactive' | 'structured'

export type LearningPageVersion = {
  id: number
  page: number
  version_no: number
  prompt: string
  schema: LearningPageSchema
  created_at: string
}

export type LearningPage = {
  id: number
  school: number
  teacher: { id: number; username: string; display_name: string }
  course: number
  lesson: number
  title: string
  generation_prompt: string
  revision_no: number
  status: 'draft' | 'ready'
  status_label: string
  is_active: boolean
  block_count: number
  form_count: number
  response_count: number
  schema: LearningPageSchema
  versions?: LearningPageVersion[]
  created_at: string
  updated_at: string
}

export type LearningPageResponse = {
  id: number
  page: number
  page_version: number
  student: { id: number; username: string; display_name: string }
  class_group: { id: number; name: string; grade: string }
  lesson_step: number
  classroom_session: number | null
  form_id: string
  answers: Record<string, unknown>
  attempt_no: number
  submitted_at: string
}

export type LearningPageFieldStats = {
  answered: number
  options?: Array<{ label: string; count: number }>
  average?: number | null
  min?: number | null
  max?: number | null
  recent?: Array<{ student: string; value: string; submitted_at: string }>
}

export type LearningPageResponseSummary = {
  page: LearningPage
  summary: {
    submission_count: number
    student_count: number
    form_count: number
    class_student_count?: number
    completed_student_count?: number
    started_student_count?: number
    pending_student_count?: number
    completion_rate?: number
  }
  scope?: {
    classroom_session: { id: number; title: string; status: string; status_label: string }
    class_group: { id: number; name: string; grade: string }
  }
  students?: Array<{
    student: { id: number; username: string; display_name: string }
    student_no: string
    current_layer: string
    status: 'completed' | 'started' | 'pending'
    status_label: string
    submitted_form_count: number
    form_count: number
    submission_count: number
    last_submitted_at: string | null
  }>
  forms: Array<{
    form_id: string
    title: string
    submission_count: number
    student_count: number
    fields: Array<{ id: string; label: string; type: LearningPageFieldType; stats: LearningPageFieldStats }>
  }>
  responses: LearningPageResponse[]
}

export function getTeacherLearningPages(lessonId: number) {
  return apiRequest<LearningPage[]>(`/api/v1/teacher/lessons/${lessonId}/learning-pages/`)
}

export function generateTeacherLearningPage(lessonId: number, direction: string, generationMode: LearningPageGenerationMode = 'auto') {
  return apiRequest<LearningPage>(`/api/v1/teacher/lessons/${lessonId}/learning-pages/`, {
    method: 'POST',
    body: toJsonBody({ direction, generation_mode: generationMode })
  })
}

export function reviseTeacherLearningPage(pageId: number, direction: string, generationMode: LearningPageGenerationMode = 'auto') {
  return apiRequest<LearningPage>(`/api/v1/teacher/learning-pages/${pageId}/revise/`, {
    method: 'POST',
    body: toJsonBody({ direction, generation_mode: generationMode })
  })
}

export function getTeacherLearningPageResponses(pageId: number, classroomSessionId?: number) {
  const query = classroomSessionId ? `?classroom_session=${classroomSessionId}` : ''
  return apiRequest<LearningPageResponseSummary>(`/api/v1/teacher/learning-pages/${pageId}/responses/${query}`)
}

export function getLearningPage(pageId: number, presentation: 'embedded' | 'popout' | 'unknown' = 'unknown') {
  return apiRequest<LearningPage>(`/api/v1/learning-pages/${pageId}/?presentation=${presentation}`)
}

export function submitLearningPageForm(pageId: number, formId: string, answers: Record<string, unknown>) {
  return apiRequest<LearningPageResponse>(`/api/v1/student/learning-pages/${pageId}/submit/`, {
    method: 'POST',
    body: toJsonBody({ form_id: formId, answers })
  })
}

export function trackLearningPageBlock(
  pageId: number,
  payload: { blockId: string; blockType: LearningPageBlock['type']; visibleMs: number; visibilityRatio: number }
) {
  return apiRequest<Record<string, never>>(`/api/v1/student/learning-pages/${pageId}/blocks/viewed/`, {
    method: 'POST',
    body: toJsonBody({
      block_id: payload.blockId,
      block_type: payload.blockType,
      visible_ms: payload.visibleMs,
      visibility_ratio: payload.visibilityRatio
    })
  })
}
