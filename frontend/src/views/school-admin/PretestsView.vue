<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError, type FieldErrors } from '@/api/client'
import {
  archivePretestPaper,
  closeDiagnosticAdministration,
  createDiagnosticAdministration,
  createPretestPaper,
  createPretestQuestion,
  createSubject,
  deletePretestPaper,
  deletePretestQuestion,
  deleteSubject,
  getPretestPapers,
  getPendingPretestMaterials,
  getClasses,
  getDiagnosticAdministration,
  getDiagnosticAdministrations,
  getDiagnosticLearningTargetVersions,
  getPretestQuestions,
  getSubjects,
  publishPretestPaper,
  publishDiagnosticAdministration,
  replaceDiagnosticAdministrationAssignments,
  reviewPretestMaterial,
  updatePretestPaper,
  updatePretestQuestion,
  updateDiagnosticAdministration,
  updateSubject,
  type PageResult,
  type ClassGroupRow,
  type DiagnosticAdministrationPayload,
  type DiagnosticAdministrationRow,
  type DiagnosticLearningTargetVersionOption,
  type PretestPaperPayload,
  type PretestPaperRow,
  type PretestMaterialReviewRow,
  type PretestQuestionPayload,
  type PretestQuestionRow,
  type SubjectPayload,
  type SubjectRow
} from '@/api/management'
import AppShell from '@/layouts/AppShell.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import EntityFormModal from '@/components/EntityFormModal.vue'
import ManagementPage from '@/components/ManagementPage.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import { vModalFocus } from '@/directives/modalFocus'
import type { FormField } from '@/types/forms'
import { schoolAdminNav } from './nav'

type FormModel = Record<string, string | number | boolean>
type QuestionFormModel = {
  stem: string
  question_type: string
  score: number | string
  dimension: string
  learning_target_code: string
  learning_target_name: string
  learning_target_version_id: number | string
  material_requirements: string
  sort_order: number | string
  is_required: boolean
}

const navItems = schoolAdminNav('/school-admin/pretests')
const activeSection = ref<'versions' | 'administrations'>('versions')

const paperStatusOptions = [
  { label: '全部状态', value: '' },
  { label: '草稿', value: 'draft' },
  { label: '已发布', value: 'published' },
  { label: '归档', value: 'archived' }
]

const kindOptions = [
  { label: '全部类型', value: '' },
  { label: '学科学习诊断', value: 'literacy' },
  { label: '学习支持问卷', value: 'attitude' }
]

const questionTypeOptions = [
  { label: '单选', value: 'single' },
  { label: '多选', value: 'multiple' },
  { label: '量表', value: 'scale' },
  { label: '简答', value: 'text' },
  { label: '表现任务', value: 'performance' },
  { label: '操作任务', value: 'operation' },
  { label: '短项目', value: 'short_project' }
]

const likertOptions = [
  { label: '1', text: '非常不同意' },
  { label: '2', text: '不同意' },
  { label: '3', text: '不确定' },
  { label: '4', text: '同意' },
  { label: '5', text: '非常同意' }
]

