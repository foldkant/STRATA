<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import type { EChartsCoreOption } from 'echarts/core'
import { useRoute } from 'vue-router'
import { ApiError } from '@/api/client'
import {
  getTeacherLearningPageResponses,
  type LearningPageResponseSummary
} from '@/api/learningPages'
import {
  activateClassroomGroupingPlan,
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
  getClassroomGroupingDecision,
  getClassroomQuickAnswer,
  getClassroomRandomPick,
  getClassroomRandomPickPreview,
  getClassroomSession,
  getClassroomStepProgress,
  getTeacherLessonSteps,
  getTeacherStudents,
  lockClassroomStep,
  markClassroomAttendance,
  notifyClassroomGroupingPlan,
  openClassroomStep,
  restartClassroomSession,
  runClassroomCommand,
  scoreClassroomAttachment,
  scoreClassroomQuickAnswer,
  scoreClassroomRandomPick,
  setClassroomEvaluationRuntime,
  saveClassroomGroupingDecision,
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
  type GroupingDecisionPayload,
  type GroupingDecisionPoint,
  type GroupingPlanVersion,
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
import type { StudentRow } from '@/api/management'
import NoticeLine from '@/components/NoticeLine.vue'
import ResourcePreview from '@/components/ResourcePreview.vue'
import ClassroomChatDock from '@/components/ClassroomChatDock.vue'
import ClassroomEvaluationModal from '@/components/teacher/ClassroomEvaluationModal.vue'
import ClassroomGroupCollaborationModal from '@/components/teacher/ClassroomGroupCollaborationModal.vue'
import ClassroomInteractionModals from '@/components/teacher/ClassroomInteractionModals.vue'
import ClassroomCommandHeader from '@/components/teacher/ClassroomCommandHeader.vue'
import ClassroomStepFlow from '@/components/teacher/ClassroomStepFlow.vue'
import { classroomControlState } from '@/domain/classroomState'
import type { EvaluationNotAssessedEntry } from '@/domain/evaluation'
import '@/styles/teacher-classroom-console.css'
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
const classroomResourcePreview = ref<HTMLElement | null>(null)
const resourcePreviewExpanded = ref(false)
const classroomContextTab = ref<'task' | 'status' | 'activity'>('task')

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
const groupingDraftSaved = ref(false)
const groupCollaboration = ref<ClassroomGroupCollaborationRow | null>(null)
const activeGroupDocument = ref<ClassroomGroupRow | null>(null)
const groupingStudents = ref<StudentRow[]>([])
const groupingDecision = ref<GroupingDecisionPoint | null>(null)
const groupingRun = ref<GroupingCandidateRun | null>(null)
const groupingPlan = ref<GroupingPlanVersion | null>(null)
const groupingCandidateKey = ref('')
const groupingDraft = ref<GroupingCandidateAssignment[]>([])
const groupingLocks = ref<Record<number, boolean>>({})
const groupingNote = ref('')
const draggedGroupingStudentId = ref<number | null>(null)
const groupingStrategyOptions = [
  {
    value: 'random',
    label: '日常随机',
    description: '随机且尽量等人数，适合一般课堂活动。'
  },
  {
    value: 'same_layer',
    label: '同进度练习',
    description: '把当前学科学习准备情况接近的学生分在一起，适合差异化练习和集中辅导。'
  },
  {
    value: 'balanced_layer',
    label: '同伴互助',
    description: '搭配准备情况相邻的学生，适合讨论、讲解和互相检查。'
  },
  {
    value: 'ai_layer',
    label: '任务均衡',
    description: '根据当前任务的准备情况平衡各组，适合开放任务和短项目。'
  },
  {
    value: 'stable_project',
    label: '保持原组',
    description: '尽量保留已有搭档和锁定成员，适合跨课时项目。'
  }
] as const
const groupCollabForm = ref<ClassroomGroupCollaborationPayload>({
  group_size: 4,
  grouping_strategy: 'balanced_layer',
  document_type: 'docx',
  storage_quota_mb: 20,
  allow_student_upload: true,
  allow_onlyoffice_edit: true,
  regenerate: false
})
const groupingDecisionForm = ref<GroupingDecisionPayload>(createDefaultGroupingDecisionForm())

const evaluationOpen = ref(false)
const evaluationLoading = ref(false)
const evaluationNotice = ref('')
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
const selectedResourcePreviewKey = computed(() => {
  const resource = selectedResource.value
  if (!resource) return 'empty-resource'
  return [
    selectedResourceIndex.value,
    resource.id || '',
    resource.attachment_url || '',
    resource.title || ''
  ].join(':')
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
const classroomControls = computed(() => classroomControlState({
  sessionStatus: session.value?.status || 'draft',
  stepStatus: session.value?.current_step_status || 'idle',
  hasSelectedStep: Boolean(selectedStep.value),
  hasCurrentStep: Boolean(session.value?.current_step),
  stepCount: steps.value.length,
  currentStepIndex: currentStepIndex.value
}))
const canControlStep = computed(() => classroomControls.value.canPublishStep)
const stepStatusText = computed(() => session.value?.current_step_status_label || '未投放')

const classroomStats = computed(() => [
  { label: '班级人数', value: session.value?.class_group?.student_count ?? 0 },
  { label: '学习环节', value: steps.value.length },
  { label: '当前资源', value: activeResources.value.length },
  { label: '当前题目', value: activeQuestions.value.length },
  { label: '进行活动', value: openActivities.value.length }
])
const groupRows = computed(() => groupCollaboration.value?.groups || [])
const groupingStudentOptions = computed(() => groupingStudents.value.map((student) => ({
  student_id: student.user_id,
  username: student.username,
  display_name: student.display_name,
  student_no: student.student_no
})))
const selectedGroupingCandidate = computed(() => (
  groupingRun.value?.candidates.find((item) => item.key === groupingCandidateKey.value) || null
))
const groupingFallbackMessage = computed(() => {
  const run = groupingRun.value
  if (!run) return ''
  if (run.status === 'blocked') return '候选方案均未通过完整性或教育约束检查，请重新准备分组任务。'
  if (run.candidate_count < 2) return '当前没有形成至少两套可比较的候选方案，请重新准备分组任务。'
  const reason = run.conflicts[0]?.code || ''
  if (reason === 'constraints_unsatisfied') return '部分候选未满足约束，请比较候选状态后再作决定。'
  if (reason === 'ortools_unavailable') return '当前采用可用的本地生成方式形成候选，请由教师复核。'
  return ''
})
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
const lessonEvaluationDesignPath = computed(() => (
  session.value?.lesson?.id ? `/teacher/lessons/${session.value.lesson.id}/design` : ''
))
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
    color: ['#17483f'],
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
      axisLabel: { color: '#687a73', fontSize: 12 },
      splitLine: { lineStyle: { color: '#dfe5e0' } }
    },
    yAxis: {
      type: 'category',
      data: rows.map((row) => row.label),
      axisLabel: { color: '#687a73', fontSize: 12, width: 120, overflow: 'truncate' },
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#d6ded8' } }
    },
    series: [
      {
        type: 'bar',
        data: rows.map((row) => ({
          value: row.count,
          itemStyle: {
            color: row.unanswered ? '#a5b1ac' : row.correct ? '#32674f' : '#b94f3d',
            borderRadius: [0, 7, 7, 0]
          },
          label: {
            show: true,
            position: 'right',
            color: '#334a43',
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
  return row.current_layer_label || row.current_layer || '尚未安排'
}

function formatFileSize(size: number) {
  if (!size) return '0 B'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function toDatetimeLocal(value: string | Date) {
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}

function createDefaultGroupingDecisionForm(): GroupingDecisionPayload {
  return {
    task_purpose: 'peer_explanation',
    task_stage: '',
    role_requirements: ['coordinator', 'recorder', 'presenter', 'verifier'],
    resource_requirements: [],
    safety_constraints: { prohibited_pairs: [] },
    opportunity_requirements: {
      required_group_roles: ['coordinator', 'recorder'],
      required_for_every_student: ['collaboration']
    },
    stability_until: toDatetimeLocal(new Date(Date.now() + 14 * 24 * 60 * 60 * 1000)),
    task_context: { source: 'teacher_classroom_console' }
  }
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

function syncGroupingDecisionForm(point: GroupingDecisionPoint | null) {
  if (!point) return
  groupingDecisionForm.value = {
    task_purpose: point.task_purpose,
    task_stage: point.task_stage,
    role_requirements: [...point.role_requirements],
    resource_requirements: [...point.resource_requirements],
    safety_constraints: {
      prohibited_pairs: (point.safety_constraints.prohibited_pairs || []).map((pair) => [...pair])
    },
    opportunity_requirements: {
      required_group_roles: [...(point.opportunity_requirements.required_group_roles || [])],
      required_for_every_student: [...(point.opportunity_requirements.required_for_every_student || ['collaboration'])]
    },
    stability_until: point.stability_until ? toDatetimeLocal(point.stability_until) : null,
    task_context: { source: 'teacher_classroom_console' }
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
    if (run && groupingDecision.value && run.decision_point.id !== groupingDecision.value.id) {
      groupingRun.value = null
      groupingCandidateKey.value = ''
      groupingDraft.value = []
      return
    }
    groupingRun.value = run
    if (run?.selected_candidate_key) {
      selectGroupingCandidate(run.selected_candidate_key)
    } else {
      groupingCandidateKey.value = ''
      groupingDraft.value = []
      groupingLocks.value = {}
    }
  } catch {
    groupingRun.value = null
  }
}

async function loadGroupingDecision() {
  if (!session.value) return
  try {
    groupingDecision.value = await getClassroomGroupingDecision(session.value.id)
    syncGroupingDecisionForm(groupingDecision.value)
  } catch {
    groupingDecision.value = null
  }
}

async function loadGroupingStudents() {
  const classId = session.value?.class_group?.id
  if (!classId) return
  try {
    const page = await getTeacherStudents({ class: classId, status: 'active', page_size: 200 })
    groupingStudents.value = page.results
  } catch {
    groupingStudents.value = []
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
  notice.value = ''
  groupCollabOpen.value = true
  groupingPlan.value = null
  await Promise.all([loadGroupCollaboration(), loadGroupingDecision(), loadGroupingStudents()])
  groupingDraftSaved.value = Boolean(groupCollaboration.value)
  await loadGroupingCandidates()
}

async function saveGroupCollaborationDraft() {
  if (!session.value || groupCollabLoading.value) return
  groupCollabLoading.value = true
  notice.value = ''
  try {
    const submittedDraft = { ...groupCollabForm.value, regenerate: false }
    const row = await setupClassroomGroupCollaboration(session.value.id, {
      ...submittedDraft
    })
    groupCollaboration.value = row
    groupingDraftSaved.value = true
    if (row.is_enabled) {
      groupCollabForm.value = submittedDraft
    } else {
      syncGroupCollaborationForm(row)
    }
    notice.value = '小组合作设置草稿已保存；尚未生成或启用分组。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '小组合作设置草稿保存失败。'
  } finally {
    groupCollabLoading.value = false
  }
}

async function saveGroupingDecision() {
  if (!session.value || !groupCollaboration.value || groupCollabLoading.value) return
  groupCollabLoading.value = true
  notice.value = ''
  try {
    const point = await saveClassroomGroupingDecision(session.value.id, {
      ...groupingDecisionForm.value,
      task_stage: groupingDecisionForm.value.task_stage.trim(),
      resource_requirements: groupingDecisionForm.value.resource_requirements.map((item) => item.trim()).filter(Boolean),
      safety_constraints: {
        prohibited_pairs: groupingDecisionForm.value.safety_constraints.prohibited_pairs.map((pair) => [...pair])
      },
      opportunity_requirements: {
        required_group_roles: [...groupingDecisionForm.value.opportunity_requirements.required_group_roles],
        required_for_every_student: [...groupingDecisionForm.value.opportunity_requirements.required_for_every_student]
      },
      task_context: { source: 'teacher_classroom_console' }
    })
    groupingDecision.value = point
    syncGroupingDecisionForm(point)
    groupingRun.value = null
    groupingPlan.value = null
    groupingCandidateKey.value = ''
    groupingDraft.value = []
    groupingLocks.value = {}
    notice.value = '本次分组任务已保存；现在可以生成候选方案。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '本次分组任务保存失败。'
  } finally {
    groupCollabLoading.value = false
  }
}

async function generateGroupingCandidates() {
  if (!session.value || !groupCollaboration.value || !groupingDecision.value || groupCollabLoading.value) return
  groupCollabLoading.value = true
  notice.value = ''
  try {
    const lockedAssignments = Object.fromEntries(
      groupingDraft.value.flatMap((group) => group.members
        .filter((member) => groupingLocks.value[member.student_id])
        .map((member) => [String(member.student_id), group.group_no]))
    )
    const run = await generateClassroomGroupingCandidates(session.value.id, {
      decision_point_id: groupingDecision.value.id,
      locked_assignments: lockedAssignments
    })
    groupingRun.value = run
    groupingDecision.value = run.decision_point
    groupingPlan.value = null
    groupingCandidateKey.value = ''
    groupingDraft.value = []
    groupingLocks.value = {}
    notice.value = run.candidate_count >= 2
      ? `已生成 ${run.candidate_count} 套候选方案，请由教师逐一比较后选择。`
      : '未形成至少两套可比较方案，请重新准备分组任务。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '分组候选生成失败。'
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

function setGroupingStudentGroup(studentId: number, event: Event) {
  const target = event.target as HTMLSelectElement | null
  if (target) moveGroupingStudent(studentId, Number(target.value))
}

async function confirmGroupingPlan() {
  if (!session.value || !groupingRun.value || !groupingCandidateKey.value || groupCollabLoading.value) return
  groupCollabLoading.value = true
  notice.value = ''
  try {
    const studentGroups = Object.fromEntries(
      groupingDraft.value.flatMap((group) => group.members.map((member) => [String(member.student_id), group.group_no]))
    )
    const roles = Object.fromEntries(
      groupingDraft.value.flatMap((group) => group.members.map((member) => [String(member.student_id), member.role]))
    )
    const plan = await confirmClassroomGroupingCandidate(session.value.id, groupingRun.value.id, {
      candidate_key: groupingCandidateKey.value,
      adjustments: { student_groups: studentGroups, roles },
      note: groupingNote.value.trim()
    })
    groupingPlan.value = plan
    groupingDecision.value = plan.decision_point
    groupingRun.value.selected_candidate_key = groupingCandidateKey.value
    notice.value = plan.status === 'reviewed'
      ? '教师复核结果已保存；方案尚未启用，也未通知学生。'
      : `已载入当前方案状态：${plan.status_label}。`
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '教师复核结果保存失败。'
  } finally {
    groupCollabLoading.value = false
  }
}

async function activateGroupingPlan() {
  if (!session.value || !groupingPlan.value || groupCollabLoading.value) return
  const confirmed = window.confirm('确认启用已复核的分组方案？启用后课堂将切换到该方案，但不会自动发送学生通知。')
  if (!confirmed) return
  groupCollabLoading.value = true
  notice.value = ''
  try {
    const result = await activateClassroomGroupingPlan(session.value.id, groupingPlan.value.id)
    groupingPlan.value = result.plan
    groupingDecision.value = result.plan.decision_point
    groupCollaboration.value = result.collaboration
    syncGroupCollaborationForm(result.collaboration)
    notice.value = '分组方案已启用；尚未通知学生。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '分组方案启用失败。'
  } finally {
    groupCollabLoading.value = false
  }
}

async function notifyStudentsOfGroupingPlan() {
  if (!session.value || !groupingPlan.value || groupCollabLoading.value) return
  const confirmed = window.confirm('确认向全班发送分组更新通知？通知只包含学生需要查看的小组、角色和学习任务提示。')
  if (!confirmed) return
  groupCollabLoading.value = true
  notice.value = ''
  try {
    const plan = await notifyClassroomGroupingPlan(session.value.id, groupingPlan.value.id)
    groupingPlan.value = plan
    groupingDecision.value = plan.decision_point
    notice.value = '分组通知已发送给学生。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '学生分组通知发送失败。'
  } finally {
    groupCollabLoading.value = false
  }
}

function restartGroupingWorkflow() {
  groupingDraftSaved.value = false
  groupingDecision.value = null
  groupingRun.value = null
  groupingPlan.value = null
  groupingCandidateKey.value = ''
  groupingDraft.value = []
  groupingLocks.value = {}
  groupingNote.value = ''
  groupingDecisionForm.value = createDefaultGroupingDecisionForm()
  notice.value = '已进入新的分组任务准备；当前已启用小组保持不变。'
}

async function refreshGroupingWorkflow() {
  groupingPlan.value = null
  await Promise.all([loadGroupCollaboration(), loadGroupingDecision(), loadGroupingStudents()])
  await loadGroupingCandidates()
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
    if (!silent) evaluationNotice.value = ''
  } catch (error) {
    if (!silent) {
      evaluationNotice.value = error instanceof ApiError ? error.message : '课堂评价加载失败。'
    }
  } finally {
    if (!silent) evaluationLoading.value = false
  }
}

async function openEvaluationPanel() {
  evaluationNotice.value = ''
  evaluationOpen.value = true
  await loadEvaluation()
}

async function setRuntimeEvaluationEnabled(enabled: boolean) {
  if (!session.value) return
  evaluationLoading.value = true
  evaluationNotice.value = ''
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
    evaluationNotice.value = error instanceof ApiError ? error.message : '课堂评价开关保存失败。'
  } finally {
    evaluationLoading.value = false
  }
}

function prepareEvaluationStep(stepId: number) {
  const step = steps.value.find((item) => item.id === stepId)
  if (!step) return
  selectStep(step)
  evaluationOpen.value = false
  notice.value = `已定位到“${step.title}”环节。确认内容后点击“投放此环节”，再开启课堂评价。`
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

async function resetResourcePreviewPosition() {
  await nextTick()
  const preview = classroomResourcePreview.value
  if (!preview) return
  preview.scrollTo({ top: 0, left: 0 })
  preview.querySelector<HTMLElement>('.resource-preview-body')?.scrollTo({ top: 0, left: 0 })
}

function selectResource(index: number) {
  selectedResourceIndex.value = index
  resetResourcePreviewPosition()
}

async function toggleResourcePreview() {
  resourcePreviewExpanded.value = !resourcePreviewExpanded.value
  document.body.classList.toggle('resource-preview-page-open', resourcePreviewExpanded.value)
  await resetResourcePreviewPosition()
  classroomResourcePreview.value
    ?.querySelector<HTMLButtonElement>('[data-test="resource-preview-expand"]')
    ?.focus()
}

async function closeExpandedResourcePreview() {
  if (!resourcePreviewExpanded.value) return
  resourcePreviewExpanded.value = false
  document.body.classList.remove('resource-preview-page-open')
  await resetResourcePreviewPosition()
  classroomResourcePreview.value
    ?.querySelector<HTMLButtonElement>('[data-test="resource-preview-expand"]')
    ?.focus()
}

function handleResourcePreviewKeydown(event: KeyboardEvent) {
  if (!resourcePreviewExpanded.value) return
  if (event.key === 'Escape') {
    event.preventDefault()
    closeExpandedResourcePreview()
    return
  }
  if (event.key !== 'Tab') return

  const preview = classroomResourcePreview.value
  const focusable = preview
    ? Array.from(preview.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), video[controls], [tabindex]:not([tabindex="-1"])'
    )).filter((element) => (
      !element.hidden
      && getComputedStyle(element).display !== 'none'
      && getComputedStyle(element).visibility !== 'hidden'
    ))
    : []
  if (!preview || !focusable.length) {
    event.preventDefault()
    preview?.focus({ preventScroll: true })
    return
  }

  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  const active = document.activeElement
  if (event.shiftKey && (active === first || !preview.contains(active))) {
    event.preventDefault()
    last.focus({ preventScroll: true })
  } else if (!event.shiftKey && (active === last || !preview.contains(active))) {
    event.preventDefault()
    first.focus({ preventScroll: true })
  }
}

watch(selectedResourcePreviewKey, () => {
  resourcePreviewExpanded.value = false
  document.body.classList.remove('resource-preview-page-open')
  resetResourcePreviewPosition()
})

onMounted(() => {
  timerTickHandle = window.setInterval(() => {
    nowTick.value = Date.now()
  }, 1000)
  startStepProgressPolling()
  window.addEventListener('keydown', handleResourcePreviewKeydown)
  loadPage()
})

onUnmounted(() => {
  stopQuickAnswerPolling()
  stopStepProgressPolling()
  stopRandomPickAnimation()
  stopLearningPageProgressPolling()
  window.removeEventListener('keydown', handleResourcePreviewKeydown)
  document.body.classList.remove('resource-preview-page-open')
  if (timerTickHandle !== null) {
    window.clearInterval(timerTickHandle)
  }
})
</script>

<template>
  <main class="classroom-fullscreen-page teacher-classroom-fullscreen">
    <NoticeLine v-if="notice" :message="notice" floating @dismiss="notice = ''" />
    <section v-if="loading || !session" class="panel classroom-fullscreen-loading">
      <p class="empty">正在加载课堂控制台</p>
    </section>

    <section v-else class="classroom-console-shell" :class="{ 'has-active-timer': activeTimerActivity }">
      <ClassroomCommandHeader
        :session="session"
        :current-step-title="currentStep?.title || ''"
        :step-status-text="stepStatusText"
        :class-label="classLabel()"
        :saving="saving"
        :loading="loading"
        :controls="classroomControls"
        :commands="classroomCommands"
        :group-enabled="Boolean(groupCollaboration?.is_enabled)"
        :group-status-text="groupCollaboration ? groupCollaborationOpenText : ''"
        :evaluation-enabled="runtimeEvaluationEnabled"
        @refresh="refreshConsole"
        @start="startSession"
        @finish="finishSession"
        @restart="restartSession"
        @command="runCommand"
        @open-group="openGroupCollaborationPanel"
        @open-evaluation="openEvaluationPanel"
      />

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
        <ClassroomStepFlow
          :steps="steps"
          :selected-step-id="selectedStepId"
          :current-step-id="currentStep?.id || null"
          :current-step-status="session.current_step_status"
          :step-status-text="stepStatusText"
          @select="selectStep"
        />

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
              <button class="secondary-button" type="button" :disabled="saving || !classroomControls.canLockStep" @click="lockCurrentStep">
                锁定提交
              </button>
              <button class="secondary-button" type="button" :disabled="saving || !classroomControls.canCloseStep" @click="closeCurrentStep">
                关闭环节
              </button>
              <button class="secondary-button" type="button" :disabled="saving || !classroomControls.canPublishNextStep" @click="publishNextStep">
                下一环节
              </button>
            </div>
          </div>

          <section class="classroom-stage-grid">
            <article class="live-preview-area classroom-resource-stage" :class="{ 'has-resource-tabs': activeResources.length > 1 }">
              <header>
                <span>资源预览</span>
                <strong>{{ resourceTitle(selectedResource) || '暂无资源' }}</strong>
              </header>
              <div v-if="activeResources.length > 1" class="student-resource-tabs classroom-resource-tabs" role="tablist" aria-label="切换课堂资源">
                <button
                  v-for="(resource, index) in activeResources"
                  :key="`${resource.id || resource.title}-${index}`"
                  type="button"
                  :class="{ active: selectedResourceIndex === index }"
                  role="tab"
                  :aria-selected="selectedResourceIndex === index"
                  :title="resourceTitle(resource)"
                  @click="selectResource(index)"
                >
                  {{ resourceTitle(resource) }}
                </button>
              </div>
              <div
                ref="classroomResourcePreview"
                class="classroom-resource-preview"
                :class="{ 'is-page-expanded': resourcePreviewExpanded }"
                :role="resourcePreviewExpanded ? 'dialog' : undefined"
                :aria-modal="resourcePreviewExpanded ? 'true' : undefined"
                :aria-label="resourcePreviewExpanded ? `正在放大查看：${resourceTitle(selectedResource)}` : undefined"
                :tabindex="resourcePreviewExpanded ? -1 : undefined"
              >
                <ResourcePreview
                  :key="selectedResourcePreviewKey"
                  :resource="selectedResource"
                  office-mode="view"
                  :expandable="Boolean(selectedResource)"
                  :expanded="resourcePreviewExpanded"
                  @toggle-expand="toggleResourcePreview"
                />
              </div>
            </article>
          </section>
        </main>
        <aside class="console-pane classroom-context-pane">
          <div class="console-pane-header">
            <div>
              <strong>课堂信息</strong>
              <span>任务、课堂情况与正在进行的活动集中在这里。</span>
            </div>
          </div>
          <nav class="classroom-context-tabs" role="tablist" aria-label="课堂信息分类">
            <button id="classroom-tab-task" type="button" role="tab" aria-controls="classroom-panel-task" :aria-selected="classroomContextTab === 'task'" :class="{ active: classroomContextTab === 'task' }" @click="classroomContextTab = 'task'">
              环节任务<small>{{ activeQuestions.length + activeLearningPages.length }} 项</small>
            </button>
            <button id="classroom-tab-status" type="button" role="tab" aria-controls="classroom-panel-status" :aria-selected="classroomContextTab === 'status'" :class="{ active: classroomContextTab === 'status' }" @click="classroomContextTab = 'status'">
              课堂情况<small>{{ session.status_label }}</small>
            </button>
            <button id="classroom-tab-activity" type="button" role="tab" aria-controls="classroom-panel-activity" :aria-selected="classroomContextTab === 'activity'" :class="{ active: classroomContextTab === 'activity' }" @click="classroomContextTab = 'activity'">
              课堂活动<small>{{ openActivities.length }} 项进行中</small>
            </button>
          </nav>
          <section id="classroom-panel-task" v-show="classroomContextTab === 'task'" class="classroom-context-panel task-panel" role="tabpanel" aria-labelledby="classroom-tab-task">
            <header>
              <span>本环节任务</span>
              <strong>{{ activeQuestions.length }} 道题 · {{ activeLearningPages.length }} 份 AI 任务单 · {{ activeActivities.length }} 个活动</strong>
            </header>
            <p class="student-instruction">{{ selectedStep?.student_instruction || '教师暂未填写学生可见说明。' }}</p>

            <div v-if="activeQuestions.length" class="classroom-question-list">
              <details v-for="(question, index) in activeQuestions" :key="question.id" class="classroom-question-item">
                <summary>
                  <span>{{ question.question_type_label }} · 面向 {{ question.target_layer_label || '全体' }} · {{ questionScoreSummary(question) }} · {{ question.is_required ? '必答' : '选答' }}</span>
                  <strong>{{ index + 1 }}. {{ question.stem }}</strong>
                </summary>
                <div class="classroom-question-detail">
                  <small v-if="question.options.length">选项：{{ question.options.join(' / ') }}</small>
                  <small v-if="question.question_type !== 'file'">参考答案：{{ questionAnswerSummary(question) }}</small>
                  <small v-else>{{ questionProgressMeta(question) }}</small>
                  <button class="question-progress-button" type="button" :disabled="!isCurrentSelected || !currentStep" @click="openQuestionProgress(question)">
                    {{ isCurrentSelected && currentStep ? '查看完成情况' : '投放后查看' }}
                  </button>
                </div>
              </details>
            </div>
            <p v-else-if="!activeLearningPages.length" class="empty">当前环节没有课堂题或 AI 学习任务单。</p>

            <section v-if="activeLearningPages.length" class="classroom-learning-page-list">
              <header><strong>AI 学习任务单</strong><span>{{ activeLearningPages.length }} 份</span></header>
              <article v-for="resource in activeLearningPages" :key="resource.learning_page_id || resource.id">
                <div><span>网页任务单 · v{{ resource.revision_no || 1 }}</span><strong>{{ resource.title }}</strong></div>
                <button class="question-progress-button" type="button" @click="openLearningPageProgress(resource)">查看完成情况</button>
              </article>
            </section>

            <div v-if="activeActivities.length" class="classroom-activity-tags">
              <span v-for="activity in activeActivities" :key="activity">{{ activity }}</span>
            </div>
          </section>

          <section id="classroom-panel-status" v-show="classroomContextTab === 'status'" class="classroom-context-panel status-panel" role="tabpanel" aria-labelledby="classroom-tab-status">
            <div class="student-state-summary">
              <div v-for="item in classroomStats" :key="item.label"><strong>{{ item.value }}</strong><span>{{ item.label }}</span></div>
            </div>
            <div class="live-message-list classroom-run-log">
              <strong>运行信息</strong>
              <p><span>课堂</span>{{ session.status_label }}，开始时间：{{ formatDateTime(session.started_at) }}</p>
              <p><span>环节</span>{{ currentStep?.title || '未投放' }}，状态：{{ session.current_step_status_label }}</p>
              <p><span>提交</span>{{ session.submission_locked ? '已锁定' : '允许提交' }}</p>
              <p><span>学习内容匹配</span>{{ session.is_layered ? '当前投放环节含差异化题目，学生端按教师确认的学习内容安排匹配。' : '当前投放环节没有差异化题目。' }}</p>
            </div>
          </section>

          <section id="classroom-panel-activity" v-show="classroomContextTab === 'activity'" class="classroom-context-panel activity-panel" role="tabpanel" aria-labelledby="classroom-tab-activity">
            <div class="live-message-list classroom-run-log classroom-activity-log">
              <strong>正在进行的课堂活动</strong>
              <p v-if="!openActivities.length"><span>状态</span>暂无进行中的课堂活动。</p>
              <article v-for="activity in openActivities" :key="activity.id" class="classroom-activity-row">
                <p>
                  <span>{{ activity.activity_type_label }}</span>
                  {{ activity.title }}{{ metadataText(activity) ? `，${metadataText(activity)}` : '' }}
                  <template v-if="responseCount(activity)">，已响应 {{ responseCount(activity) }} 人<template v-if="responseNames(activity)">：{{ responseNames(activity) }}</template></template>
                </p>
                <button class="secondary-button mini" type="button" :disabled="saving" @click="closeActivity(activity)">关闭</button>
                <button v-if="isSignInActivity(activity)" class="primary-button mini" type="button" :disabled="saving" @click="openAttendancePanel(activity)">查看签到</button>
                <button v-if="isQuickAnswerActivity(activity)" class="primary-button mini" type="button" :disabled="saving" @click="openQuickAnswerPanel(activity)">查看抢答</button>
                <button v-if="isRandomPickActivity(activity)" class="primary-button mini" type="button" :disabled="saving" @click="openRandomPickPanel(activity)">查看点名</button>
              </article>
            </div>
          </section>
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

      <ClassroomEvaluationModal
        :open="evaluationOpen"
        :session-title="session.title"
        :class-label="classLabel()"
        :loading="evaluationLoading"
        :notice="evaluationNotice"
        :lesson-design-path="lessonEvaluationDesignPath"
        :runtime-enabled="runtimeEvaluationEnabled"
        :enabled-count="evaluationEnabledCount"
        :summary-items="evaluationSummaryItems"
        :data="evaluationData"
        :enable-teacher="evaluationForm.enable_teacher"
        :selected-student-id="selectedTeacherEvalStudentId"
        :selected-student="selectedTeacherEvalStudent"
        :teacher-criteria="teacherEvaluationCriteria"
        :ratings="teacherEvaluationRatings"
        :not-assessed="teacherEvaluationNotAssessed"
        :comment="teacherEvaluationComment"
        @close="evaluationOpen = false"
        @refresh="loadEvaluation()"
        @toggle-runtime="setRuntimeEvaluationEnabled"
        @select-student="selectTeacherEvaluationStudent"
        @rating="setTeacherEvaluationRating"
        @not-assessed="setTeacherEvaluationNotAssessed"
        @update:comment="teacherEvaluationComment = $event"
        @submit="submitTeacherEvaluation"
        @prepare-step="prepareEvaluationStep"
      />

      <ClassroomGroupCollaborationModal
        v-model:form="groupCollabForm"
        v-model:decision-form="groupingDecisionForm"
        v-model:candidate-key="groupingCandidateKey"
        v-model:grouping-draft="groupingDraft"
        v-model:grouping-locks="groupingLocks"
        v-model:grouping-note="groupingNote"
        v-model:active-document="activeGroupDocument"
        :open="groupCollabOpen"
        :loading="groupCollabLoading"
        :session-title="session.title"
        :class-label="classLabel()"
        :status-message="notice"
        :draft-saved="groupingDraftSaved"
        :collaboration="groupCollaboration"
        :strategy-options="groupingStrategyOptions"
        :students="groupingStudentOptions"
        :decision="groupingDecision"
        :grouping-run="groupingRun"
        :selected-candidate="selectedGroupingCandidate"
        :plan="groupingPlan"
        :fallback-message="groupingFallbackMessage"
        :collaboration-status-text="groupCollaborationOpenText"
        :groups="groupRows"
        @close="groupCollabOpen = false"
        @save-draft="saveGroupCollaborationDraft"
        @save-decision="saveGroupingDecision"
        @generate-candidates="generateGroupingCandidates"
        @close-collaboration="closeGroupCollaboration"
        @select-candidate="selectGroupingCandidate"
        @drag-start="onGroupingDragStart"
        @drag-end="draggedGroupingStudentId = null"
        @drop="onGroupingDrop"
        @set-student-group="setGroupingStudentGroup"
        @confirm-review="confirmGroupingPlan"
        @activate="activateGroupingPlan"
        @notify-students="notifyStudentsOfGroupingPlan"
        @restart-workflow="restartGroupingWorkflow"
        @refresh="refreshGroupingWorkflow"
      />

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

      <ClassroomInteractionModals
        v-model:attendance-filter="attendanceFilter"
        :session-title="session.title"
        :class-label="classLabel()"
        :attendance-open="attendanceOpen"
        :attendance-loading="attendanceLoading"
        :attendance-activity="attendanceActivity"
        :attendance-data="attendanceData"
        :attendance-rows="filteredAttendanceRows"
        :attendance-actions="attendanceStatusOptions"
        :quick-answer-open="quickAnswerOpen"
        :quick-answer-loading="quickAnswerLoading"
        :quick-answer-activity="quickAnswerActivity"
        :quick-answer-data="quickAnswerData"
        :random-pick-open="randomPickOpen"
        :random-pick-loading="randomPickLoading"
        :random-pick-activity="randomPickActivity"
        :random-pick-data="randomPickData"
        :random-pick-animating="randomPickAnimating"
        :random-pick-students="randomPickStudents"
        :random-pick-current-student-id="randomPickCurrentStudentId"
        :random-pick-picked-student="randomPickPickedStudent"
        :random-pick-display-student="randomPickDisplayStudent"
        @close-attendance="attendanceOpen = false"
        @refresh-attendance="openAttendancePanel"
        @close-activity="closeActivity"
        @mark-attendance="markAttendance"
        @close-quick-answer="closeQuickAnswerPanel"
        @score-quick-answer="scoreQuickAnswer"
        @close-random-pick="closeRandomPickPanel"
        @start-random-pick="startRandomPickDraw"
        @score-random-pick="scoreRandomPick"
      />

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
