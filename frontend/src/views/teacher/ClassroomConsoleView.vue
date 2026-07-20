<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, onUnmounted, ref } from 'vue'
import type { EChartsCoreOption } from 'echarts/core'
import { RouterLink, useRoute } from 'vue-router'
import { ApiError } from '@/api/client'
import {
  getTeacherLearningPageResponses,
  type LearningPageResponseSummary
} from '@/api/learningPages'
import {
  closeClassroomActivity,
  closeClassroomGroupCollaboration,
  closeClassroomStep,
  confirmClassroomGroupingCandidate,
  finishClassroomSession,
  generateClassroomGroupingCandidates,
  getClassroomAttendance,
  getClassroomEvaluation,
  getClassroomGroupCollaboration,
  getClassroomGroupingCandidates,
  getClassroomQuickAnswer,
  getClassroomRandomPick,
  getClassroomRandomPickPreview,
  getClassroomSession,
  getClassroomStepProgress,
  getTeacherLessonSteps,
  lockClassroomStep,
  markClassroomAttendance,
  openClassroomStep,
  restartClassroomSession,
  runClassroomCommand,
  scoreClassroomAttachment,
  scoreClassroomQuickAnswer,
  scoreClassroomRandomPick,
  setClassroomEvaluationRuntime,
  setupClassroomGroupCollaboration,
  startClassroomSession,
  submitClassroomTeacherEvaluation,
  type AttendanceStatus,
  type ClassroomActivityRow,
  type ClassroomAttendancePayload,
  type ClassroomAttendanceRow,
  type ClassroomCommandPayload,
  type ClassroomEvaluationConfigPayload,
  type ClassroomEvaluationCriterion,
  type ClassroomEvaluationPayload,
  type ClassroomEvaluationStudentRow,
  type ClassroomEvaluationType,
  type ClassroomGroupCollaborationPayload,
  type ClassroomGroupCollaborationRow,
  type ClassroomGroupRow,
  type GroupingCandidateAssignment,
  type GroupingCandidateRun,
  type ClassroomSessionRow,
  type ClassroomStepProgressAnswer,
  type ClassroomStepProgressPayload,
  type ClassroomStepProgressRow,
  type LessonStepQuestion,
  type LessonStepRow,
  type QuickAnswerPayload,
  type QuickAnswerRow,
  type RandomPickPayload,
  type RandomPickPreviewPayload,
  type RandomPickStudentRow,
  type ResourceBinding,
  type StudentWorkAttachmentRow
} from '@/api/teacher'
import NoticeLine from '@/components/NoticeLine.vue'
import OnlyOfficeEditor from '@/components/OnlyOfficeEditor.vue'
import ResourcePreview from '@/components/ResourcePreview.vue'
import ClassroomChatDock from '@/components/ClassroomChatDock.vue'
import EvaluationRatingInput from '@/components/evaluation/EvaluationRatingInput.vue'
import type { EvaluationNotAssessedEntry } from '@/domain/evaluation'

const EChartPanel = defineAsyncComponent(() => import('@/components/EChartPanel.vue'))
const LearningPageStatsModal = defineAsyncComponent(() => import('@/components/teacher/LearningPageStatsModal.vue'))

const route = useRoute()
const sessionId = computed(() => Number(route.params.sessionId || 0))
const loading = ref(false)
const saving = ref(false)
const notice = ref('')
const session = ref<ClassroomSessionRow | null>(null)
const steps = ref<LessonStepRow[]>([])
const classroomActivities = ref<ClassroomActivityRow[]>([])
const selectedStepId = ref<number | null>(null)
const selectedResourceIndex = ref(0)

const attendanceOpen = ref(false)
const attendanceLoading = ref(false)
const attendanceActivity = ref<ClassroomActivityRow | null>(null)
const attendanceData = ref<ClassroomAttendancePayload | null>(null)
const attendanceFilter = ref<AttendanceStatus | 'all'>('all')

const quickAnswerOpen = ref(false)
const quickAnswerLoading = ref(false)
const quickAnswerActivity = ref<ClassroomActivityRow | null>(null)
const quickAnswerData = ref<QuickAnswerPayload | null>(null)
let quickAnswerPollHandle: number | null = null

const randomPickOpen = ref(false)
const randomPickLoading = ref(false)
const randomPickActivity = ref<ClassroomActivityRow | null>(null)
const randomPickData = ref<RandomPickPayload | RandomPickPreviewPayload | null>(null)
const randomPickAnimating = ref(false)
const randomPickCurrentStudentId = ref<number | null>(null)
const randomPickPickedStudentId = ref<number | null>(null)
let randomPickAnimationHandle: number | null = null
let randomPickTimeoutHandle: number | null = null

const nowTick = ref(Date.now())
const timerDialogOpen = ref(false)
const timerMinutes = ref(5)
const timerSeconds = ref(0)
let timerTickHandle: number | null = null
const broadcastDialogOpen = ref(false)
const broadcastContent = ref('')

const stepProgressLoading = ref(false)
const stepProgressData = ref<ClassroomStepProgressPayload | null>(null)
let stepProgressPollHandle: number | null = null
const questionProgressOpen = ref(false)
const questionProgressQuestionId = ref('')
const attachmentScoringId = ref<number | null>(null)
const attachmentScoreDrafts = ref<Record<number, string>>({})
const attachmentFeedbackDrafts = ref<Record<number, string>>({})
const selectedPreviewAttachment = ref<StudentWorkAttachmentRow | null>(null)
const learningPageProgressOpen = ref(false)
const learningPageProgressLoading = ref(false)
const selectedLearningPageId = ref<number | null>(null)
const selectedLearningPageTitle = ref('')
const learningPageProgressData = ref<LearningPageResponseSummary | null>(null)
let learningPageProgressPollHandle: number | null = null

const groupCollabOpen = ref(false)
const groupCollabLoading = ref(false)
const groupCollaboration = ref<ClassroomGroupCollaborationRow | null>(null)
const activeGroupDocument = ref<ClassroomGroupRow | null>(null)
const groupingRun = ref<GroupingCandidateRun | null>(null)
const groupingCandidateKey = ref('')
const groupingDraft = ref<GroupingCandidateAssignment[]>([])
const groupingLocks = ref<Record<number, boolean>>({})
const groupingNote = ref('')
const draggedGroupingStudentId = ref<number | null>(null)
const groupCollabForm = ref<ClassroomGroupCollaborationPayload>({
  group_size: 4,
  grouping_strategy: 'balanced_layer',
  document_type: 'docx',
  storage_quota_mb: 100,
  allow_student_upload: true,
  allow_onlyoffice_edit: true,
  regenerate: false
})

const evaluationOpen = ref(false)
const evaluationLoading = ref(false)
const evaluationData = ref<ClassroomEvaluationPayload | null>(null)
const evaluationForm = ref<ClassroomEvaluationConfigPayload>({
  enable_self: false,
  enable_peer: false,
  enable_teacher: false,
  self_criteria: [],
  peer_criteria: [],
  teacher_criteria: []
})
const selectedTeacherEvalStudentId = ref<number | null>(null)
const teacherEvaluationRatings = ref<Record<string, number>>({})
const teacherEvaluationNotAssessed = ref<Record<string, EvaluationNotAssessedEntry>>({})
const teacherEvaluationComment = ref('')

const selectedStep = computed(() => steps.value.find((item) => item.id === selectedStepId.value) || steps.value[0] || null)
const currentStep = computed(() => {
  const currentId = session.value?.current_step?.id
  return currentId ? steps.value.find((item) => item.id === currentId) || null : null
})
const activeResources = computed(() => selectedStep.value?.resource_items || [])
const activeLearningPages = computed(() => activeResources.value.filter((item) => (
  item.kind === 'learning_page' && Number(item.learning_page_id || 0) > 0
)))
const activeQuestions = computed(() => selectedStep.value?.question_items || [])
const activeActivities = computed(() => selectedStep.value?.activity_items || [])
const openActivities = computed(() => classroomActivities.value.filter((item) => item.status === 'open'))
const activeTimerActivity = computed(() => openActivities.value.find((item) => item.metadata?.command === 'timer') || null)
const selectedResource = computed<ResourceBinding | null>(() => {
  if (!activeResources.value.length) return null
  return activeResources.value[Math.min(selectedResourceIndex.value, activeResources.value.length - 1)] || null
})
const randomPickStudents = computed(() => randomPickData.value?.students || [])
const randomPickCurrentStudent = computed(() => randomPickStudents.value.find((row) => row.student_id === randomPickCurrentStudentId.value) || null)
const randomPickPickedStudent = computed(() => {
  return randomPickData.value?.picked_student
    || randomPickStudents.value.find((row) => row.student_id === randomPickPickedStudentId.value)
    || null
})
const randomPickDisplayStudent = computed(() => randomPickCurrentStudent.value || randomPickPickedStudent.value)
const selectedStepIndex = computed(() => steps.value.findIndex((item) => item.id === selectedStep.value?.id))
const currentStepIndex = computed(() => steps.value.findIndex((item) => item.id === currentStep.value?.id))
const isCurrentSelected = computed(() => Boolean(selectedStep.value && currentStep.value?.id === selectedStep.value.id))
const canControlStep = computed(() => Boolean(session.value && selectedStep.value && session.value.status !== 'finished'))
const stepStatusText = computed(() => session.value?.current_step_status_label || '未投放')

const classroomStats = computed(() => [
  { label: '班级人数', value: session.value?.class_group?.student_count ?? 0 },
  { label: '学习环节', value: steps.value.length },
  { label: '当前资源', value: activeResources.value.length },
  { label: '当前题目', value: activeQuestions.value.length },
  { label: '进行活动', value: openActivities.value.length }
])
const groupRows = computed(() => groupCollaboration.value?.groups || [])
const selectedGroupingCandidate = computed(() => (
  groupingRun.value?.candidates.find((item) => item.key === groupingCandidateKey.value) || null
))
const groupCollaborationOpenText = computed(() => {
  if (!groupCollaboration.value) return '未开启'
  return `${groupCollaboration.value.status_label} · ${groupCollaboration.value.group_count} 组`
})
const evaluationTypeOptions: Array<{ type: ClassroomEvaluationType; label: string; criteriaKey: keyof ClassroomEvaluationConfigPayload; enabledKey: keyof ClassroomEvaluationConfigPayload }> = [
  { type: 'self', label: '自评', criteriaKey: 'self_criteria', enabledKey: 'enable_self' },
  { type: 'peer', label: '互评', criteriaKey: 'peer_criteria', enabledKey: 'enable_peer' },
  { type: 'teacher', label: '师评', criteriaKey: 'teacher_criteria', enabledKey: 'enable_teacher' }
]
const evaluationSummaryItems = computed(() => evaluationTypeOptions.map((item) => ({
  ...item,
  summary: evaluationData.value?.summary?.[item.type] || null,
  criteria: evaluationCriteria(item.type)
})))
const selectedTeacherEvalStudent = computed(() => {
  const studentId = selectedTeacherEvalStudentId.value
  return evaluationData.value?.students.find((item) => item.student.id === studentId) || null
})
const teacherEvaluationCriteria = computed(() => evaluationForm.value.teacher_criteria)
const evaluationEnabledCount = computed(() => evaluationTypeOptions.filter((item) => Boolean(evaluationForm.value[item.enabledKey])).length)
const runtimeEvaluationEnabled = computed(() => Boolean(evaluationData.value?.runtime_enabled ?? session.value?.evaluation_enabled))
const stepProgressRows = computed(() => stepProgressData.value?.rows || [])
const submittedProgressPercent = computed(() => {
  const summary = stepProgressData.value?.summary
  if (!summary?.total) return 0
  return Math.round((summary.submitted / summary.total) * 100)
})
const submittedProgressStyle = computed(() => ({ width: `${submittedProgressPercent.value}%` }))
const progressSubmittedRows = computed(() => stepProgressRows.value.filter((row) => row.submitted))
const progressPendingRows = computed(() => stepProgressRows.value.filter((row) => !row.submitted))
const selectedProgressQuestion = computed(() => activeQuestions.value.find((item) => item.id === questionProgressQuestionId.value) || null)

function questionTargetsProgressRow(question: LessonStepQuestion, row: ClassroomStepProgressRow) {
  const target = String(question.target_layer || 'all')
  if (target === 'all' || target === 'A/B/C') return true
  const layer = String(row.current_layer || '').trim()
  if (!layer) return false
  return target.split('/').includes(layer)
}

const questionProgressRows = computed(() => {
  const questionId = questionProgressQuestionId.value
  const question = selectedProgressQuestion.value
  if (!questionId || !question) return []
  return stepProgressRows.value
    .filter((row) => questionTargetsProgressRow(question, row))
    .map((row) => ({
      ...row,
      question_answer: row.answers.find((answer) => answer.question_id === questionId) || null
    }))
})
const questionProgressSummary = computed(() => {
  const rows = questionProgressRows.value
  const answers = rows.map((row) => row.question_answer).filter((answer): answer is ClassroomStepProgressAnswer => Boolean(answer))
  const answered = answers.filter((answer) => answer.is_answered).length
  const correct = answers.filter((answer) => answer.is_correct === true).length
  const wrong = answers.filter((answer) => answer.is_correct === false).length
  const fileUploaded = answers.filter((answer) => Boolean(answer.attachment)).length
  const fileScored = answers.filter((answer) => answer.attachment?.score !== null && answer.attachment?.score !== undefined).length
  const pendingReview = answers.filter((answer) => answer.is_answered && !answer.auto_gradable && answer.score === null).length
  return {
    total: rows.length,
    answered,
    unanswered: Math.max(rows.length - answered, 0),
    correct,
    wrong,
    fileUploaded,
    fileScored,
    pendingReview,
  }
})

