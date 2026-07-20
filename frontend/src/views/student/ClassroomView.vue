<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ApiError } from '@/api/client'
import {
  acknowledgeClassroomScoreFeedback,
  getStudentClassroom,
  getStudentClassroomEvaluation,
  getStudentGroupCollaboration,
  recordClassroomResourceOpened,
  recordClassroomVideoProgress,
  respondClassroomActivity,
  submitStudentClassroomEvaluation,
  submitStudentStepAnswer,
  uploadStudentGroupFile,
  uploadStudentStepAttachment,
  type StudentClassroom,
  type StudentClassroomActivity,
  type StudentClassroomScoreFeedback,
  type StudentEvaluationContext,
  type StudentEvaluationCriterion,
  type StudentEvaluationType,
  type StudentGroupCollaboration,
  type StudentGroupFile,
  type StudentLessonQuestion,
  type StudentResourceBinding,
  type StudentWorkAttachment
} from '@/api/student'
import { useAuthStore } from '@/stores/auth'
import FilePicker from '@/components/FilePicker.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import OnlyOfficeEditor from '@/components/OnlyOfficeEditor.vue'
import ResourcePreview from '@/components/ResourcePreview.vue'
import ClassroomChatDock from '@/components/ClassroomChatDock.vue'
import EvaluationRatingInput from '@/components/evaluation/EvaluationRatingInput.vue'
import type { EvaluationNotAssessedEntry } from '@/domain/evaluation'

const route = useRoute()
const auth = useAuthStore()
const classroomId = computed(() => Number(route.params.sessionId || 0))
const classroom = ref<StudentClassroom | null>(null)
const selectedResourceIndex = ref(0)
const notice = ref('')
const loading = ref(false)
const respondingId = ref<number | null>(null)
const localResponses = ref<Record<number, boolean>>({})
const answerSubmitting = ref(false)
const answerDrafts = ref<Record<string, string>>({})
type QuestionAnswerValue = string | string[] | StudentWorkAttachment
const questionAnswerDrafts = ref<Record<string, Record<string, QuestionAnswerValue>>>({})
const uploadingQuestionId = ref('')
const taskModalOpen = ref(false)
const submittedStepIds = ref<Record<number, boolean>>({})
const nowTick = ref(Date.now())
const dismissedQuickAnswerIds = ref<Record<number, boolean>>({})
const dismissedBroadcastIds = ref<Record<number, boolean>>({})
const acknowledgedScoreEventIds = ref<Record<number, boolean>>({})
const scoreFeedbackOpen = ref(false)
const activeScoreFeedback = ref<(StudentClassroomScoreFeedback & { activity_id: number }) | null>(null)
const groupCollaboration = ref<StudentGroupCollaboration | null>(null)
const groupCollaborationLoading = ref(false)
const groupDocumentOpen = ref(false)
const groupFileDescription = ref('')
const groupFileUploading = ref(false)
const groupSelectedFile = ref<File | null>(null)
const evaluationContext = ref<StudentEvaluationContext | null>(null)
const evaluationOpen = ref(false)
const evaluationLoading = ref(false)
const evaluationSubmitting = ref(false)
const activeEvaluationType = ref<StudentEvaluationType>('self')
const selectedPeerTargetId = ref<number | null>(null)
const evaluationRatingDrafts = ref<Record<StudentEvaluationType, Record<string, number>>>({
  self: {},
  peer: {}
})
const evaluationNotAssessedDrafts = ref<
  Record<StudentEvaluationType, Record<string, EvaluationNotAssessedEntry>>
>({
  self: {},
  peer: {}
})
const evaluationCommentDrafts = ref<Record<StudentEvaluationType, string>>({
  self: '',
  peer: ''
})
let timerHandle: number | null = null
let refreshHandle: number | null = null

const currentStep = computed(() => classroom.value?.current_step || null)
const currentResources = computed(() => currentStep.value?.resource_items || [])
const currentQuestions = computed(() => currentStep.value?.question_items || [])
const openActivities = computed(() => classroom.value?.activities?.filter((item) => item.status === 'open') || [])
const activeTimerActivity = computed(() => openActivities.value.find((item) => commandOf(item) === 'timer') || null)
const quickAnswerActivity = computed(() => openActivities.value.find((item) => commandOf(item) === 'quick_answer') || null)
const quickAnswerModalOpen = ref(false)
const activeBroadcastActivity = computed(() => {
  return openActivities.value.find((item) => commandOf(item) === 'broadcast' && !hasResponded(item) && !dismissedBroadcastIds.value[item.id]) || null
})
const broadcastModalOpen = ref(false)
const randomPickActivity = computed(() => openActivities.value.find((item) => commandOf(item) === 'random_pick' && isPickedMe(item)) || null)
const randomPickModalOpen = ref(false)
const dismissedRandomPickIds = ref<Record<number, boolean>>({})
const selectedResource = computed<StudentResourceBinding | null>(() => {
  if (!currentResources.value.length) return null
  return currentResources.value[Math.min(selectedResourceIndex.value, currentResources.value.length - 1)] || null
})

function trackResourceOpened(payload: {
  resourceId: number | string
  presentation: 'embedded' | 'popout' | 'external' | 'download' | 'unknown'
}) {
  if (!classroom.value) return
  void recordClassroomResourceOpened(
    classroom.value.id,
    payload.resourceId,
    payload.presentation
  ).catch(() => undefined)
}

function trackVideoProgress(payload: {
  resourceId: number | string
  positionSeconds: number
  mediaSeconds: number
  playbackRate: number
  durationMs: number
}) {
  if (!classroom.value) return
  void recordClassroomVideoProgress(classroom.value.id, payload.resourceId, {
    position_seconds: payload.positionSeconds,
    media_seconds: payload.mediaSeconds,
    playback_rate: payload.playbackRate,
    duration_ms: payload.durationMs
  }).catch(() => undefined)
}
const answerDraft = computed({
  get() {
    const id = currentStep.value?.id
    return id ? answerDrafts.value[String(id)] || '' : ''
  },
  set(value: string) {
    const id = currentStep.value?.id
    if (!id) return
    answerDrafts.value = { ...answerDrafts.value, [String(id)]: value }
  }
})
const answerSubmitDisabled = computed(() => {
  return answerSubmitting.value
    || !currentStep.value
    || classroom.value?.current_step_status !== 'open'
    || Boolean(classroom.value?.submission_locked)
})
const hasSubmittedCurrentStep = computed(() => {
  const id = currentStep.value?.id
  return Boolean(id && submittedStepIds.value[id])
})
const stepNeedsTextAnswer = computed(() => {
  const stepType = String(currentStep.value?.step_type || '')
  return !currentQuestions.value.length && ['question', 'task', 'discussion', 'reflection', 'evaluation', 'ai_worksheet'].includes(stepType)
})
const hasTaskSubmission = computed(() => currentQuestions.value.length > 0 || stepNeedsTextAnswer.value)
const taskSummaryItems = computed(() => {
  return [
    { label: '题目', value: currentQuestions.value.length },
    { label: '资源', value: currentResources.value.length },
    { label: '活动', value: openActivities.value.length }
  ]
})
const myGroup = computed(() => groupCollaboration.value?.my_group || null)
const groupFiles = computed<StudentGroupFile[]>(() => myGroup.value?.files || [])
const groupStoragePercent = computed(() => {
  const group = myGroup.value
  const quota = Number(groupCollaboration.value?.storage_quota_mb || 0) * 1024 * 1024
  if (!group || !quota) return 0
  return Math.min(100, Math.round((group.used_storage_bytes / quota) * 100))
})
const groupStorageStyle = computed(() => ({ width: `${groupStoragePercent.value}%` }))
const selfEvaluationCriteria = computed(() => evaluationContext.value?.config.self_criteria || [])
const peerEvaluationCriteria = computed(() => evaluationContext.value?.config.peer_criteria || [])
const peerEvaluationTargets = computed(() => evaluationContext.value?.peer_targets || [])
const evaluationAvailable = computed(() => {
  const config = evaluationContext.value?.config
  return Boolean(config?.enable_self || (config?.enable_peer && peerEvaluationTargets.value.length))
})
const activeEvaluationCriteria = computed<StudentEvaluationCriterion[]>(() => (
  activeEvaluationType.value === 'self' ? selfEvaluationCriteria.value : peerEvaluationCriteria.value
))
const activePeerEvaluationTarget = computed(() => peerEvaluationTargets.value.find((item) => item.student_id === selectedPeerTargetId.value) || null)
const activeEvaluationSubmitted = computed(() => {
  if (activeEvaluationType.value === 'self') return Boolean(evaluationContext.value?.self_submission)
  return Boolean(activePeerEvaluationTarget.value?.submission)
})