const subjects = ref<SubjectRow[]>([])
const rows = ref<PretestPaperRow[]>([])
const questions = ref<PretestQuestionRow[]>([])
const learningTargetVersions = ref<DiagnosticLearningTargetVersionOption[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const query = ref('')
const status = ref('')
const selectedSubject = ref('')
const selectedKind = ref('')
const loading = ref(false)
const saving = ref(false)
const notice = ref('')
const pendingMaterials = ref<PretestMaterialReviewRow[]>([])
const administrations = ref<DiagnosticAdministrationRow[]>([])
const classes = ref<ClassGroupRow[]>([])
const publishedPapers = ref<PretestPaperRow[]>([])
const administrationOpen = ref(false)
const editingAdministration = ref<DiagnosticAdministrationRow | null>(null)
const administrationErrors = ref<FieldErrors>({})
const administrationModel = ref({
  paper_version_id: '',
  purpose: 'entry_diagnostic' as DiagnosticAdministrationRow['purpose'],
  batch_code: '',
  title: '',
  open_at: '',
  close_at: ''
})
const assignmentDrafts = ref<Record<number, {
  selected: boolean
  cohort_role: 'experiment' | 'control' | 'unassigned'
  opportunity_status: 'offered' | 'not_offered'
}>>({})
const materialReviewOpen = ref(false)
const reviewTarget = ref<PretestMaterialReviewRow | null>(null)
const reviewScore = ref<number | string>('')
const reviewScoreMax = ref<number | string>('')
const reviewFeedback = ref('')

const subjectOpen = ref(false)
const paperOpen = ref(false)
const questionOpen = ref(false)
const questionManagerOpen = ref(false)
const editingSubject = ref<SubjectRow | null>(null)
const editingPaper = ref<PretestPaperRow | null>(null)
const editingQuestion = ref<PretestQuestionRow | null>(null)
const activePaper = ref<PretestPaperRow | null>(null)
const subjectErrors = ref<FieldErrors>({})
const paperErrors = ref<FieldErrors>({})
const questionErrors = ref<FieldErrors>({})
const subjectModel = ref<FormModel>(emptySubject())
const paperModel = ref<FormModel>(emptyPaper())
const questionModel = ref<QuestionFormModel>(emptyQuestion())
const optionDrafts = ref<string[]>(['', '', '', ''])
const answerDraft = ref<string[]>([])

const confirmOpen = ref(false)
const confirmTitle = ref('')
const confirmMessage = ref('')
const confirmDanger = ref(false)
const confirmAction = ref<null | (() => Promise<void>)>(null)

const subjectOptions = computed(() => {
  const options = subjects.value.map((subject) => ({
    label: `${subject.name}（${subject.code}）`,
    value: subject.id
  }))
  return options.length ? options : [{ label: '请先新增学科', value: '' }]
})

const currentSubject = computed(() => subjects.value.find((item) => String(item.id) === selectedSubject.value) || null)
const activeQuestionType = computed(() => String(questionModel.value.question_type || 'single'))
const isChoiceQuestion = computed(() => activeQuestionType.value === 'single' || activeQuestionType.value === 'multiple')
const isScaleQuestion = computed(() => activeQuestionType.value === 'scale')
const isTextQuestion = computed(() => activeQuestionType.value === 'text')
const isPerformanceQuestion = computed(() => ['performance', 'operation', 'short_project'].includes(activeQuestionType.value))
const selectedLearningTargetVersion = computed(() => learningTargetVersions.value.find(
  (item) => String(item.id) === String(questionModel.value.learning_target_version_id || '')
) || null)
const isLiteracyPaper = computed(() => activePaper.value?.kind === 'literacy')

const paperFields = computed<FormField[]>(() => [
  {
    name: 'subject',
    label: '所属学科',
    type: 'select',
    required: true,
    options: subjectOptions.value
  },
  {
    name: 'kind',
    label: '诊断类型',
    type: 'select',
    required: true,
    options: [
      { label: '学科学习诊断', value: 'literacy' },
      { label: '学习支持问卷', value: 'attitude' }
    ]
  },
  {
    name: 'title',
    label: '诊断名称',
    required: true,
    maxlength: 128,
    pattern: '^[\\u4e00-\\u9fa5A-Za-z0-9（）()·\\-\\s]{2,128}$',
    placeholder: '例如：信息科技学习起点诊断'
  },
  {
    name: 'version',
    label: '版本号',
    type: 'number',
    placeholder: '留空自动递增'
  },
  {
    name: 'status',
    label: '状态',
    type: 'select',
    required: true,
    options: [{ label: '草稿', value: 'draft' }],
    helper: '先保存草稿并配置评价任务，再通过列表中的发布操作生成不可修改版本。'
  },
  {
    name: 'introduction',
    label: '说明',
    type: 'textarea',
    maxlength: 500,
    placeholder: '学生作答前看到的简短说明，可为空'
  }
])

const subjectFields: FormField[] = [
  {
    name: 'name',
    label: '学科名称',
    required: true,
    maxlength: 64,
    pattern: '^[\\u4e00-\\u9fa5A-Za-z0-9（）()·\\-\\s]{2,64}$',
    placeholder: '例如：信息技术'
  },
  {
    name: 'code',
    label: '学科编号',
    required: true,
    maxlength: 32,
    pattern: '^[A-Z0-9][A-Z0-9_-]{1,31}$',
    placeholder: '例如：IT'
  },
  { name: 'is_active', label: '状态', type: 'checkbox' }
]

function emptySubject(): FormModel {
  return {
    name: '',
    code: '',
    is_active: true
  }
}

function emptyPaper(): FormModel {
  return {
    subject: selectedSubject.value || subjects.value[0]?.id || '',
    kind: selectedKind.value || 'literacy',
    title: '',
    version: '',
    status: 'draft',
    introduction: ''
  }
}

function emptyQuestion(): QuestionFormModel {
  return {
    stem: '',
    question_type: 'single',
    score: 0,
    dimension: '',
    learning_target_code: '',
    learning_target_name: '',
    learning_target_version_id: '',
    material_requirements: '',
    sort_order: questions.value.length + 1,
    is_required: true
  }
}

function setRows(data: PageResult<PretestPaperRow>) {
  rows.value = data.results
  total.value = data.count
  page.value = data.page
  pageSize.value = data.page_size
}

function subjectPayload(model: FormModel): SubjectPayload {
  return {
    name: String(model.name || '').trim(),
    code: String(model.code || '').trim().toUpperCase(),
    is_active: Boolean(model.is_active)
  }
}

function paperPayload(model: FormModel): PretestPaperPayload {
  return {
    subject: typeof model.subject === 'boolean' ? '' : model.subject,
    kind: String(model.kind || 'literacy'),
    title: String(model.title || '').trim(),
    version: model.version ? String(model.version).trim() : '',
    status: String(model.status || 'draft'),
    introduction: String(model.introduction || '').trim()
  }
}

function optionLabel(index: number) {
  return String.fromCharCode(65 + index)
}

function cleanChoiceOptions() {
  return optionDrafts.value
    .map((text, index) => ({ label: optionLabel(index), text: String(text || '').trim() }))
    .filter((item) => item.text)
}

function questionFieldError(name: string) {
  return questionErrors.value[name]?.join('；') || ''
}

function addOption() {
  if (optionDrafts.value.length >= 8) {
    notice.value = '单题最多设置 8 个选项。'
    return
  }
  optionDrafts.value.push('')
}

function removeOption(index: number) {
  if (optionDrafts.value.length <= 2) {
    notice.value = '选择题至少保留 2 个选项。'
    return
  }
  const removedLabel = optionLabel(index)
  optionDrafts.value.splice(index, 1)
  answerDraft.value = answerDraft.value
    .filter((label) => label !== removedLabel)
    .map((label) => {
      const code = label.charCodeAt(0)
      return code > removedLabel.charCodeAt(0) ? String.fromCharCode(code - 1) : label
    })
}

function isAnswer(label: string) {
  return answerDraft.value.includes(label)
}

function setSingleAnswer(label: string) {
  answerDraft.value = [label]
}

function toggleMultipleAnswer(label: string, checked: boolean) {
  if (checked) {
    if (!answerDraft.value.includes(label)) {
      answerDraft.value.push(label)
    }
    return
  }
  answerDraft.value = answerDraft.value.filter((item) => item !== label)
}

function setQuestionType(type: string) {
  questionModel.value.question_type = type
  questionErrors.value = {}
  answerDraft.value = []
  if (type === 'scale') {
    questionModel.value.score = questionModel.value.score || 5
  }
  if (type === 'single' || type === 'multiple') {
    if (optionDrafts.value.length < 2) {
      optionDrafts.value = ['', '', '', '']
    }
  }
}

function questionPayload(model: QuestionFormModel): PretestQuestionPayload {
  const questionType = String(model.question_type || 'single')
  let options: string | { label: string; text: string }[] = []
  let answer: string | string[] = []
  if (questionType === 'single' || questionType === 'multiple') {
    options = cleanChoiceOptions()
    answer = answerDraft.value
  } else if (questionType === 'scale') {
    options = likertOptions
    answer = []
  }
  return {
    stem: String(model.stem || '').trim(),
    question_type: questionType,
    options,
    answer,
    score: typeof model.score === 'boolean' ? 0 : model.score || 0,
    dimension: String(model.dimension || '').trim(),
    learning_target_code: String(model.learning_target_code || '').trim(),
    learning_target_name: String(model.learning_target_name || '').trim(),
    learning_target_version_id: model.learning_target_version_id || null,
    material_requirements: String(model.material_requirements || '').split(/\r?\n/).map((item) => item.trim()).filter(Boolean),
    sort_order: typeof model.sort_order === 'boolean' ? 0 : model.sort_order || 0,
    is_required: Boolean(model.is_required)
  }
}

function classForStatus(statusValue: string) {
  if (statusValue === 'published') return 'status-active'
  if (statusValue === 'draft') return 'status-warning'
  return 'status-archived'
}

function administrationStatusClass(statusValue: string) {
  if (statusValue === 'published') return 'status-active'
  if (statusValue === 'draft') return 'status-warning'
  return 'status-archived'
}

function localDateTime(value: string | null) {
  if (!value) return ''
  const date = new Date(value)
  const offset = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - offset).toISOString().slice(0, 16)
}

function apiDateTime(value: string) {
  return value ? new Date(value).toISOString() : null
}

function resetAssignmentDrafts() {
  assignmentDrafts.value = Object.fromEntries(
    classes.value.map((row) => [row.id, {
      selected: false,
      cohort_role: 'unassigned' as const,
      opportunity_status: 'offered' as const
    }])
  )
}

async function loadAdministrations() {
  administrations.value = await getDiagnosticAdministrations({
    subject: selectedSubject.value,
    page_size: 300
  })
}

async function loadAdministrationOptions() {
  const [classPage, paperPage] = await Promise.all([
    getClasses({ status: 'active', page_size: 200 }),
    getPretestPapers({ status: 'published', page_size: 200 })
  ])
  classes.value = classPage.results
  publishedPapers.value = paperPage.results.filter((row) => Boolean(row.published_version))
}

function selectedPublishedPaper() {
  return publishedPapers.value.find(
    (row) => row.published_version?.id === Number(administrationModel.value.paper_version_id)
  ) || null
}

async function openAdministrationCreate() {
  administrationErrors.value = {}
  editingAdministration.value = null
  await loadAdministrationOptions()
  resetAssignmentDrafts()
  const first = publishedPapers.value.find((row) => row.subject.id === Number(selectedSubject.value))
    || publishedPapers.value[0]
  administrationModel.value = {
    paper_version_id: first?.published_version ? String(first.published_version.id) : '',
    purpose: 'entry_diagnostic',
    batch_code: `ENTRY-${new Date().toISOString().slice(0, 10).replaceAll('-', '')}`,
    title: first ? `${first.subject.name}学习起点诊断` : '',
    open_at: '',
    close_at: ''
  }
  administrationOpen.value = true
}

