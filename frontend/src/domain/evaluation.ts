export type EvaluationNotAssessedReasonCode =
  | 'no_evidence'
  | 'not_observed'
  | 'not_applicable'
  | 'technical_issue'
  | 'other'

export type EvaluationNotAssessedEntry = {
  reason: EvaluationNotAssessedReasonCode
  reason_label?: string
  note: string
}

export type EvaluationCriterionDisplay = {
  id: string
  title: string
  description: string
  level_descriptions?: string[]
  skip_condition?: string
}

export const evaluationNotAssessedOptions: Array<{
  value: EvaluationNotAssessedReasonCode
  label: string
}> = [
  { value: 'no_evidence', label: '缺少作品或答案' },
  { value: 'not_observed', label: '本节未安排或未观察到' },
  { value: 'not_applicable', label: '不适用于当前任务' },
  { value: 'technical_issue', label: '技术或数据问题' },
  { value: 'other', label: '其他' }
]
