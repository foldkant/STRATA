<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ApiError, type FieldErrors } from '@/api/client'
import {
  createTeacherLessonStep,
  deleteTeacherLessonStep,
  generateTeacherLessonStepQuestions,
  getTeacherCourse,
  getTeacherLesson,
  getTeacherLessonSteps,
  getTeacherResources,
  reorderTeacherLessonSteps,
  updateTeacherLessonStep,
  uploadTeacherResource,
  type CourseRow,
  type LessonRow,
  type LessonStepPayload,
  type LessonStepQuestion,
  type LessonStepQuestionType,
  type LessonStepRow,
  type LessonStepType,
  type ResourceBinding,
  type ResourceRow
} from '@/api/teacher'
import AppShell from '@/layouts/AppShell.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import ResourcePreview from '@/components/ResourcePreview.vue'
import { teacherNav } from './nav'

type ToolTab = 'resource' | 'question' | 'document' | 'ai'
type PreviewMode = 'student' | 'resource'
type QuestionLayerMode = 'standard' | 'layered_score' | 'layered_target'
type LayerCode = 'A' | 'B' | 'C'
type QuestionLibraryItem = LessonStepQuestion & {
  library_key: string
  source_step_id: number | null
  source_step_title: string
  from_current_step: boolean
}

const route = useRoute()
const lessonId = computed(() => Number(route.params.lessonId || 0))
const navItems = teacherNav('/teacher/courses')
const loading = ref(false)
const saving = ref(false)
const notice = ref('')
const lesson = ref<LessonRow | null>(null)
const course = ref<CourseRow | null>(null)
const lessonSteps = ref<LessonStepRow[]>([])
const activeStepId = ref<number | null>(null)
const activeTool = ref<ToolTab>('resource')
const formErrors = ref<FieldErrors>({})
const resourceErrors = ref<FieldErrors>({})
const resourceLoading = ref(false)
const resourceSaving = ref(false)
const resourceRows = ref<ResourceRow[]>([])
const resourceQuery = ref('')
const selectedResourceFile = ref<File | null>(null)
const resourceFileInput = ref<HTMLInputElement | null>(null)
const selectedPreviewResource = ref<ResourceBinding | null>(null)
const previewOpen = ref(false)
const previewMode = ref<PreviewMode>('student')
const editingQuestionId = ref<string | null>(null)
const stepModalOpen = ref(false)
const resourceUploadOpen = ref(false)
const questionBuilderOpen = ref(false)
const aiQuestionModalOpen = ref(false)
const settingsOpen = ref(false)
const questionListRef = ref<HTMLElement | null>(null)
const lastTouchedQuestionId = ref('')
const aiQuestionLoading = ref(false)
const aiQuestionErrors = ref<FieldErrors>({})
const aiQuestionNotice = ref('')
const aiGeneratedQuestions = ref<LessonStepQuestion[]>([])
const aiGeneratedGroups = ref<Array<{
  target_layer: string
  target_layer_label: string
  questions: LessonStepQuestion[]
  score_defaults: {
    base_score: number
    layer_scores: Record<LayerCode, number>
  }
}>>([])
const aiScoreDefaults = ref<{ base_score: number; groups: Record<string, { base_score: number; layer_scores: Record<LayerCode, number> }>; note: string } | null>(null)

const stepTypeOptions: Array<{ value: LessonStepType; label: string }> = [
  { value: 'intro', label: '导入' },
  { value: 'resource', label: '资源学习' },
  { value: 'question', label: '课堂题' },
  { value: 'task', label: '任务实践' },
  { value: 'upload', label: '作品上传' },
  { value: 'discussion', label: '讨论反馈' },
  { value: 'evaluation', label: '展示评价' },
  { value: 'reflection', label: '小结反思' },
  { value: 'ai_worksheet', label: 'AI 学习单' },
  { value: 'document', label: '协作文档' }
]

const targetLayerOptions = [
  { value: 'all', label: '全体' },
  { value: 'A', label: 'A' },
  { value: 'B', label: 'B' },
  { value: 'C', label: 'C' },
  { value: 'A/B', label: 'A/B' },
  { value: 'B/C', label: 'B/C' },
  { value: 'A/B/C', label: 'A/B/C' }
]
const targetLayerSpecificOptions = targetLayerOptions.filter((item) => !['all', 'A/B/C'].includes(item.value))
const questionLayerModeOptions: Array<{ value: QuestionLayerMode; label: string; description: string }> = [
  { value: 'standard', label: '普通同分', description: '所有学生看到同一道题，使用基础分值。' },
  { value: 'layered_score', label: '同题分层分值', description: '所有层级看到同一道题，A/B/C 可设置不同分值。' },
  { value: 'layered_target', label: '分层专属题', description: '只给指定层级或相邻层级显示，可按需要设置分值。' }
]
const layerScoreCodes: LayerCode[] = ['A', 'B', 'C']

const stepForm = reactive<LessonStepPayload>({
  title: '',
  step_type: 'resource',
  student_instruction: '',
  teacher_note: '',
  sort_order: 10,
  is_required: true,
  estimated_minutes: 10,
  target_layer: 'all',
  status: 'ready',
  resource_items: [],
  activity_items: [],
  question_items: [],
  ai_prompt: '',
  collect_student_log: true,
  collect_class_log: true
})

const questionDraft = reactive<LessonStepQuestion>({
  id: '',
  question_type: 'single',
  stem: '',
  options: ['', ''],
  answer: [],
  score: 2,
  target_layer: 'all',
  use_layer_scores: false,
  layer_scores: { A: '', B: '', C: '' },
  analysis: '',
  is_required: true,
  sort_order: 10
})

const resourceUploadForm = reactive({
  title: '',
  content: ''
})

const aiQuestionForm = reactive({
  direction: '',
  question_type: 'single' as LessonStepQuestionType,
  count: 1,
  requirement: ''
})

const allowedResourceExt = new Set([
  'jpg',
  'jpeg',
  'png',
  'webp',
  'gif',
  'mp4',
  'webm',
  'mov',
  'mp3',
  'wav',
  'pdf',
  'doc',
  'docx',
  'ppt',
  'pptx',
  'xls',
  'xlsx',
  'csv',
  'txt',
  'md',
  'zip',
  'rar',
  '7z'
])

const questionTypeOptions: Array<{ value: LessonStepQuestionType; label: string }> = [
  { value: 'single', label: '单选' },
  { value: 'multiple', label: '多选' },
  { value: 'judge', label: '判断' },
  { value: 'blank', label: '填空' },
  { value: 'text', label: '简答' }
]

const documentRows = [
  { title: '教师协同教案', scope: '备课组', permission: '教师可编辑' },
  { title: '学生任务单', scope: '学生只读', permission: '禁止外链脚本' },
  { title: '小组协作文档', scope: '按小组复制', permission: '组内编辑' }
]

const activeStep = computed(() => lessonSteps.value.find((item) => item.id === activeStepId.value) || null)
const activeStepIndex = computed(() => lessonSteps.value.findIndex((item) => item.id === activeStepId.value))
const lessonTitle = computed(() => lesson.value?.title || '课时设计')
const courseTitle = computed(() => course.value?.title || lesson.value?.course_title || '课程')
const subjectName = computed(() => course.value?.subject?.name || '未设置学科')
const totalMinutes = computed(() => lessonSteps.value.reduce((total, item) => total + item.estimated_minutes, 0))
const teachingModeTitle = computed(() => (course.value?.teaching_model === 'pbl' ? '项目式学习课时设计' : '任务驱动课时设计'))
const currentStepLabel = computed(() => activeStep.value ? '编辑环节' : '新增环节')
const canMoveUp = computed(() => activeStepIndex.value > 0)
const canMoveDown = computed(() => activeStepIndex.value >= 0 && activeStepIndex.value < lessonSteps.value.length - 1)
const selectedTargetLayerLabel = computed(() => targetLayerOptions.find((item) => item.value === stepForm.target_layer)?.label || '全体')
const questionCount = computed(() => stepForm.question_items.length)
const activeQuestionItems = computed(() => [...stepForm.question_items].sort((a, b) => Number(a.sort_order) - Number(b.sort_order)))
const layeredQuestionCount = computed(() => stepForm.question_items.filter((item) => getQuestionLayerMode(item) !== 'standard').length)
const standardQuestionCount = computed(() => Math.max(questionCount.value - layeredQuestionCount.value, 0))
const lessonQuestionLibrary = computed<QuestionLibraryItem[]>(() => {
  const rows: QuestionLibraryItem[] = []
  stepForm.question_items.forEach((item, index) => {
    rows.push({
      ...item,
      library_key: `current:${item.id || index}`,
      source_step_id: activeStepId.value,
      source_step_title: stepForm.title || '当前环节',
      from_current_step: true
    })
  })
  lessonSteps.value.forEach((step) => {
    if (step.id === activeStepId.value) return
    ;(step.question_items || []).forEach((item, index) => {
      rows.push({
        ...item,
        library_key: `${step.id}:${item.id || index}`,
        source_step_id: step.id,
        source_step_title: step.title,
        from_current_step: false
      })
    })
  })
  return rows.sort((a, b) => Number(a.sort_order) - Number(b.sort_order) || a.source_step_title.localeCompare(b.source_step_title))
})
const isChoiceQuestion = computed(() => ['single', 'multiple'].includes(questionDraft.question_type))
const isJudgeQuestion = computed(() => questionDraft.question_type === 'judge')
const questionNeedsOptions = computed(() => isChoiceQuestion.value || isJudgeQuestion.value)
const stepModalTitle = computed(() => (activeStep.value ? '编辑环节' : '新增环节'))
const questionLayerMode = computed<QuestionLayerMode>({
  get() {
    return getQuestionLayerMode(questionDraft)
  },
  set(value) {
    applyQuestionLayerMode(value)
  }
})
const activeLayerScoreCodes = computed(() => layerCodesFromTarget(questionDraft.target_layer))
const questionLayerModeHelp = computed(() => {
  if (questionLayerMode.value === 'standard') return '普通课堂和分层课堂都会显示这道题，学生使用统一基础分。'
  if (questionLayerMode.value === 'layered_score') return '适合“同题不同评价标准”，分层课堂中学生只获得自己层级对应分值。'
  return '适合“不同层级做不同题”，分层课堂中只有匹配层级的学生能看到。'
})

