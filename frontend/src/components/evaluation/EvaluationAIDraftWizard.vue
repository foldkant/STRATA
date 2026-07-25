<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ApiError } from '@/api/client'
import {
  cancelEvaluationAIDraft,
  confirmEvaluationAIDraftModes,
  createEvaluationAIDraft,
  generateEvaluationAIDraft,
  getEvaluationAIDraft,
  getEvaluationAIDrafts,
  retrieveEvaluationAIDraftReferences,
  saveEvaluationAIPlanDraft,
  suggestEvaluationAIDraftModes,
  type EvaluationAIDraftCheck,
  type EvaluationAIDraftContext,
  type EvaluationAIDraftReviewDecision,
  type EvaluationAIDraftRow,
  type EvaluationAIStandardDraft,
  type EvaluationAIStandardVersionOption,
  type EvaluationOptions,
  type EvaluationPlanPayload,
  type EvaluationPlanRow,
  type EvaluationStandardRow,
  type EvaluationTaskMode
} from '@/api/evaluation'
import { vModalFocus } from '@/directives/modalFocus'

const props = defineProps<{
  options: EvaluationOptions
  initialCourseId?: number | null
  initialGradeOrStage?: string
  initialUnitTitle?: string
  initialCourseContent?: string
  initialContentSourceLabel?: string
  initialEvaluationPurpose?: EvaluationAIDraftContext['evaluation_purpose']
}>()

const emit = defineEmits<{
  close: []
  saved: [row: EvaluationPlanRow, standard: EvaluationStandardRow]
}>()

type ReviewDecision = EvaluationAIDraftReviewDecision['decision'] | 'pending'
type ReviewItem = {
  key: string
  type: EvaluationAIDraftReviewDecision['item_type']
  code: string
  label: string
  model: Record<string, any>
  field?: string
  parentCode?: string
}

const progressSteps = ['确认教学信息', '核对课标依据', '生成并审阅初稿', '保存草稿']
const progressStep = computed(() => step.value === 1 ? 1 : step.value === 2 ? 2 : step.value < 7 ? 3 : 4)
const progressMaxStep = computed(() => maxStep.value === 1 ? 1 : maxStep.value === 2 ? 2 : maxStep.value < 7 ? 3 : 4)
const requiredReferenceTypes = [
  { value: 'core_competency', label: '核心素养' },
  { value: 'course_objective', label: '课程目标' },
  { value: 'course_content', label: '课程内容' },
  { value: 'academic_quality', label: '学业质量' }
] as const
const purposeOptions = [
  { value: 'entry_diagnostic', label: '学习起点诊断' },
  { value: 'formative', label: '形成性评价' },
  { value: 'summative', label: '阶段性评价' },
  { value: 'project', label: '项目学习评价' }
] as const
const processingStatuses = new Set([
  'queued',
  'retrieving_references',
  'suggesting_modes',
  'generating_draft'
])

const step = ref(1)
const maxStep = ref(1)
const session = ref<EvaluationAIDraftRow | null>(null)
const recentSessions = ref<EvaluationAIDraftRow[]>([])
const standardVersions = ref<EvaluationAIStandardVersionOption[]>([])
const loadingSessions = ref(false)
const actionBusy = ref(false)
const polling = ref(false)
const busyMessage = ref('')
const notice = ref('')
const noticeTone = ref<'error' | 'warning' | 'info'>('info')
const modeSelections = ref<EvaluationTaskMode[]>([])
const teacherModeNote = ref('')
const planDraft = ref<EvaluationPlanPayload | null>(null)
const standardDraft = ref<EvaluationAIStandardDraft | null>(null)
const scoringItemKeys = ref<Record<string, string>>({})
const reviewDecisions = reactive<Record<string, ReviewDecision>>({})
const saveAcknowledged = ref(false)
const cancelConfirm = ref(false)
const batchAcceptConfirm = ref(false)
const regenerateConfirm = ref(false)
const saved = ref(false)
const createdContextFingerprint = ref('')
let pendingCreationFingerprint = ''
let pendingCreationKey = ''
let pollController: AbortController | null = null
let componentActive = true