async function openAdministrationEdit(row: DiagnosticAdministrationRow) {
  if (row.status !== 'draft') return
  administrationErrors.value = {}
  await loadAdministrationOptions()
  const detail = await getDiagnosticAdministration(row.id)
  editingAdministration.value = detail
  resetAssignmentDrafts()
  detail.assignments?.forEach((item) => {
    assignmentDrafts.value[item.class_group.id] = {
      selected: true,
      cohort_role: item.cohort_role,
      opportunity_status: item.opportunity_status
    }
  })
  administrationModel.value = {
    paper_version_id: String(detail.paper_version.id),
    purpose: detail.purpose,
    batch_code: detail.batch_code,
    title: detail.title,
    open_at: localDateTime(detail.open_at),
    close_at: localDateTime(detail.close_at)
  }
  administrationOpen.value = true
}

function closeAdministrationEditor() {
  if (saving.value) return
  administrationOpen.value = false
}

function administrationPayload(): DiagnosticAdministrationPayload | null {
  const paper = selectedPublishedPaper()
  if (!paper?.published_version) {
    administrationErrors.value = { paper_version_id: ['请选择一个已发布的诊断版本。'] }
    return null
  }
  return {
    subject_id: paper.subject.id,
    paper_version_id: paper.published_version.id,
    purpose: administrationModel.value.purpose,
    batch_code: administrationModel.value.batch_code.trim(),
    title: administrationModel.value.title.trim(),
    open_at: apiDateTime(administrationModel.value.open_at),
    close_at: apiDateTime(administrationModel.value.close_at),
    expected_updated_at: editingAdministration.value?.updated_at
  }
}

async function submitAdministration() {
  if (saving.value) return
  const payload = administrationPayload()
  if (!payload) return
  const assignments = Object.entries(assignmentDrafts.value)
    .filter(([, value]) => value.selected)
    .map(([classId, value]) => ({
      class_group_id: Number(classId),
      cohort_role: value.cohort_role,
      opportunity_status: value.opportunity_status
    }))
  if (!assignments.length) {
    administrationErrors.value = { assignments: ['请至少选择一个班级。'] }
    return
  }
  saving.value = true
  administrationErrors.value = {}
  try {
    const draft = editingAdministration.value
      ? await updateDiagnosticAdministration(editingAdministration.value.id, payload)
      : await createDiagnosticAdministration(payload)
    await replaceDiagnosticAdministrationAssignments(draft.id, assignments, draft.updated_at)
    administrationOpen.value = false
    notice.value = '诊断实施草稿及班级指派已保存。'
    await loadAdministrations()
  } catch (exc) {
    if (exc instanceof ApiError) {
      administrationErrors.value = exc.errors
      notice.value = exc.message
    } else {
      notice.value = '诊断实施草稿保存失败。'
    }
  } finally {
    saving.value = false
  }
}

function publishAdministration(row: DiagnosticAdministrationRow) {
  ask(
    '发布诊断实施批次',
    `发布后将冻结“${row.paper_version.title} v${row.paper_version.version_no}”及全部班级、实验角色和评价机会安排，确认发布？`,
    async () => {
      await publishDiagnosticAdministration(row.id)
      notice.value = '诊断实施批次已发布，版本与班级指派已经冻结。'
      await loadAdministrations()
    }
  )
}

function closeAdministration(row: DiagnosticAdministrationRow) {
  ask('关闭诊断实施批次', `确认关闭“${row.title}”？关闭后学生不能继续提交。`, async () => {
    await closeDiagnosticAdministration(row.id)
    notice.value = '诊断实施批次已关闭。'
    await loadAdministrations()
  })
}

async function loadSubjects() {
  subjects.value = await getSubjects()
  if (!selectedSubject.value && subjects.value.length) {
    selectedSubject.value = String(subjects.value[0].id)
  }
}

async function load() {
  loading.value = true
  try {
    setRows(
      await getPretestPapers({
        q: query.value,
        status: status.value,
        subject: selectedSubject.value,
        kind: selectedKind.value,
        page: page.value,
        page_size: pageSize.value
      })
    )
  } finally {
    loading.value = false
  }
}

async function loadPendingMaterials() {
  try {
    pendingMaterials.value = await getPendingPretestMaterials({
      subject: selectedSubject.value
    })
  } catch (exc) {
    notice.value = exc instanceof ApiError ? exc.message : '待评价材料加载失败。'
  }
}

async function openMaterialReviews() {
  await loadPendingMaterials()
  materialReviewOpen.value = true
}

function closeMaterialReviews() {
  if (saving.value) return
  materialReviewOpen.value = false
  reviewTarget.value = null
}

function selectReviewMaterial(row: PretestMaterialReviewRow) {
  reviewTarget.value = row
  reviewScore.value = ''
  reviewScoreMax.value = row.score_max || ''
  reviewFeedback.value = ''
}

function materialAnswer(row: PretestMaterialReviewRow) {
  if (Array.isArray(row.answer)) return row.answer.join('；')
  if (row.answer === null || row.answer === undefined || row.answer === '') return '未填写文字说明'
  return typeof row.answer === 'object' ? JSON.stringify(row.answer) : String(row.answer)
}

