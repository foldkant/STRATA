import { apiRequest, toJsonBody } from './client'
import type { CurriculumNode } from './curriculumStandards'
import type { EvaluationCurriculumAlignment } from '@/domain/evaluation'

export type EvaluationChoice = {
  value: string
  label: string
  enabled?: boolean
}

export type EvaluationReviewStatus = 'draft' | 'reviewed' | 'legacy_unverified'

export type EvaluationAllowedActions = {
  edit: boolean
  review: boolean
  publish: boolean
}

export type EvaluationAtomicMode = 'test' | 'operation' | 'project' | 'artifact' | 'oral_defense'
export type EvaluationTaskMode = EvaluationAtomicMode | 'mixed'
export type EvaluationEvidenceOwnership = 'individual' | 'group' | 'both'

export type EvaluationCourse = {
  id: number
  title: string
  subject: { id: number; name: string; code: string }
  school_stage?: 'k1_k9' | 'k10_k12'
  is_active: boolean
}

export type EvaluationOptions = {
  courses: EvaluationCourse[]
  scopes: EvaluationChoice[]
  review_statuses: EvaluationChoice[]
  dimensions: EvaluationChoice[]
  assessment_modes: EvaluationChoice[]
  evidence_ownerships: EvaluationChoice[]
  material_types: EvaluationChoice[]
  thinking_requirements: EvaluationChoice[]
  plan_versions: EvaluationPlanVersionOption[]
  standard_versions: EvaluationStandardVersionOption[]
  trial_types: EvaluationChoice[]
  trial_statuses: EvaluationChoice[]
  trial_conclusions: EvaluationChoice[]
}

export type EvaluationStandardVersionOption = {
  id: number
  title: string
  version_no: number
  subject: { id: number; name: string }
  course: { id: number; title: string } | null
}

export type EvaluationVersion = {
  id: number
  version_no: number
  content_hash: string
  review_status: EvaluationReviewStatus
  review_status_label: string
  published_by: string
  published_at: string
}

