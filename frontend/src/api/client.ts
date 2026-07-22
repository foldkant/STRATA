import { findStudentPrivacyViolations, isStudentApiUrl, sanitizeStudentPayload } from '@/domain/studentPrivacy'

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

const unsafeMethods = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])
let csrfRequest: Promise<string> | null = null

function getCookie(name: string): string {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`))
  return match ? decodeURIComponent(match[1]) : ''
}

async function refreshCsrfToken(): Promise<string> {
  if (!csrfRequest) {
    csrfRequest = fetch('/api/v1/auth/csrf/', {
      method: 'GET',
      credentials: 'include',
      headers: { Accept: 'application/json' }
    })
      .then(async (response) => {
        if (!response.ok) return ''
        await response.json().catch(() => null)
        return getCookie('csrftoken')
      })
      .finally(() => {
        csrfRequest = null
      })
  }
  return csrfRequest
}

async function applyCsrfHeader(headers: Headers, method: string) {
  if (!unsafeMethods.has(method) || headers.has('X-CSRFToken')) return
  const csrf = getCookie('csrftoken') || await refreshCsrfToken()
  if (csrf) {
    headers.set('X-CSRFToken', csrf)
  }
}

function errorMessage(payload: unknown, fallback: string): string {
  if (payload && typeof payload === 'object') {
    const row = payload as Record<string, unknown>
    if (typeof row.message === 'string' && row.message) return row.message
    if (typeof row.detail === 'string' && row.detail) return row.detail
  }
  return fallback
}

function applyStudentPrivacyBoundary<T>(url: string, data: T): T {
  if (!isStudentApiUrl(url)) return data
  const violations = findStudentPrivacyViolations(data)
  if (import.meta.env.DEV && violations.length) {
    console.warn('[student-privacy] Removed internal fields from API response:', violations)
  }
  return violations.length ? sanitizeStudentPayload(data) : data
}

export async function apiRequest<T>(url: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  const method = String(options.method || 'GET').toUpperCase()
  const hasBody = options.body !== undefined
  if (hasBody && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  await applyCsrfHeader(headers, method)

  let response = await fetch(url, {
    ...options,
    headers,
    credentials: 'include'
  })

  if (response.status === 403 && unsafeMethods.has(method)) {
    const csrf = await refreshCsrfToken()
    if (csrf) {
      headers.set('X-CSRFToken', csrf)
      response = await fetch(url, {
        ...options,
        headers,
        credentials: 'include'
      })
    }
  }

  const contentType = response.headers.get('Content-Type') || ''
  const payload = contentType.includes('application/json') ? await response.json() : null

  if (!response.ok) {
    throw new ApiError(errorMessage(payload, '请求失败'), response.status, payload?.errors || {})
  }

  return applyStudentPrivacyBoundary(url, (payload as ApiEnvelope<T>).data)
}

export async function uploadRequest<T>(url: string, formData: FormData, method = 'POST'): Promise<T> {
  const headers = new Headers()
  const normalizedMethod = method.toUpperCase()
  await applyCsrfHeader(headers, normalizedMethod)

  let response = await fetch(url, {
    method: normalizedMethod,
    headers,
    credentials: 'include',
    body: formData
  })

  if (response.status === 403) {
    const csrf = await refreshCsrfToken()
    if (csrf) {
      headers.set('X-CSRFToken', csrf)
      response = await fetch(url, {
        method: normalizedMethod,
        headers,
        credentials: 'include',
        body: formData
      })
    }
  }

  const contentType = response.headers.get('Content-Type') || ''
  const payload = contentType.includes('application/json') ? await response.json() : null

  if (!response.ok) {
    throw new ApiError(errorMessage(payload, '上传失败'), response.status, payload?.errors || {})
  }

  return applyStudentPrivacyBoundary(url, (payload as ApiEnvelope<T>).data)
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
