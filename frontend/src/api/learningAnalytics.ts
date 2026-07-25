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
  current_layer: string
  current_layer_label: string
  suggested_layer: string
  confidence: number
  reasons: string[]
  missing_data: string[]
  learning_summary: { summary_id?: number; data_status?: string; metrics?: LearningSummaryMetrics; index?: number | null }
  support_suggestion: string
  decision_kind: 'support' | 'content_band' | 'legacy'
  support_priority: '' | 'routine' | 'watch' | 'high'
  recommendation_status: string
  recommendation_status_label: string
  target_state: null | {
    id: number
    learning_target_code: string
    learning_target_name: string
    evidence_status: 'available' | 'partial' | 'insufficient' | 'pending_review' | 'not_observed'
    evidence_status_label: string
    evidence_coverage: number
    uncertainty: number | null
    valid_until: string | null
  }
  target_states: Array<{
    id: number
    learning_target_version_id: number
    learning_target_code: string
    learning_target_name: string
    evidence_status: 'available' | 'partial' | 'insufficient' | 'pending_review' | 'not_observed'
    evidence_coverage: number
    estimate: number | null
    uncertainty: number | null
    valid_until: string | null
    content_hash: string
  }>
  abstain_reason: string
  transition_checks: Record<string, unknown>
  mastery_snapshot_id: number | null
  rule_version: string
  source_label: string
  window_start: string | null
  window_end: string | null
  status: string
  status_label: string
  teacher_selected_layer: string
  review_reason_code: string
  review_reason_label: string
  review_note: string
  reviewed_by: string
  reviewed_at: string | null
  created_at: string
}

export type StratificationOverviewRow = {
  id: number
  student: { id: number; username: string; display_name: string; student_no: string }
  class_group: { id: number; name: string; grade: string }
  current_layer: '' | 'A' | 'B' | 'C'
  current_layer_label: string
  learning: null | {
    data_status: 'available' | 'insufficient' | 'no_opportunity' | 'quality_blocked'
    data_status_label: string
    completion_rate: number | null
    score_rate: number | null
    window_end: string
    course: { id: number; title: string }
  }
  latest_decision: StratificationSuggestionRow | null
}

export type StratificationOverviewResponse = {
  scope: {
    class_group_ids: number[]
    course: { id: number; title: string } | null
  }
  counts: {
    total: number
    A: number
    B: number
    C: number
    unassigned: number
    pending: number
  }
  class_distribution: Array<{
    id: number
    name: string
    grade: string
    A: number
    B: number
    C: number
    unassigned: number
  }>
  rows: StratificationOverviewRow[]
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

export function getStratificationOverview(params: { class_group?: number | string; course?: number | string }) {
  return apiRequest<StratificationOverviewResponse>(`${baseUrl}/stratification/overview/${queryString(params)}`)
}

export function stratificationOverviewExportUrl(params: { class_group?: number | string; course?: number | string }) {
  return `${baseUrl}/stratification/overview/export/${queryString(params)}`
}

export function reviewStratificationSuggestion(id: number, payload: { action: 'accept' | 'keep' | 'adjust' | 'defer'; layer?: string; reason_code?: string; note?: string }) {
  return apiRequest<StratificationSuggestionRow>(`${baseUrl}/stratification/${id}/review/`, {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function bulkReviewStratificationSuggestions(payload: {
  ids: number[]
  action: 'accept' | 'keep' | 'defer'
  reason_code?: string
  note?: string
}) {
  return apiRequest<{ updated_count: number; ids: number[]; action: string }>(`${baseUrl}/stratification/batch-review/`, {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function manuallyAdjustStratification(payload: {
  student: number
  course: number
  source_decision: number
  layer: 'A' | 'B' | 'C'
  reason_code: string
  note?: string
}) {
  return apiRequest<StratificationSuggestionRow>(`${baseUrl}/stratification/manual-adjust/`, {
    method: 'POST',
    body: toJsonBody(payload)
  })
}
