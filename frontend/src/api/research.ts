import { apiRequest, toJsonBody } from './client'

export type SelectOption = { value: string; label: string }

export type ResearchOptions = {
  stages: SelectOption[]
  design_types: SelectOption[]
  gates: SelectOption[]
  gate_decisions: SelectOption[]
  arms: SelectOption[]
  allocation_methods: SelectOption[]
  run_modes: SelectOption[]
  subjects: Array<{ id: number; name: string }>
  courses: Array<{ id: number; title: string; subject_id: number }>
  classes: Array<{ id: number; name: string; grade: string }>
  required_gates: Record<string, string[]>
}

export type ResearchGate = {
  id: number
  gate: string
  gate_label: string
  sequence_no: number
  decision: string
  decision_label: string
  evidence_ref: string
  note: string
  content_hash: string
  decided_by: string
  decided_at: string
}

export type ResearchCohort = {
  id: number
  class_group_id: number
  class_group_name: string
  arm: string
  arm_label: string
  allocation_method: string
  allocation_method_label: string
  allocation_unit_code: string
  development_site: boolean
  prior_policy_access: boolean
  content_hash: string
  assigned_at: string
}

export type ResearchRun = {
  id: number
  run_code: string
  mode: string
  mode_label: string
  status: 'planned' | 'active' | 'paused' | 'closed' | 'data_locked'
  status_label: string
  decision_effect: boolean
  automatic_action_enabled: boolean
  planned_start: string | null
  planned_end: string | null
  activated_at: string | null
  closed_at: string | null
  data_lock: null | {
    id: number
    decision_as_of: string
    data_cutoff: string
    row_count: number
    dataset_hash: string
    content_hash: string
    locked_at: string
  }
}

export type ResearchProtocol = {
  id: number
  version_no: number
  stage: string
  stage_label: string
  design_type: string
  design_type_label: string
  content_hash: string
  policy_hash: string
  protocol?: Record<string, unknown>
  policy_snapshot?: Record<string, unknown>
  ethics_approval_ref: string
  ethics_approved_at: string | null
  preregistration_ref: string
  preregistered_at: string | null
  consent_required?: boolean
  consent_plan?: string
  registered_at: string
  required_gates: SelectOption[]
  approved_gates: string[]
  missing_gates: SelectOption[]
  cohort_count: number
  run_count: number
  gate_decisions?: ResearchGate[]
  cohort_assignments?: ResearchCohort[]
  runs?: ResearchRun[]
}

export type ResearchStudy = {
  id: number
  code: string
  title: string
  description: string
  status: string
  status_label: string
  subject_id: number | null
  subject_name: string
  course_id: number | null
  course_title: string
  current_protocol_id: number | null
  current_protocol: ResearchProtocol | null
  protocol_versions?: ResearchProtocol[]
  created_at: string
  updated_at: string
}

const root = '/api/v1/school-admin/research'

export const getResearchOptions = () => apiRequest<ResearchOptions>(`${root}/options/`)
export const getResearchStudies = () => apiRequest<ResearchStudy[]>(`${root}/studies/`)
export const getResearchStudy = (id: number) => apiRequest<ResearchStudy>(`${root}/studies/${id}/`)

export const createResearchStudy = (payload: Record<string, unknown>) => (
  apiRequest<ResearchStudy>(`${root}/studies/`, { method: 'POST', body: toJsonBody(payload) })
)

export const registerResearchProtocol = (studyId: number, payload: Record<string, unknown>) => (
  apiRequest<ResearchProtocol>(`${root}/studies/${studyId}/register/`, { method: 'POST', body: toJsonBody(payload) })
)

export const recordResearchGate = (protocolId: number, payload: Record<string, unknown>) => (
  apiRequest<ResearchGate>(`${root}/protocols/${protocolId}/gates/`, { method: 'POST', body: toJsonBody(payload) })
)

export const freezeResearchCohort = (protocolId: number, payload: Record<string, unknown>) => (
  apiRequest<ResearchCohort>(`${root}/protocols/${protocolId}/cohorts/`, { method: 'POST', body: toJsonBody(payload) })
)

export const createResearchRun = (protocolId: number, payload: Record<string, unknown>) => (
  apiRequest<ResearchRun>(`${root}/protocols/${protocolId}/runs/`, { method: 'POST', body: toJsonBody(payload) })
)

export const activateResearchRun = (runId: number) => (
  apiRequest<ResearchRun>(`${root}/runs/${runId}/activate/`, { method: 'POST', body: '{}' })
)

export const closeResearchRun = (runId: number) => (
  apiRequest<ResearchRun>(`${root}/runs/${runId}/close/`, { method: 'POST', body: '{}' })
)

export const lockResearchRunData = (runId: number, payload: Record<string, unknown>) => (
  apiRequest<ResearchRun>(`${root}/runs/${runId}/data-lock/`, { method: 'POST', body: toJsonBody(payload) })
)

export const researchProtocolExportUrl = (protocolId: number) => `${root}/protocols/${protocolId}/export/`