type ObjectiveQuestionChartRow = {
  label: string
  count: number
  percent: number
  correct: boolean
  unanswered: boolean
}

const objectiveQuestionTypes = ['single', 'multiple', 'judge'] as const
const hasObjectiveProgressChart = computed(() => {
  const type = selectedProgressQuestion.value?.question_type || ''
  return objectiveQuestionTypes.includes(type as typeof objectiveQuestionTypes[number])
})

function answerValues(answer: ClassroomStepProgressAnswer | null) {
  return Array.isArray(answer?.answer_values) ? answer.answer_values.map((item) => String(item).trim()).filter(Boolean) : []
}

const objectiveProgressRows = computed<ObjectiveQuestionChartRow[]>(() => {
  const question = selectedProgressQuestion.value
  if (!question || !hasObjectiveProgressChart.value) return []
  const optionLabels = question.question_type === 'judge'
    ? ['正确', '错误']
    : question.options.map((item) => String(item).trim()).filter(Boolean)
  const labels = optionLabels.length ? optionLabels : question.answer.map((item) => String(item).trim()).filter(Boolean)
  const expected = new Set((question.answer || []).map((item) => String(item).trim()).filter(Boolean))
  const answerRows = questionProgressRows.value
  const counts = new Map(labels.map((label) => [label, 0]))
  let unanswered = 0

  for (const row of answerRows) {
    const answer = row.question_answer
    const values = answerValues(answer)
    if (!answer?.is_answered || values.length === 0) {
      unanswered += 1
      continue
    }
    for (const value of values) {
      if (!counts.has(value)) counts.set(value, 0)
      counts.set(value, Number(counts.get(value) || 0) + 1)
    }
  }

  const denominator = Math.max(answerRows.length, 1)
  const rows = Array.from(counts.entries()).map(([label, count]) => ({
    label,
    count,
    percent: Math.round((count / denominator) * 100),
    correct: expected.has(label),
    unanswered: false
  }))

  rows.push({
    label: '未作答',
    count: unanswered,
    percent: Math.round((unanswered / denominator) * 100),
    correct: false,
    unanswered: true
  })

  return rows
})

const objectiveProgressTotal = computed(() => objectiveProgressRows.value.reduce((sum, row) => sum + row.count, 0))
const objectiveProgressCorrectLabels = computed(() => {
  const labels = objectiveProgressRows.value.filter((row) => row.correct).map((row) => row.label)
  return labels.length ? labels.join('、') : '未设置'
})
const objectiveProgressOption = computed<EChartsCoreOption>(() => {
  const rows = objectiveProgressRows.value
  const hasValue = rows.some((row) => row.count > 0)
  return {
    color: ['#1f6feb'],
    graphic: hasValue
      ? undefined
      : {
          type: 'text',
          left: 'center',
          top: 'middle',
          style: {
            text: '暂无作答数据',
            fill: '#64748b',
            fontSize: 13
          }
        },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter(params: unknown) {
        const item = Array.isArray(params) ? params[0] as { dataIndex?: number } : null
        const row = typeof item?.dataIndex === 'number' ? rows[item.dataIndex] : null
        return row ? `${row.label}<br/>${row.count} 人 · ${row.percent}%${row.correct ? '<br/>正确答案' : ''}` : ''
      }
    },
    grid: {
      top: 12,
      right: 28,
      bottom: 20,
      left: 78,
      containLabel: true
    },
    xAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel: { color: '#64748b', fontSize: 12 },
      splitLine: { lineStyle: { color: '#e2e8f0' } }
    },
    yAxis: {
      type: 'category',
      data: rows.map((row) => row.label),
      axisLabel: { color: '#64748b', fontSize: 12, width: 120, overflow: 'truncate' },
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#d8e1ec' } }
    },
    series: [
      {
        type: 'bar',
        data: rows.map((row) => ({
          value: row.count,
          itemStyle: {
            color: row.unanswered ? '#94a3b8' : row.correct ? '#16a34a' : '#1f6feb',
            borderRadius: [0, 7, 7, 0]
          },
          label: {
            show: true,
            position: 'right',
            color: '#334155',
            fontSize: 12,
            formatter: `${row.count}人 ${row.percent}%`
          }
        })),
        barMaxWidth: 26
      }
    ]
  }
})

const classroomCommands = [
  { command: 'sign_in', label: '签到' },
  { command: 'random_pick', label: '随机点名' },
  { command: 'quick_answer', label: '抢答' },
  { command: 'timer', label: '倒计时' },
  { command: 'broadcast', label: '课堂广播' }
] as const

const attendanceStatusOptions: Array<{ status: Exclude<AttendanceStatus, 'not_signed'>; label: string }> = [
  { status: 'signed', label: '已签到' },
  { status: 'late', label: '迟到' },
  { status: 'leave', label: '请假' },
  { status: 'absent', label: '缺勤' }
]

const quickAnswerScoreActions = [
  { action: 'plus', label: '加分' },
  { action: 'minus', label: '减分' }
] as const

const filteredAttendanceRows = computed(() => {
  const rows = attendanceData.value?.rows || []
  if (attendanceFilter.value === 'all') return rows
  return rows.filter((row) => row.status === attendanceFilter.value)
})

function classLabel() {
  const item = session.value?.class_group
  if (!item) return '-'
  return `${item.grade ? `${item.grade} ` : ''}${item.name}`
}

function resourceTitle(resource: ResourceBinding | null) {
  if (!resource) return ''
  return resource.title || resource.attachment_name || '未命名资源'
}

function statusClass(status: string) {
  if (status === 'running' || status === 'open') return 'status-running'
  if (status === 'locked') return 'status-locked'
  if (status === 'finished' || status === 'closed') return 'status-closed'
  return 'status-draft'
}

function stepBadgeClass(step: LessonStepRow) {
  if (currentStep.value?.id !== step.id) return 'status-draft'
  return statusClass(session.value?.current_step_status || 'idle')
}

function stepRunLabel(step: LessonStepRow) {
  if (currentStep.value?.id !== step.id) return '待投放'
  return stepStatusText.value
}

function questionAnswerSummary(question: LessonStepQuestion) {
  if (!question.answer?.length) return '未设置'
  return question.answer.join('、')
}