function targetLayerLabel(value: string) {
  return targetLayerOptions.find((item) => item.value === value)?.label || '全体'
}

function layerCodesFromTarget(value: string): LayerCode[] {
  if (!value || value === 'all') return ['A', 'B', 'C']
  return value.split('/').filter((item): item is LayerCode => ['A', 'B', 'C'].includes(item))
}

function scoreNumber(value: number | string | undefined | null, fallback = 0) {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

function defaultScoreForType(type: LessonStepQuestionType) {
  if (type === 'text') return 5
  if (type === 'blank') return 3
  return 2
}

function suggestedLayerScores(baseScore: number, targetLayer = questionDraft.target_layer): Record<LayerCode, number> {
  const scores: Record<LayerCode, number> = { A: baseScore, B: baseScore, C: baseScore }
  if (targetLayer === 'A') scores.A = Math.min(baseScore + 1, 100)
  if (targetLayer === 'C') scores.C = Math.max(baseScore - 0.5, 0)
  if (targetLayer === 'A/B') scores.A = Math.min(baseScore + 0.5, 100)
  if (targetLayer === 'B/C') scores.C = Math.max(baseScore - 0.5, 0)
  return scores
}

function syncLayerScoresWithBase(overwrite = false) {
  const baseScore = scoreNumber(questionDraft.score)
  const suggested = suggestedLayerScores(baseScore, questionDraft.target_layer)
  layerScoreCodes.forEach((layer) => {
    if (overwrite || questionDraft.layer_scores[layer] === '' || questionDraft.layer_scores[layer] === undefined || questionDraft.layer_scores[layer] === null) {
      questionDraft.layer_scores[layer] = suggested[layer]
    }
  })
}

function getQuestionLayerMode(item: Pick<LessonStepQuestion, 'target_layer' | 'use_layer_scores'>): QuestionLayerMode {
  if (item.target_layer && item.target_layer !== 'all' && item.target_layer !== 'A/B/C') return 'layered_target'
  if (item.use_layer_scores) return 'layered_score'
  return 'standard'
}

function applyQuestionLayerMode(value: QuestionLayerMode) {
  if (value === 'standard') {
    questionDraft.target_layer = 'all'
    questionDraft.use_layer_scores = false
    syncLayerScoresWithBase(true)
    return
  }
  if (value === 'layered_score') {
    questionDraft.target_layer = 'A/B/C'
    questionDraft.use_layer_scores = true
    syncLayerScoresWithBase(false)
    return
  }
  questionDraft.target_layer = questionDraft.target_layer && !['all', 'A/B/C'].includes(questionDraft.target_layer)
    ? questionDraft.target_layer
    : 'B/C'
  questionDraft.use_layer_scores = false
  syncLayerScoresWithBase(false)
}

function onQuestionTargetLayerChange() {
  if (questionLayerMode.value === 'layered_score') {
    questionDraft.target_layer = 'A/B/C'
  }
  syncLayerScoresWithBase(false)
}

function onQuestionBaseScoreInput() {
  syncLayerScoresWithBase(false)
}

function questionScoreSummary(item: LessonStepQuestion) {
  const baseScore = scoreNumber(item.score)
  if (!item.use_layer_scores) return `${baseScore} 分`
  return layerCodesFromTarget(item.target_layer)
    .map((layer) => `${layer}:${scoreNumber(item.layer_scores?.[layer as 'A' | 'B' | 'C'], baseScore)}`)
    .join(' / ')
}

function questionLayerModeLabel(item: LessonStepQuestion) {
  const mode = getQuestionLayerMode(item)
  if (mode === 'standard') return '普通同分'
  if (mode === 'layered_score') return '同题分层分值'
  return '分层专属题'
}

function makeQuestionId() {
  return `q_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

function maxSortOrder() {
  return lessonSteps.value.length ? Math.max(...lessonSteps.value.map((item) => item.sort_order)) : 0
}

function firstPreviewableResource(items: Array<ResourceBinding | string>) {
  return items.find((item): item is ResourceBinding => typeof item !== 'string' && Boolean(item.id || item.attachment_url)) || null
}

function canPreviewResource(item: ResourceBinding | string): item is ResourceBinding {
  return typeof item !== 'string' && Boolean(item.id || item.attachment_url)
}

function openResourcePreview(item: ResourceBinding | string) {
  if (!canPreviewResource(item)) return
  selectedPreviewResource.value = item
  previewMode.value = 'resource'
  previewOpen.value = true
}

function openStudentPreview() {
  selectedPreviewResource.value = selectedPreviewResource.value || firstPreviewableResource(stepForm.resource_items)
  previewMode.value = 'student'
  previewOpen.value = true
}

function resetStepForm() {
  formErrors.value = {}
  selectedPreviewResource.value = null
  stepForm.title = ''
  stepForm.step_type = 'resource'
  stepForm.student_instruction = ''
  stepForm.teacher_note = ''
  stepForm.sort_order = maxSortOrder() + 10
  stepForm.is_required = true
  stepForm.estimated_minutes = 10
  stepForm.target_layer = 'all'
  stepForm.status = 'ready'
  stepForm.resource_items = []
  stepForm.activity_items = []
  stepForm.question_items = []
  stepForm.ai_prompt = ''
  stepForm.collect_student_log = true
  stepForm.collect_class_log = true
  resetQuestionDraft()
}

function fillStepForm(row: LessonStepRow) {
  formErrors.value = {}
  stepForm.title = row.title
  stepForm.step_type = row.step_type
  stepForm.student_instruction = row.student_instruction
  stepForm.teacher_note = row.teacher_note
  stepForm.sort_order = row.sort_order
  stepForm.is_required = row.is_required
  stepForm.estimated_minutes = row.estimated_minutes
  stepForm.target_layer = row.target_layer
  stepForm.status = row.status
  stepForm.resource_items = [...row.resource_items]
  stepForm.activity_items = [...row.activity_items]
  stepForm.question_items = [...(row.question_items || [])]
  stepForm.ai_prompt = row.ai_prompt
  stepForm.collect_student_log = row.collect_student_log
  stepForm.collect_class_log = row.collect_class_log
  selectedPreviewResource.value = firstPreviewableResource(stepForm.resource_items)
  resetQuestionDraft()
}

function createNewStep() {
  activeStepId.value = null
  resetStepForm()
  stepModalOpen.value = true
}

function selectStep(row: LessonStepRow) {
  activeStepId.value = row.id
  fillStepForm(row)
}

function openEditStepModal(row = activeStep.value) {
  if (!row) return
  if (row.id !== activeStepId.value) {
    selectStep(row)
  }
  stepModalOpen.value = true
}

function stepTypeLabel(value: string) {
  return stepTypeOptions.find((item) => item.value === value)?.label || value
}

function cleanActivityItems(items: string[]) {
  return items.map((item) => item.trim()).filter(Boolean).slice(0, 30)
}

function questionTypeLabel(value: string) {
  return questionTypeOptions.find((item) => item.value === value)?.label || value
}

function questionOptionRows(question = questionDraft) {
  if (question.question_type === 'judge') return ['正确', '错误']
  return question.options
}

function cleanQuestionItems(items: LessonStepQuestion[]) {
  return [...items]
    .map((item, index) => {
      const questionType = item.question_type
      const options = questionType === 'judge'
        ? ['正确', '错误']
        : item.options.map((option) => option.trim()).filter(Boolean).slice(0, 8)
      const answer = item.answer.map((value) => value.trim()).filter(Boolean)
      return {
        ...item,
        id: item.id || makeQuestionId(),
        stem: item.stem.trim(),
        question_type: questionType,
        options,
        answer: questionType === 'single' || questionType === 'judge' ? answer.slice(0, 1) : answer,
        score: scoreNumber(item.score),
        target_layer: targetLayerOptions.some((option) => option.value === item.target_layer) ? item.target_layer : 'all',
        use_layer_scores: Boolean(item.use_layer_scores) && item.target_layer !== 'all',
        layer_scores: {
          A: scoreNumber(item.layer_scores?.A, scoreNumber(item.score)),
          B: scoreNumber(item.layer_scores?.B, scoreNumber(item.score)),
          C: scoreNumber(item.layer_scores?.C, scoreNumber(item.score))
        },
        analysis: item.analysis.trim(),
        is_required: item.is_required,
        sort_order: Number(item.sort_order) || (index + 1) * 10
      }
    })
    .filter((item) => item.stem.length >= 2)
    .slice(0, 30)
    .sort((a, b) => Number(a.sort_order) - Number(b.sort_order))
}

function resetQuestionDraft(type: LessonStepQuestionType = 'single') {
  editingQuestionId.value = null
  questionDraft.id = ''
  questionDraft.question_type = type
  questionDraft.stem = ''
  questionDraft.options = type === 'judge' ? ['正确', '错误'] : ['', '']
  questionDraft.answer = []
  questionDraft.score = defaultScoreForType(type)
  questionDraft.target_layer = 'all'
  questionDraft.use_layer_scores = false
  questionDraft.layer_scores = suggestedLayerScores(defaultScoreForType(type), 'all')
  questionDraft.analysis = ''
  questionDraft.is_required = true
  questionDraft.sort_order = (stepForm.question_items.length + 1) * 10
}

function onQuestionTypeChange() {
  questionDraft.score = defaultScoreForType(questionDraft.question_type)
  if (questionDraft.question_type === 'judge') {
    questionDraft.options = ['正确', '错误']
    questionDraft.answer = []
  } else if (['single', 'multiple'].includes(questionDraft.question_type)) {
    questionDraft.options = questionDraft.options.filter(Boolean).length ? questionDraft.options : ['', '']
    questionDraft.answer = []
  } else {
    questionDraft.options = []
    questionDraft.answer = []
  }
  syncLayerScoresWithBase(true)
}

function addQuestionOption() {
  if (questionDraft.options.length >= 8 || isJudgeQuestion.value) return
  questionDraft.options = [...questionDraft.options, '']
}

function removeQuestionOption(index: number) {
  if (isJudgeQuestion.value) return
  const removed = questionDraft.options[index]
  questionDraft.options = questionDraft.options.filter((_, itemIndex) => itemIndex !== index)
  questionDraft.answer = questionDraft.answer.filter((value) => value !== removed)
}

function setQuestionOption(index: number, value: string) {
  const previous = questionDraft.options[index]
  questionDraft.options[index] = value
  if (previous && questionDraft.answer.includes(previous)) {
    questionDraft.answer = questionDraft.answer.map((item) => (item === previous ? value : item)).filter(Boolean)
  }
}

function toggleQuestionAnswer(value: string, checked: boolean) {
  if (!value) return
  if (questionDraft.question_type === 'single' || questionDraft.question_type === 'judge') {
    questionDraft.answer = [value]
    return
  }
  questionDraft.answer = checked
    ? Array.from(new Set([...questionDraft.answer, value]))
    : questionDraft.answer.filter((item) => item !== value)
}

function setTextQuestionAnswer(value: string) {
  questionDraft.answer = value.trim() ? [value] : []
}

function validateQuestionDraft() {
  const errors: string[] = []
  const stem = questionDraft.stem.trim()
  const score = Number(questionDraft.score)
  const options = questionOptionRows().map((option) => option.trim()).filter(Boolean)
  if (stem.length < 2 || stem.length > 1000) errors.push('题干需为 2-1000 个字符。')
  if (!Number.isFinite(score) || score < 0 || score > 100) errors.push('分值需为 0-100。')
  if (isChoiceQuestion.value && options.length < 2) errors.push('选择题至少需要 2 个选项。')
  if (!targetLayerOptions.some((item) => item.value === questionDraft.target_layer)) errors.push('题目适用层级不正确。')
  if (questionLayerMode.value === 'layered_target' && ['all', 'A/B/C'].includes(questionDraft.target_layer)) {
    errors.push('分层专属题需选择 A、B、C、A/B 或 B/C。')
  }
  if (questionLayerMode.value === 'layered_score' && questionDraft.target_layer !== 'A/B/C') {
    errors.push('同题分层分值需面向 A/B/C。')
  }
  if (questionDraft.use_layer_scores) {
    layerCodesFromTarget(questionDraft.target_layer).forEach((layer) => {
      const value = Number(questionDraft.layer_scores[layer as 'A' | 'B' | 'C'])
      if (!Number.isFinite(value) || value < 0 || value > 100) {
        errors.push(`${layer} 层分值需为 0-100。`)
      }
    })
  }
  if (questionDraft.analysis.length > 1000) errors.push('解析不能超过 1000 个字符。')
  if (errors.length) {
    notice.value = errors[0]
    return false
  }
  return true
}

function saveQuestionDraft() {
  if (!validateQuestionDraft()) return
  const cleaned = cleanQuestionItems([
    {
      ...questionDraft,
      id: editingQuestionId.value || questionDraft.id || makeQuestionId(),
      options: questionOptionRows(),
      sort_order: Number(questionDraft.sort_order) || (stepForm.question_items.length + 1) * 10
    }
  ])[0]
  if (!cleaned) return
  const exists = stepForm.question_items.some((item) => item.id === cleaned.id)
  stepForm.question_items = exists
    ? stepForm.question_items.map((item) => (item.id === cleaned.id ? cleaned : item))
    : [...stepForm.question_items, cleaned]
  lastTouchedQuestionId.value = cleaned.id
  resetQuestionDraft(questionDraft.question_type)
  questionBuilderOpen.value = false
  notice.value = exists ? '题目已更新到当前环节，请保存环节后同步到学生端。' : '题目已加入当前环节，请保存环节后同步到学生端。'
  nextTick(() => {
    questionListRef.value?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  })
}

function editQuestion(item: LessonStepQuestion) {
  editingQuestionId.value = item.id
  questionDraft.id = item.id
  questionDraft.question_type = item.question_type
  questionDraft.stem = item.stem
  questionDraft.options = item.question_type === 'judge' ? ['正确', '错误'] : [...item.options]
  questionDraft.answer = [...item.answer]
  questionDraft.score = item.score
  questionDraft.target_layer = item.target_layer || 'all'
  questionDraft.use_layer_scores = Boolean(item.use_layer_scores)
  questionDraft.layer_scores = {
    A: item.layer_scores?.A ?? item.score,
    B: item.layer_scores?.B ?? item.score,
    C: item.layer_scores?.C ?? item.score
  }
  questionDraft.analysis = item.analysis
  questionDraft.is_required = item.is_required
  questionDraft.sort_order = item.sort_order
  activeTool.value = 'question'
  questionBuilderOpen.value = true
}

function removeQuestionItem(id: string) {
  stepForm.question_items = stepForm.question_items.filter((item) => item.id !== id)
  if (editingQuestionId.value === id) resetQuestionDraft()
}

function openAiQuestionModal() {
  aiQuestionErrors.value = {}
  aiQuestionNotice.value = ''
  aiGeneratedQuestions.value = []
  aiGeneratedGroups.value = []
  aiScoreDefaults.value = null
  aiQuestionForm.direction = stepForm.ai_prompt || stepForm.student_instruction || ''
  aiQuestionForm.question_type = questionDraft.question_type || 'single'
  aiQuestionForm.count = 1
  aiQuestionForm.requirement = ''
  aiQuestionModalOpen.value = true
}

function validateAiQuestionForm() {
  const errors: FieldErrors = {}
  if (aiQuestionForm.direction.trim().length < 4 || aiQuestionForm.direction.trim().length > 1000) {
    errors.direction = ['出题方向需为 4-1000 个字符。']
  }
  if (!questionTypeOptions.some((item) => item.value === aiQuestionForm.question_type)) {
    errors.question_type = ['题型不正确。']
  }
  const count = Number(aiQuestionForm.count)
  if (!Number.isInteger(count) || count < 1 || count > 10) {
    errors.count = ['每组题目数量需为 1-10。']
  }
  if (aiQuestionForm.requirement.trim().length > 1000) {
    errors.requirement = ['补充要求不能超过 1000 个字符。']
  }
  aiQuestionErrors.value = errors
  return Object.keys(errors).length === 0
}

async function generateAiQuestions() {
  if (!validateAiQuestionForm()) return
  aiQuestionLoading.value = true
  aiQuestionNotice.value = ''
  aiGeneratedQuestions.value = []
  aiGeneratedGroups.value = []
  try {
    const result = await generateTeacherLessonStepQuestions({
      direction: aiQuestionForm.direction.trim(),
      question_type: aiQuestionForm.question_type,
      count: Number(aiQuestionForm.count),
      subject_name: subjectName.value,
      lesson_title: lessonTitle.value,
      step_title: stepForm.title,
      student_instruction: stepForm.student_instruction,
      requirement: aiQuestionForm.requirement.trim()
    })
    const allQuestions = result.questions.map((item, index) => ({
      ...item,
      id: item.id || makeQuestionId(),
      sort_order: (stepForm.question_items.length + index + 1) * 10
    }))
    aiGeneratedQuestions.value = allQuestions
    aiGeneratedGroups.value = result.groups.map((group) => ({
      ...group,
      questions: allQuestions.filter((question) => question.target_layer === group.target_layer)
    }))
    aiScoreDefaults.value = result.score_defaults
    aiQuestionNotice.value = `已生成 ${result.questions.length} 道草稿，覆盖 A、B、C、A/B、B/C 五组。请确认或修改后加入当前环节。`
  } catch (error) {
    if (error instanceof ApiError) {
      aiQuestionNotice.value = error.message
      aiQuestionErrors.value = error.errors
    } else {
      aiQuestionNotice.value = 'AI 出题失败，请稍后重试。'
    }
  } finally {
    aiQuestionLoading.value = false
  }
}

function addAiGeneratedQuestion(item: LessonStepQuestion) {
  const cleaned = cleanQuestionItems([
    {
      ...item,
      id: makeQuestionId(),
      sort_order: (stepForm.question_items.length + 1) * 10
    }
  ])[0]
  if (!cleaned) return
  stepForm.question_items = [...stepForm.question_items, cleaned]
  lastTouchedQuestionId.value = cleaned.id
  aiGeneratedQuestions.value = aiGeneratedQuestions.value.filter((question) => question.id !== item.id)
  aiGeneratedGroups.value = aiGeneratedGroups.value.map((group) => ({
    ...group,
    questions: group.questions.filter((question) => question.id !== item.id)
  }))
  notice.value = 'AI 题目草稿已加入当前环节，请保存环节后同步到学生端。'
}

function editAiGeneratedQuestion(item: LessonStepQuestion) {
  editQuestion({
    ...item,
    id: makeQuestionId(),
    sort_order: (stepForm.question_items.length + 1) * 10
  })
  aiGeneratedQuestions.value = aiGeneratedQuestions.value.filter((question) => question.id !== item.id)
  aiGeneratedGroups.value = aiGeneratedGroups.value.map((group) => ({
    ...group,
    questions: group.questions.filter((question) => question.id !== item.id)
  }))
  aiQuestionModalOpen.value = false
}

function addAllAiGeneratedQuestions() {
  const cleaned = cleanQuestionItems(
    aiGeneratedQuestions.value.map((item, index) => ({
      ...item,
      id: makeQuestionId(),
      sort_order: (stepForm.question_items.length + index + 1) * 10
    }))
  )
  if (!cleaned.length) return
  stepForm.question_items = [...stepForm.question_items, ...cleaned]
  lastTouchedQuestionId.value = cleaned[cleaned.length - 1].id
  aiGeneratedQuestions.value = []
  aiGeneratedGroups.value = []
  aiQuestionModalOpen.value = false
  notice.value = `已加入 ${cleaned.length} 道 AI 题目草稿，请保存环节后同步到学生端。`
}

function isQuestionInCurrentStep(item: QuestionLibraryItem) {
  return item.from_current_step || stepForm.question_items.some((question) => question.id === item.id)
}

function addQuestionFromLibrary(item: QuestionLibraryItem) {
  if (isQuestionInCurrentStep(item)) {
    notice.value = '该题目已在当前环节中。'
    return
  }
  const cloned: LessonStepQuestion = {
    id: makeQuestionId(),
    question_type: item.question_type,
    question_type_label: item.question_type_label,
    stem: item.stem,
    options: [...item.options],
    answer: [...item.answer],
    score: item.score,
    target_layer: item.target_layer || 'all',
    target_layer_label: item.target_layer_label,
    use_layer_scores: Boolean(item.use_layer_scores),
    layer_scores: {
      A: item.layer_scores?.A ?? item.score,
      B: item.layer_scores?.B ?? item.score,
      C: item.layer_scores?.C ?? item.score
    },
    analysis: item.analysis,
    is_required: item.is_required,
    sort_order: (stepForm.question_items.length + 1) * 10
  }
  stepForm.question_items = [...stepForm.question_items, cloned]
  lastTouchedQuestionId.value = cloned.id
  notice.value = '题目已复制加入当前环节，请保存内容后同步到学生端。'
  nextTick(() => {
    questionListRef.value?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  })
}

function questionAnswerSummary(item: LessonStepQuestion) {
  if (!item.answer.length) return '未设置参考答案'
  return item.answer.join('、')
}

function resourceBindingFromRow(row: ResourceRow): ResourceBinding {
  return {
    id: row.id,
    title: row.title,
    attachment_url: row.attachment_url,
    attachment_name: row.attachment_name,
    file_ext: row.file_ext,
    kind: 'resource'
  }
}

function resourceTitle(item: ResourceBinding | string) {
  return typeof item === 'string' ? item : item.title || item.attachment_name || item.attachment_url || '未命名资源'
}

function resourceSubTitle(item: ResourceBinding | string) {
  if (typeof item === 'string') return '旧资源占位，重新从资源库加入后可预览。'
  const ext = item.file_ext ? item.file_ext.toUpperCase() : '资源'
  return item.attachment_name ? `${ext} · ${item.attachment_name}` : ext
}

function resourceKey(item: ResourceBinding | string) {
  return typeof item === 'string' ? `legacy:${item}` : `resource:${item.id || item.title}`
}

function isResourceInCurrentStep(item: ResourceBinding | string) {
  const key = resourceKey(item)
  return stepForm.resource_items.some((existing) => resourceKey(existing) === key)
}

function cleanResourceItems(items: Array<ResourceBinding | string>) {
  const cleaned: Array<ResourceBinding | string> = []
  const seen = new Set<string>()
  items.forEach((item) => {
    const key = resourceKey(item)
    if (!key || seen.has(key)) return
    seen.add(key)
    cleaned.push(item)
  })
  return cleaned.slice(0, 30)
}

function validateStepForm() {
  const errors: FieldErrors = {}
  const title = stepForm.title.trim()
  if (!/^[\u4e00-\u9fa5A-Za-z0-9（）()·《》：:，,。\.\-\s]{2,128}$/.test(title)) {
    errors.title = ['环节标题需为 2-128 位，可包含中文、字母、数字和常用标点。']
  }
  const estimated = Number(stepForm.estimated_minutes)
  if (!Number.isInteger(estimated) || estimated < 1 || estimated > 240) {
    errors.estimated_minutes = ['预计时长需为 1-240 的整数。']
  }
  const sortOrder = Number(stepForm.sort_order)
  if (!Number.isInteger(sortOrder) || sortOrder < 0 || sortOrder > 9999) {
    errors.sort_order = ['排序需为 0-9999 的整数。']
  }
  if (stepForm.student_instruction.trim().length > 5000) {
    errors.student_instruction = ['学生可见说明不能超过 5000 个字符。']
  }
  if (stepForm.teacher_note.trim().length > 5000) {
    errors.teacher_note = ['教师备课备注不能超过 5000 个字符。']
  }
  if (stepForm.ai_prompt.trim().length > 3000) {
    errors.ai_prompt = ['AI 生成目标不能超过 3000 个字符。']
  }
  formErrors.value = errors
  return Object.keys(errors).length === 0
}

function buildPayload(): LessonStepPayload {
  return {
    ...stepForm,
    title: stepForm.title.trim(),
    student_instruction: stepForm.student_instruction.trim(),
    teacher_note: stepForm.teacher_note.trim(),
    sort_order: Number(stepForm.sort_order),
    estimated_minutes: Number(stepForm.estimated_minutes),
    status: 'ready',
    resource_items: cleanResourceItems(stepForm.resource_items),
    activity_items: cleanActivityItems(stepForm.activity_items),
    question_items: cleanQuestionItems(stepForm.question_items),
    ai_prompt: stepForm.ai_prompt.trim()
  }
}

async function loadLesson() {
  if (!Number.isFinite(lessonId.value) || lessonId.value <= 0) {
    notice.value = '课时编号不正确。'
    return
  }
  loading.value = true
  try {
    const lessonRow = await getTeacherLesson(lessonId.value)
    lesson.value = lessonRow
    course.value = await getTeacherCourse(lessonRow.course)
    lessonSteps.value = await getTeacherLessonSteps(lessonRow.id)
    await loadResources()
    if (lessonSteps.value.length) {
      selectStep(lessonSteps.value[0])
    } else {
      createNewStep()
    }
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课时设计加载失败。'
  } finally {
    loading.value = false
  }
}

async function loadResources() {
  resourceLoading.value = true
  try {
    const rows = await getTeacherResources({ q: resourceQuery.value, page_size: 30 })
    resourceRows.value = rows.results
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '资源库加载失败。'
  } finally {
    resourceLoading.value = false
  }
}

async function saveStep() {
  if (!validateStepForm() || lessonId.value <= 0) return false
  saving.value = true
  try {
    const payload = buildPayload()
    const saved = activeStep.value
      ? await updateTeacherLessonStep(activeStep.value.id, payload)
      : await createTeacherLessonStep(lessonId.value, payload)
    const exists = lessonSteps.value.some((item) => item.id === saved.id)
    lessonSteps.value = exists
      ? lessonSteps.value.map((item) => (item.id === saved.id ? saved : item)).sort((a, b) => a.sort_order - b.sort_order || a.id - b.id)
      : [...lessonSteps.value, saved].sort((a, b) => a.sort_order - b.sort_order || a.id - b.id)
    activeStepId.value = saved.id
    fillStepForm(saved)
    notice.value = exists
      ? `课时环节已更新，已保存 ${saved.question_items.length} 道题。`
      : `课时环节已创建，已保存 ${saved.question_items.length} 道题。`
    return true
  } catch (error) {
    if (error instanceof ApiError) {
      notice.value = error.message
      formErrors.value = error.errors
    } else {
      notice.value = '课时环节保存失败。'
    }
    return false
  } finally {
    saving.value = false
  }
}

async function saveStepFromModal() {
  const succeeded = await saveStep()
  if (succeeded) stepModalOpen.value = false
}

async function removeStepFromModal() {
  await removeStep()
  stepModalOpen.value = false
}

async function removeStep() {
  if (!activeStep.value) return
  const confirmed = window.confirm(`确认删除环节“${activeStep.value.title}”？`)
  if (!confirmed) return
  saving.value = true
  try {
    const currentIndex = activeStepIndex.value
    await deleteTeacherLessonStep(activeStep.value.id)
    lessonSteps.value = lessonSteps.value.filter((item) => item.id !== activeStep.value?.id)
    const next = lessonSteps.value[Math.min(currentIndex, lessonSteps.value.length - 1)]
    if (next) selectStep(next)
    else createNewStep()
    notice.value = '课时环节已删除。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课时环节删除失败。'
  } finally {
    saving.value = false
  }
}

async function moveStep(direction: -1 | 1) {
  if (!activeStep.value || !lesson.value) return
  const currentIndex = activeStepIndex.value
  const targetIndex = currentIndex + direction
  if (targetIndex < 0 || targetIndex >= lessonSteps.value.length) return

  const reordered = [...lessonSteps.value]
  const [current] = reordered.splice(currentIndex, 1)
  reordered.splice(targetIndex, 0, current)
  saving.value = true
  try {
    lessonSteps.value = await reorderTeacherLessonSteps(lesson.value.id, reordered.map((item) => item.id))
    const selected = lessonSteps.value.find((item) => item.id === current.id)
    if (selected) selectStep(selected)
    notice.value = '课时环节排序已保存。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课时环节排序失败。'
  } finally {
    saving.value = false
  }
}

function moveStepByRow(row: LessonStepRow, direction: -1 | 1) {
  if (row.id !== activeStepId.value) {
    selectStep(row)
  }
  moveStep(direction)
}

function openCreateQuestionModal() {
  resetQuestionDraft()
  questionBuilderOpen.value = true
  activeTool.value = 'question'
}

function addResourceItem(item: ResourceBinding | string) {
  const value = typeof item === 'string' ? item.trim() : item
  if (!value || stepForm.resource_items.length >= 30) return
  const key = resourceKey(value)
  if (stepForm.resource_items.some((existing) => resourceKey(existing) === key)) return
  stepForm.resource_items = [...stepForm.resource_items, value]
  if (typeof value !== 'string') {
    selectedPreviewResource.value = value
  }
}

function formatFileSize(size: number) {
  if (!size) return '无附件'
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`
  return `${(size / 1024 / 1024).toFixed(size >= 100 * 1024 * 1024 ? 0 : 1)} MB`
}

function onResourceFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] || null
  resourceErrors.value = {}
  selectedResourceFile.value = file
  if (!file) return

  const cleanExt = file.name.includes('.') ? file.name.split('.').pop()?.toLowerCase() || '' : ''
  if (!allowedResourceExt.has(cleanExt)) {
    resourceErrors.value = { attachment: ['暂不支持该资源格式。'] }
    selectedResourceFile.value = null
    input.value = ''
    return
  }
  if (file.size > 512 * 1024 * 1024) {
    resourceErrors.value = { attachment: ['资源文件不能超过 512MB。'] }
    selectedResourceFile.value = null
    input.value = ''
    return
  }
  if (!resourceUploadForm.title.trim()) {
    resourceUploadForm.title = file.name.replace(/\.[^.]+$/, '').slice(0, 128)
  }
}