function newCreationKey() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  return `ai-evaluation-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

const firstCourse = props.options.courses.find((item) => item.id === Number(props.initialCourseId)) || props.options.courses[0]
const context = reactive<EvaluationAIDraftContext>({
  course_id: firstCourse?.id || 0,
  school_stage: firstCourse?.school_stage || 'k1_k9',
  grade_or_stage: props.initialGradeOrStage?.trim() || '',
  unit_title: props.initialUnitTitle?.trim().slice(0, 120) || '',
  curriculum_standard_version_id: 0,
  course_content: props.initialCourseContent?.trim().slice(0, 4000) || '',
  evaluation_purpose: props.initialEvaluationPurpose || 'formative'
})

const selectedCourse = computed(() => props.options.courses.find((item) => item.id === Number(context.course_id)) || null)
function normalizedSubject(value: string) {
  const key = value.toLowerCase().replace(/[\s_\-·]/g, '')
  const aliases: Record<string, string> = {
    informationtechnology: 'information_technology',
    信息技术: 'information_technology',
    信息科技: 'information_technology'
  }
  return aliases[key] || key
}

function standardMatchesCourse(item: EvaluationAIStandardVersionOption) {
  const course = selectedCourse.value
  if (!course || item.school_stage !== context.school_stage) return false
  if (Array.isArray(item.compatible_course_ids)) return item.compatible_course_ids.includes(course.id)
  const courseKeys = new Set([normalizedSubject(course.subject.name), normalizedSubject(course.subject.code)])
  return [item.subject.name, item.subject.code].some((value) => courseKeys.has(normalizedSubject(value)))
}

const availableStandardVersions = computed(() => standardVersions.value.filter(standardMatchesCourse))
const contextValid = computed(() => Boolean(
  context.course_id
  && context.school_stage
  && context.grade_or_stage.trim()
  && context.unit_title.trim().length >= 2
  && context.curriculum_standard_version_id
  && context.course_content.trim().length >= 10
  && context.evaluation_purpose
))
const contextActionLabel = computed(() => {
  if (actionBusy.value || polling.value) return '正在检索课标依据'
  if (!context.course_id) return '请先选择课程'
  if (!context.grade_or_stage.trim()) return '请先填写年级或适用阶段'
  if (context.unit_title.trim().length < 2) return '请先填写单元或主题'
  if (!context.curriculum_standard_version_id) return '请先选择课程标准版本'
  if (context.course_content.trim().length < 10) return '请先补充本次课程内容'
  if (!context.evaluation_purpose) return '请先选择评价用途'
  return '检索课标依据'
})
const selectedReferenceTypes = computed(() => new Set((session.value?.curriculum_references || []).map((item) => item.node_type)))
const referenceCoverageComplete = computed(() => requiredReferenceTypes.every((item) => selectedReferenceTypes.value.has(item.value)))
const unfinishedSessions = computed(() => recentSessions.value.filter((item) => !['saved', 'cancelled'].includes(item.status)).slice(0, 3))
const backgroundMessage = computed(() => session.value?.background_task?.message || busyMessage.value)
const totalTaskWeight = computed(() => (planDraft.value?.evaluation_tasks || []).reduce((sum, item) => sum + Number(item.weight || 0), 0))

const reviewItems = computed<ReviewItem[]>(() => {
  if (!planDraft.value || !standardDraft.value) return []
  const rows: ReviewItem[] = [{
    key: 'overall:plan',
    type: 'overall',
    code: '',
    label: '方案整体设置',
    model: planDraft.value as unknown as Record<string, any>
  }]
  planDraft.value.learning_goals.forEach((item) => rows.push({
    key: `learning_goal:${item.code}`,
    type: 'learning_goal',
    code: item.code,
    label: '学习目标',
    model: item
  }))
  planDraft.value.evaluation_basis.forEach((item) => rows.push({
    key: `evaluation_basis:${item.code}`,
    type: 'evaluation_basis',
    code: item.code,
    label: '评价依据',
    model: item
  }))
  planDraft.value.learning_activities.forEach((item) => rows.push({
    key: `learning_activity:${item.code}`,
    type: 'learning_activity',
    code: item.code,
    label: '学习活动',
    model: item
  }))
  planDraft.value.learning_tasks.forEach((item) => rows.push({
    key: `learning_task:${item.code}`,
    type: 'learning_task',
    code: item.code,
    label: '学习任务',
    model: item
  }))
  planDraft.value.evaluation_tasks.forEach((item) => rows.push({
    key: `evaluation_task:${item.code}`,
    type: 'evaluation_task',
    code: item.code,
    label: '评价任务',
    model: item
  }))
  rows.push({
    key: 'follow_up_suggestion:plan',
    type: 'follow_up_suggestion',
    code: 'plan',
    label: '方案后续教学建议',
    model: planDraft.value as unknown as Record<string, any>,
    field: 'follow_up_suggestion'
  })
  rows.push({
    key: 'overall:standard',
    type: 'overall',
    code: '',
    label: '评价标准整体设置',
    model: standardDraft.value as unknown as Record<string, any>
  })
  standardDraft.value.criteria.forEach((criterion) => {
    rows.push({
      key: `evaluation_criterion:${criterion.code}`,
      type: 'evaluation_criterion',
      code: criterion.code,
      label: '评价指标',
      model: criterion
    })
    Object.keys(criterion.level_descriptions || {}).forEach((level) => rows.push({
      key: `performance_level:${criterion.code}:${level}`,
      type: 'performance_level',
      code: `${criterion.code}:${level}`,
      label: `表现水平 · ${level}`,
      model: criterion.level_descriptions,
      field: level,
      parentCode: criterion.code
    }))
    criterion.scoring_examples.forEach((example, index) => rows.push({
      key: scoringItemKeys.value[`${criterion.code}:${index}`] || `scoring_example:${criterion.code}:${example.level}:${index + 1}`,
      type: 'scoring_example',
      code: (scoringItemKeys.value[`${criterion.code}:${index}`] || `scoring_example:${criterion.code}:${example.level}:${index + 1}`).replace('scoring_example:', ''),
      label: `评分示例 · ${example.level} 星`,
      model: example,
      parentCode: criterion.code
    }))
    rows.push({
      key: `follow_up_suggestion:${criterion.code}`,
      type: 'follow_up_suggestion',
      code: criterion.code,
      label: '后续教学建议',
      model: criterion,
      field: 'follow_up_suggestion',
      parentCode: criterion.code
    })
  })
  return rows
})
const allItemsReviewed = computed(() => reviewItems.value.length > 0 && reviewItems.value.every((item) => reviewDecisions[item.key] !== 'pending'))
const pendingReviewItems = computed(() => reviewItems.value.filter((item) => decision(item) === 'pending'))
const initialCourseContent = computed(() => props.initialCourseContent?.trim().slice(0, 4000) || '')
const courseContentWasPrefilled = computed(() => Boolean(initialCourseContent.value))
const checks = computed(() => {
  const merged = new Map<string, EvaluationAIDraftCheck>()
  for (const item of session.value?.checks || []) merged.set(item.code, item)
  for (const item of localChecks.value) merged.set(item.code, item)
  return Array.from(merged.values())
})
const blockedChecks = computed(() => checks.value.filter((item) => item.status === 'blocked'))
const hasBlockedCheck = computed(() => checks.value.some((item) => item.status === 'blocked'))
const canFinishReview = computed(() => allItemsReviewed.value && !hasBlockedCheck.value)
const saveDraftActionLabel = computed(() => {
  if (actionBusy.value) return '正在保存草稿'
  if (!saveAcknowledged.value) return '请先勾选上方确认'
  if (!canFinishReview.value) return '请先完成审阅与内容检查'
  return '保存为评价草稿'
})

function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function contextFingerprint(value: EvaluationAIDraftContext) {
  return JSON.stringify({
    ...value,
    grade_or_stage: value.grade_or_stage.trim(),
    unit_title: value.unit_title.trim(),
    course_content: value.course_content.trim()
  })
}

function normalizedContext(): EvaluationAIDraftContext {
  return {
    ...context,
    course_id: Number(context.course_id),
    curriculum_standard_version_id: Number(context.curriculum_standard_version_id),
    grade_or_stage: context.grade_or_stage.trim(),
    unit_title: context.unit_title.trim(),
    course_content: context.course_content.trim()
  }
}

function ensurePlanShape(value: EvaluationPlanPayload): EvaluationPlanPayload {
  return {
    ...cloneJson(value),
    learning_goals: cloneJson(value.learning_goals || []),
    evaluation_basis: cloneJson(value.evaluation_basis || []),
    learning_activities: cloneJson(value.learning_activities || []),
    learning_tasks: cloneJson(value.learning_tasks || []),
    evaluation_tasks: cloneJson(value.evaluation_tasks || []),
    assessment_modes: [...(value.assessment_modes || [])],
    content_scope: [...(value.content_scope || [])],
    thinking_requirements: [...(value.thinking_requirements || [])],
    support_options: [...(value.support_options || [])],
    curriculum_node_ids: [...(value.curriculum_node_ids || [])],
    scoring_rules: {
      approach: value.scoring_rules?.approach || '',
      decision_rule: value.scoring_rules?.decision_rule || ''
    }
  }
}

function ensureStandardShape(value: EvaluationAIStandardDraft): EvaluationAIStandardDraft {
  return {
    ...cloneJson(value),
    criteria: (value.criteria || []).map((criterion) => ({
      ...cloneJson(criterion),
      evaluation_sources: [...(criterion.evaluation_sources || [])],
      learning_goal_codes: [...(criterion.learning_goal_codes || [])],
      evaluation_task_codes: [...(criterion.evaluation_task_codes || [])],
      material_types: [...(criterion.material_types || [])],
      support_options: [...(criterion.support_options || [])],
      common_problems: [...(criterion.common_problems || [])],
      level_descriptions: Object.fromEntries(
        Array.from({ length: 5 }, (_, index) => {
          const level = String(index + 1)
          return [level, criterion.level_descriptions?.[level] || '']
        })
      ),
      scoring_examples: cloneJson(criterion.scoring_examples || [])
    }))
  }
}

function applySession(row: EvaluationAIDraftRow) {
  if (!componentActive) return
  const changedSession = session.value?.id !== row.id
  session.value = row
  modeSelections.value = [...(row.confirmed_modes?.length
    ? row.confirmed_modes
    : row.mode_suggestions?.filter((item) => item.recommended).map((item) => item.mode) || [])]
  teacherModeNote.value = row.teacher_mode_note || teacherModeNote.value
  if (row.plan_draft) {
    planDraft.value = ensurePlanShape(row.plan_draft)
  }
  if (row.standard_draft) {
    standardDraft.value = ensureStandardShape(row.standard_draft)
    if (changedSession) scoringItemKeys.value = {}
    standardDraft.value.criteria.forEach((criterion) => criterion.scoring_examples.forEach((example, index) => {
      const slot = `${criterion.code}:${index}`
      if (!scoringItemKeys.value[slot]) scoringItemKeys.value[slot] = `scoring_example:${criterion.code}:${example.level}:${index + 1}`
    }))
  }
  if (row.plan_draft && row.standard_draft) initializeReviewDecisions()
}

function initializeReviewDecisions() {
  for (const item of reviewItems.value) {
    if (!reviewDecisions[item.key]) reviewDecisions[item.key] = 'pending'
  }
}

function hydrateContext(row: EvaluationAIDraftRow) {
  Object.assign(context, cloneJson(row.context))
  createdContextFingerprint.value = contextFingerprint(row.context)
}

function stepForSession(row: EvaluationAIDraftRow) {
  if (row.plan_draft && row.standard_draft) return row.status === 'teacher_reviewed' ? 7 : 6
  if (row.confirmed_modes?.length) return 5
  if (row.mode_suggestions?.length) return 3
  if (row.curriculum_references?.length) return 2
  return 1
}

function apiMessage(error: unknown, fallback: string) {
  if (!(error instanceof ApiError)) return error instanceof Error && error.message ? error.message : fallback
  const first = Object.values(error.errors)[0]?.[0]
  return first ? `${error.message} ${first}` : error.message
}

function setError(error: unknown, fallback: string) {
  notice.value = apiMessage(error, fallback)
  noticeTone.value = 'error'
}

function clearNotice() {
  notice.value = ''
  noticeTone.value = 'info'
}

function stopPolling() {
  pollController?.abort()
  pollController = null
  polling.value = false
}

function ensureComponentActive() {
  if (!componentActive) throw new DOMException('Dialog closed', 'AbortError')
}

function waitForNextPoll(signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const timer = window.setTimeout(resolve, 1200)
    signal.addEventListener('abort', () => {
      window.clearTimeout(timer)
      reject(new DOMException('Polling stopped', 'AbortError'))
    }, { once: true })
  })
}

async function waitForSession(
  initial: EvaluationAIDraftRow,
  ready: (row: EvaluationAIDraftRow) => boolean,
  message: string
) {
  ensureComponentActive()
  applySession(initial)
  if (ready(initial)) return initial
  if (!processingStatuses.has(initial.status) && initial.background_task?.status !== 'queued' && initial.background_task?.status !== 'running') {
    throw new Error(initial.background_task?.message || '后台任务没有返回可用结果。')
  }
  stopPolling()
  const controller = new AbortController()
  pollController = controller
  polling.value = true
  busyMessage.value = `${message}。任务在后台运行，可暂时关闭后稍后继续。`
  const startedAt = Date.now()
  try {
    while (!controller.signal.aborted && Date.now() - startedAt < 120_000) {
      await waitForNextPoll(controller.signal)
      const row = await getEvaluationAIDraft(initial.id, controller.signal)
      ensureComponentActive()
      applySession(row)
      if (row.status === 'failed' || row.background_task?.status === 'failed') {
        throw new Error(row.background_task?.message || '后台任务执行失败。')
      }
      if (ready(row)) return row
    }
    throw new Error('后台任务仍在运行。你可以暂时关闭，稍后从未完成会话继续。')
  } finally {
    if (pollController === controller) pollController = null
    polling.value = false
  }
}

async function loadSessions() {
  if (loadingSessions.value) return
  loadingSessions.value = true
  clearNotice()
  try {
    const result = await getEvaluationAIDrafts()
    ensureComponentActive()
    recentSessions.value = result.results || []
    standardVersions.value = result.curriculum_standard_versions || []
  } catch (error) {
    setError(error, '课程标准版本与未完成会话加载失败，请重试。')
  } finally {
    loadingSessions.value = false
  }
}

async function resumeDraft(id: number) {
  if (actionBusy.value) return
  actionBusy.value = true
  busyMessage.value = '正在恢复未完成会话'
  clearNotice()
  try {
    const row = await getEvaluationAIDraft(id)
    ensureComponentActive()
    applySession(row)
    hydrateContext(row)
    const targetStep = stepForSession(row)
    step.value = targetStep
    maxStep.value = Math.max(maxStep.value, targetStep)
    if (processingStatuses.has(row.status) || ['queued', 'running'].includes(row.background_task?.status || '')) {
      notice.value = '后台任务仍在运行，页面将自动刷新结果；也可以暂时关闭后稍后继续。'
      noticeTone.value = 'info'
      if (row.status === 'retrieving_references') {
        await waitForSession(row, (item) => item.curriculum_references.length > 0, '正在检索课程标准原文')
        step.value = maxStep.value = 2
      } else if (row.status === 'suggesting_modes') {
        await waitForSession(row, (item) => item.mode_suggestions.length > 0, '正在形成评价方式建议')
        step.value = maxStep.value = 3
      } else if (row.status === 'generating_draft') {
        await waitForSession(row, (item) => Boolean(item.plan_draft && item.standard_draft), '正在生成评价方案与评价标准初稿')
        step.value = maxStep.value = 6
      }
    }
  } catch (error) {
    if ((error as DOMException)?.name !== 'AbortError') setError(error, '未完成会话恢复失败。')
  } finally {
    actionBusy.value = false
    busyMessage.value = ''
  }
}

async function createAndRetrieve() {
  if (!contextValid.value || actionBusy.value) return
  actionBusy.value = true
  busyMessage.value = '正在建立会话并检索课程标准原文'
  clearNotice()
  try {
    const payload = normalizedContext()
    const fingerprint = contextFingerprint(payload)
    let row = session.value
    if (!row || createdContextFingerprint.value !== fingerprint) {
      if (pendingCreationFingerprint !== fingerprint || !pendingCreationKey) {
        pendingCreationFingerprint = fingerprint
        pendingCreationKey = newCreationKey()
      }
      row = await createEvaluationAIDraft(payload, pendingCreationKey)
      ensureComponentActive()
      applySession(row)
      createdContextFingerprint.value = fingerprint
    }
    const result = await retrieveEvaluationAIDraftReferences(row.id)
    ensureComponentActive()
    await waitForSession(result, (item) => item.curriculum_references.length > 0, '正在检索课程标准原文')
    step.value = 2
    maxStep.value = Math.max(maxStep.value, 2)
  } catch (error) {
    if ((error as DOMException)?.name !== 'AbortError') setError(error, '课程标准原文检索失败，请核对课程内容后重试。')
  } finally {
    actionBusy.value = false
    busyMessage.value = ''
  }
}

async function suggestModes() {
  if (!session.value || !referenceCoverageComplete.value || actionBusy.value) return
  actionBusy.value = true
  busyMessage.value = '正在形成评价方式建议'
  clearNotice()
  try {
    const result = await suggestEvaluationAIDraftModes(session.value.id)
    ensureComponentActive()
    await waitForSession(result, (item) => item.mode_suggestions.length > 0, '正在形成评价方式建议')
    step.value = 3
    maxStep.value = Math.max(maxStep.value, 3)
  } catch (error) {
    if ((error as DOMException)?.name !== 'AbortError') setError(error, '评价方式建议生成失败，请重试。')
  } finally {
    actionBusy.value = false
    busyMessage.value = ''
  }
}

function openModeConfirmation() {
  if (!session.value?.mode_suggestions.length) return
  step.value = 4
  maxStep.value = Math.max(maxStep.value, 4)
}

function toggleMode(mode: EvaluationTaskMode, checked: boolean) {
  modeSelections.value = checked
    ? Array.from(new Set([...modeSelections.value, mode]))
    : modeSelections.value.filter((item) => item !== mode)
}

async function confirmModes() {
  if (!session.value || !modeSelections.value.length || actionBusy.value) return
  actionBusy.value = true
  busyMessage.value = '正在保存教师确认的评价方式'
  clearNotice()
  try {
    const result = await confirmEvaluationAIDraftModes(session.value.id, {
      modes: modeSelections.value,
      teacher_note: teacherModeNote.value.trim()
    })
    ensureComponentActive()
    applySession(result)
    step.value = 5
    maxStep.value = Math.max(maxStep.value, 5)
  } catch (error) {
    setError(error, '评价方式确认失败，请重试。')
  } finally {
    actionBusy.value = false
    busyMessage.value = ''
  }
}

async function confirmModesAndGenerate() {
  if (!session.value || !modeSelections.value.length || actionBusy.value || polling.value) return
  actionBusy.value = true
  busyMessage.value = '正在保存评价方式并生成初稿'
  clearNotice()
  try {
    const confirmed = await confirmEvaluationAIDraftModes(session.value.id, {
      modes: modeSelections.value,
      teacher_note: teacherModeNote.value.trim()
    })
    ensureComponentActive()
    applySession(confirmed)
    maxStep.value = Math.max(maxStep.value, 5)
    const result = await generateEvaluationAIDraft(confirmed.id)
    ensureComponentActive()
    await waitForSession(
      result,
      (item) => Boolean(item.plan_draft && item.standard_draft),
      '正在生成评价方案与评价标准完整初稿'
    )
    step.value = 6
    maxStep.value = Math.max(maxStep.value, 6)
  } catch (error) {
    if ((error as DOMException)?.name !== 'AbortError') {
      setError(error, '评价方式确认或初稿生成失败，请稍后重试。')
    }
  } finally {
    actionBusy.value = false
    busyMessage.value = ''
  }
}

async function generateDraft() {
  if (!session.value?.confirmed_modes.length || actionBusy.value) return
  actionBusy.value = true
  busyMessage.value = '正在生成评价方案与评价标准完整初稿'
  clearNotice()
  try {
    const result = await generateEvaluationAIDraft(session.value.id)
    ensureComponentActive()
    await waitForSession(result, (item) => Boolean(item.plan_draft && item.standard_draft), '正在生成评价方案与评价标准完整初稿')
    step.value = 6
    maxStep.value = Math.max(maxStep.value, 6)
  } catch (error) {
    if ((error as DOMException)?.name !== 'AbortError') setError(error, '评价方案与评价标准初稿生成失败，请重试。')
  } finally {
    actionBusy.value = false
    busyMessage.value = ''
  }
}

function requestRegenerateDraft() {
  if (!session.value || actionBusy.value || polling.value) return
  regenerateConfirm.value = true
}

function closeRegenerateConfirm() {
  regenerateConfirm.value = false
}

function resetReviewState() {
  for (const key of Object.keys(reviewDecisions)) delete reviewDecisions[key]
  planDraft.value = null
  standardDraft.value = null
  scoringItemKeys.value = {}
  batchAcceptConfirm.value = false
}

async function regenerateDraft() {
  if (!session.value || actionBusy.value || polling.value) return
  regenerateConfirm.value = false
  actionBusy.value = true
  busyMessage.value = '正在让 AI 重新完善评价初稿'
  clearNotice()
  resetReviewState()
  try {
    const result = await generateEvaluationAIDraft(session.value.id, { regenerate: true })
    ensureComponentActive()
    const completed = await waitForSession(
      result,
      (item) => Boolean(item.plan_draft && item.standard_draft),
      '正在重新完善评价方案与评价标准初稿'
    )
    applySession(completed)
    step.value = 6
    maxStep.value = Math.max(maxStep.value, 6)
    noticeTone.value = blockedChecks.value.length ? 'warning' : 'info'
    notice.value = blockedChecks.value.length
      ? `AI 已重新形成初稿，仍有 ${blockedChecks.value.length} 项需要教师处理。`
      : 'AI 已重新形成完整初稿，请重新完成教师审阅。'
  } catch (error) {
    if ((error as DOMException)?.name !== 'AbortError') setError(error, 'AI 重新完善初稿失败，请稍后重试。')
  } finally {
    actionBusy.value = false
    busyMessage.value = ''
  }
}

function decision(item: ReviewItem) {
  return reviewDecisions[item.key] || 'pending'
}

function setDecision(item: ReviewItem, value: ReviewDecision) {
  reviewDecisions[item.key] = value
  if (item.type === 'evaluation_criterion') {
    for (const child of reviewItems.value.filter((candidate) => candidate.parentCode === item.code)) {
      reviewDecisions[child.key] = value === 'removed' ? 'removed' : 'pending'
    }
  }
}

function restoreInitialCourseContent() {
  if (!initialCourseContent.value || actionBusy.value || polling.value) return
  context.course_content = initialCourseContent.value
  clearNotice()
  notice.value = `已重新读取${props.initialContentSourceLabel || '当前课时'}的课程内容。`
}

function requestBatchAccept() {
  if (!pendingReviewItems.value.length) return
  batchAcceptConfirm.value = true
}

function confirmBatchAccept() {
  for (const item of pendingReviewItems.value) {
    reviewDecisions[item.key] = 'accepted'
  }
  batchAcceptConfirm.value = false
  noticeTone.value = 'info'
  notice.value = '已批量采纳全部待审阅项；已修改和已删除的内容保持不变。'
}

function markModified(item: ReviewItem) {
  if (decision(item) !== 'removed') reviewDecisions[item.key] = 'modified'
}

function toggleMappedValue(item: ReviewItem, field: string, value: string, checked: boolean) {
  const current = Array.isArray(item.model[field]) ? item.model[field] as string[] : []
  item.model[field] = checked
    ? Array.from(new Set([...current, value]))
    : current.filter((entry) => entry !== value)
  markModified(item)
}

function sanitizeReviewedDraft() {
  if (!planDraft.value) return null
  const result = ensurePlanShape(planDraft.value)
  const removed = new Set(Object.entries(reviewDecisions).filter(([, value]) => value === 'removed').map(([key]) => key))
  const removedGoals = new Set(result.learning_goals.filter((item) => removed.has(`learning_goal:${item.code}`)).map((item) => item.code))
  const removedActivities = new Set(result.learning_activities.filter((item) => removed.has(`learning_activity:${item.code}`)).map((item) => item.code))
  const removedBasis = new Set(result.evaluation_basis.filter((item) => removed.has(`evaluation_basis:${item.code}`)).map((item) => item.code))
  result.learning_goals = result.learning_goals.filter((item) => !removedGoals.has(item.code))
  result.evaluation_basis = result.evaluation_basis
    .filter((item) => !removed.has(`evaluation_basis:${item.code}`))
    .map((item) => ({ ...item, goal_codes: item.goal_codes.filter((code) => !removedGoals.has(code)) }))
  result.learning_activities = result.learning_activities
    .filter((item) => !removedActivities.has(item.code))
    .map((item) => ({ ...item, goal_codes: item.goal_codes.filter((code) => !removedGoals.has(code)) }))
  result.learning_tasks = result.learning_tasks
    .filter((item) => !removed.has(`learning_task:${item.code}`))
    .map((item) => ({ ...item, basis_codes: item.basis_codes.filter((code) => !removedBasis.has(code)) }))
  result.evaluation_tasks = result.evaluation_tasks
    .filter((item) => !removed.has(`evaluation_task:${item.code}`))
    .map((item) => ({
      ...item,
      goal_codes: item.goal_codes.filter((code) => !removedGoals.has(code)),
      activity_codes: item.activity_codes.filter((code) => !removedActivities.has(code))
    }))
  result.assessment_modes = Array.from(new Set(result.evaluation_tasks.map((item) => item.mode)))
  if (removed.has('follow_up_suggestion:plan')) result.follow_up_suggestion = ''
  return result
}

function sanitizeReviewedStandard(plan: EvaluationPlanPayload | null) {
  if (!standardDraft.value || !plan) return null
  const result = ensureStandardShape(standardDraft.value)
  const removed = new Set(Object.entries(reviewDecisions).filter(([, value]) => value === 'removed').map(([key]) => key))
  const goalCodes = new Set(plan.learning_goals.map((item) => item.code))
  const taskCodes = new Set(plan.evaluation_tasks.map((item) => item.code))
  result.criteria = result.criteria
    .filter((criterion) => !removed.has(`evaluation_criterion:${criterion.code}`))
    .map((criterion) => {
      const levels = { ...criterion.level_descriptions }
      for (const level of Object.keys(levels)) {
        if (removed.has(`performance_level:${criterion.code}:${level}`)) delete levels[level]
      }
      return {
        ...criterion,
        learning_goal_codes: criterion.learning_goal_codes.filter((code) => goalCodes.has(code)),
        evaluation_task_codes: criterion.evaluation_task_codes.filter((code) => taskCodes.has(code)),
        level_descriptions: levels,
        scoring_examples: criterion.scoring_examples.filter((example, index) => !removed.has(
          scoringItemKeys.value[`${criterion.code}:${index}`] || `scoring_example:${criterion.code}:${example.level}:${index + 1}`
        )),
        follow_up_suggestion: removed.has(`follow_up_suggestion:${criterion.code}`) ? '' : criterion.follow_up_suggestion
      }
    })
  return result
}

const localChecks = computed<EvaluationAIDraftCheck[]>(() => {
  const draft = sanitizeReviewedDraft()
  if (!draft) return []
  const referenceIds = new Set(session.value?.curriculum_references.map((item) => item.id) || [])
  const goalCodes = new Set(draft.learning_goals.map((item) => item.code))
  const basisCodes = new Set(draft.evaluation_basis.map((item) => item.code))
  const activityCodes = new Set(draft.learning_activities.map((item) => item.code))
  const referencesValid = draft.learning_goals.length > 0 && draft.learning_goals.every((goal) => (
    goal.curriculum_node_ids.length > 0 && goal.curriculum_node_ids.every((id) => referenceIds.has(id))
  ))
  const mappingValid = draft.evaluation_basis.length > 0
    && draft.evaluation_basis.every((basis) => basis.goal_codes.length > 0 && basis.goal_codes.every((code) => goalCodes.has(code)))
    && draft.learning_activities.length > 0
    && draft.learning_activities.every((activity) => activity.goal_codes.length > 0 && activity.goal_codes.every((code) => goalCodes.has(code)))
    && draft.learning_tasks.length > 0
    && draft.learning_tasks.every((task) => task.basis_codes.length > 0 && task.basis_codes.every((code) => basisCodes.has(code)))
    && draft.evaluation_tasks.length > 0
    && draft.evaluation_tasks.every((task) => (
      task.goal_codes.length > 0
      && task.goal_codes.every((code) => goalCodes.has(code))
      && task.activity_codes.length > 0
      && task.activity_codes.every((code) => activityCodes.has(code))
    ))
  const ownershipValid = draft.evaluation_tasks.length > 0 && draft.evaluation_tasks.every((task) => (
    ['individual', 'group', 'both'].includes(task.evidence_ownership) && task.material_types.length > 0
  ))
  const weightsValid = draft.evaluation_tasks.length > 0
    && draft.evaluation_tasks.every((task) => Number.isFinite(Number(task.weight)) && Number(task.weight) >= 0 && Number(task.weight) <= 100)
    && Math.abs(draft.evaluation_tasks.reduce((sum, task) => sum + Number(task.weight), 0) - 100) < 0.001
  const standard = sanitizeReviewedStandard(draft)
  const criterionMappingValid = Boolean(standard?.criteria.length) && standard!.criteria.every((criterion) => (
    criterion.learning_goal_codes.length > 0
    && criterion.learning_goal_codes.every((code) => goalCodes.has(code))
    && criterion.evaluation_task_codes.length > 0
    && criterion.evaluation_task_codes.every((code) => draft.evaluation_tasks.some((task) => task.code === code))
  ))
  const performanceLevelsValid = Boolean(standard?.criteria.length) && standard!.criteria.every((criterion) => (
    criterion.expected_performance.trim().length > 0
    && Array.from({ length: 5 }, (_, index) => String(index + 1)).every((level) => criterion.level_descriptions[level]?.trim().length > 0)
  ))
  const scoringExamplesValid = Boolean(standard?.criteria.length) && standard!.criteria.every((criterion) => (
    criterion.scoring_examples.length >= 2
    && new Set(criterion.scoring_examples.map((example) => example.level)).size >= 2
    && criterion.scoring_examples.every((example) => (
      Number.isFinite(Number(example.level))
      && Number(example.level) >= 1
      && Number(example.level) <= 5
      && example.title.trim().length > 0
      && example.example_description.trim().length > 0
    ))
  ))
  return [
    {
      code: 'curriculum_trace',
      label: '课程标准引用',
      status: referencesValid ? 'passed' : 'blocked',
      message: referencesValid ? '每条学习目标均保留可追溯课程标准条目。' : '存在未对应所选课标原文的学习目标，请修改或删除。'
    },
    {
      code: 'goal_task_mapping',
      label: '目标—活动—任务对应',
      status: mappingValid ? 'passed' : 'blocked',
      message: mappingValid ? '评价依据、学习活动、学习任务与评价任务的对应关系完整。' : '存在目标—依据—活动—任务对应不完整的项目，请在对应选择中修正。'
    },
    {
      code: 'evidence_ownership',
      label: '个人与小组材料归属',
      status: ownershipValid ? 'passed' : 'blocked',
      message: ownershipValid ? '每项任务均明确材料归属与材料类型。' : '存在材料归属或材料类型不完整的评价任务，请修改或删除。'
    },
    {
      code: 'task_weights',
      label: '评价任务权重',
      status: weightsValid ? 'passed' : 'blocked',
      message: weightsValid ? '评价任务权重合计为 100。' : '每项任务权重应在 0—100 之间，且所有保留任务的权重合计必须为 100。'
    },
    {
      code: 'criterion_mapping',
      label: '评价指标对应关系',
      status: criterionMappingValid ? 'passed' : 'blocked',
      message: criterionMappingValid ? '每项评价指标均对应有效学习目标和评价任务。' : '存在未对应学习目标或评价任务的评价指标，请在对应选择中修正。'
    },
    {
      code: 'performance_levels',
      label: '预期表现与表现水平',
      status: performanceLevelsValid ? 'passed' : 'blocked',
      message: performanceLevelsValid ? '每项评价指标均有预期表现和五级可辨别的表现水平。' : '评价指标需有预期表现，并完整说明 1—5 级表现水平。'
    },
    {
      code: 'scoring_examples',
      label: '评分示例',
      status: scoringExamplesValid ? 'passed' : 'blocked',
      message: scoringExamplesValid ? '每项评价指标均保留至少两个、覆盖不同表现水平的评分示例。' : '每项评价指标至少需要两个完整评分示例，并覆盖两个不同表现水平。'
    }
  ]
})

function finishReview() {
  if (!canFinishReview.value) return
  step.value = 7
  maxStep.value = 7
}

function reviewDecisionPayload(): EvaluationAIDraftReviewDecision[] {
  return reviewItems.value.map((item) => ({
    item_key: item.key,
    item_type: item.type,
    item_code: item.code,
    decision: reviewDecisions[item.key] as EvaluationAIDraftReviewDecision['decision']
  }))
}

async function saveDraftOnly() {
  const reviewedDraft = sanitizeReviewedDraft()
  const reviewedStandard = sanitizeReviewedStandard(reviewedDraft)
  if (!session.value || !reviewedDraft || !reviewedStandard || !saveAcknowledged.value || !canFinishReview.value || actionBusy.value) return
  actionBusy.value = true
  busyMessage.value = '正在保存评价方案与评价标准草稿'
  clearNotice()
  try {
    const result = await saveEvaluationAIPlanDraft(session.value.id, {
      plan_draft: reviewedDraft,
      standard_draft: reviewedStandard,
      review_decisions: reviewDecisionPayload()
    })
    ensureComponentActive()
    saved.value = true
    emit('saved', result.plan, result.standard)
  } catch (error) {
    setError(error, '评价方案与评价标准草稿保存失败。初稿会话仍保留，可修订后重试。')
  } finally {
    actionBusy.value = false
    busyMessage.value = ''
  }
}

function goBack() {
  if (step.value > 1 && !actionBusy.value) step.value -= 1
}

function requestClose() {
  componentActive = false
  stopPolling()
  emit('close')
}

function closeCancelConfirm() {
  if (!actionBusy.value) cancelConfirm.value = false
}

async function cancelDraft() {
  if (!session.value || actionBusy.value) return
  actionBusy.value = true
  busyMessage.value = '正在取消本次起草'
  clearNotice()
  try {
    await cancelEvaluationAIDraft(session.value.id)
    ensureComponentActive()
    cancelConfirm.value = false
    requestClose()
  } catch (error) {
    setError(error, '取消起草失败；会话仍保留，可稍后继续。')
  } finally {
    actionBusy.value = false
    busyMessage.value = ''
  }
}

function referencePage(reference: { source_page_start?: number | null; source_page_end?: number | null }) {
  if (!reference.source_page_start) return '页码待复核'
  if (!reference.source_page_end || reference.source_page_end === reference.source_page_start) return `第 ${reference.source_page_start} 页`
  return `第 ${reference.source_page_start}—${reference.source_page_end} 页`
}

function referenceTypeLabel(type: string) {
  return requiredReferenceTypes.find((item) => item.value === type)?.label || type
}

watch(() => context.course_id, () => {
  const course = selectedCourse.value
  if (course?.school_stage) context.school_stage = course.school_stage
  const current = standardVersions.value.find((item) => item.id === Number(context.curriculum_standard_version_id))
  if (current && !standardMatchesCourse(current)) context.curriculum_standard_version_id = 0
})

watch(() => context.school_stage, () => {
  const current = standardVersions.value.find((item) => item.id === Number(context.curriculum_standard_version_id))
  if (current && current.school_stage !== context.school_stage) context.curriculum_standard_version_id = 0
})

watch(availableStandardVersions, (versions) => {
  const currentIsAvailable = versions.some((item) => item.id === Number(context.curriculum_standard_version_id))
  if (!currentIsAvailable && versions.length === 1) {
    context.curriculum_standard_version_id = versions[0].id
  }
}, { immediate: true })

onMounted(loadSessions)
onBeforeUnmount(() => {
  componentActive = false
  stopPolling()
})
</script>

<template>
  <Teleport to="body">
    <div class="modal-backdrop ai-draft-backdrop" role="presentation" @click.self="requestClose">
      <section
        v-modal-focus="requestClose"
        class="entity-modal ai-draft-wizard"
        role="dialog"
        aria-modal="true"
        aria-labelledby="ai-draft-title"
        :aria-busy="actionBusy || polling"
      >
        <header class="modal-header ai-draft-header">
          <div>
            <span>教师主导 · AI 辅助</span>
            <h2 id="ai-draft-title">AI 辅助起草评价方案与评价标准</h2>
            <p>从课程标准原文和课程内容出发形成初稿，评价指标与表现水平也须由教师逐项审阅。</p>
          </div>
          <button class="icon-button" type="button" aria-label="暂时关闭 AI 辅助起草" @click="requestClose">×</button>
        </header>

        <p class="ai-boundary" role="note">
          AI 不能发布评价方案，不能直接进入课堂，也不能直接决定评分、学习内容与支持安排或学生分组。保存后仅形成“编辑中”草稿，仍须由教师复核确认。
        </p>

        <nav class="ai-stepper" aria-label="AI 辅助起草步骤">
          <ol>
            <li v-for="(label, index) in progressSteps" :key="label" :class="{ active: progressStep === index + 1, done: progressMaxStep > index + 1 }" :aria-current="progressStep === index + 1 ? 'step' : undefined">
              <span>{{ index + 1 }}</span><small>{{ label }}</small>
            </li>
          </ol>
        </nav>

        <div class="ai-status-region">
          <div v-if="notice" class="ai-notice" :class="noticeTone" role="alert">
            <span>{{ notice }}</span>
            <button v-if="step === 1 && !standardVersions.length" type="button" :disabled="loadingSessions" @click="loadSessions">重新加载</button>
          </div>
          <div v-if="actionBusy || polling" class="ai-background-state" role="status" aria-live="polite">
            <span class="ai-spinner" aria-hidden="true"></span>
            <div><strong>{{ backgroundMessage || '正在处理' }}</strong><small>后台任务运行期间可以暂时关闭；再次打开后可从未完成会话继续。</small></div>
          </div>
        </div>

        <main class="ai-draft-body">
          <section v-if="step === 1" class="ai-step-panel" aria-labelledby="ai-step-context">
            <header><span>第 1 步</span><h3 id="ai-step-context">明确课程内容与评价用途</h3><p>AI 只在本次明确的课程、学段、单元和已发布课标版本范围内检索与起草。</p></header>
            <div class="ai-context-layout">
              <form class="ai-context-form" @submit.prevent="createAndRetrieve">
                <label><span>课程 <b>*</b></span><AppSelect v-model="context.course_id" data-test="ai-course"><option v-for="course in options.courses" :key="course.id" :value="course.id">{{ course.subject.name }} · {{ course.title }}</option></AppSelect></label>
                <label><span>学段 <b>*</b></span><AppSelect v-model="context.school_stage" data-test="ai-stage"><option value="k1_k9">义务教育 K1–K9</option><option value="k10_k12">普通高中 K10–K12</option></AppSelect></label>
                <label><span>年级或适用阶段 <b>*</b></span><input v-model.trim="context.grade_or_stage" data-test="ai-grade" maxlength="40" placeholder="例如：八年级 / 必修模块" /></label>
                <label><span>单元或主题 <b>*</b></span><input v-model.trim="context.unit_title" data-test="ai-unit" maxlength="120" placeholder="例如：数据编码与表示" /></label>
                <label class="wide"><span>课程标准版本 <b>*</b></span><AppSelect v-model="context.curriculum_standard_version_id" data-test="ai-standard"><option :value="0">请选择已发布版本</option><option v-for="version in availableStandardVersions" :key="version.id" :value="version.id">{{ version.title }} · {{ version.version_label }} · {{ version.content_hash.slice(0, 8) }}</option></AppSelect><small v-if="!availableStandardVersions.length">当前课程与学段没有可用的已发布课程标准版本，请先联系超级管理员完成发布。</small></label>
                <label class="wide ai-course-content-field">
                  <span>本次课程内容 <b>*</b></span>
                  <div v-if="courseContentWasPrefilled" class="ai-content-source" role="status">
                    <span>已从{{ initialContentSourceLabel || '当前课时' }}自动带入，可在下方补充或修改。</span>
                    <button type="button" :disabled="actionBusy || polling" data-test="restore-lesson-content" @click="restoreInitialCourseContent">重新读取课时内容</button>
                  </div>
                  <textarea v-model.trim="context.course_content" data-test="ai-content" rows="6" maxlength="4000" placeholder="说明本单元的核心内容、学生将经历的学习活动与预期成果。"></textarea>
                  <small>系统读取的是课时与当前环节已有内容；请核对后再检索课标依据，不会覆盖课时设计原文。</small>
                </label>
                <label class="wide"><span>评价用途 <b>*</b></span><AppSelect v-model="context.evaluation_purpose" data-test="ai-purpose"><option v-for="item in purposeOptions" :key="item.value" :value="item.value">{{ item.label }}</option></AppSelect></label>
              </form>
              <aside class="ai-recent-sessions" aria-labelledby="ai-recent-title">
                <header><strong id="ai-recent-title">未完成会话</strong><button type="button" :disabled="loadingSessions" @click="loadSessions">刷新</button></header>
                <button v-for="item in unfinishedSessions" :key="item.id" type="button" :disabled="actionBusy" @click="resumeDraft(item.id)"><strong>{{ item.context.unit_title }}</strong><span>{{ item.status_label }} · {{ item.context.grade_or_stage }}</span><small>{{ new Date(item.updated_at).toLocaleString('zh-CN') }}</small></button>
                <p v-if="loadingSessions">正在加载未完成会话</p>
                <p v-else-if="!unfinishedSessions.length">暂无可继续的会话。</p>
              </aside>
            </div>
          </section>

          <section v-else-if="step === 2" class="ai-step-panel" aria-labelledby="ai-step-references">
            <header><span>第 2 步</span><h3 id="ai-step-references">核对可追溯课程标准原文</h3><p>请先核对核心素养、课程目标、课程内容与学业质量四类依据，再让 AI 建议评价方式。</p></header>
            <div class="ai-reference-coverage" aria-label="课程标准依据覆盖情况"><span v-for="item in requiredReferenceTypes" :key="item.value" :class="{ ready: selectedReferenceTypes.has(item.value) }">{{ item.label }} · {{ selectedReferenceTypes.has(item.value) ? '已检索' : '缺失' }}</span></div>
            <div class="ai-reference-list">
              <article v-for="reference in session?.curriculum_references || []" :key="reference.id">
                <header><span>{{ referenceTypeLabel(reference.node_type) }}</span><strong>{{ reference.code }} · {{ reference.title }}</strong></header>
                <p>{{ reference.content }}</p>
                <small>{{ reference.standard_title || reference.citation?.official_title || session?.curriculum_standard_version?.title }} · {{ reference.version_label || reference.citation?.version_label || session?.curriculum_standard_version?.version_label }} · {{ referencePage(reference) }}<template v-if="reference.citation?.source_content_hash"> · 原文哈希 {{ reference.citation.source_content_hash.slice(0, 8) }}</template></small>
              </article>
            </div>
            <p v-if="!referenceCoverageComplete" class="ai-inline-warning" role="alert">四类课程标准依据尚不完整，不能进入方式建议。请返回调整课程内容或课标版本后重新检索。</p>
          </section>

          <section v-else-if="step === 3" class="ai-step-panel" aria-labelledby="ai-step-suggestions">
            <header><span>第 3 步</span><h3 id="ai-step-suggestions">查看 AI 建议的评价方式</h3><p>建议仅说明哪些方式可能更适合本次课程内容，不替代教师对教学情境和学生实际情况的判断。</p></header>
            <div class="ai-mode-list">
              <article v-for="item in session?.mode_suggestions || []" :key="item.mode" :class="{ recommended: item.recommended }">
                <header><strong>{{ item.label }}</strong><span v-if="item.recommended">优先建议</span></header>
                <p>{{ item.rationale }}</p>
                <dl><div><dt>可形成的材料</dt><dd>{{ item.suitable_materials.join('、') || '待教师补充' }}</dd></div><div v-if="item.cautions.length"><dt>使用提醒</dt><dd>{{ item.cautions.join('；') }}</dd></div></dl>
              </article>
            </div>
            <fieldset class="ai-mode-confirm ai-mode-confirm-inline">
              <legend>选择本次采用的评价方式</legend>
              <label v-for="item in session?.mode_suggestions || []" :key="item.mode" :class="{ selected: modeSelections.includes(item.mode) }">
                <input type="checkbox" :checked="modeSelections.includes(item.mode)" :value="item.mode" @change="toggleMode(item.mode, ($event.target as HTMLInputElement).checked)" />
                <span><strong>{{ item.label }}</strong><small>{{ item.rationale }}</small></span>
              </label>
            </fieldset>
            <label class="ai-full-field"><span>教师补充说明（选填）</span><textarea v-model.trim="teacherModeNote" rows="3" maxlength="1000" placeholder="例如：保留个人操作材料，避免仅以小组成果判断个人表现。"></textarea></label>
          </section>

          <section v-else-if="step === 4" class="ai-step-panel" aria-labelledby="ai-step-confirm-modes">
            <header><span>第 4 步</span><h3 id="ai-step-confirm-modes">由教师确认评价方式</h3><p>至少选择一种方式。AI 后续只能围绕教师确认的方式生成任务和材料要求。</p></header>
            <fieldset class="ai-mode-confirm"><legend>本次采用的评价方式</legend><label v-for="item in session?.mode_suggestions || []" :key="item.mode" :class="{ selected: modeSelections.includes(item.mode) }"><input type="checkbox" :checked="modeSelections.includes(item.mode)" :value="item.mode" @change="toggleMode(item.mode, ($event.target as HTMLInputElement).checked)" /><span><strong>{{ item.label }}</strong><small>{{ item.rationale }}</small></span></label></fieldset>
            <label class="ai-full-field"><span>教师确认说明（选填）</span><textarea v-model.trim="teacherModeNote" rows="4" maxlength="1000" placeholder="记录采用、组合或不采用某种方式的教学考虑。"></textarea></label>
          </section>

          <section v-else-if="step === 5" class="ai-step-panel ai-generation-panel" aria-labelledby="ai-step-generate">
            <header><span>第 5 步</span><h3 id="ai-step-generate">生成评价方案与评价标准完整初稿</h3><p>初稿包含学习目标、活动、任务、材料归属，以及评价指标、预期表现、表现水平和后续教学建议。</p></header>
            <div><strong>教师已确认：{{ (session?.confirmed_modes || []).map((mode) => session?.mode_suggestions.find((item) => item.mode === mode)?.label || mode).join('、') }}</strong><p>生成可能需要一段时间。任务会在后台继续运行，可暂时关闭后从未完成会话恢复。</p><button class="primary-button" type="button" :disabled="actionBusy || polling" data-test="generate-draft" @click="generateDraft">{{ actionBusy || polling ? '正在后台生成' : '开始生成完整初稿' }}</button></div>
          </section>

          <section v-else-if="step === 6 && (!planDraft || !standardDraft)" class="ai-step-panel ai-generation-panel" aria-labelledby="ai-step-waiting">
            <header><span>正在生成</span><h3 id="ai-step-waiting">AI 正在形成评价初稿</h3><p>系统会在后台补齐学习目标、评价任务、评价依据、表现水平及其对应关系。可以暂时关闭，稍后从未完成会话继续。</p></header>
            <div><strong>{{ backgroundMessage || '正在等待后台返回完整初稿' }}</strong><p>初稿完整返回前不会显示“0 项待审阅”，也不会要求教师处理空白内容。</p></div>
          </section>

          <section v-else-if="step === 6" class="ai-step-panel" aria-labelledby="ai-step-review">
            <header><span>第 6 步</span><h3 id="ai-step-review">自动检查并由教师审阅</h3><p>可逐项审阅，也可批量采纳尚未修改的待审阅项；已修改和已删除内容不会被批量操作覆盖。</p></header>
            <section class="ai-batch-review-bar" aria-label="批量审阅">
              <div>
                <strong>待审阅 {{ pendingReviewItems.length }} 项</strong>
                <span>批量采纳仍会保存为教师审阅决定，不会直接发布或绑定课堂。</span>
              </div>
              <button v-if="pendingReviewItems.length" class="secondary-button" type="button" :disabled="actionBusy" data-test="batch-accept-pending" @click="requestBatchAccept">批量采纳待审阅项</button>
              <span v-else class="ai-batch-complete" role="status" data-test="batch-review-complete">待审阅项已全部处理</span>
            </section>
            <section v-if="batchAcceptConfirm" class="ai-batch-confirm" role="alertdialog" aria-labelledby="batch-accept-title">
              <div>
                <strong id="batch-accept-title">确认批量采纳 {{ pendingReviewItems.length }} 项？</strong>
                <span>请先确认已浏览这些内容。该操作只处理“待审阅”项，不改变已修改或已删除项。</span>
              </div>
              <div>
                <button class="secondary-button" type="button" @click="batchAcceptConfirm = false">取消</button>
                <button class="primary-button" type="button" data-test="confirm-batch-accept" @click="confirmBatchAccept">确认批量采纳</button>
              </div>
            </section>
            <section v-if="blockedChecks.length" class="ai-review-blockers" role="alert" aria-labelledby="ai-review-blockers-title" id="ai-review-blockers">
              <div>
                <strong id="ai-review-blockers-title">初稿仍有 {{ blockedChecks.length }} 项内容问题</strong>
                <span>批量采纳只完成教师审阅记录，不会掩盖目标、活动、任务或评分示例的缺项。</span>
                <ul><li v-for="item in blockedChecks" :key="item.code"><b>{{ item.label }}</b>：{{ item.message }}</li></ul>
              </div>
              <button class="secondary-button" type="button" data-test="request-regenerate-draft" @click="requestRegenerateDraft">让 AI 重新完善初稿</button>
            </section>
            <details class="ai-check-details" :open="blockedChecks.length > 0">
              <summary>查看自动检查结果：{{ checks.filter((item) => item.status === 'passed').length }} 项通过，{{ blockedChecks.length }} 项需处理</summary>
              <div class="ai-check-list" aria-label="初稿自动检查结果"><article v-for="item in checks" :key="item.code" :class="item.status"><strong>{{ item.label }}</strong><span>{{ item.status === 'passed' ? '通过' : item.status === 'warning' ? '需关注' : '需处理' }}</span><p>{{ item.message }}</p></article></div>
            </details>
            <div class="ai-review-list">
              <article v-for="item in reviewItems" :key="item.key" :class="['ai-review-card', decision(item)]" :data-test="`review-${item.key}`">
                <header><div><span>{{ item.label }}{{ item.code ? ` · ${item.code}` : '' }}</span><strong>{{ item.model.title || item.model.description || '整体设置' }}</strong></div><em>{{ decision(item) === 'pending' ? '待审阅' : decision(item) === 'accepted' ? '已采纳' : decision(item) === 'modified' ? '已修改' : '已删除' }}</em></header>
                <template v-if="decision(item) !== 'removed'">
                  <div v-if="item.key === 'overall:plan'" class="ai-review-fields">
                    <label><span>方案名称</span><input v-model="item.model.title" @input="markModified(item)" /></label>
                    <label><span>适用学生</span><input v-model="item.model.target_students" @input="markModified(item)" /></label>
                    <label class="wide"><span>总体学习目标</span><textarea v-model="item.model.learning_goal" rows="3" @input="markModified(item)"></textarea></label>
                    <label><span>评分方式</span><input v-model="item.model.scoring_rules.approach" @input="markModified(item)" /></label>
                    <label><span>评分判定说明</span><input v-model="item.model.scoring_rules.decision_rule" @input="markModified(item)" /></label>
                  </div>
                  <div v-else-if="item.key === 'overall:standard'" class="ai-review-fields">
                    <label class="wide"><span>评价标准名称</span><input v-model="item.model.title" @input="markModified(item)" /></label>
                    <label class="wide"><span>评价对象与主要表现</span><textarea v-model="item.model.evaluation_target" rows="3" @input="markModified(item)"></textarea></label>
                  </div>
                  <div v-else-if="item.type === 'evaluation_criterion'" class="ai-review-fields">
                    <label><span>评价指标名称</span><input v-model="item.model.title" @input="markModified(item)" /></label>
                    <label><span>评价维度</span><input v-model="item.model.dimension" @input="markModified(item)" /></label>
                    <label class="wide"><span>评价对象</span><textarea v-model="item.model.evaluation_target" rows="2" @input="markModified(item)"></textarea></label>
                    <label class="wide"><span>预期表现</span><textarea v-model="item.model.expected_performance" rows="3" @input="markModified(item)"></textarea></label>
                    <fieldset class="wide ai-mapping-field"><legend>对应学习目标</legend><label v-for="goal in planDraft?.learning_goals || []" :key="goal.code"><input type="checkbox" :checked="item.model.learning_goal_codes.includes(goal.code)" @change="toggleMappedValue(item, 'learning_goal_codes', goal.code, ($event.target as HTMLInputElement).checked)" /><span>{{ goal.code }} · {{ goal.title }}</span></label></fieldset>
                    <fieldset class="wide ai-mapping-field"><legend>对应评价任务</legend><label v-for="task in planDraft?.evaluation_tasks || []" :key="task.code"><input type="checkbox" :checked="item.model.evaluation_task_codes.includes(task.code)" @change="toggleMappedValue(item, 'evaluation_task_codes', task.code, ($event.target as HTMLInputElement).checked)" /><span>{{ task.code }} · {{ task.title }}</span></label></fieldset>
                    <label class="wide"><span>暂不评价条件</span><textarea v-model="item.model.skip_condition" rows="2" @input="markModified(item)"></textarea></label>
                  </div>
                  <div v-else-if="item.type === 'performance_level'" class="ai-review-fields">
                    <label class="wide"><span>{{ item.label }}的可观察表现</span><textarea v-model="item.model[item.field!]" rows="4" @input="markModified(item)"></textarea></label>
                  </div>
                  <div v-else-if="item.type === 'scoring_example'" class="ai-review-fields">
                    <label><span>表现水平（1—5 星）</span><input v-model.number="item.model.level" type="number" min="1" max="5" step="1" @input="markModified(item)" /></label>
                    <label><span>示例名称</span><input v-model="item.model.title" @input="markModified(item)" /></label>
                    <label class="wide"><span>学生表现示例说明</span><textarea v-model="item.model.example_description" rows="4" @input="markModified(item)"></textarea></label>
                    <label class="wide"><span>示例材料引用（选填）</span><input v-model="item.model.file_reference" placeholder="填写样例文件名称或材料位置" @input="markModified(item)" /></label>
                  </div>
                  <div v-else-if="item.type === 'follow_up_suggestion'" class="ai-review-fields">
                    <label class="wide"><span>{{ item.code === 'plan' ? '方案整体的后续教学建议' : '针对该评价指标的后续教学建议' }}</span><textarea v-model="item.model.follow_up_suggestion" rows="4" @input="markModified(item)"></textarea></label>
                  </div>
                  <div v-else class="ai-review-fields">
                    <label v-if="'title' in item.model"><span>名称</span><input v-model="item.model.title" @input="markModified(item)" /></label>
                    <label v-if="item.type === 'evaluation_task'"><span>评价方式</span><AppSelect v-model="item.model.mode" @change="markModified(item)"><option v-for="mode in session?.confirmed_modes || []" :key="mode" :value="mode">{{ session?.mode_suggestions.find((row) => row.mode === mode)?.label || mode }}</option></AppSelect></label>
                    <label v-if="item.type === 'evaluation_task'"><span>材料归属</span><AppSelect v-model="item.model.evidence_ownership" @change="markModified(item)"><option value="individual">个人评价材料</option><option value="group">小组评价材料</option><option value="both">个人与小组评价材料</option></AppSelect></label>
                    <label v-if="item.type === 'evaluation_task'"><span>任务权重（0—100）</span><input v-model.number="item.model.weight" type="number" min="0" max="100" step="1" @input="markModified(item)" /></label>
                    <label class="wide"><span>具体说明</span><textarea v-model="item.model.description" rows="4" @input="markModified(item)"></textarea></label>
                    <fieldset v-if="item.type === 'evaluation_basis'" class="wide ai-mapping-field"><legend>对应学习目标</legend><label v-for="goal in planDraft?.learning_goals || []" :key="goal.code"><input type="checkbox" :checked="item.model.goal_codes.includes(goal.code)" @change="toggleMappedValue(item, 'goal_codes', goal.code, ($event.target as HTMLInputElement).checked)" /><span>{{ goal.code }} · {{ goal.title }}</span></label></fieldset>
                    <fieldset v-if="item.type === 'learning_activity'" class="wide ai-mapping-field"><legend>对应学习目标</legend><label v-for="goal in planDraft?.learning_goals || []" :key="goal.code"><input type="checkbox" :checked="item.model.goal_codes.includes(goal.code)" @change="toggleMappedValue(item, 'goal_codes', goal.code, ($event.target as HTMLInputElement).checked)" /><span>{{ goal.code }} · {{ goal.title }}</span></label></fieldset>
                    <fieldset v-if="item.type === 'learning_task'" class="wide ai-mapping-field"><legend>对应评价依据</legend><label v-for="basis in planDraft?.evaluation_basis || []" :key="basis.code"><input type="checkbox" :checked="item.model.basis_codes.includes(basis.code)" @change="toggleMappedValue(item, 'basis_codes', basis.code, ($event.target as HTMLInputElement).checked)" /><span>{{ basis.code }} · {{ basis.description }}</span></label></fieldset>
                    <template v-if="item.type === 'evaluation_task'">
                      <fieldset class="wide ai-mapping-field"><legend>对应学习目标</legend><label v-for="goal in planDraft?.learning_goals || []" :key="goal.code"><input type="checkbox" :checked="item.model.goal_codes.includes(goal.code)" @change="toggleMappedValue(item, 'goal_codes', goal.code, ($event.target as HTMLInputElement).checked)" /><span>{{ goal.code }} · {{ goal.title }}</span></label></fieldset>
                      <fieldset class="wide ai-mapping-field"><legend>对应学习活动</legend><label v-for="activity in planDraft?.learning_activities || []" :key="activity.code"><input type="checkbox" :checked="item.model.activity_codes.includes(activity.code)" @change="toggleMappedValue(item, 'activity_codes', activity.code, ($event.target as HTMLInputElement).checked)" /><span>{{ activity.code }} · {{ activity.title }}</span></label></fieldset>
                      <fieldset class="wide ai-mapping-field"><legend>形成的评价材料</legend><label v-for="material in options.material_types" :key="material.value"><input type="checkbox" :checked="item.model.material_types.includes(material.value)" @change="toggleMappedValue(item, 'material_types', material.value, ($event.target as HTMLInputElement).checked)" /><span>{{ material.label }}</span></label></fieldset>
                    </template>
                  </div>
                </template>
                <p v-else>该项不会写入草稿，也不会被 AI 自动补回。</p>
                <footer><button v-if="decision(item) === 'removed'" type="button" data-test="restore-item" @click="setDecision(item, 'pending')">恢复</button><template v-else><button type="button" :class="{ active: decision(item) === 'accepted' }" data-test="accept-item" @click="setDecision(item, 'accepted')">采纳</button><button v-if="item.type !== 'overall'" class="danger-link" type="button" data-test="remove-item" @click="setDecision(item, 'removed')">删除</button></template></footer>
              </article>
            </div>
            <p class="ai-task-weight-total" :class="{ invalid: Math.abs(totalTaskWeight - 100) >= 0.001 }" role="status">当前评价任务权重合计：<strong>{{ totalTaskWeight }}</strong> / 100</p>
            <p v-if="!allItemsReviewed" class="ai-inline-warning" role="status">还有 {{ reviewItems.filter((item) => decision(item) === 'pending').length }} 项未完成教师审阅。</p>
          </section>

          <section v-else class="ai-step-panel ai-save-panel" aria-labelledby="ai-step-save">
            <header><span>第 7 步</span><h3 id="ai-step-save">仅保存为评价方案与评价标准草稿</h3><p>评价方案和评价标准均保存为“编辑中”草稿，需由教师继续复核；方案发布后，还须为评价标准选择明确的方案版本。本操作不会创建版本、发布或绑定课堂，也不会直接决定评分、学习内容与支持安排或学生分组。</p></header>
            <div class="ai-save-summary"><dl><div><dt>方案名称</dt><dd>{{ sanitizeReviewedDraft()?.title }}</dd></div><div><dt>学习目标</dt><dd>{{ sanitizeReviewedDraft()?.learning_goals.length }} 项</dd></div><div><dt>评价任务</dt><dd>{{ sanitizeReviewedDraft()?.evaluation_tasks.length }} 项</dd></div><div><dt>评价指标</dt><dd>{{ sanitizeReviewedStandard(sanitizeReviewedDraft())?.criteria.length }} 项</dd></div></dl><label><input v-model="saveAcknowledged" type="checkbox" data-test="save-acknowledgement" /><span id="ai-save-acknowledgement-help">我已逐项审阅评价方案、评价指标与表现水平，并理解两者保存后均为“编辑中”草稿。</span></label></div>
          </section>
        </main>

        <footer class="modal-actions ai-draft-actions">
          <div><button v-if="session && !saved" class="danger-link" type="button" :disabled="actionBusy" @click="cancelConfirm = true">取消本次起草</button><button class="secondary-button" type="button" @click="requestClose">暂时关闭</button></div>
          <div>
            <button v-if="step > 1" class="secondary-button" type="button" :disabled="actionBusy || polling" @click="goBack">返回上一步</button>
            <button v-if="step === 1" class="primary-button" type="button" :disabled="!contextValid || actionBusy || polling" data-test="context-next" @click="createAndRetrieve">{{ contextActionLabel }}</button>
            <button v-else-if="step === 2" class="primary-button" type="button" :disabled="!referenceCoverageComplete || actionBusy || polling" data-test="references-next" @click="suggestModes">查看评价方式建议</button>
            <button v-else-if="step === 3" class="secondary-button" type="button" :disabled="!session?.mode_suggestions.length" data-test="suggestions-next" @click="openModeConfirmation">分步确认</button>
            <button v-if="step === 3" class="primary-button" type="button" :disabled="!modeSelections.length || actionBusy || polling" data-test="confirm-generate" @click="confirmModesAndGenerate">确认方式并生成初稿</button>
            <button v-else-if="step === 4" class="primary-button" type="button" :disabled="!modeSelections.length || actionBusy" data-test="confirm-modes" @click="confirmModes">确认评价方式</button>
            <button v-else-if="step === 5" class="secondary-button" type="button" :disabled="actionBusy || polling" @click="requestClose">后台生成时可暂时关闭</button>
            <button v-else-if="step === 6" class="primary-button" type="button" :disabled="!canFinishReview" :aria-describedby="blockedChecks.length ? 'ai-review-blockers' : undefined" data-test="review-next" @click="finishReview">{{ !reviewItems.length ? '初稿正在生成，请稍候' : !allItemsReviewed ? `还有 ${pendingReviewItems.length} 项待审阅` : blockedChecks.length ? `还需处理 ${blockedChecks.length} 项内容问题` : '完成教师审阅' }}</button>
            <button v-else-if="step === 7" class="primary-button" type="button" :disabled="!saveAcknowledged || !canFinishReview || actionBusy" aria-describedby="ai-save-acknowledgement-help" data-test="save-draft-only" @click="saveDraftOnly">{{ saveDraftActionLabel }}</button>
          </div>
        </footer>

        <div v-if="regenerateConfirm" class="ai-cancel-confirm" role="alertdialog" aria-modal="true" aria-labelledby="ai-regenerate-title">
          <section v-modal-focus="closeRegenerateConfirm"><h3 id="ai-regenerate-title">让 AI 重新完善这份初稿？</h3><p>本次尚未保存的修改和批量审阅状态将重新开始；原始生成结果、模型与提示记录仍会保留，便于追溯。</p><div><button class="secondary-button" type="button" :disabled="actionBusy" data-modal-initial-focus @click="closeRegenerateConfirm">继续人工修改</button><button class="primary-button" type="button" :disabled="actionBusy" data-test="confirm-regenerate-draft" @click="regenerateDraft">确认重新完善</button></div></section>
        </div>

        <div v-if="cancelConfirm" class="ai-cancel-confirm" role="alertdialog" aria-modal="true" aria-labelledby="ai-cancel-title">
          <section v-modal-focus="closeCancelConfirm"><h3 id="ai-cancel-title">取消本次 AI 起草？</h3><p>取消后该会话不再继续生成；已保存的其他评价方案不受影响。</p><div><button class="secondary-button" type="button" :disabled="actionBusy" data-modal-initial-focus @click="closeCancelConfirm">继续起草</button><button class="primary-button danger" type="button" :disabled="actionBusy" data-test="confirm-cancel" @click="cancelDraft">确认取消</button></div></section>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.ai-draft-backdrop { z-index: 1300; }
.ai-draft-wizard { width: min(1120px, calc(100vw - 32px)); height: min(92dvh, 940px); max-height: calc(100dvh - 32px); display: grid; grid-template-rows: auto auto auto auto minmax(0, 1fr) auto; overflow: hidden; }
.ai-draft-header { align-items: flex-start; }
.ai-draft-header > div { min-width: 0; }
.ai-draft-header span, .ai-step-panel > header > span { color: var(--primary); font-size: 12px; font-weight: 800; letter-spacing: .06em; }
.ai-draft-header h2, .ai-draft-header p, .ai-step-panel h3, .ai-step-panel > header p { margin: 0; }
.ai-draft-header h2 { margin-top: 4px; }
.ai-draft-header p { margin-top: 5px; color: var(--muted); line-height: 1.5; }
.ai-boundary { margin: 0; border-block: 1px solid #c5d6cc; padding: 10px 22px; background: #eef5f1; color: #315f50; font-size: 13px; line-height: 1.55; }
.ai-stepper { overflow-x: auto; border-bottom: 1px solid var(--line); background: #f5f7f3; }
.ai-stepper ol { min-width: 560px; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); margin: 0; padding: 10px 18px; list-style: none; }
.ai-stepper li { position: relative; display: grid; justify-items: center; gap: 4px; color: #687a73; text-align: center; }
.ai-stepper li::before { content: ''; position: absolute; top: 13px; right: 50%; width: 100%; height: 2px; background: #cad4ce; transform: translateX(-50%); }
.ai-stepper li:first-child::before { display: none; }
.ai-stepper li span { position: relative; z-index: 1; width: 28px; height: 28px; display: grid; place-items: center; border: 2px solid #cad4ce; border-radius: 50%; background: #fff; font-weight: 700; }
.ai-stepper li.active span, .ai-stepper li.done span { border-color: var(--primary); background: var(--primary); color: #fff; }
.ai-stepper li.done::before, .ai-stepper li.active::before { background: var(--primary); }
.ai-stepper li.active small { color: var(--primary-dark); font-weight: 700; }
.ai-status-region { min-height: 0; }
.ai-notice, .ai-background-state { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 20px; font-size: 13px; }
.ai-notice.error { background: #fff1f2; color: #9f1239; }
.ai-notice.warning { background: #fffbeb; color: #92400e; }
.ai-notice.info { background: #eef5f1; color: #315f50; }
.ai-notice button { min-height: 36px; border: 1px solid currentColor; border-radius: 6px; padding: 0 12px; background: transparent; color: inherit; cursor: pointer; }
.ai-background-state { justify-content: flex-start; background: #edf6f0; color: #32674f; }
.ai-background-state div { display: grid; gap: 2px; }
.ai-background-state small { color: #526a61; }
.ai-spinner { width: 18px; height: 18px; flex: 0 0 18px; border: 2px solid #c6dace; border-top-color: #32674f; border-radius: 50%; animation: ai-spin .8s linear infinite; }
@keyframes ai-spin { to { transform: rotate(360deg); } }
.ai-draft-body { min-height: 0; overflow: auto; padding: 20px 22px 24px; }
.ai-step-panel { display: grid; gap: 18px; }
.ai-step-panel > header { display: grid; gap: 5px; }
.ai-step-panel h3 { font-size: 20px; }
.ai-step-panel > header p { max-width: 840px; color: var(--muted); line-height: 1.6; }
.ai-context-layout { display: grid; grid-template-columns: minmax(0, 1fr) 280px; gap: 20px; align-items: start; }
.ai-context-form, .ai-review-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.ai-context-form label, .ai-full-field, .ai-review-fields label { min-width: 0; display: grid; align-content: start; gap: 6px; }
.ai-context-form label > span, .ai-full-field > span, .ai-review-fields label > span { font-weight: 600; }
.ai-context-form input, .ai-context-form textarea, .ai-full-field textarea, .ai-review-fields input, .ai-review-fields textarea { width: 100%; min-height: 44px; border: 1px solid var(--line); border-radius: 6px; padding: 9px 11px; background: #fff; color: var(--text); font: inherit; }
.ai-context-form textarea, .ai-full-field textarea, .ai-review-fields textarea { resize: vertical; line-height: 1.55; }
.ai-context-form .wide, .ai-review-fields .wide { grid-column: 1 / -1; }
.ai-mapping-field { display: flex; flex-wrap: wrap; gap: 8px 12px; margin: 0; border: 1px solid var(--line); border-radius: 7px; padding: 10px 12px 12px; }
.ai-mapping-field legend { padding: 0 5px; font-weight: 700; }
.ai-mapping-field label { min-height: 36px; display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: start; gap: 7px; border-radius: 5px; padding: 7px 9px; background: #f7f8f4; cursor: pointer; }
.ai-mapping-field input { width: 17px; height: 17px; min-height: 0; margin-top: 1px; padding: 0; }
.ai-context-form small { color: var(--muted); line-height: 1.45; }
.ai-content-source { min-height: 40px; display: flex; align-items: center; justify-content: space-between; gap: 12px; border: 1px solid #c5d6cc; border-radius: 6px; padding: 7px 10px; background: #eef5f1; color: #315f50; font-size: 13px; }
.ai-content-source button { flex: 0 0 auto; min-height: 34px; border: 1px solid #9bb3a8; border-radius: 5px; padding: 0 10px; background: #fff; color: #17483f; cursor: pointer; }
.ai-recent-sessions { display: grid; gap: 8px; border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #f7f8f4; }
.ai-recent-sessions > header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.ai-recent-sessions > header button { border: 0; background: transparent; color: var(--primary); cursor: pointer; }
.ai-recent-sessions > button { min-height: 76px; display: grid; gap: 3px; border: 1px solid var(--line); border-radius: 7px; padding: 10px; background: #fff; color: var(--text); text-align: left; cursor: pointer; }
.ai-recent-sessions span, .ai-recent-sessions small, .ai-recent-sessions p { margin: 0; color: var(--muted); }
.ai-reference-coverage { display: flex; flex-wrap: wrap; gap: 8px; }
.ai-reference-coverage span { border: 1px solid #fecaca; border-radius: 999px; padding: 5px 9px; background: #fff1f2; color: #9f1239; font-size: 12px; }
.ai-reference-coverage span.ready { border-color: #bbf7d0; background: #f0fdf4; color: #166534; }
.ai-reference-list, .ai-mode-list, .ai-review-list { display: grid; gap: 12px; }
.ai-reference-list { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.ai-reference-list article, .ai-mode-list article, .ai-review-card { min-width: 0; border: 1px solid var(--line); border-radius: 8px; padding: 14px; background: #fff; }
.ai-reference-list header, .ai-mode-list header, .ai-review-card > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.ai-reference-list header { display: grid; justify-content: stretch; gap: 4px; }
.ai-reference-list header span { color: var(--primary); font-size: 12px; font-weight: 700; }
.ai-reference-list p, .ai-mode-list p { margin: 10px 0; color: #334a43; line-height: 1.7; white-space: pre-wrap; }
.ai-reference-list small { color: var(--muted); }
.ai-inline-warning { margin: 0; border-left: 4px solid #d97706; padding: 10px 12px; background: #fffbeb; color: #92400e; line-height: 1.55; }
.ai-mode-list { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.ai-mode-list article.recommended { border-color: #9bb3a8; box-shadow: 0 0 0 1px #d8e4dc; }
.ai-mode-list header span { border-radius: 999px; padding: 4px 8px; background: #e4ede8; color: #315f50; font-size: 12px; }
.ai-mode-list dl { display: grid; gap: 8px; margin: 0; }
.ai-mode-list dl div { display: grid; gap: 3px; }
.ai-mode-list dt { color: var(--muted); font-size: 12px; }
.ai-mode-list dd { margin: 0; line-height: 1.5; }
.ai-mode-confirm { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin: 0; border: 0; padding: 0; }
.ai-mode-confirm-inline { margin-top: 20px; border-top: 1px solid var(--line); padding-top: 18px; }
.ai-mode-confirm-inline + .ai-full-field { margin-top: 14px; }
.ai-mode-confirm legend { grid-column: 1 / -1; margin-bottom: 8px; font-weight: 700; }
.ai-mode-confirm label { min-height: 76px; display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: start; gap: 10px; border: 1px solid var(--line); border-radius: 8px; padding: 12px; cursor: pointer; }
.ai-mode-confirm label.selected { border-color: var(--primary); background: #edf4f0; }
.ai-mode-confirm input { width: 18px; height: 18px; }
.ai-mode-confirm label span { display: grid; gap: 4px; }
.ai-mode-confirm small { color: var(--muted); line-height: 1.45; }
.ai-generation-panel > div { min-height: 220px; display: grid; place-items: center; align-content: center; gap: 12px; border: 1px dashed #9bb3a8; border-radius: 10px; padding: 24px; background: #f4f7f4; text-align: center; }
.ai-generation-panel > div p { max-width: 640px; margin: 0; color: var(--muted); line-height: 1.6; }
.ai-check-list { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.ai-check-list article { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 5px 10px; border: 1px solid var(--line); border-radius: 8px; padding: 12px; }
.ai-check-list article.passed { border-color: #bbf7d0; background: #f0fdf4; }
.ai-check-list article.warning { border-color: #fde68a; background: #fffbeb; }
.ai-check-list article.blocked { border-color: #fecaca; background: #fff1f2; }
.ai-check-list article span { font-size: 12px; font-weight: 700; }
.ai-check-list article p { grid-column: 1 / -1; margin: 0; color: #475569; font-size: 13px; line-height: 1.5; }
.ai-check-details { border: 1px solid var(--line); border-radius: 8px; background: #fff; }
.ai-check-details summary { min-height: 44px; display: flex; align-items: center; padding: 10px 14px; color: #334a43; font-weight: 700; cursor: pointer; }
.ai-check-details summary:focus-visible { outline: 3px solid rgba(23, 72, 63, .28); outline-offset: 2px; }
.ai-check-details .ai-check-list { padding: 0 14px 14px; }
.ai-batch-review-bar, .ai-batch-confirm { display: flex; align-items: center; justify-content: space-between; gap: 16px; border: 1px solid #c5d6cc; border-radius: 8px; padding: 12px 14px; background: #f4f7f4; }
.ai-batch-review-bar > div, .ai-batch-confirm > div:first-child { display: grid; gap: 3px; }
.ai-batch-review-bar span, .ai-batch-confirm span { color: #475569; font-size: 13px; line-height: 1.5; }
.ai-batch-review-bar .ai-batch-complete { flex: 0 0 auto; border-radius: 999px; padding: 7px 11px; background: #dcfce7; color: #166534; font-weight: 700; }
.ai-batch-confirm { border-color: #fbbf24; background: #fffbeb; }
.ai-batch-confirm > div:last-child { flex: 0 0 auto; display: flex; gap: 8px; }
.ai-review-blockers { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; border: 1px solid #fda4af; border-left-width: 4px; border-radius: 8px; padding: 14px; background: #fff1f2; color: #881337; }
.ai-review-blockers > div { display: grid; gap: 6px; }
.ai-review-blockers span { line-height: 1.55; }
.ai-review-blockers ul { display: grid; gap: 5px; margin: 4px 0 0; padding-left: 20px; color: #9f1239; line-height: 1.5; }
.ai-review-blockers button { flex: 0 0 auto; min-height: 44px; }
.ai-review-card { display: grid; gap: 12px; }
.ai-review-card.accepted { border-color: #86efac; }
.ai-review-card.modified { border-color: #9bb3a8; }
.ai-review-card.removed { border-color: #fecaca; background: #fffafa; }
.ai-review-card > header > div { min-width: 0; display: grid; gap: 3px; }
.ai-review-card > header span { color: var(--muted); font-size: 12px; }
.ai-review-card > header strong { overflow-wrap: anywhere; }
.ai-review-card > header em { flex: 0 0 auto; border-radius: 999px; padding: 4px 8px; background: #f1f4f1; color: #526a61; font-size: 12px; font-style: normal; }
.ai-review-card > p { margin: 0; color: #9f1239; }
.ai-review-card > footer { display: flex; justify-content: flex-end; gap: 8px; }
.ai-review-card > footer button { min-height: 40px; border: 1px solid var(--line); border-radius: 6px; padding: 0 14px; background: #fff; color: var(--primary); cursor: pointer; }
.ai-review-card > footer button.active { border-color: #16a34a; background: #f0fdf4; color: #166534; }
.ai-review-card > footer .danger-link { color: #b42318; }
.ai-task-weight-total { margin: 0; border-radius: 7px; padding: 10px 12px; background: #f0fdf4; color: #166534; text-align: right; }
.ai-task-weight-total.invalid { background: #fff1f2; color: #9f1239; }
.ai-save-summary { display: grid; gap: 18px; border: 1px solid var(--line); border-radius: 9px; padding: 18px; background: #f8fafc; }
.ai-save-summary dl { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin: 0; }
.ai-save-summary dl div { display: grid; gap: 4px; border-right: 1px solid var(--line); }
.ai-save-summary dl div:last-child { border-right: 0; }
.ai-save-summary dt { color: var(--muted); font-size: 12px; }
.ai-save-summary dd { margin: 0; font-weight: 700; overflow-wrap: anywhere; }
.ai-save-summary label { display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: start; gap: 10px; border-top: 1px solid var(--line); padding-top: 16px; line-height: 1.55; cursor: pointer; }
.ai-save-summary input { width: 18px; height: 18px; }
.ai-draft-actions { display: flex; justify-content: space-between; gap: 16px; }
.ai-draft-actions > div { display: flex; align-items: center; gap: 10px; }
.ai-draft-actions .danger-link { min-height: 42px; border: 0; background: transparent; color: #b42318; cursor: pointer; }
.ai-cancel-confirm { position: absolute; inset: 0; z-index: 3; display: grid; place-items: center; padding: 20px; background: rgba(15, 23, 42, .55); }
.ai-cancel-confirm section { width: min(440px, 100%); display: grid; gap: 12px; border-radius: 9px; padding: 20px; background: #fff; box-shadow: 0 24px 60px rgba(15, 23, 42, .24); }
.ai-cancel-confirm h3, .ai-cancel-confirm p { margin: 0; }
.ai-cancel-confirm p { color: var(--muted); line-height: 1.55; }
.ai-cancel-confirm section > div { display: flex; justify-content: flex-end; gap: 10px; }
@media (prefers-reduced-motion: reduce) { .ai-spinner { animation: none; } }
@media (max-width: 780px) {
  .ai-draft-backdrop { padding: 8px; }
  .ai-draft-wizard { width: calc(100vw - 16px); height: calc(100dvh - 16px); max-height: calc(100dvh - 16px); }
  .ai-boundary, .ai-draft-body { padding-inline: 16px; }
  .ai-context-layout, .ai-context-form, .ai-review-fields, .ai-reference-list, .ai-mode-list, .ai-mode-confirm, .ai-check-list { grid-template-columns: 1fr; }
  .ai-context-form .wide, .ai-review-fields .wide { grid-column: auto; }
  .ai-recent-sessions { order: -1; }
  .ai-save-summary dl { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .ai-save-summary dl div { border: 0; }
  .ai-draft-actions, .ai-draft-actions > div { align-items: stretch; flex-direction: column-reverse; }
  .ai-content-source, .ai-batch-review-bar, .ai-batch-confirm, .ai-review-blockers { align-items: stretch; flex-direction: column; }
  .ai-batch-confirm > div:last-child { flex-direction: column-reverse; }
  .ai-draft-actions button { width: 100%; min-height: 44px; }
}
</style>
