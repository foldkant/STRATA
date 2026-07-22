import { apiRequest, queryString, toJsonBody, uploadRequest } from './client'

export type CurriculumDocumentType = 'curriculum_plan' | 'subject_standard'
export type CurriculumSchoolStage = 'k1_k9' | 'k10_k12'
export type CurriculumNodeType =
  | 'core_competency'
  | 'course_objective'
  | 'course_content'
  | 'academic_quality'

export type CurriculumVersionStatus = 'draft' | 'review_pending' | 'reviewed' | 'published' | 'archived' | 'discarded'

export type CurriculumExtractionStatus = 'pending' | 'completed' | 'needs_ocr' | 'failed'
export type CurriculumPageQualityStatus = 'complete' | 'empty' | 'low_confidence' | 'failed'
export type CurriculumPageReviewStatus = 'needs_review' | 'reviewed'

export type CurriculumProcessingJobStatus =
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'cancelling'
  | 'cancelled'
export type CurriculumProcessingJobMode = 'auto' | 'ocr'
export type CurriculumProcessingJobPriority = 'high' | 'normal' | 'low'

export type CurriculumProcessingJob = {
  id: number
  version: number
  version_label: string
  standard: number
  standard_title: string
  subject_name: string
  task_type: 'pdf_text_extraction'
  mode: CurriculumProcessingJobMode
  mode_label?: string
  priority: CurriculumProcessingJobPriority
  priority_label?: string
  status: CurriculumProcessingJobStatus
  status_label: string
  stage: string
  stage_label: string
  progress_current: number
  progress_total: number
  progress_percent: number
  resource_limit: Record<string, unknown>
  requested_by: number | null
  created_by_display: string
  cancel_requested_by_display?: string
  celery_task_id: string
  retry_of: number | null
  retry_count: number
  can_retry: boolean
  can_cancel: boolean
  worker_hostname?: string
  heartbeat_at?: string | null
  cancel_requested_at?: string | null
  error_code: string
  error_message: string
  result_summary: Record<string, unknown>
  created_at: string
  started_at: string | null
  finished_at: string | null
  updated_at: string
}

export type CurriculumProcessingJobChoice<T extends string> = {
  value: T
  label: string
}

export type CurriculumProcessingJobSummary = Record<CurriculumProcessingJobStatus | 'total' | 'active', number>

export type CurriculumProcessingJobsIndex = {
  jobs: CurriculumProcessingJob[]
  summary: CurriculumProcessingJobSummary
  statuses: Array<CurriculumProcessingJobChoice<CurriculumProcessingJobStatus>>
  priorities: Array<CurriculumProcessingJobChoice<CurriculumProcessingJobPriority>>
  modes: Array<CurriculumProcessingJobChoice<CurriculumProcessingJobMode>>
}

export type CurriculumNode = {
  id: number
  version?: number
  node_type: CurriculumNodeType
  node_type_label?: string
  code: string
  title: string
  content: string
  parent: number | null
  source_page_start: number
  source_page_end: number
  source_paragraph?: string
  sort_order: number
  version_id?: number
  version_label?: string
  standard_id?: number
  standard_title?: string
  subject_code?: string
  subject_name?: string
  school_stage?: CurriculumSchoolStage
  source_url?: string
  pdf_url?: string
  content_hash?: string
  curriculum_version_hash?: string
}

export type CurriculumAuditLog = {
  id: number
  version?: number | null
  action: string
  actor: string
  detail: Record<string, unknown>
  created_at: string
}

export type CurriculumNodeTrace = CurriculumNode & {
  source_pages: CurriculumStandardPage[]
  curriculum_standard: {
    id: number
    title: string
    record_title?: string
    document_type: CurriculumDocumentType
    school_stage: CurriculumSchoolStage
    school_stage_label?: string
    subject_code: string
    subject_name: string
  }
  curriculum_version: {
    id: number
    version_label: string
    publication_year: number | null
    issued_by: string
    source_url: string
    status: CurriculumVersionStatus
    status_label: string
    content_hash: string
    pdf_sha256?: string
    pdf_size_bytes?: number
    pdf_url: string
  }
}