async function uploadResource() {
  if (!selectedResourceFile.value) {
    resourceErrors.value = { attachment: ['请选择要上传的资源文件。'] }
    return
  }
  const title = resourceUploadForm.title.trim()
  if (!/^[\u4e00-\u9fa5A-Za-z0-9（）()·《》：:，,。\._\-\s]{2,128}$/.test(title)) {
    resourceErrors.value = { title: ['资源标题需为 2-128 位，可包含中文、字母、数字、下划线和常用标点。'] }
    return
  }
  resourceSaving.value = true
  try {
    const saved = await uploadTeacherResource({
      title,
      content: resourceUploadForm.content.trim(),
      file: selectedResourceFile.value
    })
    resourceRows.value = [saved, ...resourceRows.value.filter((item) => item.id !== saved.id)]
    addResourceItem(resourceBindingFromRow(saved))
    resourceUploadForm.title = ''
    resourceUploadForm.content = ''
    selectedResourceFile.value = null
    if (resourceFileInput.value) {
      resourceFileInput.value.value = ''
    }
    resourceErrors.value = {}
    resourceUploadOpen.value = false
    notice.value = '资源已上传，并已加入当前环节。'
  } catch (error) {
    if (error instanceof ApiError) {
      notice.value = error.message
      resourceErrors.value = error.errors
    } else {
      notice.value = '资源上传失败。'
    }
  } finally {
    resourceSaving.value = false
  }
}

