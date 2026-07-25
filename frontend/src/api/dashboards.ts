import { apiRequest } from './client'

export type Metric = {
  label: string
  value: number
  sub: string
}

export type SeriesPoint = {
  label: string
  count: number
}

export type CountSlice = {
  label: string
  value: string
  count: number
}

export type SuperAdminDashboard = {
  metrics: Metric[]
  status: Record<string, number>
  charts: {
    school_status: CountSlice[]
    import_status: CountSlice[]
    account_roles: CountSlice[]
    learning_events_7d: SeriesPoint[]
    training_jobs_7d: SeriesPoint[]
    school_students: SeriesPoint[]
    school_classes: SeriesPoint[]
  }
  recent_imports: Array<Record<string, unknown>>
  recent_logs: Array<Record<string, unknown>>
  status_rows: Array<{ label: string; count: number; level: string; path: string }>
}

export type SchoolAdminDashboard = {
  school: { id: number; name: string; code: string }
  metrics: Metric[]
  login_series: SeriesPoint[]
  event_series: SeriesPoint[]
  charts: {
    account_roles: CountSlice[]
    account_status: CountSlice[]
    student_onboarding: CountSlice[]
    student_class_status: CountSlice[]
    class_status: CountSlice[]
    class_students: SeriesPoint[]
    class_teachers: SeriesPoint[]
    class_activity: SeriesPoint[]
    teacher_load: SeriesPoint[]
    event_types: CountSlice[]
    pretest_status: CountSlice[]
    pretest_completion: CountSlice[]
    training_status: CountSlice[]
    login_series: SeriesPoint[]
    event_series: SeriesPoint[]
    active_students_7d: SeriesPoint[]
  }
  recent_classes: Array<Record<string, unknown>>
  status_rows: Array<{ label: string; count: number; level: string; detail: string; path: string }>
}

export function getSuperAdminDashboard() {
  return apiRequest<SuperAdminDashboard>('/api/v1/super-admin/dashboard/')
}

export function getSchoolAdminDashboard() {
  return apiRequest<SchoolAdminDashboard>('/api/v1/school-admin/dashboard/')
}