export type CurriculumStandardVersion = {
  id: number
  standard?: number
  title: string
  official_title?: string
  record_title?: string
  version_label: string
  publication_year: number | null
  effective_year: number | null
  issued_by: string
  source_url: string
  source_note?: string
  pdf_url: string
  pdf_sha256?: string
  pdf_size_bytes?: number
  pdf_page_count: number
  structured_text?: string
  structured_format?: string
  structured_text_sha256?: string
  extraction_status?: CurriculumExtractionStatus
  extraction_status_label?: string
  extraction_message?: string
  extraction_engine: string
  extraction_engine_version: string
  extraction_config: Record<string, unknown>
  extracted_at: string | null
  content_hash: string
  status: CurriculumVersionStatus
  status_label: string
  replaces_version: number | null
  nodes?: CurriculumNode[]
  node_count?: number
  review_note?: string
  audit_logs?: CurriculumAuditLog[]
  created_by?: string
  submitted_by?: string
  reviewed_by?: string
  published_by?: string
  archived_by?: string
  submitted_at?: string | null
  reviewed_at?: string | null
  published_at?: string | null
  archived_at?: string | null
  page_count?: number
  text_char_count?: number
  page_quality_counts?: Partial<Record<CurriculumPageQualityStatus, number>>
  unreviewed_page_count?: number
  structured_markdown_url?: string
  structured_jsonl_url?: string
  independent_review?: boolean | null
  independent_publication?: boolean | null
  governance_waiver_note?: string
  created_at?: string
  updated_at?: string
}

export type CurriculumStandard = {
  id: number
  title: string
  document_type: CurriculumDocumentType
  document_type_label?: string
  school_stage: CurriculumSchoolStage
  school_stage_label?: string
  subject_code: string
  subject_name: string
  current_version: CurriculumStandardVersion | null
  versions?: CurriculumStandardVersion[]
  version_count?: number
  is_active?: boolean
  audit_logs?: CurriculumAuditLog[]
  created_at: string
  updated_at: string
}

export type CurriculumStandardPayload = {
  title: string
  document_type: CurriculumDocumentType
  school_stage: CurriculumSchoolStage
  subject_code: string
  subject_name: string
}

export type CurriculumVersionPayload = {
  version_label: string
  publication_year: number | null
  effective_year: number | null
  issued_by: string
  official_title: string
  source_url: string
  source_note: string
  structured_text?: string
  pdf_file?: File | null
  replaces_version?: number | null
}

export type CurriculumNodePayload = {
  node_type: CurriculumNodeType
  code: string
  title: string
  content: string
  parent: number | null
  source_page_start: number
  source_page_end: number
  source_paragraph: string
  sort_order: number
}

export type CurriculumReferenceStandard = Omit<CurriculumStandard, 'current_version' | 'created_at' | 'updated_at'> & {
  current_version: CurriculumStandardVersion
  versions?: CurriculumStandardVersion[]
}

export type CurriculumReferenceOptions = {
  standards: CurriculumReferenceStandard[]
}

export type CurriculumStandardsIndex = {
  standards: CurriculumStandard[]
  school_stages: Array<{ value: CurriculumSchoolStage; label: string }>
  document_types: Array<{ value: CurriculumDocumentType; label: string }>
  version_statuses: Array<{ value: CurriculumVersionStatus; label: string }>
  node_types: Array<{ value: CurriculumNodeType; label: string }>
}

export type CurriculumStandardPage = {
  id: number
  page_number: number
  text: string
  char_count: number
  extraction_method: 'embedded_text' | 'ocr' | 'manual'
  extraction_method_label: string
  mean_confidence: number | null
  quality_status: CurriculumPageQualityStatus
  quality_status_label: string
  quality_message: string
  review_status: CurriculumPageReviewStatus
  review_status_label: string
  reviewed_by: string
  reviewed_at: string | null
  content_hash: string
}

export type CurriculumStandardPages = {
  version: { id: number; title: string; version_label: string; content_hash: string }
  pages: CurriculumStandardPage[]
}

export type CurriculumVersionComparisonItem = {
  id: number
  node_type: CurriculumNodeType
  title: string
  content_hash: string
  source_page_start: number
  source_page_end: number
  source_paragraph: string
}

