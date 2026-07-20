import { apiRequest, toJsonBody } from './client'

export type QualityLevel = 'green' | 'amber' | 'red'
export type PipelineStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'blocked'

export type QualityThresholds = {
  amber?: number
  red?: number
  direction?: 'high' | 'low'
}

export type QualityMetric = {
  key: string
  label: string
  value: number
  level: QualityLevel
  thresholds: QualityThresholds
}

export type QualityIssue = {
  code: string
  level: QualityLevel
  metric: string
  value: number
  threshold: number
}

export type DataQualityReport = {
  id: number
  report_id: string
  status: QualityLevel
  status_label: string
  checks_passed: boolean
  window_start: string
  window_end: string
  check_version: string
  source_checksum: string
  event_count: number
  receive_attempt_count: number
  rejected_event_count: number
  unconverted_old_event_count: number
  unlinked_old_event_count: number
  metrics: QualityMetric[]
  counts: Record<string, number | string | boolean | null>
  issues: QualityIssue[]
  generated_at: string
  pipeline_run_id: number
}

export type AnalyticsTaskRun = {
  id: number
  task_id: string
  task_name: string
  task_label: string
  status: string
  status_label: string
  attempt_no: number
  metrics: Record<string, unknown>
  error_code: string
  error_message: string
  started_at: string | null
  finished_at: string | null
}

export type AnalyticsPipelineRun = {
  id: number
  run_id: string
  status: PipelineStatus
  status_label: string
  trigger: string
  trigger_label: string
  attempt_no: number
  window_start: string
  window_end: string
  check_version: string
  summary: Record<string, unknown>
  error_code: string
  error_message: string
  started_at: string | null
  finished_at: string | null
  created_at: string
  tasks: AnalyticsTaskRun[]
}

export type SchoolDataQuality = {
  school: { id: number; name: string; code: string }
  current: DataQualityReport | null
  history: DataQualityReport[]
  runs: AnalyticsPipelineRun[]
}

export function getSchoolDataQuality() {
  return apiRequest<SchoolDataQuality>('/api/v1/school-admin/analytics/quality/')
}

export function runSchoolDataQuality(days = 7) {
  return apiRequest<{ run: AnalyticsPipelineRun; task_id: string }>(
    '/api/v1/school-admin/analytics/quality/run/',
    { method: 'POST', body: toJsonBody({ days }) }
  )
}

export type AnalysisSummary = {
  feature_definition_count: number
  model_input_feature_count: number
  audit_feature_count: number
  decision_point_count: number
  snapshot_count: number
  ready_snapshot_count: number
  observed_outcome_count: number
  pending_outcome_count: number
  dataset_count: number
  comparison_ready_dataset_count: number
}

export type AnalysisDecisionPoint = {
  id: number
  decision_id: string
  title: string
  class_group: { id: number; name: string }
  subject: { id: number; name: string }
  course: { id: number; title: string } | null
  purpose: string
  purpose_label: string
  status: 'planned' | 'frozen' | 'cancelled'
  status_label: string
  scheduled_for: string
  frozen_at: string | null
  student_count: number
  quality_checks_passed: boolean
  snapshot_counts: Record<'ready' | 'degraded' | 'blocked', number>
  outcome_counts: Record<'pending' | 'observed' | 'unobserved' | 'excluded', number>
}

export type AnalysisDataset = {
  id: number
  dataset_id: string
  dataset_key: string
  subject: { id: number; name: string }
  outcome: { key: string; label: string; version: string }
  feature_set: { key: string; version: string }
  status: 'building' | 'frozen' | 'failed'
  status_label: string
  decision_start: string
  decision_end: string
  row_count: number
  observed_count: number
  unobserved_count: number
  excluded_count: number
  comparison_ready: boolean
  blockers: string[]
  manifest_hash: string
  created_at: string
  frozen_at: string | null
  is_test_data: boolean
}

