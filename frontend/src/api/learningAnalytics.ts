import { apiRequest, queryString, toJsonBody } from './client'

export type LearningSummaryMetrics = {
  opportunities: {
    assigned_count: number
    required_count: number
    eligible_count: number
    started_count: number
    submitted_count: number
    graded_count: number
    withdrawn_count: number
    excused_count: number
    unavailable_count: number
  }
  completion_rate: number | null
  on_time_rate: number | null
  score: {
    graded_item_count: number
    score_raw: number
    score_max: number
    score_rate: number | null
  }
  resources: { assigned_count: number; opened_count: number; opened_rate: number | null }
  participation: { interaction_count: number; point_delta: number }
  evaluation: Record<'self' | 'peer' | 'teacher', {
    submission_count: number
    rated_item_count: number
    not_assessed_item_count: number
    average_stars: number | null
  }>
  quality: { event_count: number; flagged_event_count: number; flagged_event_rate: number }
}

export type LearningSummaryRow = {
  id: number
  student: {
    id: number
    username: string
    display_name: string
    student_no: string
    class_group: { id: number; name: string; grade: string }
  }
  subject: { id: number; name: string }
  course: { id: number; title: string }
  window_type: 'day' | '7d' | '30d' | 'unit'
  window_type_label: string
  period_key: string
  window_start: string
  window_end: string
  data_status: 'available' | 'insufficient' | 'no_opportunity' | 'quality_blocked'
  data_status_label: string
  metrics: LearningSummaryMetrics
  missing_data: string[]
  generated_at: string
}

export type LearningSummaryResponse = {
  window: string
  window_end: string | null
  rows: LearningSummaryRow[]
}

export type StratificationSuggestionRow = {
  id: number
  student: { id: number; username: string; display_name: string; student_no: string }
  class_group: { id: number; name: string; grade: string }
  subject: { id: number; name: string } | null
  course: { id: number; title: string } | null
  previous_layer: string
  suggested_layer: string
  confidence: number
  reasons: string[]
  missing_data: string[]
  learning_summary: { summary_id?: number; data_status?: string; metrics?: LearningSummaryMetrics; index?: number | null }
  support_suggestion: string
  window_start: string | null
  window_end: string | null
  status: string
  status_label: string
  teacher_selected_layer: string
  review_note: string
  reviewed_by: string
  reviewed_at: string | null
  created_at: string
}

const baseUrl = '/api/v1/teacher/analytics'

export function getLearningSummaries(params: { window: string; class_group?: number | string; course?: number | string }) {
  return apiRequest<LearningSummaryResponse>(`${baseUrl}/learning-summaries/${queryString(params)}`)
}

export function learningSummariesExportUrl(params: { window: string; class_group?: number | string; course?: number | string }) {
  return `${baseUrl}/learning-summaries/export/${queryString(params)}`
}

export function refreshLearningSummaries(payload: { as_of?: string; course?: number | string }) {
  return apiRequest<{ summaries: number; suggestions: number; as_of: string }>(`${baseUrl}/learning-summaries/refresh/`, {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function getStratificationSuggestions(params: { status?: string; class_group?: number | string; course?: number | string }) {
  return apiRequest<StratificationSuggestionRow[]>(`${baseUrl}/stratification/${queryString(params)}`)
}

export function reviewStratificationSuggestion(id: number, payload: { action: 'accept' | 'keep' | 'adjust' | 'defer'; layer?: string; note?: string }) {
  return apiRequest<StratificationSuggestionRow>(`${baseUrl}/stratification/${id}/review/`, {
    method: 'POST',
    body: toJsonBody(payload)
  })
}