const scoreFeedbackClass = computed(() => {
  const score = Number(activeScoreFeedback.value?.score || 0)
  if (score > 0) return 'positive'
  if (score < 0) return 'negative'
  return 'neutral'
})

function formatDate(value: string | null) {
  if (!value) return '未开始'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function resourceTitle(resource: StudentResourceBinding | null) {
  if (!resource) return ''
  return resource.title || resource.attachment_name || '未命名资源'
}

function questionAnswer(question: StudentLessonQuestion) {
  const stepId = currentStep.value?.id
  if (!stepId) return question.question_type === 'multiple' ? [] : ''
  const value = questionAnswerDrafts.value[String(stepId)]?.[question.id]
  if (question.question_type === 'multiple') return Array.isArray(value) ? value : []
  if (question.question_type === 'file') return value && typeof value === 'object' && !Array.isArray(value) ? value : null
  return typeof value === 'string' ? value : ''
}

function setQuestionAnswer(question: StudentLessonQuestion, value: QuestionAnswerValue) {
  const stepId = currentStep.value?.id
  if (!stepId) return
  questionAnswerDrafts.value = {
    ...questionAnswerDrafts.value,
    [String(stepId)]: {
      ...(questionAnswerDrafts.value[String(stepId)] || {}),
      [question.id]: value
    }
  }
}

function toggleMultipleAnswer(question: StudentLessonQuestion, value: string, checked: boolean) {
  const current = questionAnswer(question)
  const items = Array.isArray(current) ? current : []
  setQuestionAnswer(question, checked ? Array.from(new Set([...items, value])) : items.filter((item) => item !== value))
}

function optionChecked(question: StudentLessonQuestion, value: string) {
  const current = questionAnswer(question)
  return Array.isArray(current) ? current.includes(value) : current === value
}

function questionAnswerMissing(question: StudentLessonQuestion) {
  const value = questionAnswer(question)
  if (question.question_type === 'file') return !value || typeof value !== 'object'
  return Array.isArray(value) ? value.length === 0 : !String(value || '').trim()
}

function questionOptions(question: StudentLessonQuestion) {
  if (question.options.length) return question.options
  if (question.question_type === 'judge') return ['正确', '错误']
  return []
}

function validateQuestionAnswers() {
  for (const question of currentQuestions.value) {
    if (!question.is_required) continue
    if (questionAnswerMissing(question)) {
      notice.value = `请完成必答题：${question.stem}`
      return false
    }
  }
  return true
}

function attachmentAnswer(question: StudentLessonQuestion) {
  const value = questionAnswer(question)
  return value && typeof value === 'object' && !Array.isArray(value) ? value as StudentWorkAttachment : null
}

function fileAccept(question: StudentLessonQuestion) {
  const extensions = question.file_config?.allowed_extensions || []
  return extensions.map((item) => `.${String(item).replace(/^\./, '')}`).join(',')
}

function fileLimitText(question: StudentLessonQuestion) {
  const extensions = question.file_config?.allowed_extensions || []
  const extText = extensions.length ? extensions.map((item) => item.toUpperCase()).join(' / ') : '常见文档、图片和压缩包'
  return `${extText} · 不超过 ${question.file_config?.max_size_mb || 100}MB`
}

function formatFileSize(size: number) {
  if (!size) return '0 B'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

async function loadGroupCollaboration(silent = false) {
  if (!classroom.value) return
  if (groupCollaborationLoading.value) return
  groupCollaborationLoading.value = true
  try {
    groupCollaboration.value = await getStudentGroupCollaboration(classroom.value.id)
  } catch (error) {
    if (!silent) {
      notice.value = error instanceof ApiError ? error.message : '小组合作信息加载失败。'
    }
  } finally {
    groupCollaborationLoading.value = false
  }
}

function groupMemberText() {
  return myGroup.value?.members.map((member) => member.display_name || member.username).join('、') || '暂无成员'
}

async function uploadGroupFile(files: File[]) {
  const file = files[0]
  if (!file || !classroom.value) return
  groupSelectedFile.value = file
  if (!groupCollaboration.value?.allow_student_upload) {
    notice.value = '教师当前未开放小组共享文件上传。'
    groupSelectedFile.value = null
    return
  }
  groupFileUploading.value = true
  notice.value = ''
  try {
    await uploadStudentGroupFile(classroom.value.id, file, groupFileDescription.value.trim())
    groupFileDescription.value = ''
    await loadGroupCollaboration(true)
    notice.value = '小组文件已上传。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '小组文件上传失败。'
  } finally {
    groupFileUploading.value = false
    groupSelectedFile.value = null
  }
}

async function loadEvaluation(silent = false) {
  if (!classroom.value) return
  if (!silent) evaluationLoading.value = true
  try {
    const row = await getStudentClassroomEvaluation(classroom.value.id)
    evaluationContext.value = row
    if (row.peer_targets.length && !row.peer_targets.some((item) => item.student_id === selectedPeerTargetId.value)) {
      selectedPeerTargetId.value = row.peer_targets[0].student_id
    }
    if (!row.peer_targets.length) {
      selectedPeerTargetId.value = null
    }
    syncEvaluationDraft(activeEvaluationType.value)
  } catch (error) {
    if (!silent) {
      notice.value = error instanceof ApiError ? error.message : '课堂评价加载失败。'
    }
  } finally {
    if (!silent) evaluationLoading.value = false
  }
}

function syncEvaluationDraft(type: StudentEvaluationType) {
  const submission = type === 'self'
    ? evaluationContext.value?.self_submission
    : activePeerEvaluationTarget.value?.submission
  evaluationRatingDrafts.value = {
    ...evaluationRatingDrafts.value,
    [type]: submission?.ratings ? { ...submission.ratings } : {}
  }
  evaluationNotAssessedDrafts.value = {
    ...evaluationNotAssessedDrafts.value,
    [type]: submission?.not_assessed ? { ...submission.not_assessed } : {}
  }
  evaluationCommentDrafts.value = {
    ...evaluationCommentDrafts.value,
    [type]: submission?.comment || ''
  }
}

async function openStudentEvaluation(type: StudentEvaluationType = 'self') {
  activeEvaluationType.value = type
  evaluationOpen.value = true
  await loadEvaluation()
  if (type === 'peer' && !peerEvaluationTargets.value.length && evaluationContext.value?.config.enable_self) {
    activeEvaluationType.value = 'self'
  }
  syncEvaluationDraft(activeEvaluationType.value)
}

function switchEvaluationType(type: StudentEvaluationType) {
  activeEvaluationType.value = type
  if (type === 'peer' && !selectedPeerTargetId.value && peerEvaluationTargets.value.length) {
    selectedPeerTargetId.value = peerEvaluationTargets.value[0].student_id
  }
  syncEvaluationDraft(type)
}

function selectPeerEvaluationTarget(studentId: number) {
  selectedPeerTargetId.value = studentId
  syncEvaluationDraft('peer')
}

function setEvaluationRating(criterionId: string, value: number) {
  const notAssessed = { ...evaluationNotAssessedDrafts.value[activeEvaluationType.value] }
  delete notAssessed[criterionId]
  evaluationNotAssessedDrafts.value = {
    ...evaluationNotAssessedDrafts.value,
    [activeEvaluationType.value]: notAssessed
  }
  evaluationRatingDrafts.value = {
    ...evaluationRatingDrafts.value,
    [activeEvaluationType.value]: {
      ...evaluationRatingDrafts.value[activeEvaluationType.value],
      [criterionId]: value
    }
  }
}

function setEvaluationNotAssessed(criterionId: string, value: EvaluationNotAssessedEntry | null) {
  const type = activeEvaluationType.value
  const ratings = { ...evaluationRatingDrafts.value[type] }
  const notAssessed = { ...evaluationNotAssessedDrafts.value[type] }
  if (value) {
    delete ratings[criterionId]
    notAssessed[criterionId] = value
  } else {
    delete notAssessed[criterionId]
  }
  evaluationRatingDrafts.value = {
    ...evaluationRatingDrafts.value,
    [type]: ratings
  }
  evaluationNotAssessedDrafts.value = {
    ...evaluationNotAssessedDrafts.value,
    [type]: notAssessed
  }
}

function evaluationComment(type: StudentEvaluationType) {
  return evaluationCommentDrafts.value[type] || ''
}

function setEvaluationComment(type: StudentEvaluationType, value: string) {
  evaluationCommentDrafts.value = {
    ...evaluationCommentDrafts.value,
    [type]: value
  }
}

async function submitEvaluation() {
  if (!classroom.value) return
  if (!activeEvaluationCriteria.value.length) {
    notice.value = '暂无可提交的评价项。'
    return
  }
  if (activeEvaluationType.value === 'peer' && !activePeerEvaluationTarget.value) {
    notice.value = '请选择互评对象。'
    return
  }
  const ratings = evaluationRatingDrafts.value[activeEvaluationType.value]
  const notAssessed = evaluationNotAssessedDrafts.value[activeEvaluationType.value]
  for (const criterion of activeEvaluationCriteria.value) {
    if (!ratings[criterion.id] && !notAssessed[criterion.id]) {
      notice.value = `请为“${criterion.title}”选择星级或暂不评价。`
      return
    }
    const skipped = notAssessed[criterion.id]
    if (skipped?.reason === 'other' && !skipped.note.trim()) {
      notice.value = `请填写“${criterion.title}”暂不评价的具体说明。`
      return
    }
  }
  evaluationSubmitting.value = true
  notice.value = ''
  try {
    const row = await submitStudentClassroomEvaluation(classroom.value.id, {
      evaluation_type: activeEvaluationType.value,
      target: activeEvaluationType.value === 'peer' ? activePeerEvaluationTarget.value?.student_id : undefined,
      ratings,
      not_assessed: notAssessed,
      comment: evaluationComment(activeEvaluationType.value).trim()
    })
    evaluationContext.value = row
    syncEvaluationDraft(activeEvaluationType.value)
    notice.value = `${activeEvaluationType.value === 'self' ? '自评' : '互评'}已提交。`
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课堂评价提交失败。'
  } finally {
    evaluationSubmitting.value = false
  }
}

async function uploadQuestionFile(question: StudentLessonQuestion, files: File[]) {
  const file = files[0]
  if (!file || !currentStep.value) return
  if (answerSubmitDisabled.value) {
    notice.value = '当前环节暂不允许上传。'
    return
  }
  uploadingQuestionId.value = question.id
  notice.value = ''
  try {
    const attachment = await uploadStudentStepAttachment(currentStep.value.id, question.id, file)
    setQuestionAnswer(question, attachment)
    notice.value = '附件已上传，提交作答后教师端可查看。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '附件上传失败。'
  } finally {
    uploadingQuestionId.value = ''
  }
}

function submitButtonText() {
  if (answerSubmitting.value) return '提交中...'
  return hasSubmittedCurrentStep.value ? '重新提交' : '提交作答'
}

async function submitCurrentStepAnswer() {
  if (!classroom.value || !currentStep.value) return
  if (classroom.value.current_step_status !== 'open') {
    notice.value = '当前环节暂不允许提交。'
    return
  }
  if (classroom.value.submission_locked) {
    notice.value = '教师已锁定提交。'
    return
  }
  if (!validateQuestionAnswers()) return
  const hasStructuredQuestions = currentQuestions.value.length > 0
  const answer = hasStructuredQuestions
    ? {
        questions: questionAnswerDrafts.value[String(currentStep.value.id)] || {},
        text: answerDraft.value.trim()
      }
    : answerDraft.value.trim()
  if (!hasStructuredQuestions && !String(answer || '').trim()) {
    notice.value = '请先填写内容后再提交。'
    return
  }
  answerSubmitting.value = true
  notice.value = ''
  try {
    const result = await submitStudentStepAnswer(currentStep.value.id, answer)
    submittedStepIds.value = { ...submittedStepIds.value, [currentStep.value.id]: true }
    const scoreText = result.auto_score_max > 0 ? `，客观题 ${result.auto_score}/${result.auto_score_max} 分` : ''
    notice.value = `作答已提交${scoreText}。`
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '作答提交失败。'
  } finally {
    answerSubmitting.value = false
  }
}

function commandOf(activity: StudentClassroomActivity) {
  return String(activity.metadata?.command || activity.activity_type || '')
}

function activityDetail(activity: StudentClassroomActivity) {
  const metadata = activity.metadata || {}
  if (metadata.command === 'random_pick' && metadata.picked_student && typeof metadata.picked_student === 'object') {
    const student = metadata.picked_student as Record<string, unknown>
    return `点名：${String(student.display_name || student.username || '')}`
  }
  if (metadata.command === 'timer') {
    return timerText(activity)
  }
  if (metadata.command === 'broadcast') {
    return activity.content || '教师发送了一条课堂广播。'
  }
  return activity.content || activity.status_label
}

function activityStats(activity: StudentClassroomActivity) {
  const stats = activity.metadata?.stats
  return stats && typeof stats === 'object' ? stats as Record<string, unknown> : {}
}

function responseCount(activity: StudentClassroomActivity) {
  const value = Number(activityStats(activity).response_count || 0)
  return Number.isFinite(value) ? value : 0
}

function myResponse(activity: StudentClassroomActivity) {
  const responses = activityStats(activity).responses
  if (!Array.isArray(responses)) return null
  return responses.find((item) => {
    if (!item || typeof item !== 'object') return false
    const row = item as Record<string, unknown>
    if (Number(row.user_id) !== auth.user?.id) return false
    if (commandOf(activity) === 'sign_in') {
      return row.source === 'student' && row.attendance_status === 'signed'
    }
    return true
  }) as Record<string, unknown> | undefined || null
}

function hasResponded(activity: StudentClassroomActivity) {
  if (localResponses.value[activity.id]) return true
  return Boolean(myResponse(activity))
}

function myResponseTime(activity: StudentClassroomActivity) {
  const row = myResponse(activity)
  const value = String(row?.occurred_at || '')
  return value ? new Date(value).toLocaleTimeString('zh-CN', { hour12: false }) : ''
}

function quickAnswerScoreDefaults(activity: StudentClassroomActivity | null) {
  const defaults = activity?.metadata?.score_defaults
  if (!defaults || typeof defaults !== 'object') return { plus: 2, minus: -1 }
  const row = defaults as Record<string, unknown>
  const plus = Number(row.plus)
  const minus = Number(row.minus)
  return {
    plus: Number.isFinite(plus) ? plus : 2,
    minus: Number.isFinite(minus) ? minus : -1
  }
}

function formattedScore(value: number | string | null | undefined) {
  const score = Number(value || 0)
  return score > 0 ? `+${score}` : String(score)
}

function scoreFeedbackTitle() {
  const score = Number(activeScoreFeedback.value?.score || 0)
  const prefix = activeScoreFeedback.value?.command === 'random_pick' ? '随机点名' : '抢答'
  if (score > 0) return `${prefix}加分`
  if (score < 0) return `${prefix}减分`
  return `${prefix}评分`
}

function openQuickAnswerModalIfNeeded() {
  const activity = quickAnswerActivity.value
  if (!activity) {
    quickAnswerModalOpen.value = false
    return
  }
  if (!hasResponded(activity) && !dismissedQuickAnswerIds.value[activity.id] && !scoreFeedbackOpen.value) {
    quickAnswerModalOpen.value = true
  }
}

function openRandomPickModalIfNeeded() {
  const activity = randomPickActivity.value
  if (!activity) {
    randomPickModalOpen.value = false
    return
  }
  if (!hasResponded(activity) && !dismissedRandomPickIds.value[activity.id] && !scoreFeedbackOpen.value) {
    quickAnswerModalOpen.value = false
    randomPickModalOpen.value = true
  }
}

function openBroadcastModalIfNeeded() {
  const activity = activeBroadcastActivity.value
  if (!activity) {
    broadcastModalOpen.value = false
    return
  }
  if (!scoreFeedbackOpen.value && !quickAnswerModalOpen.value && !randomPickModalOpen.value) {
    broadcastModalOpen.value = true
  }
}

async function markScoreFeedbackSeen(activityId: number, feedback: StudentClassroomScoreFeedback) {
  if (!classroom.value || !feedback.event_id || acknowledgedScoreEventIds.value[feedback.event_id]) return
  acknowledgedScoreEventIds.value = {
    ...acknowledgedScoreEventIds.value,
    [feedback.event_id]: true
  }
  try {
    await acknowledgeClassroomScoreFeedback(classroom.value.id, activityId, feedback.event_id)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '评分反馈确认失败。'
  }
}

function detectScoreFeedback() {
  const activities = classroom.value?.activities || []
  for (const activity of activities) {
    const command = commandOf(activity)
    if (command !== 'quick_answer' && command !== 'random_pick') continue
    const feedback = activity.metadata?.my_score_feedback
    if (!feedback?.event_id) continue
    if (acknowledgedScoreEventIds.value[feedback.event_id]) continue
    activeScoreFeedback.value = { ...feedback, command: feedback.command || command, activity_id: activity.id }
    scoreFeedbackOpen.value = true
    quickAnswerModalOpen.value = false
    randomPickModalOpen.value = false
    broadcastModalOpen.value = false
    void markScoreFeedbackSeen(activity.id, feedback)
    return
  }
}

async function acknowledgeScoreFeedback() {
  scoreFeedbackOpen.value = false
  activeScoreFeedback.value = null
  openQuickAnswerModalIfNeeded()
  openRandomPickModalIfNeeded()
  openBroadcastModalIfNeeded()
}

function dismissQuickAnswerModal(activity: StudentClassroomActivity) {
  dismissedQuickAnswerIds.value = { ...dismissedQuickAnswerIds.value, [activity.id]: true }
  quickAnswerModalOpen.value = false
}

function dismissRandomPickModal(activity: StudentClassroomActivity) {
  dismissedRandomPickIds.value = { ...dismissedRandomPickIds.value, [activity.id]: true }
  randomPickModalOpen.value = false
  openBroadcastModalIfNeeded()
}

function dismissBroadcastModal(activity: StudentClassroomActivity) {
  dismissedBroadcastIds.value = { ...dismissedBroadcastIds.value, [activity.id]: true }
  broadcastModalOpen.value = false
}

async function acknowledgeBroadcast(activity: StudentClassroomActivity) {
  await respondActivity(activity, 'broadcast_seen')
  dismissedBroadcastIds.value = { ...dismissedBroadcastIds.value, [activity.id]: true }
  broadcastModalOpen.value = false
}

function pickedStudentName(activity: StudentClassroomActivity) {
  const picked = activity.metadata?.picked_student
  if (!picked || typeof picked !== 'object') return ''
  const row = picked as Record<string, unknown>
  return String(row.display_name || row.username || '')
}

function isPickedMe(activity: StudentClassroomActivity) {
  const picked = activity.metadata?.picked_student
  if (!picked || typeof picked !== 'object') return false
  return Number((picked as Record<string, unknown>).user_id) === auth.user?.id
}

function timerText(activity: StudentClassroomActivity) {
  return timerIsFinished(activity) ? '倒计时已结束' : `剩余 ${formatTimerClock(timerRemainingSeconds(activity))}`
}

function timerTotalSeconds(activity: StudentClassroomActivity | null) {
  const total = Number(activity?.metadata?.duration_seconds || 0)
  return Number.isFinite(total) && total > 0 ? total : 0
}

function timerRemainingSeconds(activity: StudentClassroomActivity | null) {
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

function timerProgressStyle(activity: StudentClassroomActivity | null) {
  const total = timerTotalSeconds(activity)
  const left = timerRemainingSeconds(activity)
  const percent = total ? Math.max(0, Math.min(100, (left / total) * 100)) : 0
  return { width: `${percent}%` }
}

function timerIsFinished(activity: StudentClassroomActivity | null) {
  return Boolean(activity) && timerRemainingSeconds(activity) <= 0
}

async function respondActivity(activity: StudentClassroomActivity, responseType?: string) {
  if (!classroom.value) return
  respondingId.value = activity.id
  notice.value = ''
  try {
    const row = await respondClassroomActivity(classroom.value.id, activity.id, {
      response_type: responseType || commandOf(activity)
    })
    localResponses.value = { ...localResponses.value, [activity.id]: true }
    classroom.value.activities = classroom.value.activities.map((item) => item.id === row.id ? row : item)
    if (commandOf(activity) === 'quick_answer') {
      quickAnswerModalOpen.value = true
    }
    if (commandOf(activity) === 'random_pick') {
      randomPickModalOpen.value = false
    }
    notice.value = commandOf(activity) === 'sign_in' ? '签到成功。' : '已提交课堂响应。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课堂响应提交失败。'
  } finally {
    respondingId.value = null
  }
}

function applyClassroomData(data: StudentClassroom) {
  const previousStepId = classroom.value?.current_step?.id || null
  classroom.value = data
  const nextStepId = data.current_step?.id || null
  if (previousStepId && nextStepId !== previousStepId) {
    taskModalOpen.value = false
    selectedResourceIndex.value = 0
  }
  detectScoreFeedback()
  openQuickAnswerModalIfNeeded()
  openRandomPickModalIfNeeded()
  openBroadcastModalIfNeeded()
  void loadGroupCollaboration(true)
  void loadEvaluation(true)
}

async function loadPage() {
  loading.value = true
  notice.value = ''
  try {
    const data = await getStudentClassroom(classroomId.value)
    selectedResourceIndex.value = 0
    applyClassroomData(data)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课堂信息加载失败。'
  } finally {
    loading.value = false
  }
}

async function refreshClassroomSilently() {
  try {
    const data = await getStudentClassroom(classroomId.value)
    applyClassroomData(data)
  } catch {
    // Polling is a temporary realtime fallback. Keep the current classroom view stable on transient failures.
  }
}

function handleRealtimeClassroomEvent(payload: { type?: string }) {
  if (payload.type === 'grouping.updated') {
    void loadGroupCollaboration(true)
  }
}

onMounted(async () => {
  timerHandle = window.setInterval(() => {
    nowTick.value = Date.now()
  }, 1000)
  refreshHandle = window.setInterval(() => {
    if (!loading.value && classroom.value) {
      refreshClassroomSilently()
    }
  }, 2000)
  if (!auth.loaded) {
    await auth.load()
  }
  await loadPage()
})

onUnmounted(() => {
  if (timerHandle !== null) {
    window.clearInterval(timerHandle)
  }
  if (refreshHandle !== null) {
    window.clearInterval(refreshHandle)
  }
})
</script>

<template>
  <main class="classroom-fullscreen-page student-classroom-fullscreen">
    <NoticeLine v-if="notice" :message="notice" />
    <section v-if="loading" class="student-panel">
      <p class="empty">正在加载课堂</p>
    </section>

    <section v-else-if="!classroom" class="student-panel">
      <p class="empty">课堂尚未开放，请等待教师开始课堂。</p>
    </section>

    <section v-else class="student-classroom-panel live-classroom-workspace">
      <article class="live-classroom-head">
        <div>
          <span>{{ classroom.status_label }} · {{ classroom.current_step_status_label }}</span>
          <strong>{{ classroom.title }}</strong>
        </div>
        <p>
          {{ classroom.teacher.display_name }} · {{ classroom.course?.title || '未绑定课程' }} ·
          {{ classroom.lesson?.title || '未指定课时' }}
        </p>
        <small>开始时间：{{ formatDate(classroom.started_at) }}</small>
      </article>

      <section v-if="activeTimerActivity" class="student-timer-banner" :class="{ finished: timerIsFinished(activeTimerActivity) }">
        <div>
          <span>课堂倒计时</span>
          <strong>{{ formatTimerClock(timerRemainingSeconds(activeTimerActivity)) }}</strong>
          <small>{{ timerIsFinished(activeTimerActivity) ? '时间到' : activeTimerActivity.content }}</small>
        </div>
        <div class="timer-progress-track" aria-hidden="true">
          <i :style="timerProgressStyle(activeTimerActivity)"></i>
        </div>
      </section>

      <article v-if="!currentStep" class="student-panel student-classroom-note">
        <h2>等待教师投放环节</h2>
        <p>课堂已经开始，请保持当前页面，教师投放学习环节后会自动刷新。</p>
      </article>

      <section v-else class="student-workspace-grid student-classroom-step-grid">
        <article class="student-resource-pane student-classroom-resource-pane" :class="{ 'has-resource-tabs': currentResources.length > 1 }">

          <div v-if="currentResources.length > 1" class="student-resource-tabs">
            <button
              v-for="(resource, index) in currentResources"
              :key="`${resource.id || resource.title}-${index}`"
              type="button"
              :class="{ active: selectedResourceIndex === index }"
              @click="selectedResourceIndex = index"
            >
              {{ resourceTitle(resource) }}
            </button>
          </div>

          <div class="student-preview-stage">
            <ResourcePreview
              :resource="selectedResource"
              office-mode="view"
              content-only
              learning-page-interactive
              @resource-opened="trackResourceOpened"
              @video-progress="trackVideoProgress"
            />
          </div>
        </article>

        <aside class="student-step-pane">
          <section class="student-step-detail">
            <header>
              <div>
                <span>本环节任务</span>
                <h2>{{ currentStep.title }}</h2>
              </div>
              <small>
                {{ classroom.current_step_status_label }}{{ classroom.submission_locked ? ' · 提交已锁定' : '' }}
              </small>
            </header>
            <p class="student-instruction">
              {{ currentStep.student_instruction || '教师暂未填写学生可见说明。' }}
            </p>

            <section class="student-task-summary-card">
              <div class="student-task-stat-grid">
                <div v-for="item in taskSummaryItems" :key="item.label">
                  <strong>{{ item.value }}</strong>
                  <span>{{ item.label }}</span>
                </div>
              </div>
              <p v-if="hasTaskSubmission">
                {{ hasSubmittedCurrentStep ? '本环节已提交，可根据教师要求重新提交。' : '点击按钮进入作答面板，题目和附件上传会在弹窗中完成。' }}
              </p>
              <p v-else>当前环节没有需要提交的课堂题，按教师要求学习左侧资源。</p>
              <button
                v-if="hasTaskSubmission"
                class="student-primary-action"
                type="button"
                @click="taskModalOpen = true"
              >
                {{ hasSubmittedCurrentStep ? '查看 / 修改作答' : '开始作答' }}
              </button>
            </section>

            <section v-if="evaluationAvailable" class="student-evaluation-entry-card">
              <header>
                <div>
                  <span>课堂评价</span>
                  <strong>5 星评价</strong>
                </div>
                <small>{{ activeEvaluationSubmitted ? '已提交，可修改' : '待完成' }}</small>
              </header>
              <p>
                <template v-if="evaluationContext?.config.enable_self">自评</template>
                <template v-if="evaluationContext?.config.enable_self && evaluationContext?.config.enable_peer && peerEvaluationTargets.length"> · </template>
                <template v-if="evaluationContext?.config.enable_peer && peerEvaluationTargets.length">小组互评</template>
              </p>
              <button class="student-primary-action compact" type="button" @click="openStudentEvaluation(evaluationContext?.config.enable_self ? 'self' : 'peer')">
                进入评价
              </button>
            </section>

            <section class="student-live-activity-panel">
              <header>
                <span>课堂控制</span>
                <strong>{{ openActivities.length }} 个进行中</strong>
              </header>
              <article v-for="activity in openActivities" :key="activity.id">
                <header>
                  <span>{{ activity.activity_type_label }}</span>
                  <small v-if="responseCount(activity)">已响应 {{ responseCount(activity) }} 人</small>
                </header>
                <strong>{{ activity.title }}</strong>
                <p>{{ activityDetail(activity) }}</p>

                <div class="student-activity-action-row">
                  <button
                    v-if="commandOf(activity) === 'sign_in'"
                    class="student-primary-action compact"
                    type="button"
                    :disabled="respondingId === activity.id || hasResponded(activity)"
                    @click="respondActivity(activity, 'sign_in')"
                  >
                    {{ hasResponded(activity) ? '已签到' : '签到' }}
                  </button>
                  <span v-if="commandOf(activity) === 'sign_in' && hasResponded(activity)" class="student-sign-success">
                    签到成功{{ myResponseTime(activity) ? ` · ${myResponseTime(activity)}` : '' }}
                  </span>
                  <button
                    v-else-if="commandOf(activity) === 'quick_answer'"
                    class="student-primary-action compact"
                    type="button"
                    :disabled="respondingId === activity.id || hasResponded(activity)"
                    @click="respondActivity(activity, 'quick_answer')"
                  >
                    {{ hasResponded(activity) ? '已抢答' : '抢答' }}
                  </button>
                  <span v-else-if="commandOf(activity) === 'random_pick'" :class="isPickedMe(activity) ? 'picked-me' : ''">
                    {{ isPickedMe(activity) ? '请准备回答' : `点名：${pickedStudentName(activity) || '等待教师确认'}` }}
                  </span>
                  <button
                    v-if="commandOf(activity) === 'random_pick' && isPickedMe(activity)"
                    class="student-primary-action compact"
                    type="button"
                    :disabled="respondingId === activity.id || hasResponded(activity)"
                    @click="respondActivity(activity, 'random_pick_ready')"
                  >
                    {{ hasResponded(activity) ? '已回应' : '我已准备' }}
                  </button>
                  <span v-else-if="commandOf(activity) === 'timer'">{{ timerText(activity) }}</span>
                  <button
                    v-if="commandOf(activity) === 'timer'"
                    class="student-ghost-button compact"
                    type="button"
                    :disabled="respondingId === activity.id || hasResponded(activity)"
                    @click="respondActivity(activity, 'timer_seen')"
                  >
                    {{ hasResponded(activity) ? '已确认' : '知道了' }}
                  </button>
                  <button
                    v-if="commandOf(activity) === 'broadcast'"
                    class="student-ghost-button compact"
                    type="button"
                    :disabled="respondingId === activity.id || hasResponded(activity)"
                    @click="acknowledgeBroadcast(activity)"
                  >
                    {{ hasResponded(activity) ? '已确认' : '已读' }}
                  </button>
                </div>
              </article>
              <p v-if="!openActivities.length" class="empty">等待教师发起签到、抢答或课堂广播。</p>
            </section>

            <section v-if="groupCollaboration && myGroup" class="student-group-collaboration-card">
              <header>
                <div>
                  <span>小组合作</span>
                  <strong>{{ myGroup.name }}</strong>
                </div>
                <button class="student-primary-action compact" type="button" @click="groupDocumentOpen = true">
                  {{ groupCollaboration.allow_onlyoffice_edit ? '打开协作文档' : '查看协作文档' }}
                </button>
              </header>
              <p>{{ groupMemberText() }}</p>
              <div class="student-group-member-chips">
                <span v-for="member in myGroup.members" :key="member.id" :class="{ leader: member.role === 'leader' }">
                  {{ member.display_name || member.username }}{{ member.role === 'leader' ? ' · 组长' : '' }}
                </span>
              </div>
              <div class="student-group-storage">
                <div>
                  <strong>{{ myGroup.used_storage_mb }}MB</strong>
                  <span>/ {{ groupCollaboration.storage_quota_mb }}MB</span>
                </div>
                <i><em :style="groupStorageStyle"></em></i>
              </div>
              <div v-if="groupCollaboration.allow_student_upload" class="student-group-upload">
                <input v-model.trim="groupFileDescription" maxlength="120" placeholder="文件说明，可不填" />
                <FilePicker
                  label="小组共享文件"
                  hint="选择后立即上传，并计入小组共享空间。"
                  choose-text="选择并上传"
                  :file="groupSelectedFile"
                  :disabled="groupFileUploading"
                  :busy="groupFileUploading"
                  compact
                  @select="uploadGroupFile"
                />
              </div>
              <div class="student-group-file-list">
                <a v-for="file in groupFiles" :key="file.id" :href="file.attachment_url" download>
                  <strong>{{ file.attachment_name }}</strong>
                  <span>{{ file.uploader?.display_name || '成员' }} · {{ formatFileSize(file.file_size) }}</span>
                </a>
                <p v-if="!groupFiles.length" class="empty">小组共享区暂无文件。</p>
              </div>
            </section>
          </section>
        </aside>
      </section>

      <div v-if="taskModalOpen && currentStep" class="modal-backdrop student-task-modal-backdrop" role="presentation" @click.self="taskModalOpen = false">
        <section class="student-task-modal" role="dialog" aria-modal="true" aria-labelledby="student-task-modal-title">
          <header class="student-task-modal-header">
            <div>
              <span>{{ classroom.current_step_status_label }}{{ classroom.submission_locked ? ' · 提交已锁定' : '' }}</span>
              <h2 id="student-task-modal-title">{{ currentStep.title }}</h2>
            </div>
            <button class="student-ghost-button compact" type="button" @click="taskModalOpen = false">关闭</button>
          </header>

          <div class="student-task-modal-body">
            <p class="student-instruction modal-instruction">
              {{ currentStep.student_instruction || '教师暂未填写学生可见说明。' }}
            </p>

            <div v-if="currentQuestions.length" class="student-lesson-question-list modal-question-list">
              <section v-for="(question, index) in currentQuestions" :key="question.id" class="student-lesson-question-card">
                <header>
                  <span>{{ question.question_type_label }}{{ question.is_required ? ' · 必答' : ' · 选答' }}</span>
                  <small>{{ question.score }} 分</small>
                </header>
                <h3>{{ index + 1 }}. {{ question.stem }}</h3>

                <div v-if="question.question_type === 'single' || question.question_type === 'judge'" class="student-option-list">
                  <label v-for="option in questionOptions(question)" :key="`${question.id}-${option}`">
                    <input
                      type="radio"
                      :name="`classroom-question-${currentStep.id}-${question.id}`"
                      :checked="optionChecked(question, option)"
                      :disabled="answerSubmitDisabled"
                      @change="setQuestionAnswer(question, option)"
                    />
                    <span>{{ option }}</span>
                  </label>
                </div>

                <div v-else-if="question.question_type === 'multiple'" class="student-option-list">
                  <label v-for="option in questionOptions(question)" :key="`${question.id}-${option}`">
                    <input
                      type="checkbox"
                      :checked="optionChecked(question, option)"
                      :disabled="answerSubmitDisabled"
                      @change="toggleMultipleAnswer(question, option, ($event.target as HTMLInputElement).checked)"
                    />
                    <span>{{ option }}</span>
                  </label>
                </div>

                <label v-else-if="question.question_type === 'blank'" class="student-answer-box inline-answer">
                  <span>我的答案</span>
                  <input
                    :value="String(questionAnswer(question) || '')"
                    :disabled="answerSubmitDisabled"
                    placeholder="填写答案"
                    @input="setQuestionAnswer(question, ($event.target as HTMLInputElement).value)"
                  />
                </label>

                <div v-else-if="question.question_type === 'file'" class="student-file-answer-box">
                  <FilePicker
                    label="提交附件"
                    :hint="fileLimitText(question)"
                    :accept="fileAccept(question)"
                    :disabled="answerSubmitDisabled || uploadingQuestionId === question.id"
                    :busy="uploadingQuestionId === question.id"
                    choose-text="选择并上传"
                    replace-text="重新上传"
                    status-label="已上传"
                    :current-name="attachmentAnswer(question)?.attachment_name || ''"
                    :current-detail="attachmentAnswer(question) ? formatFileSize(attachmentAnswer(question)?.attachment_size || 0) : ''"
                    compact
                    @select="uploadQuestionFile(question, $event)"
                  />
                </div>

                <label v-else class="student-answer-box">
                  <span>我的答案</span>
                  <textarea
                    :value="String(questionAnswer(question) || '')"
                    :disabled="answerSubmitDisabled"
                    rows="4"
                    placeholder="填写你的分析、说明或反思"
                    @input="setQuestionAnswer(question, ($event.target as HTMLTextAreaElement).value)"
                  ></textarea>
                </label>
              </section>
            </div>

            <label v-else-if="stepNeedsTextAnswer" class="student-answer-box classroom-text-answer">
              <span>我的作答</span>
              <textarea
                v-model="answerDraft"
                :disabled="answerSubmitDisabled"
                rows="8"
                placeholder="在这里填写答案、讨论内容、任务说明或学习反思"
              ></textarea>
            </label>
          </div>

          <footer class="student-classroom-answer-actions student-task-modal-actions">
            <span v-if="hasSubmittedCurrentStep" class="student-answer-submitted">已提交，教师端可查看。</span>
            <span v-else-if="classroom.submission_locked" class="student-answer-locked">教师已锁定提交。</span>
            <span v-else-if="classroom.current_step_status !== 'open'" class="student-answer-locked">当前环节未开放提交。</span>
            <span v-else>完成后提交，教师端会实时看到完成情况。</span>
            <button
              class="student-primary-action"
              type="button"
              :disabled="answerSubmitDisabled"
              @click="submitCurrentStepAnswer"
            >
              {{ submitButtonText() }}
            </button>
          </footer>
        </section>
      </div>

      <div v-if="evaluationOpen && evaluationContext" class="student-command-modal-backdrop student-evaluation-backdrop" role="presentation" @click.self="evaluationOpen = false">
        <section class="student-evaluation-modal" role="dialog" aria-modal="true" aria-labelledby="student-evaluation-title">
          <header>
            <div>
              <span>课堂评价</span>
              <h2 id="student-evaluation-title">{{ activeEvaluationType === 'self' ? '自评' : '小组互评' }}</h2>
            </div>
            <button class="student-ghost-button compact" type="button" :disabled="evaluationSubmitting" @click="evaluationOpen = false">关闭</button>
          </header>

          <div class="student-evaluation-tabs">
            <button
              v-if="evaluationContext.config.enable_self"
              type="button"
              :class="{ active: activeEvaluationType === 'self' }"
              @click="switchEvaluationType('self')"
            >
              自评
              <small v-if="evaluationContext.self_submission">已提交</small>
            </button>
            <button
              v-if="evaluationContext.config.enable_peer && peerEvaluationTargets.length"
              type="button"
              :class="{ active: activeEvaluationType === 'peer' }"
              @click="switchEvaluationType('peer')"
            >
              互评
              <small>{{ peerEvaluationTargets.length }} 位同组成员</small>
            </button>
          </div>

          <div v-if="activeEvaluationType === 'peer'" class="student-peer-targets">
            <button
              v-for="target in peerEvaluationTargets"
              :key="target.student_id"
              type="button"
              :class="{ active: selectedPeerTargetId === target.student_id }"
              @click="selectPeerEvaluationTarget(target.student_id)"
            >
              <strong>{{ target.display_name || target.username }}</strong>
              <span>{{ target.submission ? '已互评' : '未互评' }}</span>
            </button>
          </div>

          <div class="student-evaluation-list">
            <EvaluationRatingInput
              v-for="criterion in activeEvaluationCriteria"
              :key="`${activeEvaluationType}-${criterion.id}`"
              :criterion="criterion"
              :rating="evaluationRatingDrafts[activeEvaluationType][criterion.id] || 0"
              :not-assessed="evaluationNotAssessedDrafts[activeEvaluationType][criterion.id] || null"
              :disabled="evaluationSubmitting"
              @rating="setEvaluationRating"
              @not-assessed="setEvaluationNotAssessed"
            />
            <p v-if="!activeEvaluationCriteria.length" class="empty">当前暂无评价项。</p>
          </div>

          <label class="student-answer-box student-evaluation-comment">
            <span>补充说明</span>
            <textarea
              :value="evaluationComment(activeEvaluationType)"
              maxlength="1000"
              rows="3"
              placeholder="可选，写下学习反思或对同伴协作的具体观察。"
              @input="setEvaluationComment(activeEvaluationType, ($event.target as HTMLTextAreaElement).value)"
            ></textarea>
          </label>

          <footer class="student-classroom-answer-actions student-evaluation-actions">
            <span>{{ activeEvaluationSubmitted ? '已提交，可根据教师要求修改。' : '按实际材料选择星级；没有材料时选择暂不评价。' }}</span>
            <button
              class="student-primary-action"
              type="button"
              :disabled="evaluationSubmitting || evaluationLoading || !activeEvaluationCriteria.length"
              @click="submitEvaluation"
            >
              {{ evaluationSubmitting ? '提交中...' : activeEvaluationSubmitted ? '更新评价' : '提交评价' }}
            </button>
          </footer>
        </section>
      </div>

      <div v-if="groupDocumentOpen && myGroup" class="student-command-modal-backdrop student-group-document-backdrop" role="presentation" @click.self="groupDocumentOpen = false">
        <section class="student-group-document-modal" role="dialog" aria-modal="true" aria-labelledby="student-group-document-title">
          <header>
            <div>
              <span>小组协作</span>
              <h2 id="student-group-document-title">{{ myGroup.name }} · {{ myGroup.document.attachment_name }}</h2>
            </div>
            <button class="student-ghost-button compact" type="button" @click="groupDocumentOpen = false">关闭</button>
          </header>
          <div class="student-group-document-editor">
            <OnlyOfficeEditor :group-id="myGroup.id" :mode="groupCollaboration?.allow_onlyoffice_edit ? 'edit' : 'view'" />
          </div>
        </section>
      </div>

      <div v-if="broadcastModalOpen && activeBroadcastActivity" class="student-command-modal-backdrop" role="presentation">
        <section class="student-command-modal broadcast-student-modal" role="dialog" aria-modal="true" aria-labelledby="student-broadcast-title">
          <header>
            <div>
              <span>课堂广播</span>
              <h2 id="student-broadcast-title">{{ activeBroadcastActivity.title }}</h2>
            </div>
            <button
              class="student-ghost-button compact"
              type="button"
              :disabled="respondingId === activeBroadcastActivity.id"
              @click="dismissBroadcastModal(activeBroadcastActivity)"
            >
              稍后处理
            </button>
          </header>
          <p class="broadcast-message-text">{{ activeBroadcastActivity.content || '教师发送了一条课堂广播。' }}</p>
          <small>{{ formatDate(activeBroadcastActivity.opened_at) }}</small>
          <button
            class="student-primary-action quick-answer-main-button"
            type="button"
            :disabled="respondingId === activeBroadcastActivity.id || hasResponded(activeBroadcastActivity)"
            @click="acknowledgeBroadcast(activeBroadcastActivity)"
          >
            {{ hasResponded(activeBroadcastActivity) ? '已确认' : respondingId === activeBroadcastActivity.id ? '确认中...' : '知道了' }}
          </button>
        </section>
      </div>

      <div v-if="scoreFeedbackOpen && activeScoreFeedback" class="student-command-modal-backdrop" role="presentation">
        <section
          class="student-command-modal quick-answer-score-modal"
          :class="scoreFeedbackClass"
          role="dialog"
          aria-modal="true"
          aria-labelledby="student-score-feedback-title"
        >
          <header>
            <div>
              <span>教师已评分</span>
              <h2 id="student-score-feedback-title">{{ scoreFeedbackTitle() }}</h2>
            </div>
          </header>
          <div class="score-feedback-value">{{ formattedScore(activeScoreFeedback.score) }}</div>
          <p>{{ activeScoreFeedback.score_note || '教师已记录本次课堂表现。' }}</p>
          <small>活动：{{ activeScoreFeedback.activity_title || scoreFeedbackTitle() }} · {{ formatDate(activeScoreFeedback.occurred_at) }}</small>
          <button class="student-primary-action quick-answer-main-button" type="button" @click="acknowledgeScoreFeedback">
            知道了
          </button>
        </section>
      </div>

      <div v-if="randomPickModalOpen && randomPickActivity" class="student-command-modal-backdrop" role="presentation">
        <section class="student-command-modal random-pick-student-modal" role="dialog" aria-modal="true" aria-labelledby="student-random-pick-title">
          <header>
            <div>
              <span>随机点名</span>
              <h2 id="student-random-pick-title">你被点名了</h2>
            </div>
            <button
              class="student-ghost-button compact"
              type="button"
              :disabled="respondingId === randomPickActivity.id"
              @click="dismissRandomPickModal(randomPickActivity)"
            >
              稍后处理
            </button>
          </header>
          <p>{{ randomPickActivity.content || '教师已随机点名，请准备回答。' }}</p>
          <div class="quick-answer-score-hint">
            <span>默认加分 +{{ quickAnswerScoreDefaults(randomPickActivity).plus }}</span>
            <span>默认减分 {{ quickAnswerScoreDefaults(randomPickActivity).minus }}</span>
          </div>
          <button
            class="student-primary-action quick-answer-main-button"
            type="button"
            :disabled="respondingId === randomPickActivity.id || hasResponded(randomPickActivity)"
            @click="respondActivity(randomPickActivity, 'random_pick_ready')"
          >
            {{ hasResponded(randomPickActivity) ? '已回应' : respondingId === randomPickActivity.id ? '提交中...' : '我已准备' }}
          </button>
          <small v-if="hasResponded(randomPickActivity)">
            已回应{{ myResponseTime(randomPickActivity) ? ` · ${myResponseTime(randomPickActivity)}` : '' }}，等待教师评分。
          </small>
        </section>
      </div>

      <div v-if="quickAnswerModalOpen && quickAnswerActivity" class="student-command-modal-backdrop" role="presentation">
        <section class="student-command-modal quick-answer-student-modal" role="dialog" aria-modal="true" aria-labelledby="student-quick-answer-title">
          <header>
            <div>
              <span>璇惧爞鎶㈢瓟</span>
              <h2 id="student-quick-answer-title">{{ quickAnswerActivity.title }}</h2>
            </div>
            <button
              class="student-ghost-button compact"
              type="button"
              :disabled="respondingId === quickAnswerActivity.id"
              @click="dismissQuickAnswerModal(quickAnswerActivity)"
            >
              绋嶅悗澶勭悊
            </button>
          </header>
          <p>{{ quickAnswerActivity.content || '教师已开启抢答，请确认后点击抢答。' }}</p>
          <div class="quick-answer-score-hint">
            <span>榛樿鍔犲垎 +{{ quickAnswerScoreDefaults(quickAnswerActivity).plus }}</span>
            <span>榛樿鍑忓垎 {{ quickAnswerScoreDefaults(quickAnswerActivity).minus }}</span>
          </div>
          <button
            class="student-primary-action quick-answer-main-button"
            type="button"
            :disabled="respondingId === quickAnswerActivity.id || hasResponded(quickAnswerActivity)"
            @click="respondActivity(quickAnswerActivity, 'quick_answer')"
          >
            {{ hasResponded(quickAnswerActivity) ? '已抢答' : respondingId === quickAnswerActivity.id ? '提交中...' : '立即抢答' }}
          </button>
          <small v-if="hasResponded(quickAnswerActivity)">
            已提交抢答{{ myResponseTime(quickAnswerActivity) ? ` · ${myResponseTime(quickAnswerActivity)}` : '' }}，等待教师确认。
          </small>
        </section>
      </div>
    </section>
    <ClassroomChatDock
      v-if="classroom"
      :session-id="classroom.id"
      role="student"
      :running="classroom.status === 'running'"
      @classroom-event="handleRealtimeClassroomEvent"
    />
  </main>
</template>
