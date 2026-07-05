export type FieldErrors = Record<string, string[]>

export type ApiEnvelope<T> = {
  data: T
  message: string
  errors?: FieldErrors
}

export class ApiError extends Error {
  status: number
  errors: FieldErrors

  constructor(message: string, status: number, errors: FieldErrors = {}) {
    super(message)
    this.status = status
    this.errors = errors
  }
}

function getCookie(name: string): string {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`))
  return match ? decodeURIComponent(match[1]) : ''
}

export async function apiRequest<T>(url: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  const hasBody = options.body !== undefined
  if (hasBody && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const csrf = getCookie('csrftoken')
  if (csrf) {
    headers.set('X-CSRFToken', csrf)
  }

  const response = await fetch(url, {
    ...options,
    headers,
    credentials: 'include'
  })

  const contentType = response.headers.get('Content-Type') || ''
  const payload = contentType.includes('application/json') ? await response.json() : null

  if (!response.ok) {
    throw new ApiError(payload?.message || '请求失败', response.status, payload?.errors || {})
  }

  return (payload as ApiEnvelope<T>).data
}

export async function uploadRequest<T>(url: string, formData: FormData): Promise<T> {
  const headers = new Headers()
  const csrf = getCookie('csrftoken')
  if (csrf) {
    headers.set('X-CSRFToken', csrf)
  }

  const response = await fetch(url, {
    method: 'POST',
    headers,
    credentials: 'include',
    body: formData
  })

  const contentType = response.headers.get('Content-Type') || ''
  const payload = contentType.includes('application/json') ? await response.json() : null

  if (!response.ok) {
    throw new ApiError(payload?.message || '上传失败', response.status, payload?.errors || {})
  }

  return (payload as ApiEnvelope<T>).data
}

export function toJsonBody(data: unknown): BodyInit {
  return JSON.stringify(data)
}

export function queryString(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, String(value))
    }
  })
  const raw = search.toString()
  return raw ? `?${raw}` : ''
}