function removeResourceItem(index: number) {
  const removed = stepForm.resource_items[index]
  stepForm.resource_items = stepForm.resource_items.filter((_, itemIndex) => itemIndex !== index)
  if (typeof removed !== 'string' && selectedPreviewResource.value?.id === removed.id) {
    selectedPreviewResource.value = firstPreviewableResource(stepForm.resource_items)
  }
}

function moveResourceItem(index: number, direction: -1 | 1) {
  const targetIndex = index + direction
  if (targetIndex < 0 || targetIndex >= stepForm.resource_items.length) return
  const reordered = [...stepForm.resource_items]
  const [current] = reordered.splice(index, 1)
  reordered.splice(targetIndex, 0, current)
  stepForm.resource_items = reordered
}

function removeActivityItem(index: number) {
  stepForm.activity_items = stepForm.activity_items.filter((_, itemIndex) => itemIndex !== index)
}

function moveQuestionItem(id: string, direction: -1 | 1) {
  const ordered = activeQuestionItems.value
  const index = ordered.findIndex((item) => item.id === id)
  const targetIndex = index + direction
  if (index < 0 || targetIndex < 0 || targetIndex >= ordered.length) return
  const reordered = [...ordered]
  const [current] = reordered.splice(index, 1)
  reordered.splice(targetIndex, 0, current)
  stepForm.question_items = reordered.map((item, itemIndex) => ({
    ...item,
    sort_order: (itemIndex + 1) * 10
  }))
  if (editingQuestionId.value) {
    const editing = stepForm.question_items.find((item) => item.id === editingQuestionId.value)
    if (editing) questionDraft.sort_order = editing.sort_order
  }
}