export type AnalysisPreparation = {
  school: { id: number; name: string; code: string }
  summary: AnalysisSummary
  feature_set: {
    key: string
    version: string
    label: string
    manifest_hash: string
  } | null
  feature_groups: Array<{ key: string; label: string; count: number }>
  outcome_definitions: Array<{
    id: number
    key: string
    label: string
    version: string
    horizon_days: number
    min_denominator: number
  }>
  decision_points: AnalysisDecisionPoint[]
  datasets: AnalysisDataset[]
  blockers: string[]
  test_data_visible: boolean
  options: {
    classes: Array<{ id: number; name: string; grade: string; student_count: number }>
    courses: Array<{
      id: number
      title: string
      subject: { id: number; name: string }
      teacher_name: string
      class_ids: number[]
    }>
  }
}

export type LongitudinalFeatureResult = {
  feature_key: string
  status: string
  status_label: string
  observation_count: number
  student_count: number
  class_count: number
  total_variance: number | null
  between_variance: number | null
  within_variance: number | null
  intraclass_correlation: number | null
  overall_association: number | null
  within_association: number | null
  between_association: number | null
  interval_low: number | null
  interval_high: number | null
  direction: string
  details: Record<string, unknown>
}

export type LongitudinalRun = {
  id: number
  run_id: string
  dataset_id: number
  dataset_key: string
  subject: { id: number; name: string }
  status: string
  status_label: string
  analysis_version: string
  feature_count: number
  ready_feature_count: number
  row_count: number
  student_count: number
  class_count: number
  manifest: Record<string, unknown>
  manifest_hash: string
  created_at: string
  finished_at: string | null
  feature_results: LongitudinalFeatureResult[]
}

export type ModelEvaluation = {
  id: number
  model_key: string
  validation_key: string
  status: string
  status_label: string
  train_count: number
  test_count: number
  predicted_count: number
  abstained_count: number
  primary_metric: number | null
  rmse: number | null
  mae: number | null
  brier_score: number | null
  calibration_intercept: number | null
  calibration_slope: number | null
  coverage: number | null
  metrics: Record<string, unknown>
  note: string
}

export type NegativeControl = {
  control_key: string
  status: string
  status_label: string
  expected_behavior: string
  observed_metric: number | null
  baseline_metric: number | null
  details: Record<string, unknown>
}

export type ModelComparisonRun = {
  id: number
  run_id: string
  dataset_id: number
  dataset_key: string
  subject: { id: number; name: string }
  status: string
  status_label: string
  comparison_version: string
  target_type: string
  model_keys: string[]
  validation_keys: string[]
  row_count: number
  observed_count: number
  manifest: { blockers?: string[]; [key: string]: unknown }
  model_card: {
    title?: string
    status?: string
    intended_use?: string
    prohibited_use?: string
    limitations?: string[]
    [key: string]: unknown
  }
  manifest_hash: string
  created_at: string
  finished_at: string | null
  evaluations: ModelEvaluation[]
  negative_controls: NegativeControl[]
}

export type ModelValidation = {
  datasets: AnalysisDataset[]
  longitudinal_runs: LongitudinalRun[]
  comparison_runs: ModelComparisonRun[]
  calibration_runs: ClassCalibrationRun[]
  releases: ModelRelease[]
  release_audits: ModelReleaseAudit[]
  test_data_visible: boolean
  rules: {
    model_comparison_is_shadow_only: boolean
    minimum_evaluation_n: number
    model_order: string[]
    validation_order: string[]
  }
}

export type ClassCalibrationRun = {
  id: number
  run_id: string
  dataset_id: number
  dataset_key: string
  comparison_run_id: number
  subject: { id: number; name: string }
  status: string
  status_label: string
  calibration_version: string
  model_key: string
  global_parameters: Record<string, unknown>
  class_parameters: Record<string, unknown>
  model_card: Record<string, unknown>
  manifest: { blockers?: string[]; [key: string]: unknown }
  manifest_hash: string
  artifact_hash: string
  suggestion_count: number
  release: ModelRelease | null
  created_at: string
  finished_at: string | null
}