export type LearningGoal = {
  code: string
  title: string
  description: string
  curriculum_node_ids: number[]
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

export type LearningActivity = {
  code: string
  title: string
  goal_codes: string[]
  description: string
}

export type EvaluationTask = {
  code: string
  title: string
  goal_codes: string[]
  activity_codes: string[]
  mode: EvaluationTaskMode
  component_modes: EvaluationAtomicMode[]
  evidence_ownership: EvaluationEvidenceOwnership
  material_types: string[]
  weight: number
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
  learning_activities: LearningActivity[]
  learning_tasks: LearningTask[]
  evaluation_tasks: EvaluationTask[]
  assessment_modes: EvaluationTaskMode[]
  content_scope: string[]
  thinking_requirements: string[]
  support_options: string[]
  scoring_rules: { approach: string; decision_rule: string }
  follow_up_suggestion: string
  curriculum_node_ids: number[]
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
  activity_count: number
  evaluation_task_count: number
  review_status: EvaluationReviewStatus
  review_status_label: string
  reviewed_by: string | null
  reviewed_at: string | null
  allowed_actions: EvaluationAllowedActions
  latest_version: EvaluationVersion | null
  target_students?: string
  learning_goal?: string
  learning_goals?: LearningGoal[]
  evaluation_basis?: EvaluationBasis[]
  learning_activities?: LearningActivity[]
  learning_tasks?: LearningTask[]
  evaluation_tasks?: EvaluationTask[]
  assessment_modes?: EvaluationTaskMode[]
  content_scope?: string[]
  thinking_requirements?: string[]
  support_options?: string[]
  scoring_rules?: { approach?: string; decision_rule?: string }
  follow_up_suggestion?: string
  curriculum_node_ids?: number[]
  curriculum_references?: CurriculumNode[]
  curriculum_reference_count?: number
  versions?: EvaluationVersion[]
  created_at: string
  updated_at: string
}

export type EvaluationPlanVersionOption = {
  id: number
  source_plan_id: number
  title: string
  version_no: number
  content_hash: string
  review_status: EvaluationReviewStatus
  subject: { id: number; name: string }
  course: { id: number; title: string } | null
  learning_goals: LearningGoal[]
  evaluation_tasks: EvaluationTask[]
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
  learning_goal_codes: string[]
  evaluation_task_codes: string[]
  evidence_ownership: EvaluationEvidenceOwnership
  material_types: string[]
  expected_performance: string
  skip_condition: string
  support_options: string[]
  common_problems: string[]
  level_descriptions: Record<string, string>
  scoring_examples: EvaluationScoringExample[]
  follow_up_suggestion: string
}

export type EvaluationStandardPayload = {
  plan_version: number | string
  title: string
  evaluation_target: string
  criteria: EvaluationCriterion[]
}

export type EvaluationStandardRow = {
  id: number
  title: string
  plan: { id: number; title: string }
  plan_version: EvaluationPlanVersionOption | null
  subject: { id: number; name: string }
  course: { id: number; title: string } | null
  scope: string
  scope_label: string
  evaluation_target: string
  criterion_count: number
  ai_assisted?: boolean
  review_status: EvaluationReviewStatus
  review_status_label: string
  reviewed_by: string | null
  reviewed_at: string | null
  allowed_actions: EvaluationAllowedActions
  latest_version: EvaluationVersion | null
  criteria?: EvaluationCriterion[]
  versions?: EvaluationVersion[]
  created_at: string
  updated_at: string
}

export type EvaluationTrialPayload = {
  standard_version: number | string
  record_type: string
  title: string
  status: string
  activity_date: string
  participant_count: number
  agreement_rate: number | string | null
  conclusion: string
  summary: string
  issues: string[]
  action_items: string[]
}

export type EvaluationTrialRow = {
  id: number
  standard_version: EvaluationStandardVersionOption
  record_type: string
  record_type_label: string
  title: string
  status: string
  status_label: string
  activity_date: string
  participant_count: number
  agreement_rate: string | null
  conclusion: string
  conclusion_label: string
  summary: string
  issues: string[]
  action_items: string[]
  created_by: string
  updated_by: string
  completion_hash: string
  completed_by: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
}

export type EvaluationAIDraftStatus =
  | 'queued'
  | 'retrieving_references'
  | 'suggesting_modes'
  | 'generating_draft'
  | 'context_ready'
  | 'references_ready'
  | 'modes_suggested'
  | 'modes_confirmed'
  | 'draft_generated'
  | 'teacher_reviewed'
  | 'saved'
  | 'cancelled'
  | 'failed'

export type EvaluationAIStandardVersionOption = {
  id: number
  title: string
  version_label: string
  school_stage: 'k1_k9' | 'k10_k12'
  subject: { id: number; name: string; code: string }
  /** Courses explicitly matched by the server. Subject ids belong to different domains and must not be compared. */
  compatible_course_ids?: number[]
  content_hash: string
  published_at?: string | null
}

export type EvaluationAIDraftContext = {
  course_id: number
  school_stage: 'k1_k9' | 'k10_k12'
  grade_or_stage: string
  unit_title: string
  curriculum_standard_version_id: number
  course_content: string
  evaluation_purpose: 'entry_diagnostic' | 'formative' | 'summative' | 'project'
}

export type EvaluationAIModeSuggestion = {
  mode: EvaluationTaskMode
  label: string
  rationale: string
  suitable_materials: string[]
  cautions: string[]
  recommended: boolean
}

export type EvaluationAIDraftCheck = {
  code: string
  label: string
  status: 'passed' | 'warning' | 'blocked'
  message: string
}

export type EvaluationAIDraftReviewDecision = {
  item_key: string
  item_type:
    | 'overall'
    | 'learning_goal'
    | 'evaluation_basis'
    | 'learning_activity'
    | 'learning_task'
    | 'evaluation_task'
    | 'evaluation_criterion'
    | 'performance_level'
    | 'scoring_example'
    | 'follow_up_suggestion'
  item_code: string
  decision: 'accepted' | 'modified' | 'removed'
}

export type EvaluationAIStandardDraft = {
  title: string
  evaluation_target: string
  criteria: EvaluationCriterion[]
}

export type EvaluationAICurriculumReference = CurriculumNode & {
  curriculum_version_id?: number
  citation?: {
    chunk_id?: string
    source_locator?: string
    source_content_hash?: string
    source_page_hashes?: string[]
    version_content_hash?: string
    pdf_sha256?: string
    version_label?: string
    official_title?: string
    source_url?: string
  }
}

export type EvaluationAIDraftRow = {
  id: number
  status: EvaluationAIDraftStatus
  status_label: string
  context: EvaluationAIDraftContext
  curriculum_standard_version: EvaluationAIStandardVersionOption | null
  curriculum_references: EvaluationAICurriculumReference[]
  mode_suggestions: EvaluationAIModeSuggestion[]
  confirmed_modes: EvaluationTaskMode[]
  teacher_mode_note: string
  plan_draft: EvaluationPlanPayload | null
  /** Complete draft used to create an editable evaluation standard; it never creates a published version. */
  standard_draft: EvaluationAIStandardDraft | null
  checks: EvaluationAIDraftCheck[]
  background_task?: {
    status: 'queued' | 'running' | 'completed' | 'failed'
    message: string
    progress: number | null
  } | null
  created_at: string
  updated_at: string
}

export type EvaluationAIDraftListResponse = {
  results: EvaluationAIDraftRow[]
  curriculum_standard_versions: EvaluationAIStandardVersionOption[]
  evaluation_purposes: EvaluationChoice[]
}

export type EvaluationAIDraftSaveResult = {
  ai_draft: EvaluationAIDraftRow
  plan: EvaluationPlanRow
  standard: EvaluationStandardRow
  drafts_saved: { plan: true; standard: true }
}

export type LessonStepEvaluationCriterion = {
  id: number
  code: string
  title: string
  dimension: string
  dimension_label: string
  evaluation_target: string
  evaluation_sources: string[]
  expected_performance: string
  level_descriptions: string[]
  skip_condition: string
  support_options: string[]
  common_problems: string[]
  follow_up_suggestion: string
  curriculum_alignment?: EvaluationCurriculumAlignment
}

export type LessonStepEvaluationStandardOption = {
  id: number
  title: string
  version_no: number
  review_status: string
  review_status_label: string
  criterion_count: number
  criteria: LessonStepEvaluationCriterion[]
}

export type LessonStepEvaluationBinding = {
  id: number
  lesson_step: number
  standard_version: number
  standard_title: string
  version_no: number
  enable_self: boolean
  enable_peer: boolean
  enable_teacher: boolean
  locked: boolean
  criteria: LessonStepEvaluationCriterion[]
  created_at: string
  updated_at: string
}

export type LessonStepEvaluationBindingContext = {
  binding: LessonStepEvaluationBinding | null
  standards: LessonStepEvaluationStandardOption[]
  use_boundaries: LessonStepEvaluationUseBoundary[]
}

export type LessonStepEvaluationUseBoundary = {
  code: 'classroom_feedback' | 'learning_state_update' | 'research_and_model'
  label: string
  status: 'available' | 'requires_review' | 'not_direct'
  status_label: string
  description: string
}

export type LessonStepEvaluationBindingPayload = {
  standard_version: number
  enable_self: boolean
  enable_peer: boolean
  enable_teacher: boolean
}

const baseUrl = '/api/v1/teacher/evaluations'
const aiDraftBaseUrl = `${baseUrl}/ai-drafts`

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

export function reviewEvaluationPlan(id: number) {
  return apiRequest<EvaluationPlanRow>(`${baseUrl}/plans/${id}/review-confirm/`, {
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

export function reviewEvaluationStandard(id: number) {
  return apiRequest<EvaluationStandardRow>(`${baseUrl}/standards/${id}/review-confirm/`, {
    method: 'POST',
    body: toJsonBody({})
  })
}

export function getEvaluationTrials() {
  return apiRequest<EvaluationTrialRow[]>(`${baseUrl}/trials/`)
}

export function getEvaluationTrial(id: number) {
  return apiRequest<EvaluationTrialRow>(`${baseUrl}/trials/${id}/`)
}

export function saveEvaluationTrial(payload: EvaluationTrialPayload, id?: number) {
  return apiRequest<EvaluationTrialRow>(id ? `${baseUrl}/trials/${id}/` : `${baseUrl}/trials/`, {
    method: id ? 'PATCH' : 'POST',
    body: toJsonBody(payload)
  })
}

export function deleteEvaluationTrial(id: number) {
  return apiRequest<null>(`${baseUrl}/trials/${id}/`, { method: 'DELETE' })
}

export function evaluationTrialExportUrl() {
  return `${baseUrl}/trials/export/`
}

export function getEvaluationAIDrafts() {
  return apiRequest<EvaluationAIDraftListResponse>(`${aiDraftBaseUrl}/`)
}

export function createEvaluationAIDraft(payload: EvaluationAIDraftContext, idempotencyKey = '') {
  return apiRequest<EvaluationAIDraftRow>(`${aiDraftBaseUrl}/`, {
    method: 'POST',
    headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined,
    body: toJsonBody(payload)
  })
}

export function getEvaluationAIDraft(id: number, signal?: AbortSignal) {
  return apiRequest<EvaluationAIDraftRow>(`${aiDraftBaseUrl}/${id}/`, { signal })
}

export function retrieveEvaluationAIDraftReferences(id: number) {
  return apiRequest<EvaluationAIDraftRow>(`${aiDraftBaseUrl}/${id}/retrieve/`, {
    method: 'POST',
    body: toJsonBody({})
  })
}

export function suggestEvaluationAIDraftModes(id: number) {
  return apiRequest<EvaluationAIDraftRow>(`${aiDraftBaseUrl}/${id}/suggest-modes/`, {
    method: 'POST',
    body: toJsonBody({})
  })
}

export function confirmEvaluationAIDraftModes(
  id: number,
  payload: { modes: EvaluationTaskMode[]; teacher_note: string }
) {
  return apiRequest<EvaluationAIDraftRow>(`${aiDraftBaseUrl}/${id}/confirm-modes/`, {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function generateEvaluationAIDraft(id: number, options: { regenerate?: boolean } = {}) {
  return apiRequest<EvaluationAIDraftRow>(`${aiDraftBaseUrl}/${id}/generate/`, {
    method: 'POST',
    body: toJsonBody(options.regenerate ? { regenerate: true } : {})
  })
}

export function saveEvaluationAIPlanDraft(
  id: number,
  payload: {
    plan_draft: EvaluationPlanPayload
    standard_draft: EvaluationAIStandardDraft
    review_decisions: EvaluationAIDraftReviewDecision[]
  }
) {
  return apiRequest<EvaluationAIDraftSaveResult>(`${aiDraftBaseUrl}/${id}/save-plan-draft/`, {
    method: 'POST',
    body: toJsonBody(payload)
  })
}

export function cancelEvaluationAIDraft(id: number) {
  return apiRequest<EvaluationAIDraftRow>(`${aiDraftBaseUrl}/${id}/cancel/`, {
    method: 'POST',
    body: toJsonBody({})
  })
}

export function getLessonStepEvaluationBinding(stepId: number) {
  return apiRequest<LessonStepEvaluationBindingContext>(
    `${baseUrl}/lesson-steps/${stepId}/binding/`
  )
}

export function saveLessonStepEvaluationBinding(
  stepId: number,
  payload: LessonStepEvaluationBindingPayload
) {
  return apiRequest<LessonStepEvaluationBinding>(
    `${baseUrl}/lesson-steps/${stepId}/binding/`,
    {
      method: 'PATCH',
      body: toJsonBody(payload)
    }
  )
}

export function deleteLessonStepEvaluationBinding(stepId: number) {
  return apiRequest<Record<string, never>>(
    `${baseUrl}/lesson-steps/${stepId}/binding/`,
    { method: 'DELETE' }
  )
}
