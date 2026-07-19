import { apiRequest, toJsonBody } from './client'

export type MeasurementChoice = {
  value: string
  label: string
  teacher_enabled?: boolean
}

export type MeasurementCourse = {
  id: number
  title: string
  subject: { id: number; name: string }
  is_active: boolean
}

export type MeasurementOptions = {
  courses: MeasurementCourse[]
  uses: MeasurementChoice[]
  validation_statuses: MeasurementChoice[]
  rubric_modules: MeasurementChoice[]
  cognitive_complexities: MeasurementChoice[]
}

export type MeasurementVersion = {
  id: number
  version_no: number
  content_hash: string
  validation_status: string
  validation_status_label: string
  published_by: string
  published_at: string
}

export type BlueprintClaim = {
  code: string
  title: string
  description: string
}

export type BlueprintEvidence = {
  code: string
  claim_codes: string[]
  description: string
  source_types: string[]
}

export type BlueprintTask = {
  code: string
  title: string
  evidence_codes: string[]
  description: string
}

export type BlueprintPayload = {
  course: number | string
  title: string
  task_version: string
  target_population: string
  course_goal: string
  claims: BlueprintClaim[]
  evidence_rules: BlueprintEvidence[]
  task_specifications: BlueprintTask[]
  content_coverage: string[]
  cognitive_complexity: string[]
  allowed_supports: string[]
  scoring_model: { approach: string; decision_rule: string }
  next_formative_action: string
}

export type BlueprintRow = {
  id: number
  title: string
  subject: { id: number; name: string }
  course: { id: number; title: string } | null
  intended_use: string
  intended_use_label: string
  task_version: string
  claim_count: number
  evidence_count: number
  task_count: number
  validation_status: string
  validation_status_label: string
  latest_version: MeasurementVersion | null
  target_population?: string
  course_goal?: string
  claims?: BlueprintClaim[]
  evidence_rules?: BlueprintEvidence[]
  task_specifications?: BlueprintTask[]
  content_coverage?: string[]
  cognitive_complexity?: string[]
  allowed_supports?: string[]
  scoring_model?: { approach?: string; decision_rule?: string }
  next_formative_action?: string
  versions?: MeasurementVersion[]
  created_at: string
  updated_at: string
}

export type RubricAnchorExample = {
  level: number
  title: string
  evidence_summary: string
  artifact_reference: string
}

export type RubricCriterion = {
  code: string
  module: string
  title: string
  evaluation_object: string
  evidence_sources: string[]
  observable_evidence: string
  not_assessed_condition: string
  allowed_supports: string[]
  counter_examples: string[]
  anchors: Record<string, string>
  anchor_examples: RubricAnchorExample[]
  next_formative_action: string
}

export type RubricPayload = {
  blueprint: number | string
  title: string
  evaluation_object: string
  criteria: RubricCriterion[]
}

export type RubricRow = {
  id: number
  title: string
  blueprint: { id: number; title: string }
  subject: { id: number; name: string }
  course: { id: number; title: string } | null
  intended_use: string
  intended_use_label: string
  evaluation_object: string
  criterion_count: number
  validation_status: string
  validation_status_label: string
  latest_version: MeasurementVersion | null
  criteria?: RubricCriterion[]
  versions?: MeasurementVersion[]
  created_at: string
  updated_at: string
}

export function getMeasurementOptions() {
  return apiRequest<MeasurementOptions>('/api/v1/teacher/measurement/options/')
}

export function getBlueprints() {
  return apiRequest<BlueprintRow[]>('/api/v1/teacher/measurement/blueprints/')
}

export function getBlueprint(id: number) {
  return apiRequest<BlueprintRow>(`/api/v1/teacher/measurement/blueprints/${id}/`)
}

export function saveBlueprint(payload: BlueprintPayload, id?: number) {
  return apiRequest<BlueprintRow>(
    id ? `/api/v1/teacher/measurement/blueprints/${id}/` : '/api/v1/teacher/measurement/blueprints/',
    {
      method: id ? 'PATCH' : 'POST',
      body: toJsonBody(payload)
    }
  )
}

export function publishBlueprint(id: number) {
  return apiRequest<BlueprintRow>(`/api/v1/teacher/measurement/blueprints/${id}/publish/`, {
    method: 'POST',
    body: toJsonBody({})
  })
}

export function getRubrics() {
  return apiRequest<RubricRow[]>('/api/v1/teacher/measurement/rubrics/')
}

export function getRubric(id: number) {
  return apiRequest<RubricRow>(`/api/v1/teacher/measurement/rubrics/${id}/`)
}

export function saveRubric(payload: RubricPayload, id?: number) {
  return apiRequest<RubricRow>(
    id ? `/api/v1/teacher/measurement/rubrics/${id}/` : '/api/v1/teacher/measurement/rubrics/',
    {
      method: id ? 'PATCH' : 'POST',
      body: toJsonBody(payload)
    }
  )
}

export function publishRubric(id: number) {
  return apiRequest<RubricRow>(`/api/v1/teacher/measurement/rubrics/${id}/publish/`, {
    method: 'POST',
    body: toJsonBody({})
  })
}