export type ModelRelease = {
  id: number
  release_id: string
  release_version: number
  status: 'active' | 'superseded' | 'rolled_back'
  status_label: string
  school: { id: number; name: string; code: string }
  subject: { id: number; name: string }
  calibration_run_id: number
  calibration_run_key: string
  model_key: string
  is_test_data: boolean
  previous_release_id: number | null
  package_hash: string
  signing_key_id: string
  manifest: Record<string, unknown>
  released_by: string
  released_at: string
  deactivated_at: string | null
}

export type ModelReleaseAudit = {
  id: number
  action: 'publish' | 'rollback' | 'verify'
  action_label: string
  result: 'succeeded' | 'failed'
  result_label: string
  subject: { id: number; name: string }
  calibration_run_id: number | null
  release_id: number | null
  actor: string
  message: string
  details: Record<string, unknown>
  created_at: string
}

export function getAnalysisPreparation() {
  return apiRequest<AnalysisPreparation>('/api/v1/school-admin/analytics/preparation/?include_test_data=1')
}

export function createAnalysisDecisionPoint(payload: {
  class_id: number
  course_id: number
  title?: string
  scheduled_for?: string
}) {
  return apiRequest<{ decision_point: AnalysisDecisionPoint }>(
    '/api/v1/school-admin/analytics/preparation/decision-points/',
    { method: 'POST', body: toJsonBody(payload) }
  )
}

export function refreshAnalysisOutcomes() {
  return apiRequest<Record<string, number>>(
    '/api/v1/school-admin/analytics/preparation/outcomes/refresh/',
    { method: 'POST', body: toJsonBody({}) }
  )
}

export function createAnalysisDataset(payload: { subject_id: number; outcome_key: string }) {
  return apiRequest<{ dataset: AnalysisDataset }>(
    '/api/v1/school-admin/analytics/preparation/datasets/',
    { method: 'POST', body: toJsonBody(payload) }
  )
}

export function getModelValidation() {
  return apiRequest<ModelValidation>('/api/v1/school-admin/analytics/models/?include_test_data=1')
}

export function createLongitudinalAnalysis(payload: { dataset_id: number }) {
  return apiRequest<{ run: LongitudinalRun }>(
    '/api/v1/school-admin/analytics/models/longitudinal/?include_test_data=1',
    { method: 'POST', body: toJsonBody(payload) }
  )
}

export function createModelComparison(payload: { dataset_id: number }) {
  return apiRequest<{ run: ModelComparisonRun }>(
    '/api/v1/school-admin/analytics/models/compare/?include_test_data=1',
    { method: 'POST', body: toJsonBody(payload) }
  )
}

export function createAdvancedModelComparison(payload: { dataset_id: number }) {
  return apiRequest<{ run: ModelComparisonRun }>(
    '/api/v1/school-admin/analytics/models/compare-advanced/?include_test_data=1',
    { method: 'POST', body: toJsonBody(payload) }
  )
}

export function createClassCalibration(payload: { dataset_id: number }) {
  return apiRequest<{ run: ClassCalibrationRun }>(
    '/api/v1/school-admin/analytics/models/class-calibration/?include_test_data=1',
    { method: 'POST', body: toJsonBody(payload) }
  )
}

export function publishClassCalibration(id: number) {
  return apiRequest<{ release: ModelRelease }>(
    `/api/v1/school-admin/analytics/models/class-calibration/${id}/publish/?include_test_data=1`,
    { method: 'POST', body: toJsonBody({}) }
  )
}

export function rollbackModelRelease(id: number) {
  return apiRequest<{ release: ModelRelease }>(
    `/api/v1/school-admin/analytics/models/releases/${id}/rollback/?include_test_data=1`,
    { method: 'POST', body: toJsonBody({}) }
  )
}

export function verifyModelRelease(id: number) {
  return apiRequest<{ release: ModelRelease; manifest: Record<string, unknown> }>(
    `/api/v1/school-admin/analytics/models/releases/${id}/verify/?include_test_data=1`,
    { method: 'POST', body: toJsonBody({}) }
  )
}

export function modelReleasePackageUrl(id: number) {
  return `/api/v1/school-admin/analytics/models/releases/${id}/package/?include_test_data=1`
}
