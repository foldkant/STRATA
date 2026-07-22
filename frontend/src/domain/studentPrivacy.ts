export const studentHiddenFieldNames = new Set([
  'current_layer',
  'current_layer_label',
  'current_group_no',
  'target_layer',
  'target_layer_label',
  'target_layers',
  'layer_scores',
  'use_layer_scores',
  'is_layered',
  'layer_hint',
  'grouping_strategy',
  'grouping_strategy_label',
  'content_band',
  'delivered_band',
  'candidate_band',
  'confidence',
  'risk_probability',
  'model_reason',
  'model_explanation'
])

const displayFieldSuffixes = ['name', 'title', 'label', 'filename', 'file_name', 'attachment_name']
const abilityLabelPattern = /(?:^|[\s_\-（(])(?:A|B|C)\s*层|低水平组|高水平组|同层组|异层组/i

function hidesAbilityLabel(key: string, value: unknown) {
  return typeof value === 'string'
    && displayFieldSuffixes.some((suffix) => key.toLowerCase().endsWith(suffix))
    && abilityLabelPattern.test(value)
}

export function findStudentPrivacyViolations(value: unknown, path = ''): string[] {
  if (Array.isArray(value)) {
    return value.flatMap((item, index) => findStudentPrivacyViolations(item, path ? `${path}[${index}]` : `[${index}]`))
  }
  if (!value || typeof value !== 'object') return []

  const violations: string[] = []
  for (const [key, nested] of Object.entries(value as Record<string, unknown>)) {
    const nestedPath = path ? `${path}.${key}` : key
    if (studentHiddenFieldNames.has(key) || hidesAbilityLabel(key, nested)) {
      violations.push(nestedPath)
    } else {
      violations.push(...findStudentPrivacyViolations(nested, nestedPath))
    }
  }
  return violations
}

export function sanitizeStudentPayload<T>(value: T): T {
  if (Array.isArray(value)) return value.map((item) => sanitizeStudentPayload(item)) as T
  if (!value || typeof value !== 'object') return value

  const sanitized: Record<string, unknown> = {}
  for (const [key, nested] of Object.entries(value as Record<string, unknown>)) {
    if (studentHiddenFieldNames.has(key) || hidesAbilityLabel(key, nested)) continue
    sanitized[key] = sanitizeStudentPayload(nested)
  }
  return sanitized as T
}

export function isStudentApiUrl(url: string): boolean {
  return /^\/api\/v1\/student(?:\/|$)/.test(url)
}