onMounted(loadLesson)
</script>

<template>
  <AppShell title="课时设计" eyebrow="教师工作台" :nav-items="navItems" natural-scroll>
    <NoticeLine v-if="notice" :message="notice" />
    <section v-if="loading" class="panel"><p class="empty">正在加载课时设计</p></section>
    <section v-else class="lesson-designer-shell">
      <header class="lesson-designer-header lesson-designer-header-compact">
        <div>
          <p>{{ subjectName }} · {{ courseTitle }} · 课时编号 {{ lessonId }}</p>
          <h2>{{ lessonTitle }}</h2>
          <span>{{ teachingModeTitle }}。备课页制作学习过程；课堂教学负责开始课堂、投放环节和控制进度。</span>
        </div>
        <div class="lesson-designer-actions">
          <RouterLink class="secondary-button" to="/teacher/courses">返回课程</RouterLink>
          <RouterLink class="secondary-button" to="/teacher/classroom">课堂教学</RouterLink>
          <button class="secondary-button" type="button" @click="openStudentPreview">大屏预览</button>
        </div>
      </header>

      <div class="lesson-designer-grid refined-lesson-designer-grid">
        <aside class="designer-pane lesson-step-rail">
          <div class="designer-pane-header">
            <div>
              <strong>学习过程</strong>
              <span>{{ lessonSteps.length }} 个环节 · {{ totalMinutes }} 分钟</span>
            </div>
            <button class="secondary-button compact-button" type="button" @click="createNewStep">新增环节</button>
          </div>

          <div v-if="lessonSteps.length" class="step-tree-list">
            <article
              v-for="(step, index) in lessonSteps"
              :key="step.id"
              class="step-tree-item"
              :class="{ active: step.id === activeStepId }"
            >
              <button class="step-tree-main" type="button" @click="selectStep(step)">
                <em>{{ index + 1 }}</em>
                <span>
                  <strong>{{ step.title }}</strong>
                  <small>{{ step.step_type_label }} · {{ step.estimated_minutes }} 分钟 · {{ step.target_layer_label }}</small>
                </span>
              </button>
              <div class="step-tree-actions">
                <button type="button" @click="openEditStepModal(step)">编辑</button>
                <button type="button" :disabled="index === 0 || saving" @click="moveStepByRow(step, -1)">上移</button>
                <button type="button" :disabled="index === lessonSteps.length - 1 || saving" @click="moveStepByRow(step, 1)">下移</button>
              </div>
            </article>
          </div>
          <div v-else class="step-empty-state">
            <strong>还没有课时环节</strong>
            <span>先新增导入、资源学习、课堂题或任务实践环节。</span>
            <button class="primary-button" type="button" @click="createNewStep">新增第一个环节</button>
          </div>
        </aside>

        <main class="designer-pane step-editor-pane lesson-editor-workspace">
          <div class="designer-pane-header">
            <div>
              <strong>{{ stepForm.title || currentStepLabel }}</strong>
              <span>
                {{ stepTypeLabel(stepForm.step_type) }} · 面向 {{ selectedTargetLayerLabel }} ·
                {{ stepForm.resource_items.length }} 个资源 · {{ questionCount }} 道题
              </span>
            </div>
            <div class="lesson-step-toolbar">
              <button class="secondary-button compact-button" type="button" :disabled="!activeStep" @click="openEditStepModal()">编辑环节</button>
              <button class="secondary-button compact-button" type="button" @click="settingsOpen = true">高级设置</button>
              <button class="primary-button compact-button" type="button" :disabled="saving" @click="saveStep">
                {{ saving ? '保存中' : '保存内容' }}
              </button>
            </div>
          </div>

          <section class="step-composition priority-step-composition">
            <div class="step-content-groups">
              <section class="step-content-group step-overview-group">
                <header>
                  <div>
                    <strong>当前环节内容</strong>
                    <span>环节说明、资源和题目会一起保存并同步到学生端。</span>
                  </div>
                  <small>{{ stepTypeLabel(stepForm.step_type) }}</small>
                </header>
                <div class="step-overview-body">
                  <article>
                    <span>环节</span>
                    <strong>{{ stepForm.title || '未命名环节' }}</strong>
                    <small>{{ stepForm.student_instruction || '暂未填写学生可见说明。' }}</small>
                  </article>
                  <div class="composition-item-actions overview-actions">
                    <button type="button" @click="activeStep ? openEditStepModal() : createNewStep()">编辑环节</button>
                    <button type="button" @click="settingsOpen = true">高级设置</button>
                    <button type="button" @click="openStudentPreview">学生预览</button>
                  </div>
                </div>
              </section>

              <section class="step-content-group step-resource-group">
                <header>
                  <div>
                    <strong>资源顺序</strong>
                    <span>学生端按这里的顺序显示课件、视频和附件。</span>
                  </div>
                  <small>{{ stepForm.resource_items.length }} 个资源</small>
                </header>
                <div class="composition-list single-column-list">
                  <article v-for="(resource, index) in stepForm.resource_items" :key="resourceKey(resource)">
                    <span>资源 {{ index + 1 }}</span>
                    <strong>{{ resourceTitle(resource) }}</strong>
                    <small>{{ resourceSubTitle(resource) }}</small>
                    <div class="composition-item-actions">
                      <button type="button" :disabled="index === 0" @click="moveResourceItem(index, -1)">上移</button>
                      <button type="button" :disabled="index === stepForm.resource_items.length - 1" @click="moveResourceItem(index, 1)">下移</button>
                      <button v-if="canPreviewResource(resource)" type="button" @click="openResourcePreview(resource)">网页内预览</button>
                      <button type="button" @click="removeResourceItem(index)">移除</button>
                    </div>
                  </article>
                  <p v-if="!stepForm.resource_items.length" class="empty">
                    暂无资源。请从右侧“资源”中上传或从资源库加入。
                  </p>
                </div>
              </section>

              <section ref="questionListRef" class="step-content-group step-question-group">
                <header>
                  <div>
                    <strong>题目顺序</strong>
                    <span>学生端按这里的顺序显示课堂题。</span>
                  </div>
                  <small>{{ questionCount }} 道题</small>
                </header>
                <div class="layer-status-note">
                  <span>普通题 {{ standardQuestionCount }} 道</span>
                  <span>分层题 {{ layeredQuestionCount }} 道</span>
                  <small>分层过滤和 A/B/C 分值只在课堂教学开启“分层教学模式”后生效。</small>
                </div>
                <div class="composition-list single-column-list">
                  <article v-for="(question, index) in activeQuestionItems" :key="question.id" class="question-composition-card">
                    <span>题目 {{ index + 1 }}</span>
                  <strong>{{ question.stem }}</strong>
                  <small>
                    {{ questionTypeLabel(question.question_type) }} · {{ questionLayerModeLabel(question) }} · {{ targetLayerLabel(question.target_layer) }} · {{ questionScoreSummary(question) }} ·
                    {{ question.is_required ? '必答' : '选答' }}
                  </small>
                    <small class="question-answer-preview">参考答案：{{ questionAnswerSummary(question) }}</small>
                    <div class="composition-item-actions">
                      <button type="button" :disabled="index === 0" @click="moveQuestionItem(question.id, -1)">上移</button>
                      <button type="button" :disabled="index === activeQuestionItems.length - 1" @click="moveQuestionItem(question.id, 1)">下移</button>
                      <button type="button" @click="editQuestion(question)">编辑</button>
                      <button type="button" @click="removeQuestionItem(question.id)">移除</button>
                    </div>
                  </article>
                  <p v-if="!activeQuestionItems.length" class="empty">
                    暂无题目。请切换到右侧“题目”制作并加入当前环节。
                  </p>
                </div>
              </section>

              <section v-if="stepForm.activity_items.length" class="step-content-group step-activity-group">
                <header>
                  <div>
                    <strong>活动 / 任务</strong>
                    <span>旧版本占位内容，后续会升级为正式任务组件。</span>
                  </div>
                  <small>{{ stepForm.activity_items.length }} 项</small>
                </header>
                <div class="composition-list single-column-list">
                  <article v-for="(activity, index) in stepForm.activity_items" :key="`activity-${activity}`">
                    <span>活动 {{ index + 1 }}</span>
                    <strong>{{ activity }}</strong>
                    <small>后续可配置作答、提交、收题和完成统计。</small>
                    <button type="button" @click="removeActivityItem(index)">移除</button>
                  </article>
                </div>
              </section>
            </div>
          </section>

        </main>

        <aside class="designer-pane designer-side-pane lesson-tool-drawer">
          <div class="designer-tabs">
            <button :class="{ active: activeTool === 'resource' }" type="button" @click="activeTool = 'resource'">资源</button>
            <button :class="{ active: activeTool === 'question' }" type="button" @click="activeTool = 'question'">题目</button>
            <button :class="{ active: activeTool === 'document' }" type="button" @click="activeTool = 'document'">文档</button>
            <button :class="{ active: activeTool === 'ai' }" type="button" @click="activeTool = 'ai'">AI</button>
          </div>

          <div v-if="activeTool === 'resource'" class="resource-side-panel">
            <section class="tool-entry-panel">
              <strong>资源</strong>
              <p>上传课件、视频、素材包或从资源库选择，加入后会进入当前环节的资源顺序。</p>
              <button class="primary-button" type="button" @click="resourceUploadOpen = true">上传资源</button>
            </section>

            <section class="resource-library-panel">
              <div class="resource-library-toolbar">
                <input v-model.trim="resourceQuery" placeholder="搜索我的资源" @keyup.enter="loadResources" />
                <button class="secondary-button" type="button" :disabled="resourceLoading" @click="loadResources">
                  {{ resourceLoading ? '刷新中' : '刷新' }}
                </button>
              </div>
              <div class="designer-side-list compact-resource-list">
                <article v-for="item in resourceRows" :key="item.id">
                  <strong>{{ item.title }}</strong>
                  <span>{{ item.file_ext ? item.file_ext.toUpperCase() : '资源' }} · {{ formatFileSize(item.attachment_size) }}</span>
                  <small>{{ item.attachment_name || item.content || '暂无附件说明' }}</small>
                  <div class="resource-card-actions">
                    <button type="button" @click="openResourcePreview(resourceBindingFromRow(item))">网页内预览</button>
                    <a v-if="item.attachment_url" :href="item.attachment_url" download>下载</a>
                    <button
                      type="button"
                      :disabled="isResourceInCurrentStep(resourceBindingFromRow(item))"
                      @click="addResourceItem(resourceBindingFromRow(item))"
                    >
                      {{ isResourceInCurrentStep(resourceBindingFromRow(item)) ? '已在当前环节' : '加入环节' }}
                    </button>
                  </div>
                </article>
                <p v-if="!resourceLoading && !resourceRows.length" class="empty">暂无资源。可以先上传课件、视频、素材包或 PDF。</p>
              </div>
            </section>
          </div>

          <div v-else-if="activeTool === 'question'" class="question-tool-panel">
            <section class="tool-entry-panel">
              <strong>题目</strong>
              <p>新增课堂题后会加入当前环节。开启分层后，可设置题目适用层级和 A/B/C 分值。</p>
              <div class="tool-entry-actions">
                <button class="primary-button" type="button" @click="openCreateQuestionModal">新增课堂题</button>
                <button class="secondary-button" type="button" @click="openAiQuestionModal">AI 生成分层题</button>
              </div>
            </section>

            <section class="question-list-card question-list-card-priority">
              <header>
                <div>
                  <strong>本课时题库</strong>
                  <span>汇总当前课时各环节题目，可复制加入当前环节。</span>
                </div>
                <span>{{ lessonQuestionLibrary.length }} 道题</span>
              </header>
              <article
                v-for="item in lessonQuestionLibrary"
                :key="item.library_key"
                :class="{ 'just-added': item.id === lastTouchedQuestionId }"
              >
                <strong>{{ item.stem }}</strong>
                <span>{{ questionTypeLabel(item.question_type) }} · {{ questionLayerModeLabel(item) }} · {{ targetLayerLabel(item.target_layer) }} · {{ questionScoreSummary(item) }} · {{ item.is_required ? '必答' : '选答' }}</span>
                <small>来源：{{ item.source_step_title }} · 参考答案：{{ questionAnswerSummary(item) }}</small>
                <div class="resource-card-actions">
                  <button v-if="item.from_current_step" type="button" @click="editQuestion(item)">编辑</button>
                  <button
                    type="button"
                    :disabled="isQuestionInCurrentStep(item)"
                    @click="addQuestionFromLibrary(item)"
                  >
                    {{ isQuestionInCurrentStep(item) ? '已在当前环节' : '加入环节' }}
                  </button>
                </div>
              </article>
              <p v-if="!lessonQuestionLibrary.length" class="empty">本课时还没有题目。点击上方“新增课堂题”制作第一道题。</p>
            </section>

          </div>

          <div v-else-if="activeTool === 'document'" class="designer-side-list">
            <article v-for="item in documentRows" :key="item.title">
              <strong>{{ item.title }}</strong>
              <span>{{ item.scope }}</span>
              <small>{{ item.permission }}</small>
              <button type="button" @click="addResourceItem(item.title)">加入环节</button>
            </article>
          </div>

          <div v-else class="ai-draft-panel">
            <strong>AI 学习单草稿</strong>
            <p>教师配置自己的 DeepSeek 接口后，可让 AI 辅助生成学习单、问题和任务说明。第一版只保存生成目标，不直接发布 AI 内容。</p>
            <label>
              <span>生成目标</span>
              <textarea v-model.trim="stepForm.ai_prompt" rows="7" maxlength="3000" placeholder="写清楚本环节要生成什么，例如：面向 B/C 层学生生成一份数据采集流程学习单。"></textarea>
            </label>
            <div class="row-actions">
              <RouterLink to="/teacher/ai">AI接入</RouterLink>
              <button class="primary-button" type="button" @click="saveStep">保存目标</button>
            </div>
          </div>
        </aside>
      </div>
    </section>

    <Teleport to="body">
      <div v-if="stepModalOpen" class="modal-backdrop" role="presentation" @click.self="stepModalOpen = false">
        <section class="entity-modal compact-modal lesson-settings-modal" role="dialog" aria-modal="true" aria-labelledby="step-editor-title">
          <header class="modal-header">
            <div>
              <h2 id="step-editor-title">{{ stepModalTitle }}</h2>
              <p>设置环节名称、类型、时长和学生可见说明；顺序在左侧学习过程中调整。</p>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" @click="stepModalOpen = false">×</button>
          </header>

          <div class="lesson-settings-body">
            <label class="span-2">
              <span>环节标题 <b>*</b></span>
              <input v-model.trim="stepForm.title" maxlength="128" placeholder="例如 导入、任务分析、作品提交" />
              <small v-if="formErrors.title" class="field-error">{{ formErrors.title[0] }}</small>
            </label>
            <label>
              <span>环节类型</span>
              <select v-model="stepForm.step_type">
                <option v-for="item in stepTypeOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
              </select>
              <small v-if="formErrors.step_type" class="field-error">{{ formErrors.step_type[0] }}</small>
            </label>
            <label>
              <span>预计时长 <b>*</b></span>
              <input v-model="stepForm.estimated_minutes" type="number" min="1" max="240" />
              <small v-if="formErrors.estimated_minutes" class="field-error">{{ formErrors.estimated_minutes[0] }}</small>
            </label>
            <label>
              <span>适用层级</span>
              <select v-model="stepForm.target_layer">
                <option v-for="item in targetLayerOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
              </select>
            </label>
            <label class="settings-check-row">
              <input v-model="stepForm.is_required" type="checkbox" />
              <span>必做环节</span>
            </label>
            <label class="span-2">
              <span>学生可见说明</span>
              <textarea v-model.trim="stepForm.student_instruction" rows="4" maxlength="5000" placeholder="写给学生看的任务说明、学习要求或操作提示。"></textarea>
              <small v-if="formErrors.student_instruction" class="field-error">{{ formErrors.student_instruction[0] }}</small>
            </label>
          </div>

          <footer class="modal-actions">
            <button v-if="activeStep" class="secondary-button danger" type="button" :disabled="saving" @click="removeStepFromModal">删除环节</button>
            <button class="secondary-button" type="button" :disabled="saving" @click="stepModalOpen = false">取消</button>
            <button class="primary-button" type="button" :disabled="saving" @click="saveStepFromModal">
              {{ saving ? '保存中' : '保存环节' }}
            </button>
          </footer>
        </section>
      </div>
    </Teleport>

    <Teleport to="body">
      <div v-if="resourceUploadOpen" class="modal-backdrop" role="presentation" @click.self="resourceUploadOpen = false">
        <section class="entity-modal compact-modal lesson-settings-modal" role="dialog" aria-modal="true" aria-labelledby="resource-upload-title">
          <header class="modal-header">
            <div>
              <h2 id="resource-upload-title">上传课程资源</h2>
              <p>上传后自动加入当前环节，并进入资源顺序。</p>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" @click="resourceUploadOpen = false">×</button>
          </header>

          <div class="lesson-settings-body">
            <label class="span-2">
              <span>资源标题 <b>*</b></span>
              <input v-model.trim="resourceUploadForm.title" maxlength="128" placeholder="例如 数据采集任务素材" />
              <small v-if="resourceErrors.title" class="field-error">{{ resourceErrors.title[0] }}</small>
            </label>
            <label class="span-2">
              <span>说明</span>
              <textarea v-model.trim="resourceUploadForm.content" rows="3" maxlength="1000" placeholder="给自己或学生看的简要说明，可不填。"></textarea>
              <small v-if="resourceErrors.content" class="field-error">{{ resourceErrors.content[0] }}</small>
            </label>
            <label class="span-2">
              <span>本地文件 <b>*</b></span>
              <input
                ref="resourceFileInput"
                type="file"
                accept=".jpg,.jpeg,.png,.webp,.gif,.mp4,.webm,.mov,.mp3,.wav,.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.csv,.txt,.md,.zip,.rar,.7z"
                @change="onResourceFileChange"
              />
              <small v-if="selectedResourceFile">{{ selectedResourceFile.name }} · {{ formatFileSize(selectedResourceFile.size) }}</small>
              <small v-if="resourceErrors.attachment" class="field-error">{{ resourceErrors.attachment[0] }}</small>
            </label>
          </div>

          <footer class="modal-actions">
            <button class="secondary-button" type="button" :disabled="resourceSaving" @click="resourceUploadOpen = false">取消</button>
            <button class="primary-button" type="button" :disabled="resourceSaving" @click="uploadResource">
              {{ resourceSaving ? '上传中' : '上传并加入环节' }}
            </button>
          </footer>
        </section>
      </div>
    </Teleport>

    <Teleport to="body">
      <div v-if="aiQuestionModalOpen" class="modal-backdrop" role="presentation" @click.self="aiQuestionModalOpen = false">
        <section class="entity-modal compact-modal lesson-ai-question-modal" role="dialog" aria-modal="true" aria-labelledby="ai-question-title">
          <header class="modal-header">
            <div>
              <h2 id="ai-question-title">AI 生成分层题</h2>
              <p>老师只填写一个出题方向，系统同时生成 A、B、C、A/B、B/C 五组题目草稿。题目不会自动发布。</p>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" @click="aiQuestionModalOpen = false">×</button>
          </header>

          <div class="ai-question-modal-body">
            <section class="ai-question-form-panel">
              <label class="span-2">
                <span>出题方向 <b>*</b></span>
                <textarea
                  v-model.trim="aiQuestionForm.direction"
                  rows="5"
                  maxlength="1000"
                  placeholder="例如：围绕数据采集流程，给 B/C 层学生生成基础巩固题，强调数据来源、字段含义和采集规范。"
                ></textarea>
                <small v-if="aiQuestionErrors.direction" class="field-error">{{ aiQuestionErrors.direction[0] }}</small>
              </label>
              <label>
                <span>题型</span>
                <select v-model="aiQuestionForm.question_type">
                  <option v-for="item in questionTypeOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
                </select>
                <small v-if="aiQuestionErrors.question_type" class="field-error">{{ aiQuestionErrors.question_type[0] }}</small>
              </label>
              <label>
                <span>每组数量</span>
                <input v-model="aiQuestionForm.count" type="number" min="1" max="10" />
                <small v-if="aiQuestionErrors.count" class="field-error">{{ aiQuestionErrors.count[0] }}</small>
              </label>
              <label class="span-2">
                <span>补充要求</span>
                <textarea
                  v-model.trim="aiQuestionForm.requirement"
                  rows="3"
                  maxlength="1000"
                  placeholder="可写题目难度、选项风格、是否贴近项目任务、是否需要易错项等。"
                ></textarea>
                <small v-if="aiQuestionErrors.requirement" class="field-error">{{ aiQuestionErrors.requirement[0] }}</small>
              </label>
              <div class="ai-score-defaults span-2">
                <strong>生成范围</strong>
                <span>一次生成 A、B、C、A/B、B/C 五组题目。选择/判断默认 2 分，填空默认 3 分，简答默认 5 分；AI 返回的是建议值，教师可逐题修改。</span>
              </div>
            </section>

            <section class="ai-question-result-panel">
              <header>
                <div>
                  <strong>生成结果</strong>
                  <span>{{ aiGeneratedQuestions.length ? `${aiGeneratedQuestions.length} 道草稿待确认` : '生成后按 A/B/C 分组显示' }}</span>
                </div>
                <button class="secondary-button" type="button" :disabled="aiQuestionLoading || !aiGeneratedQuestions.length" @click="addAllAiGeneratedQuestions">
                  全部加入
                </button>
              </header>

              <NoticeLine v-if="aiQuestionNotice" :message="aiQuestionNotice" :tone="aiGeneratedQuestions.length ? 'success' : 'warning'" />

              <div v-if="aiScoreDefaults" class="ai-score-note">
                <strong>建议分值</strong>
                <span>基础 {{ aiScoreDefaults.base_score }} 分 · A/B/C/A-B/B-C 五组分别给出分值建议</span>
                <small>{{ aiScoreDefaults.note }}</small>
              </div>

              <div class="ai-question-group-list">
                <section v-for="group in aiGeneratedGroups" :key="group.target_layer" class="ai-question-group-card">
                  <header>
                    <div>
                      <strong>{{ targetLayerLabel(group.target_layer) }} 组</strong>
                      <span>{{ group.questions.length }} 道 · A {{ group.score_defaults.layer_scores.A }} / B {{ group.score_defaults.layer_scores.B }} / C {{ group.score_defaults.layer_scores.C }}</span>
                    </div>
                  </header>
                  <div class="ai-question-result-list">
                    <article v-for="item in group.questions" :key="item.id">
                      <header>
                        <span>{{ questionTypeLabel(item.question_type) }} · {{ targetLayerLabel(item.target_layer) }}</span>
                        <strong>{{ questionScoreSummary(item) }}</strong>
                      </header>
                      <p>{{ item.stem }}</p>
                      <div v-if="item.options.length" class="ai-option-preview">
                        <small v-for="(option, index) in item.options" :key="`${item.id}-option-${index}`">{{ String.fromCharCode(65 + index) }}. {{ option }}</small>
                      </div>
                      <small>参考答案：{{ questionAnswerSummary(item) }}</small>
                      <small v-if="item.analysis">解析：{{ item.analysis }}</small>
                      <div class="resource-card-actions">
                        <button type="button" @click="editAiGeneratedQuestion(item)">编辑后加入</button>
                        <button type="button" @click="addAiGeneratedQuestion(item)">直接加入</button>
                      </div>
                    </article>
                  </div>
                </section>
                <p v-if="!aiQuestionLoading && !aiGeneratedQuestions.length" class="empty">
                  尚未生成题目。生成前请确认教师 AI 接入已配置并启用。
                </p>
              </div>
            </section>
          </div>

          <footer class="modal-actions">
            <RouterLink class="secondary-button" to="/teacher/ai">AI 接入</RouterLink>
            <button class="secondary-button" type="button" :disabled="aiQuestionLoading" @click="aiQuestionModalOpen = false">关闭</button>
            <button class="primary-button" type="button" :disabled="aiQuestionLoading" @click="generateAiQuestions">
              {{ aiQuestionLoading ? '生成中' : '生成题目草稿' }}
            </button>
          </footer>
        </section>
      </div>
    </Teleport>

    <Teleport to="body">
      <div v-if="questionBuilderOpen" class="modal-backdrop" role="presentation" @click.self="questionBuilderOpen = false">
        <section class="entity-modal compact-modal lesson-question-modal" role="dialog" aria-modal="true" aria-labelledby="question-builder-title">
          <header class="modal-header">
            <div>
              <h2 id="question-builder-title">{{ editingQuestionId ? '编辑课堂题' : '新增课堂题' }}</h2>
              <p>可按 A/B/C 层设置不同题目或不同分值；学生端只看到适合自己层级的题目。</p>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" @click="questionBuilderOpen = false">×</button>
          </header>

          <div class="question-modal-body">
            <section class="question-builder-card modal-question-builder">
              <label>
                <span>题型</span>
                <select v-model="questionDraft.question_type" @change="onQuestionTypeChange">
                  <option v-for="item in questionTypeOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
                </select>
              </label>
              <label>
                <span>基础分值</span>
                <input v-model="questionDraft.score" type="number" min="0" max="100" step="0.5" @input="onQuestionBaseScoreInput" />
                <small>系统先按题型给基础分，后续 AI 只提供建议，教师可修改。</small>
              </label>
              <label class="check-row">
                <input v-model="questionDraft.is_required" type="checkbox" />
                <span>必答</span>
              </label>
              <section class="layer-mode-panel span-2">
                <header>
                  <strong>分层设置</strong>
                  <span>{{ questionLayerModeHelp }}</span>
                </header>
                <div class="layer-mode-options">
                  <label
                    v-for="item in questionLayerModeOptions"
                    :key="item.value"
                    :class="{ active: questionLayerMode === item.value }"
                  >
                    <input v-model="questionLayerMode" type="radio" :value="item.value" />
                    <span>
                      <strong>{{ item.label }}</strong>
                      <small>{{ item.description }}</small>
                    </span>
                  </label>
                </div>
                <div v-if="questionLayerMode === 'layered_target'" class="layer-target-row">
                  <label>
                    <span>适用层级</span>
                    <select v-model="questionDraft.target_layer" @change="onQuestionTargetLayerChange">
                      <option v-for="item in targetLayerSpecificOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
                    </select>
                  </label>
                  <small>A/B 和 B/C 用于相邻层级共用题；第一版不开放 A/C。</small>
                </div>
                <div v-if="questionDraft.use_layer_scores" class="layer-score-grid span-2">
                  <label v-for="layer in activeLayerScoreCodes" :key="layer">
                    <span>{{ layer }} 层分值</span>
                    <input v-model="questionDraft.layer_scores[layer]" type="number" min="0" max="100" step="0.5" />
                  </label>
                  <small class="span-2">这里的 A/B/C 分值会作为题目设计上下文进入后续学习分析，但不直接作为学生分层模型的唯一标签。</small>
                </div>
              </section>
              <label class="span-2">
                <span>题干 <b>*</b></span>
                <textarea v-model.trim="questionDraft.stem" rows="4" maxlength="1000" placeholder="输入题干，支持课堂即时题、任务问题或反思题。"></textarea>
              </label>

              <div v-if="questionNeedsOptions" class="question-option-editor span-2">
                <span>选项</span>
                <label v-for="(_, index) in questionDraft.options" :key="`option-${index}`" class="question-option-row">
                  <small>{{ String.fromCharCode(65 + index) }}</small>
                  <input
                    :value="questionDraft.options[index]"
                    :readonly="isJudgeQuestion"
                    maxlength="200"
                    @input="setQuestionOption(index, ($event.target as HTMLInputElement).value)"
                  />
                  <button v-if="!isJudgeQuestion" type="button" @click="removeQuestionOption(index)">移除</button>
                </label>
                <button v-if="!isJudgeQuestion" class="secondary-button compact-button" type="button" @click="addQuestionOption">添加选项</button>
              </div>

              <div v-if="questionNeedsOptions" class="question-answer-editor span-2">
                <span>参考答案</span>
                <label v-for="option in questionOptionRows()" :key="`answer-${option}`">
                  <input
                    :type="questionDraft.question_type === 'multiple' ? 'checkbox' : 'radio'"
                    :name="`question-answer-${questionDraft.id || 'draft'}`"
                    :checked="questionDraft.answer.includes(option)"
                    @change="toggleQuestionAnswer(option, ($event.target as HTMLInputElement).checked)"
                  />
                  <small>{{ option || '未填写选项' }}</small>
                </label>
              </div>

              <label v-else class="span-2">
                <span>参考答案</span>
                <textarea
                  :value="questionDraft.answer[0] || ''"
                  rows="3"
                  maxlength="1000"
                  placeholder="填空题可写标准答案；简答题可写评分参考。"
                  @input="setTextQuestionAnswer(($event.target as HTMLTextAreaElement).value)"
                ></textarea>
              </label>

              <label>
                <span>排序</span>
                <input v-model="questionDraft.sort_order" type="number" min="0" max="9999" />
              </label>
              <label class="span-2">
                <span>解析 / 评分说明</span>
                <textarea v-model.trim="questionDraft.analysis" rows="3" maxlength="1000" placeholder="可填写给教师参考的解析或评分标准。"></textarea>
              </label>
            </section>
          </div>

          <footer class="modal-actions">
            <button class="secondary-button" type="button" @click="questionBuilderOpen = false">取消</button>
            <button class="primary-button" type="button" @click="saveQuestionDraft">
              {{ editingQuestionId ? '更新题目' : '加入当前环节' }}
            </button>
          </footer>
        </section>
      </div>
    </Teleport>

    <Teleport to="body">
      <div v-if="settingsOpen" class="modal-backdrop" role="presentation" @click.self="settingsOpen = false">
        <section class="entity-modal compact-modal lesson-settings-modal" role="dialog" aria-modal="true" aria-labelledby="lesson-settings-title">
          <header class="modal-header">
            <div>
              <h2 id="lesson-settings-title">环节设置</h2>
              <p>{{ stepForm.title || currentStepLabel }} · 设置会和当前环节内容一起保存。</p>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" @click="settingsOpen = false">×</button>
          </header>

          <div class="lesson-settings-body">
            <label class="settings-check-row">
              <input v-model="stepForm.is_required" type="checkbox" />
              <span>必做环节</span>
            </label>
            <label class="settings-check-row">
              <input v-model="stepForm.collect_student_log" type="checkbox" />
              <span>写入学生日志</span>
            </label>
            <label class="settings-check-row">
              <input v-model="stepForm.collect_class_log" type="checkbox" />
              <span>写入班级日志</span>
            </label>
            <label class="span-2">
              <span>教师备课备注</span>
              <textarea v-model.trim="stepForm.teacher_note" rows="3" maxlength="5000" placeholder="记录讲解重点、追问、易错点和差异化处理。"></textarea>
              <small v-if="formErrors.teacher_note" class="field-error">{{ formErrors.teacher_note[0] }}</small>
            </label>
            <label class="span-2">
              <span>AI 生成目标</span>
              <textarea v-model.trim="stepForm.ai_prompt" rows="3" maxlength="3000" placeholder="例如：基于本环节生成一份任务驱动学习单，包含选择题、简答题和作品上传要求。"></textarea>
              <small v-if="formErrors.ai_prompt" class="field-error">{{ formErrors.ai_prompt[0] }}</small>
            </label>
          </div>

          <footer class="modal-actions">
            <button class="secondary-button" type="button" :disabled="saving" @click="settingsOpen = false">关闭</button>
            <button class="primary-button" type="button" :disabled="saving" @click="saveStep">
              {{ saving ? '保存中' : '保存当前环节' }}
            </button>
          </footer>
        </section>
      </div>
    </Teleport>

    <Teleport to="body">
      <div v-if="previewOpen" class="lesson-preview-backdrop" role="presentation" @click.self="previewOpen = false">
        <section class="lesson-preview-modal" role="dialog" aria-modal="true" aria-labelledby="lesson-preview-title">
          <header class="lesson-preview-header">
            <div>
              <span>{{ previewMode === 'resource' ? '资源预览 / 编辑' : '学生视图预览' }}</span>
              <h2 id="lesson-preview-title">{{ stepForm.title || lessonTitle }}</h2>
            </div>
            <button class="icon-button" type="button" aria-label="关闭预览" @click="previewOpen = false">×</button>
          </header>

          <div v-if="previewMode === 'resource'" class="lesson-preview-body single-preview">
            <ResourcePreview :resource="selectedPreviewResource" office-mode="edit" />
          </div>

          <div v-else class="lesson-preview-body student-preview-large">
            <main class="student-preview-main">
              <ResourcePreview v-if="selectedPreviewResource" :resource="selectedPreviewResource" office-mode="view" />
              <div v-else class="preview-canvas large">
                <span>当前环节</span>
                <strong>{{ stepForm.title || '未命名环节' }}</strong>
                <p>{{ stepForm.student_instruction || '暂无学生可见说明。' }}</p>
              </div>
            </main>
            <aside class="student-preview-flow">
              <span>本环节任务</span>
              <h3>{{ stepForm.title || lessonTitle }}</h3>
              <p>{{ stepForm.student_instruction || '暂无学生可见说明。' }}</p>
              <div v-if="activeQuestionItems.length" class="student-preview-question-list">
                <article v-for="(question, index) in activeQuestionItems" :key="`preview-question-${question.id}`">
                  <span>{{ questionTypeLabel(question.question_type) }}{{ question.is_required ? ' · 必答' : ' · 选答' }}</span>
                  <strong>{{ index + 1 }}. {{ question.stem }}</strong>
                  <small>{{ questionLayerModeLabel(question) }} · {{ targetLayerLabel(question.target_layer) }} · {{ questionScoreSummary(question) }}</small>
                </article>
              </div>
              <div v-if="stepForm.activity_items.length" class="preview-items">
                <small v-for="item in stepForm.activity_items" :key="`preview-activity-${item}`">活动：{{ item }}</small>
              </div>
              <button class="primary-button" type="button" disabled>
                {{ activeQuestionItems.length ? '学生端提交作答' : '学生端完成入口' }}
              </button>
            </aside>
          </div>
        </section>
      </div>
    </Teleport>
  </AppShell>
</template>
