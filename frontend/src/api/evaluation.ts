import { apiRequest, toJsonBody } from './client'

export type EvaluationChoice = {
  value: string
  label: string
  enabled?: boolean
}

export type EvaluationCourse = {
  id: number
  title: string
  subject: { id: number; name: string }
  is_active: boolean
}

export type EvaluationOptions = {
  courses: EvaluationCourse[]
  scopes: EvaluationChoice[]
  review_statuses: EvaluationChoice[]
  dimensions: EvaluationChoice[]
  thinking_requirements: EvaluationChoice[]
}

export type EvaluationVersion = {
  id: number
  version_no: number
  content_hash: string
  review_status: string
  review_status_label: string
  published_by: string
  published_at: string
}

export type LearningGoal = {
  code: string
  title: string
  description: string
}

export type EvaluationBasis = {
  code: string
  goal_codes: string[]
  description: string
  source_types: string[]
}

export type LearningTask = {
  code: string
  title: string
  basis_codes: string[]
  description: string
}

export type EvaluationPlanPayload = {
  course: number | string
  title: string
  content_version: string
  target_students: string
  learning_goal: string
  learning_goals: LearningGoal[]
  evaluation_basis: EvaluationBasis[]
  learning_tasks: LearningTask[]
  content_scope: string[]
  thinking_requirements: string[]
  support_options: string[]
  scoring_rules: { approach: string; decision_rule: string }
  follow_up_suggestion: string
}

export type EvaluationPlanRow = {
  id: number
  title: string
  subject: { id: number; name: string }
  course: { id: number; title: string } | null
  scope: string
  scope_label: string
  content_version: string
  goal_count: number
  basis_count: number
  task_count: number
  review_status: string
  review_status_label: string
  latest_version: EvaluationVersion | null
  target_students?: string
  learning_goal?: string
  learning_goals?: LearningGoal[]
  evaluation_basis?: EvaluationBasis[]
  learning_tasks?: LearningTask[]
  content_scope?: string[]
  thinking_requirements?: string[]
  support_options?: string[]
  scoring_rules?: { approach?: string; decision_rule?: string }
  follow_up_suggestion?: string
  versions?: EvaluationVersion[]
  created_at: string
  updated_at: string
}

export type EvaluationScoringExample = {
  level: number
  title: string
  example_description: string
  file_reference: string
}

export type EvaluationCriterion = {
  code: string
  dimension: string
  title: string
  evaluation_target: string
  evaluation_sources: string[]
  expected_performance: string
  skip_condition: string
  support_options: string[]
  common_problems: string[]
  level_descriptions: Record<string, string>
  scoring_examples: EvaluationScoringExample[]
  follow_up_suggestion: string
}

export type EvaluationStandardPayload = {
  plan: number | string
  title: string
  evaluation_target: string
  criteria: EvaluationCriterion[]
}

export type EvaluationStandardRow = {
  id: number
  title: string
  plan: { id: number; title: string }
  subject: { id: number; name: string }
  course: { id: number; title: string } | null
  scope: string
  scope_label: string
  evaluation_target: string
  criterion_count: number
  review_status: string
  review_status_label: string
  latest_version: EvaluationVersion | null
  criteria?: EvaluationCriterion[]
  versions?: EvaluationVersion[]
  created_at: string
  updated_at: string
}

const baseUrl = '/api/v1/school-admin/evaluations'

export function getEvaluationOptions() {
  return apiRequest<EvaluationOptions>(`${baseUrl}/options/`)
}

export function getEvaluationPlans() {
  return apiRequest<EvaluationPlanRow[]>(`${baseUrl}/plans/`)
}

export function getEvaluationPlan(id: number) {
  return apiRequest<EvaluationPlanRow>(`${baseUrl}/plans/${id}/`)
}

export function saveEvaluationPlan(payload: EvaluationPlanPayload, id?: number) {
  return apiRequest<EvaluationPlanRow>(id ? `${baseUrl}/plans/${id}/` : `${baseUrl}/plans/`, {
    method: id ? 'PATCH' : 'POST',
    body: toJsonBody(payload)
  })
}

export function publishEvaluationPlan(id: number) {
  return apiRequest<EvaluationPlanRow>(`${baseUrl}/plans/${id}/publish/`, {
    method: 'POST',
    body: toJsonBody({})
  })
}

export function getEvaluationStandards() {
  return apiRequest<EvaluationStandardRow[]>(`${baseUrl}/standards/`)
}

export function getEvaluationStandard(id: number) {
  return apiRequest<EvaluationStandardRow>(`${baseUrl}/standards/${id}/`)
}

export function saveEvaluationStandard(payload: EvaluationStandardPayload, id?: number) {
  return apiRequest<EvaluationStandardRow>(id ? `${baseUrl}/standards/${id}/` : `${baseUrl}/standards/`, {
    method: id ? 'PATCH' : 'POST',
    body: toJsonBody(payload)
  })
}

export function publishEvaluationStandard(id: number) {
  return apiRequest<EvaluationStandardRow>(`${baseUrl}/standards/${id}/publish/`, {
    method: 'POST',
    body: toJsonBody({})
  })
}