export type CurriculumVersionComparison = {
  standard_id: number
  standard_title: string
  from_version: { id: number; version_label: string; content_hash: string; pdf_sha256: string; structured_text_sha256: string }
  to_version: { id: number; version_label: string; content_hash: string; pdf_sha256: string; structured_text_sha256: string }
  metadata_changes: Array<{ field: string; before: string | number | null; after: string | number | null }>
  content_item_counts: Record<'added' | 'removed' | 'modified' | 'unchanged', number>
  content_items: Array<{
    code: string
    change_type: 'added' | 'removed' | 'modified' | 'unchanged'
    before: CurriculumVersionComparisonItem | null
    after: CurriculumVersionComparisonItem | null
  }>
}

const superAdminBase = '/api/v1/super-admin'

export function getCurriculumStandards(params: {
  q?: string
  document_type?: CurriculumDocumentType | ''
  school_stage?: CurriculumSchoolStage | ''
  subject_code?: string
} = {}) {
  return apiRequest<CurriculumStandardsIndex>(
    `${superAdminBase}/curriculum-standards/${queryString(params)}`
  )
}

export function getCurriculumStandard(id: number) {
  return apiRequest<CurriculumStandard>(`${superAdminBase}/curriculum-standards/${id}/`)
}

export function saveCurriculumStandard(payload: CurriculumStandardPayload, id?: number) {
  return apiRequest<CurriculumStandard>(
    id ? `${superAdminBase}/curriculum-standards/${id}/` : `${superAdminBase}/curriculum-standards/`,
    {
      method: id ? 'PATCH' : 'POST',
      body: toJsonBody(payload)
    }
  )
}

export function setCurriculumStandardActive(id: number, isActive: boolean) {
  return apiRequest<CurriculumStandard>(`${superAdminBase}/curriculum-standards/${id}/`, {
    method: 'PATCH',
    body: toJsonBody({ is_active: isActive })
  })
}

function versionFormData(payload: CurriculumVersionPayload, includePdf = true) {
  const form = new FormData()
  form.append('version_label', payload.version_label)
  if (payload.publication_year !== null) form.append('publication_year', String(payload.publication_year))
  if (payload.effective_year !== null) form.append('effective_year', String(payload.effective_year))
  form.append('issued_by', payload.issued_by)
  form.append('official_title', payload.official_title)
  form.append('source_url', payload.source_url)
  form.append('source_note', payload.source_note)
  if (payload.structured_text !== undefined) form.append('structured_text', payload.structured_text)
  if (includePdf && payload.pdf_file) form.append('pdf_file', payload.pdf_file)
  if (payload.replaces_version) form.append('replaces_version', String(payload.replaces_version))
  return form
}

export function createCurriculumStandardVersion(standardId: number, payload: CurriculumVersionPayload) {
  return uploadRequest<CurriculumStandardVersion>(
    `${superAdminBase}/curriculum-standards/${standardId}/versions/`,
    versionFormData(payload)
  )
}

export function getCurriculumStandardVersion(id: number) {
  return apiRequest<CurriculumStandardVersion>(`${superAdminBase}/curriculum-standard-versions/${id}/`)
}

export function saveCurriculumStandardVersion(id: number, payload: CurriculumVersionPayload) {
  return uploadRequest<CurriculumStandardVersion>(
    `${superAdminBase}/curriculum-standard-versions/${id}/`,
    versionFormData(payload, false),
    'PATCH'
  )
}

export function discardCurriculumStandardVersion(id: number) {
  return apiRequest<null>(`${superAdminBase}/curriculum-standard-versions/${id}/`, {
    method: 'DELETE'
  })
}

export function publishCurriculumStandardVersion(id: number) {
  return apiRequest<CurriculumStandardVersion>(
    `${superAdminBase}/curriculum-standard-versions/${id}/publish/`,
    { method: 'POST', body: toJsonBody({}) }
  )
}

export function submitCurriculumStandardVersionReview(id: number) {
  return apiRequest<CurriculumStandardVersion>(
    `${superAdminBase}/curriculum-standard-versions/${id}/submit-review/`,
    { method: 'POST', body: toJsonBody({}) }
  )
}

export function reviewCurriculumStandardVersion(id: number, approved: boolean, note: string) {
  return apiRequest<CurriculumStandardVersion>(
    `${superAdminBase}/curriculum-standard-versions/${id}/review/`,
    { method: 'POST', body: toJsonBody({ approved, note }) }
  )
}

export function archiveCurriculumStandardVersion(id: number) {
  return apiRequest<CurriculumStandardVersion>(
    `${superAdminBase}/curriculum-standard-versions/${id}/archive/`,
    { method: 'POST', body: toJsonBody({}) }
  )
}