function materialFileSize(size: number) {
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

async function submitMaterialReview() {
  if (saving.value || !reviewTarget.value) return
  const score = Number(reviewScore.value)
  const scoreMax = Number(reviewScoreMax.value)
  if (!Number.isFinite(score) || !Number.isFinite(scoreMax) || scoreMax <= 0 || score < 0 || score > scoreMax) {
    notice.value = '得分必须位于 0 与满分之间。'
    return
  }
  saving.value = true
  try {
    await reviewPretestMaterial(reviewTarget.value.material_id, {
      score,
      feedback: reviewFeedback.value.trim()
    })
    notice.value = '评价已保存，并生成新的学习目标情况版本。'
    reviewTarget.value = null
    await loadPendingMaterials()
  } catch (exc) {
    notice.value = exc instanceof ApiError ? exc.message : '评价保存失败。'
  } finally {
    saving.value = false
  }
}

function ask(title: string, message: string, action: () => Promise<void>, danger = false) {
  confirmTitle.value = title
  confirmMessage.value = message
  confirmAction.value = action
  confirmDanger.value = danger
  confirmOpen.value = true
}

async function runConfirm() {
  if (saving.value || !confirmAction.value) return
  saving.value = true
  notice.value = ''
  try {
    await confirmAction.value()
    confirmOpen.value = false
    await load()
  } catch (exc) {
    notice.value = exc instanceof ApiError ? exc.message : '操作失败。'
  } finally {
    saving.value = false
  }
}

function openSubjectCreate() {
  editingSubject.value = null
  subjectErrors.value = {}
  subjectModel.value = emptySubject()
  subjectOpen.value = true
}

function editSubject(subject: SubjectRow) {
  editingSubject.value = subject
  subjectErrors.value = {}
  subjectModel.value = {
    name: subject.name,
    code: subject.code,
    is_active: subject.is_active
  }
  subjectOpen.value = true
}

function editCurrentSubject() {
  if (currentSubject.value) {
    editSubject(currentSubject.value)
  }
}

async function submitSubject() {
  if (saving.value) return
  saving.value = true
  notice.value = ''
  subjectErrors.value = {}
  try {
    if (editingSubject.value) {
      await updateSubject(editingSubject.value.id, subjectPayload(subjectModel.value))
      notice.value = '学科已更新。'
    } else {
      await createSubject(subjectPayload(subjectModel.value))
      notice.value = '学科已创建。'
    }
    subjectOpen.value = false
    await loadSubjects()
    await load()
  } catch (exc) {
    if (exc instanceof ApiError) {
      subjectErrors.value = exc.errors
      notice.value = exc.message
    } else {
      notice.value = '保存失败。'
    }
  } finally {
    saving.value = false
  }
}

function removeSubject(subject: SubjectRow) {
  if (subject.is_active) {
    notice.value = '请先停用学科，再执行删除。'
    return
  }
  ask('删除学科', `确认删除 ${subject.name}？已有课程、学习起点诊断或作答记录时系统会拒绝物理删除。`, async () => {
    await deleteSubject(subject.id)
    notice.value = '学科已删除。'
    await loadSubjects()
  }, true)
}

function removeCurrentSubject() {
  if (currentSubject.value) {
    removeSubject(currentSubject.value)
  }
}

function openPaperCreate() {
  editingPaper.value = null
  paperErrors.value = {}
  paperModel.value = emptyPaper()
  paperOpen.value = true
}

function editPaper(row: PretestPaperRow) {
  if (row.status !== 'draft') {
    notice.value = '已发布或已归档版本不可修改，请新建下一版本。'
    return
  }
  editingPaper.value = row
  paperErrors.value = {}
  paperModel.value = {
    subject: row.subject.id,
    kind: row.kind,
    title: row.title,
    version: row.version,
    status: row.status,
    introduction: row.introduction
  }
  paperOpen.value = true
}

async function submitPaper() {
  if (saving.value) return
  saving.value = true
  notice.value = ''
  paperErrors.value = {}
  try {
    if (editingPaper.value) {
      await updatePretestPaper(editingPaper.value.id, paperPayload(paperModel.value))
      notice.value = '学习起点诊断草稿已更新。'
    } else {
      await createPretestPaper(paperPayload(paperModel.value))
      notice.value = '学习起点诊断草稿已创建。'
    }
    paperOpen.value = false
    await load()
  } catch (exc) {
    if (exc instanceof ApiError) {
      paperErrors.value = exc.errors
      notice.value = exc.message
    } else {
      notice.value = '保存失败。'
    }
  } finally {
    saving.value = false
  }
}

function publishPaper(row: PretestPaperRow) {
  ask('发布学习起点诊断', `确认发布 ${row.title}？发布后任务与评分依据不可修改，同一学科同一类型下的旧发布版本会自动归档。`, async () => {
    await publishPretestPaper(row.id)
    notice.value = '学习起点诊断版本已发布。'
  })
}

function archivePaper(row: PretestPaperRow) {
  ask('归档学习起点诊断', `确认归档 ${row.title}？归档后学生不会再收到这个诊断版本。`, async () => {
    await archivePretestPaper(row.id)
    notice.value = '学习起点诊断版本已归档。'
  })
}

function removePaper(row: PretestPaperRow) {
  if (row.status === 'published') {
    notice.value = '已发布诊断版本不能直接删除，请先归档。'
    return
  }
  ask('删除学习起点诊断', `确认删除 ${row.title}？已有学生提交时系统会拒绝物理删除。`, async () => {
    await deletePretestPaper(row.id)
    notice.value = '学习起点诊断草稿已删除。'
  }, true)
}

async function openQuestions(row: PretestPaperRow) {
  activePaper.value = row
  questionErrors.value = {}
  const [questionRows, targetRows] = await Promise.all([
    getPretestQuestions(row.id),
    getDiagnosticLearningTargetVersions({ subject: row.subject.id })
  ])
  questions.value = questionRows
  learningTargetVersions.value = targetRows
  questionManagerOpen.value = true
}

function selectLearningTargetVersion(value: string) {
  questionModel.value.learning_target_version_id = value
  const target = learningTargetVersions.value.find((item) => String(item.id) === value)
  if (!target) return
  questionModel.value.learning_target_code = target.code
  questionModel.value.learning_target_name = target.title
  questionErrors.value = {
    ...questionErrors.value,
    learning_target_version_id: [],
    learning_target_code: [],
    learning_target_name: []
  }
}

function openQuestionCreate() {
  if (activePaper.value?.status !== 'draft') {
    notice.value = '已发布或已归档版本只读，请新建下一版本后调整评价任务。'
    return
  }
  editingQuestion.value = null
  questionErrors.value = {}
  questionModel.value = emptyQuestion()
  optionDrafts.value = ['', '', '', '']
  answerDraft.value = []
  questionManagerOpen.value = false
  questionOpen.value = true
}

function editQuestion(row: PretestQuestionRow) {
  if (activePaper.value?.status !== 'draft') {
    notice.value = '已发布或已归档版本只读，请新建下一版本后调整评价任务。'
    return
  }
  editingQuestion.value = row
  questionErrors.value = {}
  questionModel.value = {
    stem: row.stem,
    question_type: row.question_type,
    score: row.score,
    dimension: row.dimension,
    learning_target_code: row.learning_target_code,
    learning_target_name: row.learning_target_name,
    learning_target_version_id: row.learning_target_version?.id || '',
    material_requirements: row.material_requirements.join('\n'),
    sort_order: row.sort_order,
    is_required: row.is_required
  }
  optionDrafts.value = row.options.length
    ? row.options.map((item) => item.text)
    : ['', '', '', '']
  answerDraft.value = [...row.answer]
  questionManagerOpen.value = false
  questionOpen.value = true
}

async function submitQuestion() {
  if (saving.value || !activePaper.value) return
  saving.value = true
  notice.value = ''
  questionErrors.value = {}
  try {
    if (editingQuestion.value) {
      await updatePretestQuestion(activePaper.value.id, editingQuestion.value.id, questionPayload(questionModel.value))
      notice.value = '评价任务已更新。'
    } else {
      await createPretestQuestion(activePaper.value.id, questionPayload(questionModel.value))
      notice.value = '评价任务已创建。'
    }
    questions.value = await getPretestQuestions(activePaper.value.id)
    questionOpen.value = false
    questionManagerOpen.value = true
    await load()
  } catch (exc) {
    if (exc instanceof ApiError) {
      questionErrors.value = exc.errors
      notice.value = exc.message
    } else {
      notice.value = '保存失败。'
    }
  } finally {
    saving.value = false
  }
}

function closeQuestionEditor() {
  if (saving.value) return
  questionOpen.value = false
  if (activePaper.value) {
    questionManagerOpen.value = true
  }
}

function closeQuestionManager() {
  if (saving.value) return
  questionManagerOpen.value = false
}

function removeQuestion(row: PretestQuestionRow) {
  if (!activePaper.value) return
  if (activePaper.value.status !== 'draft') {
    notice.value = '已发布或已归档版本不可删除评价任务。'
    return
  }
  ask('删除评价任务', '确认删除这个评价任务？已发布版本始终保持只读。', async () => {
    if (!activePaper.value) return
    await deletePretestQuestion(activePaper.value.id, row.id)
    questions.value = await getPretestQuestions(activePaper.value.id)
    notice.value = '评价任务已删除。'
  }, true)
}

function resetFilters() {
  query.value = ''
  status.value = ''
  selectedKind.value = ''
  page.value = 1
  load()
}

onMounted(async () => {
  await loadSubjects()
  await Promise.all([load(), loadPendingMaterials(), loadAdministrations()])
})
</script>

<template>
  <AppShell title="学习起点诊断（前测）" eyebrow="学校教学管理" :nav-items="navItems" shell-variant="school-admin">
    <NoticeLine v-if="notice" :message="notice" floating @dismiss="notice = ''" />

    <nav class="pretest-section-tabs" aria-label="学习起点诊断管理范围">
      <button type="button" :class="{ active: activeSection === 'versions' }" @click="activeSection = 'versions'">
        诊断版本与评价任务
      </button>
      <button type="button" :class="{ active: activeSection === 'administrations' }" @click="activeSection = 'administrations'; loadAdministrations()">
        实施批次与实验班级
      </button>
    </nav>

    <section v-if="activeSection === 'versions'" class="panel pretest-review-callout">
      <div>
        <span>表现性评价材料</span>
        <strong>{{ pendingMaterials.length }} 项等待评价</strong>
        <p>操作任务、表现任务和短项目先保存原始材料；完成评价后，再形成评分记录和学习目标的初始情况。</p>
      </div>
      <button class="primary-button" type="button" @click="openMaterialReviews">查看待评价材料</button>
    </section>

    <section v-if="activeSection === 'versions'" class="screen-grid pretest-layout">
      <article class="panel subject-panel">
        <div class="panel-heading split">
          <div>
            <h2>学科</h2>
            <p>按学科管理学习起点诊断，每次提交只形成学习目标级初始情况。</p>
          </div>
          <button class="primary-button" type="button" @click="openSubjectCreate">新增学科</button>
        </div>
        <div class="subject-list">
          <button
            v-for="subject in subjects"
            :key="subject.id"
            class="subject-row"
            :class="{ active: selectedSubject === String(subject.id) }"
            type="button"
            @click="selectedSubject = String(subject.id); page = 1; load(); loadPendingMaterials()"
          >
            <span>
              <strong>{{ subject.name }}</strong>
              <small>{{ subject.code }} · {{ subject.pretest_count }} 个诊断版本</small>
            </span>
            <em :class="subject.is_active ? 'status-active' : 'status-disabled'">{{ subject.is_active ? '启用' : '停用' }}</em>
          </button>
          <p v-if="!subjects.length" class="empty">暂无学科</p>
        </div>
        <div v-if="subjects.length" class="subject-actions">
          <button
            class="secondary-button"
            type="button"
            :disabled="!selectedSubject"
            @click="editCurrentSubject"
          >
            编辑当前学科
          </button>
          <button
            class="secondary-button danger"
            type="button"
            :disabled="!selectedSubject"
            @click="removeCurrentSubject"
          >
            删除
          </button>
        </div>
      </article>

      <div class="pretest-main">
        <div class="extra-filter">
          <label>
            <span>诊断类型</span>
            <AppSelect v-model="selectedKind" @change="page = 1; load()">
              <option v-for="item in kindOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
            </AppSelect>
          </label>
        </div>
        <ManagementPage
          v-model:query="query"
          v-model:status="status"
          title="学习起点诊断版本"
          description="可组合客观题、简答、表现任务、操作任务和短项目；已发布版本不可修改，缺失材料、设备问题或未获得机会不会计为低水平。"
          :total="total"
          :page="page"
          :page-size="pageSize"
          :rows="rows"
          :loading="loading"
          :status-options="paperStatusOptions"
          primary-label="新建诊断版本"
          :show-template="false"
          :show-import="false"
          :show-export="false"
          @create="openPaperCreate"
          @search="page = 1; load()"
          @reset="resetFilters"
          @page="page = $event; load()"
        >
          <template #head>
            <thead>
              <tr>
                <th>学科</th>
                <th>类型</th>
                <th>诊断名称</th>
                <th>版本</th>
                <th>评价任务</th>
                <th>作答</th>
                <th>状态</th>
                <th class="actions-col">操作</th>
              </tr>
            </thead>
          </template>
          <template #rows="{ rows: tableRows }">
            <tr v-for="row in tableRows" :key="row.id">
              <td>{{ row.subject.name }}</td>
              <td>{{ row.kind_label }}</td>
              <td>{{ row.title }}</td>
              <td>v{{ row.version }}</td>
              <td>{{ row.question_count }}</td>
              <td>{{ row.submission_count }}</td>
              <td><span class="status-pill" :class="classForStatus(row.status)">{{ row.status_label }}</span></td>
              <td class="row-actions">
                <button type="button" @click="openQuestions(row)">评价任务</button>
                <button v-if="row.status === 'draft'" type="button" @click="editPaper(row)">编辑</button>
                <button v-if="row.status !== 'published'" type="button" @click="publishPaper(row)">发布</button>
                <button v-if="row.status !== 'archived'" type="button" @click="archivePaper(row)">归档</button>
                <button type="button" class="danger-link" @click="removePaper(row)">删除</button>
              </td>
            </tr>
          </template>
        </ManagementPage>
      </div>
    </section>

    <section v-else class="panel diagnostic-administration-panel">
      <header class="panel-heading split">
        <div>
          <h2>诊断实施批次</h2>
          <p>每个批次绑定一个不可变诊断版本。教育实验前测或后测必须在同一批次中同时指派实验班与对照班。</p>
        </div>
        <button class="primary-button" type="button" @click="openAdministrationCreate">新建实施批次</button>
      </header>
      <div class="administration-table-wrap">
        <table>
          <thead>
            <tr>
              <th>批次与用途</th>
              <th>冻结诊断版本</th>
              <th>班级</th>
              <th>提交</th>
              <th>实施时间</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in administrations" :key="row.id">
              <td><strong>{{ row.title }}</strong><small>{{ row.batch_code }} · {{ row.purpose_label }}</small></td>
              <td><strong>{{ row.paper_version.title }}</strong><small>v{{ row.paper_version.version_no }} · SHA-256 {{ row.paper_version.content_hash.slice(0, 12) }}</small></td>
              <td>{{ row.assignment_count }}</td>
              <td>{{ row.submission_count }}</td>
              <td><small>{{ row.open_at ? localDateTime(row.open_at).replace('T', ' ') : '发布后开放' }}<br />至 {{ row.close_at ? localDateTime(row.close_at).replace('T', ' ') : '手动关闭' }}</small></td>
              <td><span class="status-pill" :class="administrationStatusClass(row.status)">{{ row.status_label }}</span></td>
              <td class="row-actions">
                <button v-if="row.status === 'draft'" type="button" @click="openAdministrationEdit(row)">编辑指派</button>
                <button v-if="row.status === 'draft'" type="button" @click="publishAdministration(row)">发布</button>
                <button v-if="row.status === 'published'" type="button" @click="closeAdministration(row)">关闭</button>
              </td>
            </tr>
            <tr v-if="!administrations.length"><td colspan="7" class="empty">尚未建立诊断实施批次。</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <Teleport to="body">
      <div v-if="administrationOpen" class="modal-backdrop" role="presentation" @click.self="closeAdministrationEditor">
        <section v-modal-focus="closeAdministrationEditor" class="entity-modal compact-modal diagnostic-administration-modal" role="dialog" aria-modal="true" aria-labelledby="diagnostic-administration-title">
          <header class="modal-header">
            <div>
              <h2 id="diagnostic-administration-title">{{ editingAdministration ? '编辑诊断实施草稿' : '新建诊断实施批次' }}</h2>
              <p>先选择精确发布版本，再设置班级、实验角色与评价机会；发布后全部冻结。</p>
            </div>
              <button class="icon-button" type="button" aria-label="关闭" :disabled="saving" @click="closeAdministrationEditor">×</button>
          </header>
          <form class="diagnostic-administration-form" @submit.prevent="submitAdministration">
            <div class="administration-fields">
              <label class="span-2">
                <span>冻结诊断版本 <b>*</b></span>
                <AppSelect v-model="administrationModel.paper_version_id" :disabled="Boolean(editingAdministration)">
                  <option value="">请选择已发布版本</option>
                  <option v-for="row in publishedPapers" :key="row.published_version?.id" :value="String(row.published_version?.id || '')">
                    {{ row.subject.name }} · {{ row.title }} · v{{ row.version }}
                  </option>
                </AppSelect>
                <small v-if="administrationErrors.paper_version_id" class="field-error">{{ administrationErrors.paper_version_id.join('；') }}</small>
              </label>
              <label>
                <span>实施用途 <b>*</b></span>
                <AppSelect v-model="administrationModel.purpose">
                  <option value="entry_diagnostic">学习起点诊断</option>
                  <option value="research_pretest">教育实验前测</option>
                  <option value="research_posttest">教育实验后测</option>
                  <option value="pilot">诊断工具试测</option>
                </AppSelect>
                <small v-if="administrationErrors.purpose" class="field-error">{{ administrationErrors.purpose.join('；') }}</small>
              </label>
              <label>
                <span>批次编码 <b>*</b></span>
                <input v-model="administrationModel.batch_code" maxlength="64" placeholder="例如 EXP-202609-IT-PRE" />
                <small v-if="administrationErrors.batch_code" class="field-error">{{ administrationErrors.batch_code.join('；') }}</small>
              </label>
              <label class="span-2">
                <span>实施名称 <b>*</b></span>
                <input v-model="administrationModel.title" maxlength="160" placeholder="例如：2026级信息科技教育实验前测" />
                <small v-if="administrationErrors.title" class="field-error">{{ administrationErrors.title.join('；') }}</small>
              </label>
              <label><span>开放时间</span><input v-model="administrationModel.open_at" type="datetime-local" /></label>
              <label><span>关闭时间</span><input v-model="administrationModel.close_at" type="datetime-local" /></label>
            </div>

            <section class="administration-assignments">
              <header>
                <div><strong>班级指派</strong><small>学生只会看到指派给其当前班级的实施批次。</small></div>
                <small v-if="administrationErrors.assignments" class="field-error">{{ administrationErrors.assignments.join('；') }}</small>
              </header>
              <div class="assignment-grid">
                <article v-for="row in classes" :key="row.id" :class="{ selected: assignmentDrafts[row.id]?.selected }">
                  <label class="assignment-select">
                    <input v-model="assignmentDrafts[row.id].selected" type="checkbox" />
                    <span><strong>{{ row.name }}</strong><small>{{ row.grade || '未设置年级' }}</small></span>
                  </label>
                  <template v-if="assignmentDrafts[row.id]?.selected">
                    <AppSelect v-model="assignmentDrafts[row.id].cohort_role">
                      <option value="unassigned">未设置实验角色</option>
                      <option value="experiment">实验班</option>
                      <option value="control">对照班</option>
                    </AppSelect>
                    <AppSelect v-model="assignmentDrafts[row.id].opportunity_status">
                      <option value="offered">已提供评价机会</option>
                      <option value="not_offered">未提供评价机会</option>
                    </AppSelect>
                  </template>
                </article>
                <p v-if="!classes.length" class="empty">当前没有可指派的在读班级。</p>
              </div>
            </section>
          </form>
          <footer class="modal-actions">
            <button class="secondary-button" type="button" :disabled="saving" @click="closeAdministrationEditor">取消</button>
            <button class="primary-button" type="button" :disabled="saving" @click="submitAdministration">{{ saving ? '保存中' : '保存草稿与指派' }}</button>
          </footer>
        </section>
      </div>
    </Teleport>

    <EntityFormModal
      v-model:model="subjectModel"
      :open="subjectOpen"
      :title="editingSubject ? '编辑学科' : '新增学科'"
      :fields="subjectFields"
      :errors="subjectErrors"
      :loading="saving"
      submit-label="保存"
      @close="subjectOpen = false"
      @submit="submitSubject"
    />

    <EntityFormModal
      v-model:model="paperModel"
      :open="paperOpen"
      :title="editingPaper ? '编辑学习起点诊断' : '新建学习起点诊断版本'"
      :fields="paperFields"
      :errors="paperErrors"
      :loading="saving"
      submit-label="保存"
      @close="paperOpen = false"
      @submit="submitPaper"
    />

    <Teleport to="body">
      <div v-if="materialReviewOpen" class="modal-backdrop" role="presentation" @click.self="closeMaterialReviews">
        <section v-modal-focus="closeMaterialReviews" class="entity-modal compact-modal pretest-material-review-modal" role="dialog" aria-modal="true" aria-labelledby="material-review-title">
          <header class="modal-header">
            <div><h2 id="material-review-title">学习起点诊断材料评价</h2><p>只评价已经形成的材料；材料缺失、设备问题或未获得机会不计为低水平。</p></div>
            <button class="icon-button" type="button" aria-label="关闭" :disabled="saving" @click="closeMaterialReviews">×</button>
          </header>
          <div class="pretest-material-review-body">
            <aside>
              <button v-for="row in pendingMaterials" :key="row.material_id" type="button" :class="{ active: reviewTarget?.material_id === row.material_id }" @click="selectReviewMaterial(row)">
                <strong>{{ row.student.display_name }}</strong>
                <span>{{ row.subject.name }} · {{ row.material_type_label }}</span>
                <small>{{ row.learning_target_code }} · {{ row.class_group?.name || '未分班' }}</small>
              </button>
              <p v-if="!pendingMaterials.length" class="empty">当前没有等待评价的材料。</p>
            </aside>
            <form v-if="reviewTarget" @submit.prevent="submitMaterialReview">
              <header><h3>{{ reviewTarget.student.display_name }}的评价材料</h3><p>{{ reviewTarget.learning_target_code }} · {{ reviewTarget.material_type_label }}</p></header>
              <section class="material-answer-preview">
                <strong>学生提交</strong>
                <p>{{ materialAnswer(reviewTarget) }}</p>
                <ul v-if="reviewTarget.material_requirements.length"><li v-for="item in reviewTarget.material_requirements" :key="item">{{ item }}</li></ul>
                <div v-if="reviewTarget.attachments.length" class="material-attachment-list">
                  <strong>作品与操作附件</strong>
                  <a
                    v-for="file in reviewTarget.attachments"
                    :key="file.attachment_id"
                    :href="file.download_url"
                    target="_blank"
                    rel="noopener"
                  >
                    <span>{{ file.original_name }}</span>
                    <small>{{ materialFileSize(file.file_size) }} · SHA-256 {{ file.file_sha256.slice(0, 12) }}</small>
                  </a>
                </div>
              </section>
              <div class="material-score-grid">
                <label><span>得分</span><input v-model="reviewScore" type="number" min="0" :max="Number(reviewScoreMax) || undefined" step="0.1" required /></label>
                <label><span>满分（发布版本固定）</span><input :value="reviewScoreMax" type="number" readonly aria-readonly="true" /></label>
              </div>
              <label><span>评价反馈</span><textarea v-model="reviewFeedback" rows="5" maxlength="2000" placeholder="记录表现依据、需要保持的做法和后续学习建议" /></label>
              <footer><button class="primary-button" type="submit" :disabled="saving">{{ saving ? '保存中' : '保存评价' }}</button></footer>
            </form>
            <p v-else class="empty">请选择一项材料开始评价。</p>
          </div>
        </section>
      </div>

      <div v-if="questionOpen && activePaper" class="modal-backdrop" role="presentation" @click.self="closeQuestionEditor">
        <section v-modal-focus="closeQuestionEditor" class="entity-modal compact-modal question-editor-modal" role="dialog" aria-modal="true" aria-labelledby="question-editor-title">
          <header class="modal-header">
            <div>
              <h2 id="question-editor-title">{{ editingQuestion ? '编辑评价任务' : '新增评价任务' }}</h2>
              <p>{{ activePaper.subject.name }} · {{ activePaper.kind_label }} · {{ activePaper.title }}</p>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" :disabled="saving" @click="closeQuestionEditor">×</button>
          </header>

          <form class="question-editor-body" @submit.prevent="submitQuestion">
            <label class="span-2">
              <span>任务说明 <b>*</b></span>
              <textarea
                v-model="questionModel.stem"
                maxlength="1000"
                placeholder="输入题目、操作要求、表现任务或短项目说明"
              />
              <small v-if="questionFieldError('stem')" class="field-error">{{ questionFieldError('stem') }}</small>
            </label>

            <label>
              <span>评价任务类型 <b>*</b></span>
              <AppSelect :value="activeQuestionType" @change="setQuestionType(($event.target as HTMLSelectElement).value)">
                <option v-for="item in questionTypeOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
              </AppSelect>
              <small v-if="questionFieldError('question_type')" class="field-error">{{ questionFieldError('question_type') }}</small>
            </label>

            <label>
              <span>评价维度</span>
              <input v-model="questionModel.dimension" maxlength="64" placeholder="例如：计算思维、学习兴趣" />
              <small v-if="questionFieldError('dimension')" class="field-error">{{ questionFieldError('dimension') }}</small>
            </label>

            <label class="span-2">
              <span>课标对齐的学习目标版本 <b v-if="isLiteracyPaper">*（正式实施）</b></span>
              <AppSelect
                :value="questionModel.learning_target_version_id"
                @change="selectLearningTargetVersion(($event.target as HTMLSelectElement).value)"
              >
                <option value="">
                  {{ isLiteracyPaper ? '仅用于试测：暂未映射（不能建立正式实施批次）' : '非学习目标量表（不进入学习目标情况估计）' }}
                </option>
                <option v-for="item in learningTargetVersions" :key="item.id" :value="item.id">
                  {{ item.course.title }} · {{ item.code }} · {{ item.title }} · v{{ item.version_no }} · {{ item.content_hash.slice(0, 8) }}
                </option>
              </AppSelect>
              <small v-if="selectedLearningTargetVersion">
                已冻结逻辑身份 {{ selectedLearningTargetVersion.logical_key }}，发布后按完整内容摘要追溯；不因同名目标更新而漂移。
              </small>
              <small v-else-if="isLiteracyPaper">
                未映射任务只能用于试测。学习起点诊断、教育实验前测和后测必须逐项选择课标依据完整的学习目标版本。
              </small>
              <small v-else>问卷维度与学习目标情况分开保存，不将态度量表结果解释为学科能力水平。</small>
              <small v-if="questionFieldError('learning_target_version_id')" class="field-error">{{ questionFieldError('learning_target_version_id') }}</small>
            </label>

            <label>
              <span>{{ selectedLearningTargetVersion ? '学习目标代码' : isLiteracyPaper ? '试测目标代码' : '问卷维度代码' }} <b>*</b></span>
              <input
                v-model="questionModel.learning_target_code"
                :readonly="Boolean(selectedLearningTargetVersion)"
                maxlength="96"
                placeholder="例如 IT-DATA-G1"
              />
              <small v-if="questionFieldError('learning_target_code')" class="field-error">{{ questionFieldError('learning_target_code') }}</small>
            </label>

            <label>
              <span>{{ selectedLearningTargetVersion ? '学习目标名称' : isLiteracyPaper ? '试测目标名称' : '问卷维度名称' }} <b>*</b></span>
              <input
                v-model="questionModel.learning_target_name"
                :readonly="Boolean(selectedLearningTargetVersion)"
                maxlength="300"
                placeholder="例如 能够选择并说明合适的数据表达方式"
              />
              <small v-if="questionFieldError('learning_target_name')" class="field-error">{{ questionFieldError('learning_target_name') }}</small>
            </label>

            <label class="span-2">
              <span>评价材料要求</span>
              <textarea v-model="questionModel.material_requirements" rows="3" placeholder="每行一种材料，例如：操作过程记录、作品文件、个人说明" />
              <small>个人材料与小组材料应分别说明，不能用小组结果直接替代个人学习情况。</small>
            </label>

            <div v-if="isChoiceQuestion" class="span-2 question-config-panel">
              <div class="config-heading">
                <div>
                  <strong>选项设置</strong>
                  <small>{{ activeQuestionType === 'single' ? '单选题只能设置一个正确答案。' : '多选题可设置多个正确答案。' }}</small>
                </div>
                <button class="secondary-button" type="button" @click="addOption">新增选项</button>
              </div>
              <div class="option-editor-list">
                <div v-for="(_, index) in optionDrafts" :key="index" class="option-editor-row">
                  <span class="option-label">{{ optionLabel(index) }}</span>
                  <input v-model="optionDrafts[index]" :placeholder="`选项 ${optionLabel(index)}`" />
                  <label v-if="activeQuestionType === 'single'" class="answer-check">
                    <input
                      type="radio"
                      name="single-answer"
                      :checked="isAnswer(optionLabel(index))"
                      @change="setSingleAnswer(optionLabel(index))"
                    />
                    <span>答案</span>
                  </label>
                  <label v-else class="answer-check">
                    <input
                      type="checkbox"
                      :checked="isAnswer(optionLabel(index))"
                      @change="toggleMultipleAnswer(optionLabel(index), ($event.target as HTMLInputElement).checked)"
                    />
                    <span>答案</span>
                  </label>
                  <button class="secondary-button danger compact-button" type="button" @click="removeOption(index)">删除</button>
                </div>
              </div>
              <small v-if="questionFieldError('options')" class="field-error">{{ questionFieldError('options') }}</small>
              <small v-if="questionFieldError('answer')" class="field-error">{{ questionFieldError('answer') }}</small>
            </div>

            <div v-if="isScaleQuestion" class="span-2 question-config-panel">
              <div class="config-heading">
                <div>
                  <strong>5 点李克特量表</strong>
                  <small>量表题固定使用 1-5 分：非常不同意、不同意、不确定、同意、非常同意。</small>
                </div>
              </div>
              <div class="likert-preview">
                <span v-for="item in likertOptions" :key="item.label">{{ item.label }} {{ item.text }}</span>
              </div>
              <small v-if="questionFieldError('options')" class="field-error">{{ questionFieldError('options') }}</small>
            </div>

            <div v-if="isTextQuestion" class="span-2 question-config-panel">
              <div class="config-heading">
                <div>
                  <strong>简答题</strong>
                  <small>简答题不设置选项和标准答案，后续由教师查看或纳入人工评价。</small>
                </div>
              </div>
            </div>

            <div v-if="isPerformanceQuestion" class="span-2 question-config-panel">
              <div class="config-heading">
                <div>
                  <strong>{{ activeQuestionType === 'operation' ? '操作任务' : activeQuestionType === 'short_project' ? '短项目' : '表现任务' }}</strong>
                  <small>提交后进入人工评价，只记录目标级材料状态，不自动换算为初始层级。</small>
                </div>
              </div>
            </div>

            <label>
              <span>分值</span>
              <input v-model="questionModel.score" type="number" min="0" step="0.5" placeholder="例如：5" />
              <small v-if="questionFieldError('score')" class="field-error">{{ questionFieldError('score') }}</small>
            </label>

            <label>
              <span>排序</span>
              <input v-model="questionModel.sort_order" type="number" min="0" max="9999" placeholder="数字越小越靠前" />
              <small v-if="questionFieldError('sort_order')" class="field-error">{{ questionFieldError('sort_order') }}</small>
            </label>

            <label class="check-row span-2">
              <input v-model="questionModel.is_required" type="checkbox" />
              <em>设为必答题</em>
            </label>
          </form>

          <footer class="modal-actions">
            <button class="secondary-button" type="button" :disabled="saving" @click="closeQuestionEditor">取消</button>
            <button class="primary-button" type="button" :disabled="saving" @click="submitQuestion">保存</button>
          </footer>
        </section>
      </div>
    </Teleport>

    <Teleport to="body">
      <div v-if="questionManagerOpen && activePaper" class="modal-backdrop" role="presentation" @click.self="closeQuestionManager">
        <section v-modal-focus="closeQuestionManager" class="entity-modal compact-modal question-modal" role="dialog" aria-modal="true" aria-labelledby="question-manager-title">
          <header class="modal-header">
            <div>
              <h2 id="question-manager-title">评价任务管理</h2>
              <p>{{ activePaper.subject.name }} · {{ activePaper.kind_label }} · {{ activePaper.title }}</p>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" :disabled="saving" @click="closeQuestionManager">×</button>
          </header>

          <div class="batch-modal-body">
            <div class="class-check-header">
              <span>共 {{ questions.length }} 个评价任务</span>
              <button v-if="activePaper.status === 'draft'" class="primary-button" type="button" @click="openQuestionCreate">新增评价任务</button>
            </div>
            <div class="question-list">
              <article v-for="item in questions" :key="item.id" class="question-item">
                <header>
                  <strong>{{ item.sort_order }}. {{ item.stem }}</strong>
                  <span>{{ item.question_type_label }} · {{ item.score }} 分</span>
                </header>
                <p>
                  {{ item.learning_target_version ? '正式学习目标' : item.legacy_unmapped ? '试测/问卷维度（不进入正式目标估计）' : '学习目标' }}：
                  {{ item.learning_target_code }} · {{ item.learning_target_name }}
                  <template v-if="item.learning_target_version">
                    · v{{ item.learning_target_version.version_no }} · {{ item.learning_target_version.content_hash.slice(0, 8) }}
                  </template>
                </p>
                <p v-if="item.dimension">评价维度：{{ item.dimension }}</p>
                <ol v-if="item.options.length">
                  <li v-for="option in item.options" :key="option.label">{{ option.label }}. {{ option.text }}</li>
                </ol>
                <footer>
                  <span>答案：{{ item.answer.length ? item.answer.join(', ') : '未设置' }}</span>
                  <div class="row-actions">
                    <button v-if="activePaper.status === 'draft'" type="button" @click="editQuestion(item)">编辑</button>
                    <button v-if="activePaper.status === 'draft'" type="button" class="danger-link" @click="removeQuestion(item)">删除</button>
                  </div>
                </footer>
              </article>
              <p v-if="!questions.length" class="empty">暂无评价任务</p>
            </div>
          </div>

          <footer class="modal-actions">
            <button class="secondary-button" type="button" :disabled="saving" @click="closeQuestionManager">关闭</button>
          </footer>
        </section>
      </div>
    </Teleport>

    <ConfirmDialog
      :open="confirmOpen"
      :title="confirmTitle"
      :message="confirmMessage"
      :danger="confirmDanger"
      :loading="saving"
      confirm-label="确认"
      @close="confirmOpen = false"
      @confirm="runConfirm"
    />
  </AppShell>
</template>

<style scoped>
.pretest-review-callout {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
  border-color: #bfdbfe;
  background: #f8fbff;
}
.pretest-review-callout > div { display: grid; gap: 4px; }
.pretest-review-callout span { color: #1d4ed8; font-size: 12px; font-weight: 800; }
.pretest-review-callout strong { font-size: 18px; }
.pretest-review-callout p { margin: 0; color: #475569; }
.pretest-material-review-modal { width: min(980px, 100%); }
.pretest-material-review-body {
  display: grid;
  grid-template-columns: minmax(240px, 0.38fr) minmax(0, 1fr);
  min-height: 480px;
  overflow: hidden;
}
.pretest-material-review-body > aside {
  display: grid;
  align-content: start;
  gap: 8px;
  border-right: 1px solid var(--line);
  background: #f8fafc;
  padding: 14px;
  overflow: auto;
}
.pretest-material-review-body > aside button {
  display: grid;
  gap: 4px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  padding: 10px;
  text-align: left;
  cursor: pointer;
}
.pretest-material-review-body > aside button.active { border-color: #2563eb; box-shadow: 0 0 0 1px #2563eb; }
.pretest-material-review-body > aside span,
.pretest-material-review-body > aside small { color: #64748b; }
.pretest-material-review-body > form {
  display: grid;
  align-content: start;
  gap: 14px;
  padding: 18px;
  overflow: auto;
}
.pretest-material-review-body > form header h3,
.pretest-material-review-body > form header p,
.material-answer-preview p { margin: 0; }
.material-answer-preview {
  display: grid;
  gap: 8px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #f8fafc;
  padding: 12px;
}
.material-answer-preview p { white-space: pre-wrap; line-height: 1.65; }
.material-attachment-list,
.material-attachment-list a {
  display: grid;
  gap: 4px;
}
.material-attachment-list {
  gap: 8px;
  border-top: 1px dashed var(--line);
  padding-top: 10px;
}
.material-attachment-list a {
  min-height: 44px;
  justify-content: center;
  border: 1px solid #bfdbfe;
  border-radius: 7px;
  background: #fff;
  color: #1d4ed8;
  padding: 8px 10px;
  text-decoration: none;
}
.material-attachment-list a:focus-visible {
  outline: 3px solid rgba(37, 99, 235, 0.3);
  outline-offset: 2px;
}
.material-attachment-list a small { color: #475569; overflow-wrap: anywhere; }
.material-score-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.pretest-material-review-body form label { display: grid; gap: 6px; }
.pretest-material-review-body form input,
.pretest-material-review-body form textarea {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 7px;
  padding: 9px 10px;
  font: inherit;
}
.pretest-material-review-body form footer { display: flex; justify-content: flex-end; }
.pretest-section-tabs {
  display: inline-flex;
  gap: 4px;
  margin-bottom: 14px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: #f8fafc;
  padding: 4px;
}
.pretest-section-tabs button {
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #475569;
  padding: 9px 14px;
  font-weight: 700;
  cursor: pointer;
}
.pretest-section-tabs button.active { background: #fff; color: #1d4ed8; box-shadow: 0 1px 4px rgba(15, 23, 42, 0.12); }
.diagnostic-administration-panel { display: grid; gap: 14px; }
.administration-table-wrap { overflow: auto; }
.administration-table-wrap table { width: 100%; min-width: 980px; border-collapse: collapse; }
.administration-table-wrap th,
.administration-table-wrap td { border-bottom: 1px solid var(--line); padding: 11px 10px; text-align: left; vertical-align: middle; }
.administration-table-wrap th { color: #64748b; font-size: 12px; }
.administration-table-wrap td > strong,
.administration-table-wrap td > small { display: block; }
.administration-table-wrap td > small { margin-top: 3px; color: #64748b; line-height: 1.45; }
.diagnostic-administration-modal { width: min(980px, 100%); max-height: min(90vh, 860px); }
.diagnostic-administration-form { display: grid; gap: 18px; padding: 18px; overflow: auto; }
.administration-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.administration-fields label { display: grid; gap: 6px; }
.administration-fields .span-2 { grid-column: span 2; }
.administration-fields input { width: 100%; border: 1px solid var(--line); border-radius: 7px; padding: 9px 10px; font: inherit; }
.administration-assignments { display: grid; gap: 10px; }
.administration-assignments > header { display: flex; justify-content: space-between; gap: 12px; }
.administration-assignments > header > div { display: grid; gap: 3px; }
.administration-assignments small { color: #64748b; }
.assignment-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; max-height: 310px; overflow: auto; }
.assignment-grid article { display: grid; grid-template-columns: minmax(150px, 1fr); gap: 8px; border: 1px solid var(--line); border-radius: 8px; padding: 9px; }
.assignment-grid article.selected { grid-template-columns: minmax(150px, 1fr) minmax(130px, .8fr) minmax(145px, .9fr); border-color: #93c5fd; background: #f8fbff; }
.assignment-select { display: flex; align-items: center; gap: 9px; min-width: 0; }
.assignment-select span { display: grid; min-width: 0; }
.assignment-select small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
@media (max-width: 760px) {
  .pretest-review-callout { align-items: stretch; flex-direction: column; }
  .pretest-material-review-body { grid-template-columns: 1fr; }
  .pretest-material-review-body > aside { max-height: 220px; border-right: 0; border-bottom: 1px solid var(--line); }
  .pretest-section-tabs { display: grid; width: 100%; }
  .administration-fields,
  .assignment-grid { grid-template-columns: 1fr; }
  .administration-fields .span-2 { grid-column: auto; }
  .assignment-grid article.selected { grid-template-columns: 1fr; }
}
</style>
