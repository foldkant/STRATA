import { apiRequest, queryString, uploadRequest } from './client'
import type { CountSlice, Metric, SeriesPoint } from './dashboards'

export type CollectionValidation = {
  errors: string[]
  warnings: string[]
  file_count: number
  uncompressed_size: number
  validated_at: string
}

export type CollectionBatch = {
  id: number
  batch_code: string
  source_school_code: string
  source_school: { id: number; name: string } | null
  source_system_version: string
  status: 'uploaded' | 'validated' | 'imported' | 'failed'
  status_label: string
  uploaded_by: string
  uploaded_at: string
  imported_at: string | null
  checksum: string
  log: string
  validation: CollectionValidation | Record<string, never>
  package_name: string
  manifest?: Record<string, unknown>
}

export type CollectionPage = {
  count: number
  page: number
  page_size: number
  results: CollectionBatch[]
  status_counts: CountSlice[]
}

export type CrossSchoolRow = {
  id: number
  name: string
  code: string
  is_test_data: boolean
  status: string
  status_label: string
  teacher_count: number
  student_count: number
  class_count: number
  course_count: number
  events_30d: number
  events_per_student_30d: number
  active_students_7d: number
  active_rate_7d: number
  layer_coverage: number
  collection_count: number
}

export type CrossSchoolAnalysis = {
  scope: {
    include_test_data: boolean
    formal_schools: number
    test_schools: number
  }
  metrics: Metric[]
  charts: {
    school_students: SeriesPoint[]
    school_activity: SeriesPoint[]
    school_active_rate: SeriesPoint[]
    school_layer_coverage: SeriesPoint[]
    layers: CountSlice[]
    event_types: CountSlice[]
    event_series_30d: SeriesPoint[]
    collection_status: CountSlice[]
    training_status: CountSlice[]
  }
  schools: CrossSchoolRow[]
  recent_collections: CollectionBatch[]
}

export type HealthCheck = {
  key: string
  name: string
  status: string
  level: 'ok' | 'warn' | 'failed'
  detail: string
}

export type IncidentRow = {
  id: string
  time: string
  type: string
  target: string
  school: string
  detail: string
  path: string
}

export type AuditLogRow = {
  id: number
  created_at: string
  action: string
  actor: string
  school: string
  target: string
  ip_address: string
  detail: Record<string, unknown>
}

export type SystemHealth = {
  checked_at: string
  metrics: Metric[]
  checks: HealthCheck[]
  incidents: IncidentRow[]
  audit_logs: AuditLogRow[]
}

export function getCollectionBatches(params: {
  q?: string
  status?: string
  page?: number
  page_size?: number
} = {}) {
  return apiRequest<CollectionPage>(`/api/v1/super-admin/collection/${queryString(params)}`)
}

export function uploadCollectionBatch(file: File) {
  const formData = new FormData()
  formData.append('package_file', file)
  return uploadRequest<CollectionBatch>('/api/v1/super-admin/collection/', formData)
}

export function getCollectionBatch(id: number) {
  return apiRequest<CollectionBatch>(`/api/v1/super-admin/collection/${id}/`)
}

export function deleteCollectionBatch(id: number) {
  return apiRequest<Record<string, never>>(`/api/v1/super-admin/collection/${id}/`, { method: 'DELETE' })
}

export function getCrossSchoolAnalysis(includeTestData = false) {
  return apiRequest<CrossSchoolAnalysis>(
    `/api/v1/super-admin/analysis/${queryString({ include_test_data: includeTestData ? 1 : undefined })}`
  )
}

export function getSystemHealth() {
  return apiRequest<SystemHealth>('/api/v1/super-admin/health/')
}
