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