export function restoreCurriculumStandardVersion(id: number) {
  return apiRequest<CurriculumStandardVersion>(
    `${superAdminBase}/curriculum-standard-versions/${id}/restore/`,
    { method: 'POST', body: toJsonBody({}) }
  )
}

export function getCurriculumStandardPages(id: number, params: {
  q?: string
  quality_status?: CurriculumPageQualityStatus | ''
  review_status?: CurriculumPageReviewStatus | ''
} = {}) {
  return apiRequest<CurriculumStandardPages>(
    `/api/v1/curriculum-standard-versions/${id}/pages/${queryString(params)}`
  )
}

export function saveCurriculumStandardPage(id: number, text: string) {
  return apiRequest<CurriculumStandardPage>(
    `${superAdminBase}/curriculum-standard-pages/${id}/`,
    { method: 'PATCH', body: toJsonBody({ text }) }
  )
}

export function reviewCurriculumStandardPages(id: number, pageIds?: number[]) {
  return apiRequest<{ reviewed_page_count: number; version: CurriculumStandardVersion }>(
    `${superAdminBase}/curriculum-standard-versions/${id}/pages/review/`,
    {
      method: 'POST',
      body: toJsonBody(pageIds ? { page_ids: pageIds } : {})
    }
  )
}

export function compareCurriculumStandardVersions(fromId: number, toId: number) {
  return apiRequest<CurriculumVersionComparison>(
    `/api/v1/curriculum-standard-versions/compare/${queryString({ from_id: fromId, to_id: toId })}`
  )
}

export function createCurriculumNode(versionId: number, payload: CurriculumNodePayload) {
  return apiRequest<CurriculumNode>(
    `${superAdminBase}/curriculum-standard-versions/${versionId}/nodes/`,
    { method: 'POST', body: toJsonBody(payload) }
  )
}

export function saveCurriculumNode(id: number, payload: CurriculumNodePayload) {
  return apiRequest<CurriculumNode>(
    `${superAdminBase}/curriculum-standard-nodes/${id}/`,
    { method: 'PATCH', body: toJsonBody(payload) }
  )
}

export function deleteCurriculumNode(id: number) {
  return apiRequest<Record<string, never>>(
    `${superAdminBase}/curriculum-standard-nodes/${id}/`,
    { method: 'DELETE' }
  )
}

export function getCurriculumReferenceOptions(params: {
  subject_code?: string
  subject_name?: string
  school_stage?: CurriculumSchoolStage | ''
  node_type?: CurriculumNodeType | ''
  include_history?: boolean
} = {}) {
  return apiRequest<CurriculumReferenceOptions>(
    `/api/v1/curriculum-standards/reference-options/${queryString({
      ...params,
      include_history: params.include_history ? 1 : undefined
    })}`
  )
}

export function getCurriculumNodeReference(id: number) {
  return apiRequest<CurriculumNodeTrace>(`/api/v1/curriculum-standard-nodes/${id}/`)
}

export function getCurriculumProcessingJobs(params: {
  status?: CurriculumProcessingJobStatus | ''
  version?: number
  standard?: number
} = {}) {
  return apiRequest<CurriculumProcessingJobsIndex>(
    `${superAdminBase}/curriculum-processing-jobs/${queryString(params)}`
  )
}

export function createCurriculumProcessingJob(
  versionId: number,
  payload: {
    mode: CurriculumProcessingJobMode
    priority: CurriculumProcessingJobPriority
  }
) {
  return apiRequest<CurriculumProcessingJob>(
    `${superAdminBase}/curriculum-standard-versions/${versionId}/processing-jobs/`,
    { method: 'POST', body: toJsonBody(payload) }
  )
}

export function cancelCurriculumProcessingJob(id: number) {
  return apiRequest<CurriculumProcessingJob>(
    `${superAdminBase}/curriculum-processing-jobs/${id}/cancel/`,
    { method: 'POST', body: toJsonBody({}) }
  )
}

export function retryCurriculumProcessingJob(id: number) {
  return apiRequest<CurriculumProcessingJob>(
    `${superAdminBase}/curriculum-processing-jobs/${id}/retry/`,
    { method: 'POST', body: toJsonBody({}) }
  )
}