function scoreNumber(value: number | string | undefined | null, fallback = 0) {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

function questionScoreSummary(question: LessonStepQuestion) {
  const baseScore = scoreNumber(question.score)
  if (!question.use_layer_scores) return `${baseScore} 分`
  const scores = question.layer_scores || { A: question.score, B: question.score, C: question.score }
  return `A:${scoreNumber(scores.A, baseScore)} / B:${scoreNumber(scores.B, baseScore)} / C:${scoreNumber(scores.C, baseScore)}`
}

function formatDateTime(value: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '-'
}

function timerTotalSeconds(activity: ClassroomActivityRow | null) {
  const total = Number(activity?.metadata?.duration_seconds || 0)
  return Number.isFinite(total) && total > 0 ? total : 0
}

function timerRemainingSeconds(activity: ClassroomActivityRow | null) {
  nowTick.value
  const deadline = String(activity?.metadata?.deadline_at || '')
  const end = deadline ? new Date(deadline).getTime() : 0
  if (!end) return 0
  return Math.max(0, Math.ceil((end - Date.now()) / 1000))
}

function formatTimerClock(seconds: number) {
  const value = Math.max(0, Math.floor(seconds))
  const minutes = Math.floor(value / 60)
  const rest = value % 60
  return `${String(minutes).padStart(2, '0')}:${String(rest).padStart(2, '0')}`
}

function timerProgressStyle(activity: ClassroomActivityRow | null) {
  const total = timerTotalSeconds(activity)
  const left = timerRemainingSeconds(activity)
  const percent = total ? Math.max(0, Math.min(100, (left / total) * 100)) : 0
  return { width: `${percent}%` }
}

function timerIsFinished(activity: ClassroomActivityRow | null) {
  return Boolean(activity) && timerRemainingSeconds(activity) <= 0
}

function metadataText(activity: ClassroomActivityRow) {
  const metadata = activity.metadata || {}
  if (metadata.command === 'random_pick' && metadata.picked_student && typeof metadata.picked_student === 'object') {
    const student = metadata.picked_student as Record<string, unknown>
    return `点名：${String(student.display_name || student.username || '')}`
  }
  if (metadata.command === 'timer') {
    return timerIsFinished(activity) ? '倒计时已结束' : `剩余 ${formatTimerClock(timerRemainingSeconds(activity))}`
  }
  if (metadata.command === 'broadcast') {
    return activity.content
  }
  return ''
}

function activityStats(activity: ClassroomActivityRow) {
  const stats = activity.metadata?.stats
  return stats && typeof stats === 'object' ? stats as Record<string, unknown> : {}
}

function responseCount(activity: ClassroomActivityRow) {
  const value = Number(activityStats(activity).response_count || 0)
  return Number.isFinite(value) ? value : 0
}

function responseNames(activity: ClassroomActivityRow) {
  const responses = activityStats(activity).responses
  if (!Array.isArray(responses)) return ''
  return responses
    .map((item) => {
      if (!item || typeof item !== 'object') return ''
      const row = item as Record<string, unknown>
      return String(row.display_name || row.username || '')
    })
    .filter(Boolean)
    .slice(0, 8)
    .join('、')
}

function isSignInActivity(activity: ClassroomActivityRow) {
  return activity.metadata?.command === 'sign_in'
}

function isQuickAnswerActivity(activity: ClassroomActivityRow) {
  return activity.metadata?.command === 'quick_answer'
}

function isRandomPickActivity(activity: ClassroomActivityRow) {
  return activity.metadata?.command === 'random_pick'
}

function attendanceStatusClass(status: AttendanceStatus) {
  if (status === 'signed') return 'status-active'
  if (status === 'late') return 'status-warning'
  if (status === 'leave') return 'status-locked'
  if (status === 'absent') return 'status-closed'
  return 'status-disabled'
}

function quickAnswerScoreClass(row: QuickAnswerRow) {
  if (row.score_action === 'plus') return 'status-active'
  if (row.score_action === 'minus') return 'status-closed'
  return 'status-disabled'
}

function quickAnswerScoreText(row: QuickAnswerRow) {
  if (row.score === null || row.score === undefined) return '未评分'
  return row.score > 0 ? `+${row.score}` : String(row.score)
}

function randomPickScoreClass(row: RandomPickStudentRow | null) {
  if (!row || row.score === null || row.score === undefined) return 'status-disabled'
  if (row.score_action === 'plus' || row.score > 0) return 'status-active'
  if (row.score_action === 'minus' || row.score < 0) return 'status-closed'
  return 'status-disabled'
}

function randomPickScoreText(row: RandomPickStudentRow | null) {
  if (!row || row.score === null || row.score === undefined) return '未评分'
  return row.score > 0 ? `+${row.score}` : String(row.score)
}

function progressStatusClass(row: ClassroomStepProgressRow) {
  if (!row.submitted) return 'status-disabled'
  if (row.auto_score_max > 0 && row.auto_score !== null && row.auto_score >= row.auto_score_max) return 'status-active'
  if (row.auto_score_max > 0) return 'status-warning'
  return 'status-running'
}

function progressStatusText(row: ClassroomStepProgressRow) {
  if (!row.submitted) return '未提交'
  if (row.auto_score_max > 0 && row.auto_score !== null) return `${row.auto_score}/${row.auto_score_max} 分`
  return '已提交'
}

function answerStatusText(answer: ClassroomStepProgressRow['answers'][number]) {
  if (!answer.is_answered) return '未作答'
  if (answer.question_type === 'file') {
    return answer.attachment?.score !== null && answer.attachment?.score !== undefined ? `已评分 ${answer.attachment.score}` : '待评分'
  }
  if (!answer.auto_gradable) return '待批阅'
  return answer.is_correct ? '正确' : '需订正'
}

function answerStatusClass(answer: ClassroomStepProgressRow['answers'][number]) {
  if (!answer.is_answered) return 'status-disabled'
  if (answer.question_type === 'file') {
    return answer.attachment?.score !== null && answer.attachment?.score !== undefined ? 'status-active' : 'status-running'
  }
  if (!answer.auto_gradable) return 'status-running'
  return answer.is_correct ? 'status-active' : 'status-closed'
}

function studentLayerText(row: ClassroomStepProgressRow) {
  return row.current_layer_label || row.current_layer || '未分层'
}

function formatFileSize(size: number) {
  if (!size) return '0 B'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function syncGroupCollaborationForm(row: ClassroomGroupCollaborationRow | null) {
  if (!row) return
  groupCollabForm.value = {
    group_size: row.group_size,
    grouping_strategy: row.grouping_strategy,
    document_type: row.document_type,
    storage_quota_mb: row.storage_quota_mb,
    allow_student_upload: row.allow_student_upload,
    allow_onlyoffice_edit: row.allow_onlyoffice_edit,
    regenerate: false
  }
}

function cloneGroupingAssignments(assignments: GroupingCandidateAssignment[]) {
  return assignments.map((group) => ({
    group_no: group.group_no,
    members: group.members.map((member) => ({ ...member }))
  }))
}

function selectGroupingCandidate(key: string) {
  const candidate = groupingRun.value?.candidates.find((item) => item.key === key)
  if (!candidate) return
  groupingCandidateKey.value = key
  groupingDraft.value = cloneGroupingAssignments(candidate.assignments)
  groupingLocks.value = Object.fromEntries(
    candidate.assignments.flatMap((group) => group.members.map((member) => [member.student_id, Boolean(member.locked)]))
  )
}

async function loadGroupingCandidates() {
  if (!session.value) return
  try {
    const run = await getClassroomGroupingCandidates(session.value.id)
    groupingRun.value = run
    if (run?.candidates.length) {
      selectGroupingCandidate(run.selected_candidate_key || run.candidates[0].key)
    }
  } catch {
    groupingRun.value = null
  }
}

async function loadGroupCollaboration(silent = false) {
  if (!session.value) return
  if (!silent) groupCollabLoading.value = true
  try {
    const row = await getClassroomGroupCollaboration(session.value.id)
    groupCollaboration.value = row
    syncGroupCollaborationForm(row)
  } catch (error) {
    if (!silent) {
      notice.value = error instanceof ApiError ? error.message : '小组合作信息加载失败。'
    }
  } finally {
    if (!silent) groupCollabLoading.value = false
  }
}

async function openGroupCollaborationPanel() {
  groupCollabOpen.value = true
  await Promise.all([loadGroupCollaboration(), loadGroupingCandidates()])
}

async function saveGroupCollaboration(regenerate = false) {
  if (!session.value) return
  groupCollabLoading.value = true
  notice.value = ''
  try {
    if (regenerate) {
      if (!groupCollaboration.value) {
        notice.value = '请先开启小组合作，再生成分组候选。'
        return
      }
      const lockedAssignments = Object.fromEntries(
        groupingDraft.value.flatMap((group) => group.members
          .filter((member) => groupingLocks.value[member.student_id])
          .map((member) => [String(member.student_id), group.group_no]))
      )
      const run = await generateClassroomGroupingCandidates(session.value.id, {
        ...groupCollabForm.value,
        regenerate: false,
        locked_assignments: lockedAssignments
      })
      groupingRun.value = run
      if (run.candidates.length) selectGroupingCandidate(run.candidates[0].key)
      notice.value = run.candidates.length > 1
        ? '已生成多套分组候选，请检查后确认。'
        : '当前材料只能生成随机候选，请检查后确认。'
      return
    }
    const row = await setupClassroomGroupCollaboration(session.value.id, {
      ...groupCollabForm.value,
      regenerate: false
    })
    groupCollaboration.value = row
    syncGroupCollaborationForm(row)
    notice.value = '小组合作设置已保存。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '小组合作设置保存失败。'
  } finally {
    groupCollabLoading.value = false
  }
}

function moveGroupingStudent(studentId: number, targetGroupNo: number) {
  const source = groupingDraft.value.find((group) => group.members.some((member) => member.student_id === studentId))
  const target = groupingDraft.value.find((group) => group.group_no === targetGroupNo)
  if (!source || !target || source === target || groupingLocks.value[studentId]) return
  const memberIndex = source.members.findIndex((member) => member.student_id === studentId)
  const [member] = source.members.splice(memberIndex, 1)
  target.members.push(member)
}

function onGroupingDragStart(studentId: number) {
  if (groupingLocks.value[studentId]) return
  draggedGroupingStudentId.value = studentId
}

function onGroupingDrop(groupNo: number) {
  if (draggedGroupingStudentId.value !== null) {
    moveGroupingStudent(draggedGroupingStudentId.value, groupNo)
  }
  draggedGroupingStudentId.value = null
}

function groupingStudentGroup(studentId: number) {
  return groupingDraft.value.find((group) => group.members.some((member) => member.student_id === studentId))?.group_no || 1
}

function setGroupingStudentGroup(studentId: number, event: Event) {
  const target = event.target as HTMLSelectElement | null
  if (target) moveGroupingStudent(studentId, Number(target.value))
}

async function confirmGroupingPlan() {
  if (!session.value || !groupingRun.value || !groupingCandidateKey.value) return
  if (!window.confirm('确认启用当前分组？学生将立即切换到新小组，旧小组材料继续保留。')) return
  groupCollabLoading.value = true
  notice.value = ''
  try {
    const studentGroups = Object.fromEntries(
      groupingDraft.value.flatMap((group) => group.members.map((member) => [String(member.student_id), group.group_no]))
    )
    const roles = Object.fromEntries(
      groupingDraft.value.flatMap((group) => group.members.map((member) => [String(member.student_id), member.role]))
    )
    const row = await confirmClassroomGroupingCandidate(session.value.id, groupingRun.value.id, {
      candidate_key: groupingCandidateKey.value,
      adjustments: { student_groups: studentGroups, roles },
      note: groupingNote.value.trim()
    })
    groupCollaboration.value = row
    syncGroupCollaborationForm(row)
    groupingRun.value.selected_candidate_key = groupingCandidateKey.value
    notice.value = '新分组已生效，学生端会立即刷新。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '分组确认失败。'
  } finally {
    groupCollabLoading.value = false
  }
}

async function closeGroupCollaboration() {
  if (!session.value || !groupCollaboration.value) return
  const confirmed = window.confirm('确认关闭本次课堂的小组合作？学生将不能继续编辑小组协作文档或上传共享文件。')
  if (!confirmed) return
  groupCollabLoading.value = true
  try {
    groupCollaboration.value = await closeClassroomGroupCollaboration(session.value.id)
    syncGroupCollaborationForm(groupCollaboration.value)
    notice.value = '小组合作已关闭。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '小组合作关闭失败。'
  } finally {
    groupCollabLoading.value = false
  }
}

function openGroupDocument(group: ClassroomGroupRow) {
  activeGroupDocument.value = group
}

function closeGroupDocument() {
  activeGroupDocument.value = null
}

function groupMembersText(group: ClassroomGroupRow) {
  return group.members.map((member) => member.display_name || member.username).join('、') || '暂无成员'
}

function groupStoragePercent(group: ClassroomGroupRow) {
  const quota = Number(groupCollaboration.value?.storage_quota_mb || 0) * 1024 * 1024
  if (!quota) return 0
  return Math.min(100, Math.round((group.used_storage_bytes / quota) * 100))
}

function groupStorageStyle(group: ClassroomGroupRow) {
  return { width: `${groupStoragePercent(group)}%` }
}

function handleRealtimeClassroomEvent(payload: { type?: string }) {
  if (payload.type === 'grouping.updated' && groupCollabOpen.value) {
    void loadGroupCollaboration(true)
  }
}

function evaluationCriteria(type: ClassroomEvaluationType) {
  const option = evaluationTypeOptions.find((item) => item.type === type)
  if (!option) return []
  return evaluationForm.value[option.criteriaKey] as ClassroomEvaluationCriterion[]
}

function syncEvaluationForm(row: ClassroomEvaluationPayload | null) {
  if (!row) return
  evaluationForm.value = {
    enable_self: row.config.enable_self,
    enable_peer: row.config.enable_peer,
    enable_teacher: row.config.enable_teacher,
    self_criteria: row.config.self_criteria,
    peer_criteria: row.config.peer_criteria,
    teacher_criteria: row.config.teacher_criteria
  }
  if (!selectedTeacherEvalStudentId.value && row.students.length) {
    selectedTeacherEvalStudentId.value = row.students[0].student.id
  }
  syncTeacherEvaluationDraft()
}

async function loadEvaluation(silent = false) {
  if (!session.value) return
  if (!silent) evaluationLoading.value = true
  try {
    const row = await getClassroomEvaluation(session.value.id)
    evaluationData.value = row
    syncEvaluationForm(row)
  } catch (error) {
    if (!silent) {
      notice.value = error instanceof ApiError ? error.message : '课程评价加载失败。'
    }
  } finally {
    if (!silent) evaluationLoading.value = false
  }
}

async function openEvaluationPanel() {
  evaluationOpen.value = true
  await loadEvaluation()
}

async function setRuntimeEvaluationEnabled(enabled: boolean) {
  if (!session.value) return
  evaluationLoading.value = true
  notice.value = ''
  try {
    const row = await setClassroomEvaluationRuntime(session.value.id, enabled)
    evaluationData.value = row
    syncEvaluationForm(row)
    session.value = {
      ...session.value,
      evaluation_enabled: Boolean(row.runtime_enabled),
      evaluation_opened_at: row.runtime_opened_at || session.value.evaluation_opened_at
    }
    notice.value = enabled ? '课堂评价已开启。' : '课堂评价已关闭。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课堂评价开关保存失败。'
  } finally {
    evaluationLoading.value = false
  }
}

function syncTeacherEvaluationDraft(row: ClassroomEvaluationStudentRow | null = selectedTeacherEvalStudent.value) {
  const submission = row?.teacher_submission
  teacherEvaluationRatings.value = submission?.ratings ? { ...submission.ratings } : {}
  teacherEvaluationNotAssessed.value = submission?.not_assessed ? { ...submission.not_assessed } : {}
  teacherEvaluationComment.value = submission?.comment || ''
}

function selectTeacherEvaluationStudent(studentId: number) {
  selectedTeacherEvalStudentId.value = studentId
  const row = evaluationData.value?.students.find((item) => item.student.id === studentId) || null
  syncTeacherEvaluationDraft(row)
}

function setTeacherEvaluationRating(criterionId: string, value: number) {
  const notAssessed = { ...teacherEvaluationNotAssessed.value }
  delete notAssessed[criterionId]
  teacherEvaluationNotAssessed.value = notAssessed
  teacherEvaluationRatings.value = {
    ...teacherEvaluationRatings.value,
    [criterionId]: value
  }
}

function setTeacherEvaluationNotAssessed(criterionId: string, value: EvaluationNotAssessedEntry | null) {
  const ratings = { ...teacherEvaluationRatings.value }
  const notAssessed = { ...teacherEvaluationNotAssessed.value }
  if (value) {
    delete ratings[criterionId]
    notAssessed[criterionId] = value
  } else {
    delete notAssessed[criterionId]
  }
  teacherEvaluationRatings.value = ratings
  teacherEvaluationNotAssessed.value = notAssessed
}

function ratingAverageText(value: number | null | undefined) {
  return value === null || value === undefined ? '暂无' : `${value.toFixed(1)} 星`
}

async function submitTeacherEvaluation() {
  if (!session.value || !selectedTeacherEvalStudent.value) return
  if (!evaluationForm.value.enable_teacher) {
    notice.value = '请先开启师评并保存评价项。'
    return
  }
  for (const criterion of teacherEvaluationCriteria.value) {
    if (!teacherEvaluationRatings.value[criterion.id] && !teacherEvaluationNotAssessed.value[criterion.id]) {
      notice.value = `请为“${criterion.title}”选择星级或暂不评价。`
      return
    }
    const skipped = teacherEvaluationNotAssessed.value[criterion.id]
    if (skipped?.reason === 'other' && !skipped.note.trim()) {
      notice.value = `请填写“${criterion.title}”暂不评价的具体说明。`
      return
    }
  }
  evaluationLoading.value = true
  notice.value = ''
  try {
    const row = await submitClassroomTeacherEvaluation(session.value.id, {
      target: selectedTeacherEvalStudent.value.student.id,
      ratings: teacherEvaluationRatings.value,
      not_assessed: teacherEvaluationNotAssessed.value,
      comment: teacherEvaluationComment.value.trim()
    })
    evaluationData.value = row
    syncEvaluationForm(row)
    const updated = row.students.find((item) => item.student.id === selectedTeacherEvalStudentId.value) || null
    syncTeacherEvaluationDraft(updated)
    notice.value = '师评已保存。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '师评保存失败。'
  } finally {
    evaluationLoading.value = false
  }
}

function openQuestionProgress(question: LessonStepQuestion) {
  if (!isCurrentSelected.value || !currentStep.value) {
    notice.value = '请先投放该环节后再查看题目完成情况。'
    return
  }
  questionProgressQuestionId.value = question.id
  questionProgressOpen.value = true
  selectedPreviewAttachment.value = null
  loadStepProgress()
}

function closeQuestionProgress() {
  questionProgressOpen.value = false
  selectedPreviewAttachment.value = null
}

async function loadLearningPageProgress(silent = false) {
  if (!selectedLearningPageId.value || !session.value) return
  if (!silent) learningPageProgressLoading.value = true
  try {
    learningPageProgressData.value = await getTeacherLearningPageResponses(selectedLearningPageId.value, session.value.id)
  } catch (error) {
    if (!silent) {
      notice.value = error instanceof ApiError ? error.message : 'AI 学习任务单完成情况加载失败。'
    }
  } finally {
    if (!silent) learningPageProgressLoading.value = false
  }
}

function startLearningPageProgressPolling() {
  stopLearningPageProgressPolling()
  learningPageProgressPollHandle = window.setInterval(() => {
    if (learningPageProgressOpen.value) loadLearningPageProgress(true)
  }, 3000)
}

function stopLearningPageProgressPolling() {
  if (learningPageProgressPollHandle === null) return
  window.clearInterval(learningPageProgressPollHandle)
  learningPageProgressPollHandle = null
}

function openLearningPageProgress(resource: ResourceBinding) {
  const pageId = Number(resource.learning_page_id || 0)
  if (!pageId || !session.value) return
  selectedLearningPageId.value = pageId
  selectedLearningPageTitle.value = resource.title || 'AI 学习任务单'
  learningPageProgressData.value = null
  learningPageProgressOpen.value = true
  loadLearningPageProgress()
  startLearningPageProgressPolling()
}

function closeLearningPageProgress() {
  learningPageProgressOpen.value = false
  stopLearningPageProgressPolling()
}

function questionProgressMeta(question: LessonStepQuestion) {
  const base = `${question.question_type_label || question.question_type} · 面向 ${question.target_layer_label || '全体'} · ${questionScoreSummary(question)}`
  if (question.question_type !== 'file') return base
  const config = question.file_config
  const extensions = config?.allowed_extensions?.length ? config.allowed_extensions.map((item) => item.toUpperCase()).join(' / ') : '默认格式'
  return `${base} · ${extensions} · ${config?.max_size_mb || 100}MB`
}

function questionProgressAnswerText(answer: ClassroomStepProgressAnswer | null) {
  if (!answer) return '未提交'
  if (answer.question_type === 'file') return answer.attachment?.attachment_name || '未上传附件'
  return answer.answer_text || (answer.is_answered ? '已作答' : '未作答')
}

function questionProgressStatusClass(answer: ClassroomStepProgressAnswer | null) {
  if (!answer || !answer.is_answered) return 'status-disabled'
  return answerStatusClass(answer)
}

function questionProgressStatusText(answer: ClassroomStepProgressAnswer | null) {
  if (!answer) return '未提交'
  return answerStatusText(answer)
}

function previewAttachment(attachment: StudentWorkAttachmentRow) {
  selectedPreviewAttachment.value = attachment
}

function answerAttachment(answer: ClassroomStepProgressAnswer | null) {
  return answer?.attachment || null
}

function previewAttachmentResource(attachment: StudentWorkAttachmentRow | null) {
  if (!attachment) return null
  return {
    title: attachment.attachment_name || attachment.title,
    attachment_url: attachment.attachment_url,
    attachment_name: attachment.attachment_name,
    file_ext: attachment.file_ext,
    content: attachment.feedback || '学生提交附件'
  }
}

function attachmentScoreDraft(attachment: StudentWorkAttachmentRow) {
  return attachmentScoreDrafts.value[attachment.id] ?? (attachment.score === null || attachment.score === undefined ? '' : String(attachment.score))
}

function setAttachmentScoreDraft(attachment: StudentWorkAttachmentRow, value: string) {
  attachmentScoreDrafts.value = { ...attachmentScoreDrafts.value, [attachment.id]: value }
}

function attachmentFeedbackDraft(attachment: StudentWorkAttachmentRow) {
  return attachmentFeedbackDrafts.value[attachment.id] ?? attachment.feedback ?? ''
}

function setAttachmentFeedbackDraft(attachment: StudentWorkAttachmentRow, value: string) {
  attachmentFeedbackDrafts.value = { ...attachmentFeedbackDrafts.value, [attachment.id]: value }
}

async function saveAttachmentScore(attachment: StudentWorkAttachmentRow) {
  if (!session.value) return
  const score = attachmentScoreDraft(attachment)
  const feedback = attachmentFeedbackDraft(attachment)
  attachmentScoringId.value = attachment.id
  notice.value = ''
  try {
    const saved = await scoreClassroomAttachment(session.value.id, attachment.id, { score, feedback })
    attachmentScoreDrafts.value = { ...attachmentScoreDrafts.value, [attachment.id]: String(saved.score ?? '') }
    attachmentFeedbackDrafts.value = { ...attachmentFeedbackDrafts.value, [attachment.id]: saved.feedback || '' }
    if (selectedPreviewAttachment.value?.id === attachment.id) {
      selectedPreviewAttachment.value = saved
    }
    await loadStepProgress()
    notice.value = '附件评分已保存。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '附件评分保存失败。'
  } finally {
    attachmentScoringId.value = null
  }
}

function refreshActivity(row: ClassroomActivityRow) {
  const others = classroomActivities.value.filter((item) => item.id !== row.id)
  classroomActivities.value = [row, ...others]
}

function syncSelectedStep() {
  const currentId = session.value?.current_step?.id
  selectedStepId.value = currentId && steps.value.some((item) => item.id === currentId)
    ? currentId
    : steps.value[0]?.id || null
  selectedResourceIndex.value = 0
}

async function loadStepProgress(silent = false) {
  if (!session.value) return
  if (!silent) {
    stepProgressLoading.value = true
  }
  try {
    stepProgressData.value = await getClassroomStepProgress(session.value.id)
  } catch (error) {
    if (!silent) {
      notice.value = error instanceof ApiError ? error.message : '完成情况加载失败。'
    }
  } finally {
    if (!silent) {
      stepProgressLoading.value = false
    }
  }
}

function startStepProgressPolling() {
  if (stepProgressPollHandle !== null) return
  stepProgressPollHandle = window.setInterval(() => {
    if (session.value?.status === 'running' && session.value.current_step) {
      loadStepProgress(true)
    }
  }, 2000)
}

function stopStepProgressPolling() {
  if (stepProgressPollHandle === null) return
  window.clearInterval(stepProgressPollHandle)
  stepProgressPollHandle = null
}

async function loadPage() {
  loading.value = true
  notice.value = ''
  try {
    const row = await getClassroomSession(sessionId.value)
    session.value = row
    classroomActivities.value = row.activities || []
    steps.value = row.lesson?.id ? await getTeacherLessonSteps(row.lesson.id) : []
    syncSelectedStep()
    await loadStepProgress(true)
    await loadGroupCollaboration(true)
    await loadEvaluation(true)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课堂控制台加载失败。'
  } finally {
    loading.value = false
  }
}

async function refreshConsole() {
  await loadPage()
  notice.value = '课堂状态已刷新。'
}

async function closeActivity(row: ClassroomActivityRow) {
  saving.value = true
  try {
    const updated = await closeClassroomActivity(row.id)
    classroomActivities.value = classroomActivities.value.map((item) => item.id === updated.id ? updated : item)
    if (quickAnswerActivity.value?.id === updated.id) {
      quickAnswerActivity.value = updated
      stopQuickAnswerPolling()
    }
    if (randomPickActivity.value?.id === updated.id) {
      randomPickActivity.value = updated
      closeRandomPickPanel()
    }
    notice.value = `已关闭：${row.title}`
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课堂活动关闭失败。'
  } finally {
    saving.value = false
  }
}

async function openAttendancePanel(activity?: ClassroomActivityRow) {
  if (!session.value) return
  const target = activity || openActivities.value.find((item) => isSignInActivity(item)) || null
  if (!target) return
  attendanceActivity.value = target
  attendanceOpen.value = true
  attendanceLoading.value = true
  notice.value = ''
  try {
    const data = await getClassroomAttendance(session.value.id, target.id)
    attendanceData.value = data
    attendanceActivity.value = data.activity
    refreshActivity(data.activity)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '签到名单加载失败。'
  } finally {
    attendanceLoading.value = false
  }
}

async function markAttendance(row: ClassroomAttendanceRow, status: Exclude<AttendanceStatus, 'not_signed'>) {
  if (!session.value || !attendanceActivity.value) return
  const label = attendanceStatusOptions.find((item) => item.status === status)?.label || '考勤'
  const note = status === 'signed' ? '' : window.prompt(`请输入 ${row.display_name || row.username} 的${label}备注`, row.note || '') ?? ''
  attendanceLoading.value = true
  try {
    const data = await markClassroomAttendance(session.value.id, attendanceActivity.value.id, {
      student_id: row.student_id,
      status,
      note
    })
    attendanceData.value = data
    attendanceActivity.value = data.activity
    refreshActivity(data.activity)
    notice.value = `${row.display_name || row.username} 已标记为 ${data.rows.find((item) => item.student_id === row.student_id)?.status_label || ''}`
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '签到状态更新失败。'
  } finally {
    attendanceLoading.value = false
  }
}

async function openQuickAnswerPanel(activity?: ClassroomActivityRow) {
  if (!session.value) return
  const target = activity || openActivities.value.find((item) => isQuickAnswerActivity(item)) || null
  if (!target) return
  quickAnswerActivity.value = target
  quickAnswerOpen.value = true
  quickAnswerLoading.value = true
  startQuickAnswerPolling()
  notice.value = ''
  try {
    const data = await getClassroomQuickAnswer(session.value.id, target.id)
    quickAnswerData.value = data
    quickAnswerActivity.value = data.activity
    refreshActivity(data.activity)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '抢答结果加载失败。'
  } finally {
    quickAnswerLoading.value = false
  }
}

async function refreshQuickAnswerPanelSilently() {
  if (!session.value || !quickAnswerOpen.value || !quickAnswerActivity.value || quickAnswerLoading.value) return
  try {
    const data = await getClassroomQuickAnswer(session.value.id, quickAnswerActivity.value.id)
    quickAnswerData.value = data
    quickAnswerActivity.value = data.activity
    refreshActivity(data.activity)
    if (data.activity.status !== 'open') {
      stopQuickAnswerPolling()
    }
  } catch {
    // Temporary realtime fallback before classroom WebSocket push is wired in.
  }
}

function startQuickAnswerPolling() {
  if (quickAnswerPollHandle !== null) return
  quickAnswerPollHandle = window.setInterval(() => {
    refreshQuickAnswerPanelSilently()
  }, 1000)
}

function stopQuickAnswerPolling() {
  if (quickAnswerPollHandle === null) return
  window.clearInterval(quickAnswerPollHandle)
  quickAnswerPollHandle = null
}

function closeQuickAnswerPanel() {
  quickAnswerOpen.value = false
  stopQuickAnswerPolling()
}

async function scoreQuickAnswer(row: QuickAnswerRow, action: 'plus' | 'minus') {
  if (!session.value || !quickAnswerActivity.value || !quickAnswerData.value) return
  const defaults = quickAnswerData.value.score_defaults
  const score = action === 'plus' ? defaults.plus : defaults.minus
  quickAnswerLoading.value = true
  try {
    const data = await scoreClassroomQuickAnswer(session.value.id, quickAnswerActivity.value.id, {
      student_id: row.student_id,
      action,
      score,
      note: action === 'plus' ? '抢答正确，平台默认加分' : '抢答需订正，平台默认减分'
    })
    quickAnswerData.value = data
    quickAnswerActivity.value = data.activity
    refreshActivity(data.activity)
    notice.value = `${row.display_name || row.username} 抢答${action === 'plus' ? '加分' : '减分'}已记录。`
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '抢答评分失败。'
  } finally {
    quickAnswerLoading.value = false
  }
}

function stopRandomPickAnimation() {
  if (randomPickAnimationHandle !== null) {
    window.clearInterval(randomPickAnimationHandle)
    randomPickAnimationHandle = null
  }
  if (randomPickTimeoutHandle !== null) {
    window.clearTimeout(randomPickTimeoutHandle)
    randomPickTimeoutHandle = null
  }
  randomPickAnimating.value = false
}

function closeRandomPickPanel() {
  randomPickOpen.value = false
  stopRandomPickAnimation()
}

async function openRandomPickPanel(activity?: ClassroomActivityRow) {
  if (!session.value) return
  randomPickOpen.value = true
  randomPickLoading.value = true
  stopRandomPickAnimation()
  notice.value = ''
  try {
    if (activity) {
      const data = await getClassroomRandomPick(session.value.id, activity.id)
      randomPickData.value = data
      randomPickActivity.value = data.activity
      randomPickPickedStudentId.value = data.picked_student?.student_id || null
      randomPickCurrentStudentId.value = randomPickPickedStudentId.value
      refreshActivity(data.activity)
    } else {
      const data = await getClassroomRandomPickPreview(session.value.id)
      randomPickData.value = data
      randomPickActivity.value = null
      randomPickPickedStudentId.value = null
      randomPickCurrentStudentId.value = null
    }
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '随机点名名单加载失败。'
    randomPickOpen.value = false
  } finally {
    randomPickLoading.value = false
  }
}

async function commitRandomPick(student: RandomPickStudentRow) {
  if (!session.value) return
  randomPickLoading.value = true
  try {
    const activity = await runClassroomCommand(session.value.id, {
      command: 'random_pick',
      picked_user_id: student.student_id
    })
    refreshActivity(activity)
    const data = await getClassroomRandomPick(session.value.id, activity.id)
    randomPickData.value = data
    randomPickActivity.value = data.activity
    randomPickPickedStudentId.value = data.picked_student?.student_id || student.student_id
    randomPickCurrentStudentId.value = randomPickPickedStudentId.value
    notice.value = `已点名：${data.picked_student?.display_name || student.display_name || student.username}`
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '随机点名投放失败。'
  } finally {
    randomPickLoading.value = false
    randomPickAnimating.value = false
  }
}

function startRandomPickDraw() {
  if (!randomPickData.value || randomPickAnimating.value || randomPickActivity.value) return
  const students = randomPickData.value.students
  if (!students.length) {
    notice.value = '当前班级没有可点名学生。'
    return
  }
  stopRandomPickAnimation()
  randomPickPickedStudentId.value = null
  randomPickAnimating.value = true
  const finalStudent = students[Math.floor(Math.random() * students.length)]
  let index = Math.floor(Math.random() * students.length)
  randomPickCurrentStudentId.value = students[index % students.length].student_id
  randomPickAnimationHandle = window.setInterval(() => {
    randomPickCurrentStudentId.value = students[index % students.length].student_id
    index += 1
  }, 140)
  randomPickTimeoutHandle = window.setTimeout(() => {
    if (randomPickAnimationHandle !== null) {
      window.clearInterval(randomPickAnimationHandle)
      randomPickAnimationHandle = null
    }
    randomPickCurrentStudentId.value = finalStudent.student_id
    randomPickPickedStudentId.value = finalStudent.student_id
    commitRandomPick(finalStudent)
  }, 2600)
}

async function scoreRandomPick(action: 'plus' | 'minus') {
  if (!session.value || !randomPickActivity.value || !randomPickData.value || !randomPickPickedStudent.value) return
  const defaults = randomPickData.value.score_defaults
  const score = action === 'plus' ? defaults.plus : defaults.minus
  randomPickLoading.value = true
  try {
    const data = await scoreClassroomRandomPick(session.value.id, randomPickActivity.value.id, {
      student_id: randomPickPickedStudent.value.student_id,
      action,
      score,
      note: action === 'plus' ? '随机点名回答较好，平台默认加分。' : '随机点名回答需订正，平台默认减分。'
    })
    randomPickData.value = data
    randomPickActivity.value = data.activity
    randomPickPickedStudentId.value = data.picked_student?.student_id || randomPickPickedStudentId.value
    randomPickCurrentStudentId.value = randomPickPickedStudentId.value
    refreshActivity(data.activity)
    notice.value = `${data.picked_student?.display_name || '学生'}随机点名${action === 'plus' ? '加分' : '减分'}已记录。`
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '随机点名评分失败。'
  } finally {
    randomPickLoading.value = false
  }
}

function clampTimerInput(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) return min
  return Math.min(max, Math.max(min, Math.floor(value)))
}

function openTimerDialog() {
  const left = timerRemainingSeconds(activeTimerActivity.value)
  const seed = left > 0 ? left : 300
  timerMinutes.value = Math.floor(seed / 60)
  timerSeconds.value = seed % 60
  timerDialogOpen.value = true
}

function closeTimerDialog() {
  timerDialogOpen.value = false
}

function openBroadcastDialog() {
  broadcastContent.value = ''
  broadcastDialogOpen.value = true
}

function closeBroadcastDialog() {
  if (saving.value) return
  broadcastDialogOpen.value = false
}

function adjustTimerPart(part: 'minutes' | 'seconds', delta: number) {
  if (part === 'minutes') {
    timerMinutes.value = clampTimerInput(Number(timerMinutes.value) + delta, 0, 120)
    return
  }
  let next = Number(timerSeconds.value) + delta
  if (next > 59) {
    next = 0
    timerMinutes.value = clampTimerInput(Number(timerMinutes.value) + 1, 0, 120)
  } else if (next < 0) {
    next = 59
    timerMinutes.value = clampTimerInput(Number(timerMinutes.value) - 1, 0, 120)
  }
  timerSeconds.value = clampTimerInput(next, 0, 59)
}

function normalizeTimerInputs() {
  timerMinutes.value = clampTimerInput(Number(timerMinutes.value), 0, 120)
  timerSeconds.value = clampTimerInput(Number(timerSeconds.value), 0, 59)
}

async function startTimerFromDialog() {
  if (!session.value) return
  normalizeTimerInputs()
  const durationSeconds = timerMinutes.value * 60 + timerSeconds.value
  if (durationSeconds < 1) {
    notice.value = '倒计时时长至少 1 秒。'
    return
  }
  saving.value = true
  try {
    const row = await runClassroomCommand(session.value.id, {
      command: 'timer',
      duration_seconds: durationSeconds
    })
    refreshActivity(row)
    timerDialogOpen.value = false
    notice.value = `倒计时已开始：${formatTimerClock(durationSeconds)}`
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '倒计时启动失败。'
  } finally {
    saving.value = false
  }
}

async function submitBroadcast() {
  if (!session.value) return
  const content = broadcastContent.value.trim()
  if (!content) {
    notice.value = '请填写广播内容。'
    return
  }
  if (content.length > 1000) {
    notice.value = '广播内容不能超过 1000 个字符。'
    return
  }
  saving.value = true
  notice.value = ''
  try {
    const row = await runClassroomCommand(session.value.id, {
      command: 'broadcast',
      content
    })
    refreshActivity(row)
    broadcastDialogOpen.value = false
    broadcastContent.value = ''
    notice.value = '课堂广播已发送。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课堂广播发送失败。'
  } finally {
    saving.value = false
  }
}

async function startSession() {
  if (!session.value) return null
  saving.value = true
  try {
    session.value = await startClassroomSession(session.value.id)
    await loadStepProgress(true)
    notice.value = '课堂已开始。'
    return session.value
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课堂开始失败。'
    return null
  } finally {
    saving.value = false
  }
}

async function runCommand(command: ClassroomCommandPayload['command']) {
  if (!session.value) return
  if (session.value.status !== 'running') {
    notice.value = '请先开始课堂，再使用课堂控制。'
    return
  }
  if (command === 'sign_in') {
    const existing = openActivities.value.find((item) => isSignInActivity(item))
    if (existing) {
      await openAttendancePanel(existing)
      return
    }
  }
  if (command === 'quick_answer') {
    const existing = openActivities.value.find((item) => isQuickAnswerActivity(item))
    if (existing) {
      await openQuickAnswerPanel(existing)
      return
    }
  }
  if (command === 'random_pick') {
    await openRandomPickPanel()
    return
  }
  if (command === 'timer') {
    openTimerDialog()
    return
  }
  if (command === 'broadcast') {
    openBroadcastDialog()
    return
  }
  const payload: ClassroomCommandPayload = { command }
  saving.value = true
  try {
    const row = await runClassroomCommand(session.value.id, payload)
    refreshActivity(row)
    if (command === 'sign_in') {
      await openAttendancePanel(row)
    }
    if (command === 'quick_answer') {
      await openQuickAnswerPanel(row)
    }
    notice.value = `已执行：${classroomCommands.find((item) => item.command === command)?.label || row.title}`
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课堂控制执行失败。'
  } finally {
    saving.value = false
  }
}

async function finishSession() {
  if (!session.value) return
  const confirmed = window.confirm('确认结束当前课堂？结束后当前环节会关闭，学生端不再继续提交。')
  if (!confirmed) return
  saving.value = true
  try {
    session.value = await finishClassroomSession(session.value.id)
    await loadStepProgress(true)
    notice.value = '课堂已结束。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课堂结束失败。'
  } finally {
    saving.value = false
  }
}

async function restartSession() {
  if (!session.value) return
  const confirmed = window.confirm('确认重新开始当前课堂？当前投放环节会清空，学生端进入课堂后会等待教师重新投放。')
  if (!confirmed) return
  saving.value = true
  try {
    session.value = await restartClassroomSession(session.value.id)
    selectedStepId.value = steps.value[0]?.id || null
    selectedResourceIndex.value = 0
    await loadStepProgress(true)
    notice.value = '课堂已重新开始，请选择环节并投放。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课堂重新开始失败。'
  } finally {
    saving.value = false
  }
}

async function publishSelectedStep() {
  if (!session.value || !selectedStep.value) return
  saving.value = true
  notice.value = ''
  try {
    let activeSession = session.value
    if (activeSession.status === 'draft') {
      activeSession = await startClassroomSession(activeSession.id)
    }
    session.value = await openClassroomStep(activeSession.id, selectedStep.value.id)
    await loadStepProgress(true)
    notice.value = `已投放环节：${selectedStep.value.title}`
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '环节投放失败。'
  } finally {
    saving.value = false
  }
}

async function lockCurrentStep() {
  if (!session.value) return
  saving.value = true
  try {
    session.value = await lockClassroomStep(session.value.id)
    await loadStepProgress(true)
    notice.value = '当前环节已锁定提交。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '锁定提交失败。'
  } finally {
    saving.value = false
  }
}

async function closeCurrentStep() {
  if (!session.value) return
  saving.value = true
  try {
    session.value = await closeClassroomStep(session.value.id)
    await loadStepProgress(true)
    notice.value = '当前环节已关闭。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '关闭环节失败。'
  } finally {
    saving.value = false
  }
}

async function publishNextStep() {
  if (!steps.value.length) return
  const baseIndex = currentStepIndex.value >= 0 ? currentStepIndex.value : selectedStepIndex.value
  const next = steps.value[Math.min(baseIndex + 1, steps.value.length - 1)]
  if (!next) return
  selectStep(next)
  await publishSelectedStep()
}

function selectStep(step: LessonStepRow) {
  selectedStepId.value = step.id
  selectedResourceIndex.value = 0
}

onMounted(() => {
  timerTickHandle = window.setInterval(() => {
    nowTick.value = Date.now()
  }, 1000)
  startStepProgressPolling()
  loadPage()
})

onUnmounted(() => {
  stopQuickAnswerPolling()
  stopStepProgressPolling()
  stopRandomPickAnimation()
  stopLearningPageProgressPolling()
  if (timerTickHandle !== null) {
    window.clearInterval(timerTickHandle)
  }
})
</script>

<template>
  <main class="classroom-fullscreen-page teacher-classroom-fullscreen">
    <NoticeLine v-if="notice" :message="notice" />
    <section v-if="loading || !session" class="panel classroom-fullscreen-loading">
      <p class="empty">正在加载课堂控制台</p>
    </section>

    <section v-else class="classroom-console-shell">
      <header class="classroom-console-top classroom-control-header">
        <div>
          <p>{{ session.course?.title || '未绑定课程' }} · {{ session.lesson?.title || '未绑定课时' }} · {{ classLabel() }}</p>
          <h2>{{ session.title }}</h2>
          <span>
            当前环节：{{ currentStep?.title || '未投放' }} · {{ stepStatusText }}
            <template v-if="session.submission_locked"> · 提交已锁定</template>
          </span>
        </div>
        <div class="lesson-designer-actions">
          <RouterLink class="secondary-button" to="/teacher/classroom">课堂列表</RouterLink>
          <RouterLink v-if="session.lesson" class="secondary-button" :to="`/teacher/lessons/${session.lesson.id}/design`">课时设计</RouterLink>
          <button class="secondary-button" type="button" :disabled="loading" @click="refreshConsole">刷新状态</button>
          <button v-if="session.status === 'draft'" class="primary-button" type="button" :disabled="saving" @click="startSession">开始课堂</button>
          <button v-if="session.status === 'running'" class="primary-button danger" type="button" :disabled="saving" @click="finishSession">结束课堂</button>
          <button v-if="session.status === 'finished'" class="primary-button" type="button" :disabled="saving" @click="restartSession">重新开始</button>
        </div>
      </header>

      <section class="classroom-control-strip classroom-command-strip classroom-command-strip-top">
        <button
          v-for="item in classroomCommands"
          :key="item.command"
          type="button"
          :disabled="saving || session.status !== 'running'"
          @click="runCommand(item.command)"
        >
          {{ item.label }}
        </button>
        <button
          type="button"
          :class="{ active: Boolean(groupCollaboration?.is_enabled) }"
          :disabled="saving || session.status === 'finished'"
          @click="openGroupCollaborationPanel"
        >
          小组合作
          <small v-if="groupCollaboration">{{ groupCollaborationOpenText }}</small>
        </button>
        <button
          type="button"
          :class="{ active: runtimeEvaluationEnabled }"
          :disabled="saving || session.status === 'finished'"
          @click="openEvaluationPanel"
        >
          评价情况
          <small v-if="runtimeEvaluationEnabled">已开放</small>
        </button>
      </section>

      <section v-if="activeTimerActivity" class="teacher-timer-banner" :class="{ finished: timerIsFinished(activeTimerActivity) }">
        <div>
          <span>课堂倒计时</span>
          <strong>{{ formatTimerClock(timerRemainingSeconds(activeTimerActivity)) }}</strong>
          <small>{{ timerIsFinished(activeTimerActivity) ? '时间到' : activeTimerActivity.content }}</small>
        </div>
        <div class="timer-progress-track" aria-hidden="true">
          <i :style="timerProgressStyle(activeTimerActivity)"></i>
        </div>
        <button class="secondary-button mini" type="button" :disabled="saving" @click="openTimerDialog">调整时间</button>
      </section>

      <div class="classroom-console-grid classroom-control-grid">
        <aside class="console-pane classroom-step-flow">
          <div class="console-pane-header">
            <div>
              <strong>学习过程</strong>
              <span>{{ steps.length }} 个环节</span>
            </div>
          </div>
          <div class="classroom-step-list">
            <button
              v-for="(step, index) in steps"
              :key="step.id"
              class="classroom-step-run"
              :class="{ active: step.id === selectedStepId, live: currentStep?.id === step.id }"
              type="button"
              @click="selectStep(step)"
            >
              <em>{{ index + 1 }}</em>
              <span>
                <strong>{{ step.title }}</strong>
                <small>{{ step.step_type_label }} · {{ step.estimated_minutes }} 分钟 · {{ step.target_layer_label }}</small>
              </span>
              <i :class="stepBadgeClass(step)">{{ stepRunLabel(step) }}</i>
            </button>
            <p v-if="!steps.length" class="empty">该课堂未指定课时，或课时还没有保存环节。</p>
          </div>
        </aside>

        <main class="console-pane current-step-console classroom-stage-pane">
          <div class="console-pane-header">
            <div>
              <strong>{{ selectedStep?.title || '未选择环节' }}</strong>
              <span>
                {{ selectedStep?.step_type_label || '课堂环节' }}
                <template v-if="selectedStepIndex >= 0"> · 第 {{ selectedStepIndex + 1 }} 个环节</template>
              </span>
            </div>
            <div class="classroom-primary-controls compact-classroom-controls">
              <button class="primary-button" type="button" :disabled="saving || !canControlStep" @click="publishSelectedStep">
                {{ session.status === 'draft' ? '开始并投放' : isCurrentSelected ? '重新投放' : '投放此环节' }}
              </button>
              <button class="secondary-button" type="button" :disabled="saving || session.current_step_status !== 'open'" @click="lockCurrentStep">
                锁定提交
              </button>
              <button class="secondary-button" type="button" :disabled="saving || !session.current_step || session.current_step_status === 'closed'" @click="closeCurrentStep">
                关闭环节
              </button>
              <button class="secondary-button" type="button" :disabled="saving || session.status === 'finished' || !steps.length || currentStepIndex >= steps.length - 1" @click="publishNextStep">
                下一环节
              </button>
            </div>
          </div>

          <section class="classroom-stage-grid">
            <article class="live-preview-area classroom-resource-stage">
              <header>
                <span>资源预览</span>
                <strong>{{ resourceTitle(selectedResource) || '暂无资源' }}</strong>
              </header>
              <div v-if="activeResources.length > 1" class="student-resource-tabs">
                <button
                  v-for="(resource, index) in activeResources"
                  :key="`${resource.id || resource.title}-${index}`"
                  type="button"
                  :class="{ active: selectedResourceIndex === index }"
                  @click="selectedResourceIndex = index"
                >
                  {{ resourceTitle(resource) }}
                </button>
              </div>
              <div class="classroom-resource-preview">
                <ResourcePreview :resource="selectedResource" office-mode="view" />
              </div>
            </article>

            <aside class="classroom-step-task-panel">
              <header>
                <span>本环节任务</span>
                <strong>{{ activeQuestions.length }} 道题 · {{ activeLearningPages.length }} 份 AI 任务单 · {{ activeActivities.length }} 个活动</strong>
              </header>
              <p class="student-instruction">{{ selectedStep?.student_instruction || '教师暂未填写学生可见说明。' }}</p>

              <div v-if="activeQuestions.length" class="classroom-question-list">
                <article v-for="(question, index) in activeQuestions" :key="question.id">
                  <span>
                    {{ question.question_type_label }} · 面向 {{ question.target_layer_label || '全体' }} ·
                    {{ questionScoreSummary(question) }} · {{ question.is_required ? '必答' : '选答' }}
                  </span>
                  <strong>{{ index + 1 }}. {{ question.stem }}</strong>
                  <small v-if="question.options.length">选项：{{ question.options.join(' / ') }}</small>
                  <small v-if="question.question_type !== 'file'">参考答案：{{ questionAnswerSummary(question) }}</small>
                  <small v-else>{{ questionProgressMeta(question) }}</small>
                  <button
                    class="question-progress-button"
                    type="button"
                    :disabled="!isCurrentSelected || !currentStep"
                    @click="openQuestionProgress(question)"
                  >
                    {{ isCurrentSelected && currentStep ? '查看完成情况' : '投放后查看' }}
                  </button>
                </article>
              </div>
              <p v-else-if="!activeLearningPages.length" class="empty">当前环节没有课堂题或 AI 学习任务单。</p>

              <section v-if="activeLearningPages.length" class="classroom-learning-page-list">
                <header><strong>AI 学习任务单</strong><span>{{ activeLearningPages.length }} 份</span></header>
                <article v-for="resource in activeLearningPages" :key="resource.learning_page_id || resource.id">
                  <div>
                    <span>网页任务单 · v{{ resource.revision_no || 1 }}</span>
                    <strong>{{ resource.title }}</strong>
                  </div>
                  <button class="question-progress-button" type="button" @click="openLearningPageProgress(resource)">查看完成情况</button>
                </article>
              </section>

              <div v-if="activeActivities.length" class="classroom-activity-tags">
                <span v-for="activity in activeActivities" :key="activity">{{ activity }}</span>
              </div>
            </aside>
          </section>
        </main>

        <aside class="console-pane student-live-pane classroom-live-pane">
          <div class="console-pane-header">
            <div>
              <strong>课堂状态</strong>
              <span>当前为本地轮询同步，后续接入 WebSocket。</span>
            </div>
          </div>
          <div class="student-state-summary">
            <div v-for="item in classroomStats" :key="item.label">
              <strong>{{ item.value }}</strong>
              <span>{{ item.label }}</span>
            </div>
          </div>
          <div class="live-message-list classroom-run-log">
            <strong>运行信息</strong>
            <p><span>课堂</span>{{ session.status_label }}，开始时间：{{ formatDateTime(session.started_at) }}</p>
            <p><span>环节</span>{{ currentStep?.title || '未投放' }}，状态：{{ session.current_step_status_label }}</p>
            <p><span>提交</span>{{ session.submission_locked ? '已锁定' : '允许提交' }}</p>
            <p><span>分层</span>{{ session.is_layered ? '当前投放环节含分层题，学生端按层级匹配。' : '当前投放环节没有分层题。' }}</p>
          </div>
          <div class="live-message-list classroom-run-log classroom-activity-log">
            <strong>课堂控制</strong>
            <p v-if="!openActivities.length"><span>状态</span>暂无进行中的课堂活动。</p>
            <article v-for="activity in openActivities" :key="activity.id" class="classroom-activity-row">
              <p>
                <span>{{ activity.activity_type_label }}</span>
                {{ activity.title }}{{ metadataText(activity) ? `，${metadataText(activity)}` : '' }}
                <template v-if="responseCount(activity)">
                  ，已响应 {{ responseCount(activity) }} 人
                  <template v-if="responseNames(activity)">：{{ responseNames(activity) }}</template>
                </template>
              </p>
              <button class="secondary-button mini" type="button" :disabled="saving" @click="closeActivity(activity)">关闭</button>
              <button v-if="isSignInActivity(activity)" class="primary-button mini" type="button" :disabled="saving" @click="openAttendancePanel(activity)">
                查看签到
              </button>
              <button v-if="isQuickAnswerActivity(activity)" class="primary-button mini" type="button" :disabled="saving" @click="openQuickAnswerPanel(activity)">
                查看抢答
              </button>
              <button v-if="isRandomPickActivity(activity)" class="primary-button mini" type="button" :disabled="saving" @click="openRandomPickPanel(activity)">
                查看点名
              </button>
            </article>
          </div>
        </aside>
      </div>

      <LearningPageStatsModal
        :open="learningPageProgressOpen"
        :loading="learningPageProgressLoading"
        :stats="learningPageProgressData"
        :fallback-title="selectedLearningPageTitle"
        @close="closeLearningPageProgress"
        @refresh="loadLearningPageProgress()"
      />

      <div v-if="questionProgressOpen && selectedProgressQuestion" class="modal-backdrop" role="presentation" @click.self="closeQuestionProgress">
        <section class="entity-modal question-progress-modal" role="dialog" aria-modal="true" aria-labelledby="question-progress-title">
          <header class="modal-header">
            <div>
              <h2 id="question-progress-title">题目完成情况</h2>
              <p>{{ questionProgressMeta(selectedProgressQuestion) }}</p>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" @click="closeQuestionProgress">×</button>
          </header>

          <div class="question-progress-stem">
            <span>题目</span>
            <strong>{{ selectedProgressQuestion.stem }}</strong>
          </div>

          <div class="question-progress-modal-body" :class="{ 'has-preview': selectedProgressQuestion.question_type === 'file' }">
            <section class="question-progress-main">
              <div class="question-progress-summary-grid">
                <div>
                  <strong>{{ questionProgressSummary.answered }}/{{ questionProgressSummary.total }}</strong>
                  <span>已作答</span>
                </div>
                <div v-if="selectedProgressQuestion.question_type !== 'file'">
                  <strong>{{ questionProgressSummary.correct }}</strong>
                  <span>正确</span>
                </div>
                <div v-if="selectedProgressQuestion.question_type !== 'file'">
                  <strong>{{ questionProgressSummary.wrong }}</strong>
                  <span>错误</span>
                </div>
                <div v-if="selectedProgressQuestion.question_type === 'file'">
                  <strong>{{ questionProgressSummary.fileUploaded }}</strong>
                  <span>已上传</span>
                </div>
                <div v-if="selectedProgressQuestion.question_type === 'file'">
                  <strong>{{ questionProgressSummary.fileScored }}</strong>
                  <span>已评分</span>
                </div>
                <div>
                  <strong>{{ questionProgressSummary.unanswered }}</strong>
                  <span>未完成</span>
                </div>
              </div>

              <section v-if="hasObjectiveProgressChart" class="question-progress-chart-section">
                <EChartPanel
                  title="选项分布"
                  :subtitle="`正确答案：${objectiveProgressCorrectLabels}`"
                  :total="`${questionProgressSummary.answered}/${questionProgressSummary.total}`"
                  :option="objectiveProgressOption"
                  wide
                />
                <div class="question-progress-option-legend" aria-hidden="true">
                  <span class="correct">正确答案</span>
                  <span class="selected">学生选择</span>
                  <span class="unanswered">未作答</span>
                </div>
              </section>

              <div class="question-progress-table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>学生</th>
                      <th>层级</th>
                      <th>状态</th>
                      <th>作答 / 附件</th>
                      <th>提交时间</th>
                      <th v-if="selectedProgressQuestion.question_type === 'file'">评分</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in questionProgressRows" :key="row.student_id">
                      <td>
                        <strong>{{ row.display_name || row.username }}</strong>
                        <small>{{ row.student_no || row.username }}</small>
                      </td>
                      <td>{{ studentLayerText(row) }}</td>
                      <td>
                        <span class="status-pill" :class="questionProgressStatusClass(row.question_answer)">
                          {{ questionProgressStatusText(row.question_answer) }}
                        </span>
                      </td>
                      <td>
                        <div class="question-progress-answer-cell">
                          <span>{{ questionProgressAnswerText(row.question_answer) }}</span>
                          <template v-if="answerAttachment(row.question_answer)">
                            <small>{{ formatFileSize(answerAttachment(row.question_answer)?.attachment_size || 0) }}</small>
                            <div class="question-progress-file-actions">
                              <button type="button" @click="previewAttachment(answerAttachment(row.question_answer)!)">预览</button>
                              <a :href="answerAttachment(row.question_answer)?.attachment_url" download>下载</a>
                            </div>
                          </template>
                        </div>
                      </td>
                      <td>{{ row.submitted_at ? formatDateTime(row.submitted_at) : '-' }}</td>
                      <td v-if="selectedProgressQuestion.question_type === 'file'">
                        <div v-if="answerAttachment(row.question_answer)" class="attachment-score-editor">
                          <input
                            type="number"
                            min="0"
                            :max="row.question_answer?.max_score || selectedProgressQuestion.score"
                            step="0.5"
                            :value="attachmentScoreDraft(answerAttachment(row.question_answer)!)"
                            placeholder="分数"
                            @input="setAttachmentScoreDraft(answerAttachment(row.question_answer)!, ($event.target as HTMLInputElement).value)"
                          />
                          <input
                            :value="attachmentFeedbackDraft(answerAttachment(row.question_answer)!)"
                            maxlength="1000"
                            placeholder="反馈"
                            @input="setAttachmentFeedbackDraft(answerAttachment(row.question_answer)!, ($event.target as HTMLInputElement).value)"
                          />
                          <button
                            class="primary-button mini"
                            type="button"
                            :disabled="attachmentScoringId === answerAttachment(row.question_answer)?.id"
                            @click="saveAttachmentScore(answerAttachment(row.question_answer)!)"
                          >
                            保存
                          </button>
                        </div>
                        <span v-else class="muted-cell">未上传</span>
                      </td>
                    </tr>
                  </tbody>
                </table>
                <p v-if="!questionProgressRows.length" class="empty">当前班级暂无学生。</p>
              </div>
            </section>

            <aside v-if="selectedProgressQuestion.question_type === 'file'" class="question-progress-preview">
              <header>
                <strong>附件预览</strong>
                <span>{{ selectedPreviewAttachment?.attachment_name || '点击左侧附件预览' }}</span>
              </header>
              <ResourcePreview :resource="previewAttachmentResource(selectedPreviewAttachment)" office-mode="view" />
            </aside>
          </div>

          <footer class="modal-actions">
            <button class="secondary-button" type="button" :disabled="stepProgressLoading" @click="loadStepProgress()">刷新</button>
            <button class="primary-button" type="button" @click="closeQuestionProgress">关闭</button>
          </footer>
        </section>
      </div>

      <div v-if="evaluationOpen" class="modal-backdrop classroom-evaluation-backdrop" role="presentation" @click.self="evaluationOpen = false">
        <section class="entity-modal classroom-evaluation-modal runtime-evaluation-modal" role="dialog" aria-modal="true" aria-labelledby="classroom-evaluation-title">
          <header class="modal-header">
            <div>
              <h2 id="classroom-evaluation-title">课堂评价情况</h2>
              <p>{{ session.title }} · {{ classLabel() }} · 评价内容来自课时设计</p>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" :disabled="evaluationLoading" @click="evaluationOpen = false">×</button>
          </header>

          <div class="classroom-evaluation-body runtime-evaluation-body">
            <section class="evaluation-summary-panel runtime-evaluation-overview">
              <header class="evaluation-section-head">
                <div>
                  <span>完成情况</span>
                  <strong>按 5 星评价统计</strong>
                </div>
                <button class="secondary-button mini" type="button" :disabled="evaluationLoading" @click="loadEvaluation()">刷新</button>
              </header>
              <div class="evaluation-runtime-switch-card" :class="{ active: runtimeEvaluationEnabled }">
                <div>
                  <span>{{ runtimeEvaluationEnabled ? '课堂评价已开启' : '课堂评价未开启' }}</span>
                  <strong>{{ runtimeEvaluationEnabled ? `${evaluationEnabledCount} 类评价已开放` : '默认关闭' }}</strong>
                </div>
                <button
                  class="primary-button mini"
                  type="button"
                  :class="{ danger: runtimeEvaluationEnabled }"
                  :disabled="evaluationLoading"
                  @click="setRuntimeEvaluationEnabled(!runtimeEvaluationEnabled)"
                >
                  {{ runtimeEvaluationEnabled ? '关闭评价' : '开启评价' }}
                </button>
              </div>
              <div class="evaluation-summary-grid">
                <article v-for="item in evaluationSummaryItems" :key="item.type">
                  <span>{{ item.label }}{{ item.summary?.enabled ? ' · 已配置' : ' · 未配置' }}</span>
                  <strong>{{ item.summary?.submitted || 0 }}/{{ item.summary?.total || 0 }}</strong>
                  <small>
                    已评分 {{ item.summary?.rated_item_count || 0 }}/{{ item.summary?.total_item_count || 0 }} 项
                    <template v-if="item.summary?.not_assessed_item_count"> · 暂不评价 {{ item.summary.not_assessed_item_count }} 项</template>
                    · 平均 {{ ratingAverageText(item.summary?.average) }}
                  </small>
                </article>
              </div>

              <div class="runtime-evaluation-criteria-list">
                <section v-for="item in evaluationSummaryItems" :key="`criteria-${item.type}`">
                  <header>
                    <strong>{{ item.label }}评价项</strong>
                    <span>{{ item.criteria.length }} 项</span>
                  </header>
                  <article v-for="criterion in item.criteria" :key="criterion.id">
                    <strong>{{ criterion.title }}</strong>
                    <small>{{ criterion.description || '未填写观察说明。' }}</small>
                  </article>
                  <p v-if="!item.criteria.length" class="empty">未在课时设计中设置{{ item.label }}评价项。</p>
                </section>
              </div>
            </section>

            <section class="teacher-evaluation-panel">
              <header class="evaluation-section-head">
                <div>
                  <span>师评</span>
                  <strong>选择学生后填写星级或暂不评价</strong>
                </div>
              </header>
              <div class="teacher-evaluation-layout">
                <div class="teacher-evaluation-student-list">
                  <button
                    v-for="row in evaluationData?.students || []"
                    :key="row.student.id"
                    type="button"
                    :class="{ active: selectedTeacherEvalStudentId === row.student.id }"
                    @click="selectTeacherEvaluationStudent(row.student.id)"
                  >
                    <strong>{{ row.student.display_name || row.student.username }}</strong>
                    <span>
                      {{ row.profile?.student_no || row.student.username }}
                      <template v-if="row.peer_submission_count"> · 互评 {{ row.peer_submission_count }}</template>
                      <template v-if="row.teacher_submission"> · 已师评</template>
                    </span>
                  </button>
                  <p v-if="!(evaluationData?.students || []).length" class="empty">当前班级暂无学生。</p>
                </div>

                <div class="teacher-evaluation-form">
                  <p v-if="!evaluationForm.enable_teacher" class="evaluation-warning">师评未在课时设计中开启，课堂内不能填写师评。</p>
                  <template v-if="selectedTeacherEvalStudent">
                    <div class="teacher-evaluation-target">
                      <strong>{{ selectedTeacherEvalStudent.student.display_name || selectedTeacherEvalStudent.student.username }}</strong>
                      <span>
                        自评：{{ selectedTeacherEvalStudent.self_submission ? '已提交' : '未提交' }} ·
                        互评平均：{{ ratingAverageText(selectedTeacherEvalStudent.peer_average) }}
                      </span>
                    </div>
                    <div class="evaluation-star-list">
                      <EvaluationRatingInput
                        v-for="criterion in teacherEvaluationCriteria"
                        :key="criterion.id"
                        :criterion="criterion"
                        :rating="teacherEvaluationRatings[criterion.id] || 0"
                        :not-assessed="teacherEvaluationNotAssessed[criterion.id] || null"
                        :disabled="evaluationLoading"
                        @rating="setTeacherEvaluationRating"
                        @not-assessed="setTeacherEvaluationNotAssessed"
                      />
                      <p v-if="!teacherEvaluationCriteria.length" class="empty">请先回到课时设计设置师评评价项。</p>
                    </div>
                    <label class="evaluation-comment-box">
                      <span>师评备注</span>
                      <textarea v-model="teacherEvaluationComment" maxlength="1000" rows="3" placeholder="可选，记录课堂观察或后续辅导建议。"></textarea>
                    </label>
                  </template>
                </div>
              </div>
            </section>
          </div>

          <footer class="modal-actions evaluation-modal-actions">
            <span>评价内容在课时设计中维护；没有足够材料时选择暂不评价。</span>
            <button class="secondary-button" type="button" :disabled="evaluationLoading" @click="evaluationOpen = false">关闭</button>
            <button class="primary-button" type="button" :disabled="evaluationLoading || !selectedTeacherEvalStudent || !evaluationForm.enable_teacher" @click="submitTeacherEvaluation">
              保存师评
            </button>
          </footer>
        </section>
      </div>

      <div v-if="groupCollabOpen" class="modal-backdrop" role="presentation" @click.self="groupCollabOpen = false">
        <section class="entity-modal group-collaboration-modal" role="dialog" aria-modal="true" aria-labelledby="group-collaboration-title">
          <header class="modal-header">
            <div>
              <h2 id="group-collaboration-title">小组分组合作</h2>
              <p>{{ session.title }} · {{ classLabel() }}</p>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" @click="groupCollabOpen = false">×</button>
          </header>

          <div class="group-collaboration-body">
            <section class="group-collaboration-settings">
              <label>
                <span>每组人数</span>
                <input v-model.number="groupCollabForm.group_size" type="number" min="2" max="12" />
              </label>
              <label>
                <span>分组方式</span>
                <select v-model="groupCollabForm.grouping_strategy">
                  <option value="random">随机分组</option>
                  <option value="same_layer">准备度接近</option>
                  <option value="balanced_layer">相邻互助</option>
                  <option value="ai_layer">任务匹配</option>
                  <option value="stable_project">项目稳定</option>
                </select>
              </label>
              <label>
                <span>协作文档</span>
                <select v-model="groupCollabForm.document_type">
                  <option value="docx">Word 文档</option>
                  <option value="pptx">PPT 演示</option>
                  <option value="xlsx">Excel 表格</option>
                </select>
              </label>
              <label>
                <span>小组空间</span>
                <input v-model.number="groupCollabForm.storage_quota_mb" type="number" min="10" max="2048" />
              </label>
              <label class="group-collaboration-check">
                <input v-model="groupCollabForm.allow_onlyoffice_edit" type="checkbox" />
                <span>允许学生在线协作编辑</span>
              </label>
              <label class="group-collaboration-check">
                <input v-model="groupCollabForm.allow_student_upload" type="checkbox" />
                <span>允许学生上传小组共享文件</span>
              </label>
              <div class="group-collaboration-actions">
                <button class="primary-button" type="button" :disabled="groupCollabLoading" @click="saveGroupCollaboration(false)">
                  {{ groupCollaboration ? '保存设置' : '开启小组合作' }}
                </button>
                <button class="secondary-button" type="button" :disabled="groupCollabLoading || !groupCollaboration" @click="saveGroupCollaboration(true)">
                  {{ groupingRun ? '重新计算' : '生成分组候选' }}
                </button>
                <button
                  v-if="groupCollaboration?.status === 'open'"
                  class="secondary-button danger"
                  type="button"
                  :disabled="groupCollabLoading"
                  @click="closeGroupCollaboration"
                >
                  关闭合作
                </button>
              </div>
            </section>

            <section v-if="groupingRun" class="grouping-candidate-workspace">
              <header class="grouping-candidate-header">
                <div>
                  <span>{{ groupingRun.status_label }}</span>
                  <strong>选择并调整分组方案</strong>
                </div>
                <small>锁定的学生在重新计算时保持当前小组</small>
              </header>

              <div class="grouping-candidate-tabs" role="tablist" aria-label="分组候选">
                <button
                  v-for="candidate in groupingRun.candidates"
                  :key="candidate.key"
                  type="button"
                  :class="{ active: groupingCandidateKey === candidate.key }"
                  @click="selectGroupingCandidate(candidate.key)"
                >
                  <strong>{{ candidate.label }}</strong>
                  <span>{{ candidate.assignments.length }} 组 · 人数差 {{ candidate.fairness.group_size_gap }}</span>
                </button>
              </div>

              <div v-if="selectedGroupingCandidate" class="grouping-plan-editor">
                <article
                  v-for="group in groupingDraft"
                  :key="group.group_no"
                  class="grouping-draft-group"
                  @dragover.prevent
                  @drop="onGroupingDrop(group.group_no)"
                >
                  <header>
                    <strong>第{{ group.group_no }}组</strong>
                    <span>{{ group.members.length }} 人</span>
                  </header>
                  <div class="grouping-draft-members">
                    <div
                      v-for="member in group.members"
                      :key="member.student_id"
                      class="grouping-draft-member"
                      :class="{ locked: groupingLocks[member.student_id] }"
                      :draggable="!groupingLocks[member.student_id]"
                      @dragstart="onGroupingDragStart(member.student_id)"
                      @dragend="draggedGroupingStudentId = null"
                    >
                      <div>
                        <strong>{{ member.display_name || member.username }}</strong>
                        <small>{{ member.student_no || member.username }}</small>
                      </div>
                      <label>
                        <span class="sr-only">调整小组</span>
                        <select
                          :value="groupingStudentGroup(member.student_id)"
                          :disabled="groupingLocks[member.student_id]"
                          @change="setGroupingStudentGroup(member.student_id, $event)"
                        >
                          <option v-for="target in groupingDraft" :key="target.group_no" :value="target.group_no">第{{ target.group_no }}组</option>
                        </select>
                      </label>
                      <label>
                        <span class="sr-only">调整角色</span>
                        <select v-model="member.role">
                          <option value="coordinator">协调</option>
                          <option value="recorder">记录</option>
                          <option value="resource">资源</option>
                          <option value="presenter">展示</option>
                          <option value="verifier">核验</option>
                          <option value="member">成员</option>
                        </select>
                      </label>
                      <label class="grouping-lock-toggle">
                        <input v-model="groupingLocks[member.student_id]" type="checkbox" />
                        <span>锁定</span>
                      </label>
                    </div>
                  </div>
                </article>
              </div>

              <div class="grouping-confirm-row">
                <label>
                  <span>调整说明</span>
                  <input v-model="groupingNote" maxlength="500" placeholder="可选，记录本次人工调整原因" />
                </label>
                <button class="primary-button" type="button" :disabled="groupCollabLoading || !selectedGroupingCandidate" @click="confirmGroupingPlan">
                  确认启用
                </button>
              </div>
            </section>

            <section class="group-collaboration-list">
              <header>
                <div>
                  <span>{{ groupCollaborationOpenText }}</span>
                  <strong>分组与共享空间</strong>
                </div>
                <button class="secondary-button mini" type="button" :disabled="groupCollabLoading" @click="loadGroupCollaboration()">刷新</button>
              </header>

              <div v-if="groupRows.length" class="group-card-grid">
                <article v-for="group in groupRows" :key="group.id" class="group-card">
                  <header>
                    <div>
                      <span>{{ group.members.length }} 名成员</span>
                      <strong>{{ group.name }}</strong>
                    </div>
                    <button class="primary-button mini" type="button" @click="openGroupDocument(group)">打开协作文档</button>
                  </header>
                  <p>{{ groupMembersText(group) }}</p>
                  <div class="group-member-chips">
                    <span v-for="member in group.members" :key="member.id" :class="{ leader: member.role === 'leader' }">
                      {{ member.display_name || member.username }}{{ member.role === 'leader' ? ' · 组长' : '' }}
                    </span>
                  </div>
                  <div class="group-storage-line">
                    <div>
                      <strong>{{ group.used_storage_mb }}MB</strong>
                      <span>/ {{ groupCollaboration?.storage_quota_mb || 0 }}MB</span>
                    </div>
                    <i><em :style="groupStorageStyle(group)"></em></i>
                  </div>
                  <div class="group-file-list">
                    <strong>共享文件 {{ group.file_count }}</strong>
                    <a v-for="file in group.files.slice(0, 4)" :key="file.id" :href="file.attachment_url" download>
                      {{ file.attachment_name }} · {{ formatFileSize(file.file_size) }}
                    </a>
                    <span v-if="!group.files.length">暂无上传文件</span>
                  </div>
                </article>
              </div>
              <p v-else class="empty">保存设置后系统会按当前班级学生生成默认分组。</p>
            </section>
          </div>

          <footer class="modal-actions">
            <span>学生只看到小组、角色和任务，不显示内部判断依据。</span>
            <button class="primary-button" type="button" @click="groupCollabOpen = false">完成</button>
          </footer>
        </section>
      </div>

      <div v-if="activeGroupDocument" class="modal-backdrop group-document-backdrop" role="presentation" @click.self="closeGroupDocument">
        <section class="entity-modal group-document-modal" role="dialog" aria-modal="true" aria-labelledby="group-document-title">
          <header class="modal-header">
            <div>
              <h2 id="group-document-title">{{ activeGroupDocument.name }}协作文档</h2>
              <p>{{ activeGroupDocument.document.attachment_name }}</p>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" @click="closeGroupDocument">×</button>
          </header>
          <div class="group-document-editor">
            <OnlyOfficeEditor :group-id="activeGroupDocument.id" mode="edit" />
          </div>
        </section>
      </div>

      <div v-if="broadcastDialogOpen" class="modal-backdrop" role="presentation" @click.self="closeBroadcastDialog">
        <section class="entity-modal broadcast-setup-modal" role="dialog" aria-modal="true" aria-labelledby="broadcast-setup-title">
          <header class="modal-header">
            <div>
              <h2 id="broadcast-setup-title">课堂广播</h2>
              <p>{{ session.title }} · {{ classLabel() }}</p>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" :disabled="saving" @click="closeBroadcastDialog">×</button>
          </header>
          <label class="broadcast-editor">
            <span>广播内容</span>
            <textarea
              v-model="broadcastContent"
              maxlength="1000"
              rows="6"
              placeholder="输入需要立即通知全班学生的信息"
              @keydown.ctrl.enter.prevent="submitBroadcast"
            ></textarea>
            <small>{{ broadcastContent.trim().length }}/1000，学生端会以弹窗方式收到。</small>
          </label>
          <footer class="modal-actions">
            <button class="secondary-button" type="button" :disabled="saving" @click="closeBroadcastDialog">取消</button>
            <button class="primary-button" type="button" :disabled="saving || !broadcastContent.trim()" @click="submitBroadcast">
              {{ saving ? '发送中...' : '发送广播' }}
            </button>
          </footer>
        </section>
      </div>

      <div v-if="timerDialogOpen" class="modal-backdrop" role="presentation" @click.self="closeTimerDialog">
        <section class="entity-modal timer-setup-modal" role="dialog" aria-modal="true" aria-labelledby="timer-setup-title">
          <header class="modal-header">
            <div>
              <h2 id="timer-setup-title">课堂倒计时</h2>
              <p>{{ session.title }} · {{ classLabel() }}</p>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" @click="closeTimerDialog">×</button>
          </header>
          <div class="timer-setup-body">
            <label class="timer-stepper">
              <span>分钟</span>
              <div>
                <button type="button" aria-label="减少一分钟" :disabled="saving" @click="adjustTimerPart('minutes', -1)">−</button>
                <input v-model.number="timerMinutes" type="number" min="0" max="120" step="1" @blur="normalizeTimerInputs" />
                <button type="button" aria-label="增加一分钟" :disabled="saving" @click="adjustTimerPart('minutes', 1)">+</button>
              </div>
            </label>
            <label class="timer-stepper">
              <span>秒钟</span>
              <div>
                <button type="button" aria-label="减少一秒" :disabled="saving" @click="adjustTimerPart('seconds', -1)">−</button>
                <input v-model.number="timerSeconds" type="number" min="0" max="59" step="1" @blur="normalizeTimerInputs" />
                <button type="button" aria-label="增加一秒" :disabled="saving" @click="adjustTimerPart('seconds', 1)">+</button>
              </div>
            </label>
            <div class="timer-setup-preview">
              <span>将启动</span>
              <strong>{{ formatTimerClock(timerMinutes * 60 + timerSeconds) }}</strong>
            </div>
          </div>
          <footer class="modal-actions">
            <button class="secondary-button" type="button" :disabled="saving" @click="closeTimerDialog">取消</button>
            <button class="primary-button" type="button" :disabled="saving || timerMinutes * 60 + timerSeconds < 1" @click="startTimerFromDialog">
              {{ activeTimerActivity ? '重新开始倒计时' : '开始倒计时' }}
            </button>
          </footer>
        </section>
      </div>

      <div v-if="attendanceOpen && attendanceActivity" class="modal-backdrop" role="presentation" @click.self="attendanceOpen = false">
        <section class="entity-modal attendance-modal" role="dialog" aria-modal="true" aria-labelledby="attendance-title">
          <header class="modal-header">
            <div>
              <h2 id="attendance-title">课堂签到</h2>
              <p>{{ session.title }} · {{ classLabel() }}</p>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" @click="attendanceOpen = false">×</button>
          </header>

          <div class="attendance-summary-grid">
            <button type="button" :class="{ active: attendanceFilter === 'all' }" @click="attendanceFilter = 'all'">
              <strong>{{ attendanceData?.summary.total || 0 }}</strong>
              <span>全部</span>
            </button>
            <button type="button" :class="{ active: attendanceFilter === 'signed' }" @click="attendanceFilter = 'signed'">
              <strong>{{ attendanceData?.summary.signed || 0 }}</strong>
              <span>已签到</span>
            </button>
            <button type="button" :class="{ active: attendanceFilter === 'late' }" @click="attendanceFilter = 'late'">
              <strong>{{ attendanceData?.summary.late || 0 }}</strong>
              <span>迟到</span>
            </button>
            <button type="button" :class="{ active: attendanceFilter === 'leave' }" @click="attendanceFilter = 'leave'">
              <strong>{{ attendanceData?.summary.leave || 0 }}</strong>
              <span>请假</span>
            </button>
            <button type="button" :class="{ active: attendanceFilter === 'absent' }" @click="attendanceFilter = 'absent'">
              <strong>{{ attendanceData?.summary.absent || 0 }}</strong>
              <span>缺勤</span>
            </button>
            <button type="button" :class="{ active: attendanceFilter === 'not_signed' }" @click="attendanceFilter = 'not_signed'">
              <strong>{{ attendanceData?.summary.not_signed || 0 }}</strong>
              <span>未签到</span>
            </button>
          </div>

          <div class="attendance-toolbar">
            <span>{{ attendanceActivity.status_label }} · {{ formatDateTime(attendanceActivity.opened_at) }}</span>
            <div>
              <button class="secondary-button mini" type="button" :disabled="attendanceLoading" @click="openAttendancePanel(attendanceActivity)">刷新名单</button>
              <button class="secondary-button mini" type="button" :disabled="attendanceLoading" @click="closeActivity(attendanceActivity); attendanceOpen = false">关闭签到</button>
            </div>
          </div>

          <div class="attendance-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>学生</th>
                  <th>账号</th>
                  <th>学号</th>
                  <th>层级</th>
                  <th>状态</th>
                  <th>时间/备注</th>
                  <th>手工标记</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in filteredAttendanceRows" :key="row.student_id">
                  <td>{{ row.display_name }}</td>
                  <td>{{ row.username }}</td>
                  <td>{{ row.student_no || '-' }}</td>
                  <td>{{ row.current_layer ? `${row.current_layer} ${row.current_layer_label}` : '-' }}</td>
                  <td><span class="status-pill" :class="attendanceStatusClass(row.status)">{{ row.status_label }}</span></td>
                  <td>
                    <span class="attendance-note">
                      {{ row.occurred_at ? formatDateTime(row.occurred_at) : '-' }}
                      <template v-if="row.note"> · {{ row.note }}</template>
                    </span>
                  </td>
                  <td>
                    <div class="attendance-actions">
                      <button
                        v-for="item in attendanceStatusOptions"
                        :key="`${row.student_id}-${item.status}`"
                        type="button"
                        :disabled="attendanceLoading"
                        @click="markAttendance(row, item.status)"
                      >
                        {{ item.label }}
                      </button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
            <p v-if="attendanceLoading" class="empty">正在加载签到信息...</p>
            <p v-else-if="!filteredAttendanceRows.length" class="empty">当前筛选下没有学生。</p>
          </div>
        </section>
      </div>

      <div v-if="quickAnswerOpen && quickAnswerActivity" class="modal-backdrop" role="presentation" @click.self="closeQuickAnswerPanel">
        <section class="entity-modal attendance-modal quick-answer-modal" role="dialog" aria-modal="true" aria-labelledby="quick-answer-title">
          <header class="modal-header">
            <div>
              <h2 id="quick-answer-title">课堂抢答</h2>
              <p>{{ session.title }} · {{ classLabel() }}</p>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" @click="closeQuickAnswerPanel">×</button>
          </header>

          <div class="attendance-summary-grid quick-answer-summary-grid">
            <button type="button" class="active">
              <strong>{{ quickAnswerData?.summary.total || 0 }}</strong>
              <span>抢答人数</span>
            </button>
            <button type="button">
              <strong>{{ quickAnswerData?.summary.scored || 0 }}</strong>
              <span>已评分</span>
            </button>
            <button type="button">
              <strong>+{{ quickAnswerData?.score_defaults.plus ?? 2 }}</strong>
              <span>默认加分</span>
            </button>
            <button type="button">
              <strong>{{ quickAnswerData?.score_defaults.minus ?? -1 }}</strong>
              <span>默认减分</span>
            </button>
          </div>

          <div class="attendance-toolbar">
            <span>{{ quickAnswerActivity.status_label }} · {{ formatDateTime(quickAnswerActivity.opened_at) }}</span>
            <div>
              <span class="live-refresh-indicator">自动更新中</span>
              <button class="secondary-button mini" type="button" :disabled="quickAnswerLoading" @click="closeActivity(quickAnswerActivity); closeQuickAnswerPanel()">关闭抢答</button>
            </div>
          </div>

          <div class="attendance-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>顺序</th>
                  <th>学生</th>
                  <th>账号</th>
                  <th>学号</th>
                  <th>层级</th>
                  <th>抢答时间</th>
                  <th>得分</th>
                  <th>评分</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in quickAnswerData?.rows || []" :key="row.event_id">
                  <td><span class="quick-rank-badge">{{ row.rank }}</span></td>
                  <td>{{ row.display_name }}</td>
                  <td>{{ row.username }}</td>
                  <td>{{ row.student_no || '-' }}</td>
                  <td>{{ row.current_layer ? `${row.current_layer} ${row.current_layer_label}` : '-' }}</td>
                  <td>{{ formatDateTime(row.responded_at) }}</td>
                  <td><span class="status-pill" :class="quickAnswerScoreClass(row)">{{ quickAnswerScoreText(row) }}</span></td>
                  <td>
                    <div class="attendance-actions quick-answer-actions">
                      <button
                        v-for="item in quickAnswerScoreActions"
                        :key="`${row.student_id}-${item.action}`"
                        type="button"
                        :class="item.action === 'minus' ? 'danger-action' : ''"
                        :disabled="quickAnswerLoading"
                        @click="scoreQuickAnswer(row, item.action)"
                      >
                        {{ item.label }}
                      </button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
            <p v-if="quickAnswerLoading" class="empty">正在加载抢答结果...</p>
            <p v-else-if="!(quickAnswerData?.rows || []).length" class="empty">抢答已开启，等待学生响应。</p>
          </div>
        </section>
      </div>

      <div v-if="randomPickOpen" class="modal-backdrop" role="presentation" @click.self="closeRandomPickPanel">
        <section class="entity-modal attendance-modal random-pick-modal" role="dialog" aria-modal="true" aria-labelledby="random-pick-title">
          <header class="modal-header">
            <div>
              <h2 id="random-pick-title">随机点名</h2>
              <p>{{ session.title }} · {{ classLabel() }}</p>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" @click="closeRandomPickPanel">×</button>
          </header>

          <div class="random-pick-layout">
            <section class="random-pick-draw-panel">
              <div class="random-pick-spotlight" :class="{ rolling: randomPickAnimating, picked: Boolean(randomPickPickedStudent) }">
                <span>{{ randomPickAnimating ? '正在抽取' : randomPickPickedStudent ? '已抽中' : '准备点名' }}</span>
                <strong>{{ randomPickDisplayStudent?.display_name || randomPickDisplayStudent?.username || '点击随机抽取' }}</strong>
                <small>
                  默认加分 +{{ randomPickData?.score_defaults.plus ?? 2 }} · 默认减分 {{ randomPickData?.score_defaults.minus ?? -1 }}
                </small>
              </div>
              <button
                class="primary-button random-pick-main-button"
                type="button"
                :disabled="randomPickLoading || randomPickAnimating || Boolean(randomPickActivity) || !randomPickStudents.length"
                @click="startRandomPickDraw"
              >
                {{ randomPickActivity ? '已投放给学生' : randomPickAnimating ? '抽取中...' : '随机抽取' }}
              </button>
              <button
                v-if="randomPickActivity"
                class="secondary-button"
                type="button"
                :disabled="randomPickLoading"
                @click="closeActivity(randomPickActivity)"
              >
                关闭点名
              </button>
            </section>

            <section class="random-pick-list-panel">
              <div class="class-check-header">
                <span>共 {{ randomPickStudents.length }} 名学生</span>
                <span v-if="randomPickLoading">正在同步...</span>
              </div>
              <div class="random-pick-student-grid">
                <span
                  v-for="row in randomPickStudents"
                  :key="row.student_id"
                  class="random-pick-student-chip"
                  :class="{
                    rolling: randomPickCurrentStudentId === row.student_id && randomPickAnimating,
                    picked: randomPickPickedStudent?.student_id === row.student_id
                  }"
                >
                  <strong>{{ row.display_name || row.username }}</strong>
                  <small>{{ row.student_no || row.username }}{{ row.current_layer ? ` · ${row.current_layer}` : '' }}</small>
                </span>
              </div>
              <p v-if="!randomPickLoading && !randomPickStudents.length" class="empty">当前班级没有可点名学生。</p>
            </section>

            <section v-if="randomPickPickedStudent" class="random-pick-score-panel">
              <header>
                <div>
                  <span>评分</span>
                  <strong>{{ randomPickPickedStudent.display_name || randomPickPickedStudent.username }}</strong>
                </div>
                <span class="status-pill" :class="randomPickScoreClass(randomPickPickedStudent)">
                  {{ randomPickScoreText(randomPickPickedStudent) }}
                </span>
              </header>
              <p>教师评分后，学生端会收到一次性弹窗反馈。</p>
              <div class="attendance-actions random-pick-score-actions">
                <button type="button" :disabled="randomPickLoading || !randomPickActivity" @click="scoreRandomPick('plus')">
                  加分 +{{ randomPickData?.score_defaults.plus ?? 2 }}
                </button>
                <button class="danger-action" type="button" :disabled="randomPickLoading || !randomPickActivity" @click="scoreRandomPick('minus')">
                  减分 {{ randomPickData?.score_defaults.minus ?? -1 }}
                </button>
              </div>
            </section>
          </div>
        </section>
      </div>
    </section>
    <ClassroomChatDock
      v-if="session"
      :session-id="session.id"
      role="teacher"
      :running="session.status === 'running'"
      @classroom-event="handleRealtimeClassroomEvent"
    />
  </main>
</template>
