import { apiRequest } from './client'

export type OnlyOfficePayload = {
  server_url: string
  mode: 'view' | 'edit'
  can_edit: boolean
  config: Record<string, unknown>
}

export function getResourceOfficeConfig(resourceId: number | string, mode: 'view' | 'edit' = 'view') {
  return apiRequest<OnlyOfficePayload>(`/api/v1/resources/${resourceId}/office-config/?mode=${mode}`)
}
