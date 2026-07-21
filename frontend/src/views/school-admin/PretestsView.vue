<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError, type FieldErrors } from '@/api/client'
import {
  archivePretestPaper,
  createPretestPaper,
  createPretestQuestion,
  createSubject,
  deletePretestPaper,
  deletePretestQuestion,
  deleteSubject,
  getPretestPapers,
  getPretestQuestions,
  getSubjects,
  publishPretestPaper,
  updatePretestPaper,
  updatePretestQuestion,
  updateSubject,
  type PageResult,
  type PretestPaperPayload,
  type PretestPaperRow,
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
import type { FormField } from '@/types/forms'
import { schoolAdminNav } from './nav'

type FormModel = Record<string, string | number | boolean>
type QuestionFormModel = {
  stem: string
  question_type: string
  score: number | string
  dimension: string
  sort_order: number | string
  is_required: boolean
}

const navItems = schoolAdminNav('/school-admin/pretests')

const paperStatusOptions = [
  { label: '全部状态', value: '' },
  { label: '草稿', value: 'draft' },
  { label: '已发布', value: 'published' },
  { label: '归档', value: 'archived' }
]

const kindOptions = [
  { label: '全部类型', value: '' },
  { label: '素养测试', value: 'literacy' },
  { label: '学习态度问卷', value: 'attitude' }
]

const questionTypeOptions = [
  { label: '单选', value: 'single' },
  { label: '多选', value: 'multiple' },
  { label: '量表', value: 'scale' },
  { label: '简答', value: 'text' }
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
    label: '前测类型',
    type: 'select',
    required: true,
    options: [
      { label: '素养测试', value: 'literacy' },
      { label: '学习态度问卷', value: 'attitude' }
    ]
  },
  {
    name: 'title',
    label: '套卷名称',
    required: true,
    maxlength: 128,
    pattern: '^[\\u4e00-\\u9fa5A-Za-z0-9（）()·\\-\\s]{2,128}$',
    placeholder: '例如：信息技术入学素养测试'
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
    options: [
      { label: '草稿', value: 'draft' },
      { label: '已发布', value: 'published' },
      { label: '归档', value: 'archived' }
    ],
    helper: '同一学科同一类型只保留一套已发布版本。'
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
    sort_order: typeof model.sort_order === 'boolean' ? 0 : model.sort_order || 0,
    is_required: Boolean(model.is_required)
  }
}

function classForStatus(statusValue: string) {
  if (statusValue === 'published') return 'status-active'
  if (statusValue === 'draft') return 'status-warning'
  return 'status-archived'
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

function ask(title: string, message: string, action: () => Promise<void>, danger = false) {
  confirmTitle.value = title
  confirmMessage.value = message
  confirmAction.value = action
  confirmDanger.value = danger
  confirmOpen.value = true
}

async function runConfirm() {
  if (!confirmAction.value) return
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
  ask('删除学科', `确认删除 ${subject.name}？已有课程、前测或作答记录时系统会拒绝物理删除。`, async () => {
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
  saving.value = true
  notice.value = ''
  paperErrors.value = {}
  try {
    if (editingPaper.value) {
      await updatePretestPaper(editingPaper.value.id, paperPayload(paperModel.value))
      notice.value = '前测套卷已更新。'
    } else {
      await createPretestPaper(paperPayload(paperModel.value))
      notice.value = '前测套卷已创建。'
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
  ask('发布前测套卷', `确认发布 ${row.title}？同一学科同一类型下，其他已发布版本会自动归档。`, async () => {
    await publishPretestPaper(row.id)
    notice.value = '前测套卷已发布。'
  })
}

function archivePaper(row: PretestPaperRow) {
  ask('归档前测套卷', `确认归档 ${row.title}？归档后学生不会再收到这套前测。`, async () => {
    await archivePretestPaper(row.id)
    notice.value = '前测套卷已归档。'
  })
}

function removePaper(row: PretestPaperRow) {
  if (row.status === 'published') {
    notice.value = '已发布前测不能直接删除，请先归档。'
    return
  }
  ask('删除前测套卷', `确认删除 ${row.title}？已有学生作答时系统会拒绝物理删除。`, async () => {
    await deletePretestPaper(row.id)
    notice.value = '前测套卷已删除。'
  }, true)
}

async function openQuestions(row: PretestPaperRow) {
  activePaper.value = row
  questionErrors.value = {}
  questions.value = await getPretestQuestions(row.id)
  questionManagerOpen.value = true
}

function openQuestionCreate() {
  editingQuestion.value = null
  questionErrors.value = {}
  questionModel.value = emptyQuestion()
  optionDrafts.value = ['', '', '', '']
  answerDraft.value = []
  questionManagerOpen.value = false
  questionOpen.value = true
}

function editQuestion(row: PretestQuestionRow) {
  editingQuestion.value = row
  questionErrors.value = {}
  questionModel.value = {
    stem: row.stem,
    question_type: row.question_type,
    score: row.score,
    dimension: row.dimension,
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
  if (!activePaper.value) return
  saving.value = true
  notice.value = ''
  questionErrors.value = {}
  try {
    if (editingQuestion.value) {
      await updatePretestQuestion(activePaper.value.id, editingQuestion.value.id, questionPayload(questionModel.value))
      notice.value = '题目已更新。'
    } else {
      await createPretestQuestion(activePaper.value.id, questionPayload(questionModel.value))
      notice.value = '题目已创建。'
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
  questionOpen.value = false
  if (activePaper.value) {
    questionManagerOpen.value = true
  }
}

function removeQuestion(row: PretestQuestionRow) {
  if (!activePaper.value) return
  ask('删除题目', '确认删除这道题？已发布且已有作答记录的套卷会拒绝物理删除。', async () => {
    if (!activePaper.value) return
    await deletePretestQuestion(activePaper.value.id, row.id)
    questions.value = await getPretestQuestions(activePaper.value.id)
    notice.value = '题目已删除。'
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
  await load()
})
</script>

<template>
  <AppShell title="学科与学科前测" eyebrow="学校管理员" :nav-items="navItems">
    <NoticeLine v-if="notice" :message="notice" floating @dismiss="notice = ''" />

    <section class="screen-grid pretest-layout">
      <article class="panel subject-panel">
        <div class="panel-heading split">
          <div>
            <h2>学科</h2>
            <p>不同学科使用独立前测。</p>
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
            @click="selectedSubject = String(subject.id); page = 1; load()"
          >
            <span>
              <strong>{{ subject.name }}</strong>
              <small>{{ subject.code }} · {{ subject.pretest_count }} 套前测</small>
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
            <span>前测类型</span>
            <AppSelect v-model="selectedKind" @change="page = 1; load()">
              <option v-for="item in kindOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
            </AppSelect>
          </label>
        </div>
        <ManagementPage
          v-model:query="query"
          v-model:status="status"
          title="学科前测套卷"
          description="每个学科可维护素养测试和学习态度问卷。学生进入该学科学习前，需要完成当前发布版本。"
          :total="total"
          :page="page"
          :page-size="pageSize"
          :rows="rows"
          :loading="loading"
          :status-options="paperStatusOptions"
          primary-label="新增套卷"
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
                <th>套卷</th>
                <th>版本</th>
                <th>题目</th>
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
                <button type="button" @click="openQuestions(row)">题目</button>
                <button type="button" @click="editPaper(row)">编辑</button>
                <button v-if="row.status !== 'published'" type="button" @click="publishPaper(row)">发布</button>
                <button v-if="row.status !== 'archived'" type="button" @click="archivePaper(row)">归档</button>
                <button type="button" class="danger-link" @click="removePaper(row)">删除</button>
              </td>
            </tr>
          </template>
        </ManagementPage>
      </div>
    </section>

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
      :title="editingPaper ? '编辑前测套卷' : '新增前测套卷'"
      :fields="paperFields"
      :errors="paperErrors"
      :loading="saving"
      submit-label="保存"
      @close="paperOpen = false"
      @submit="submitPaper"
    />

    <Teleport to="body">
      <div v-if="questionOpen && activePaper" class="modal-backdrop" role="presentation" @click.self="closeQuestionEditor">
        <section class="entity-modal compact-modal question-editor-modal" role="dialog" aria-modal="true" aria-labelledby="question-editor-title">
          <header class="modal-header">
            <div>
              <h2 id="question-editor-title">{{ editingQuestion ? '编辑题目' : '新增题目' }}</h2>
              <p>{{ activePaper.subject.name }} · {{ activePaper.kind_label }} · {{ activePaper.title }}</p>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" @click="closeQuestionEditor">×</button>
          </header>

          <form class="question-editor-body" @submit.prevent="submitQuestion">
            <label class="span-2">
              <span>题干 <b>*</b></span>
              <textarea
                v-model="questionModel.stem"
                maxlength="1000"
                placeholder="输入题目内容"
              />
              <small v-if="questionFieldError('stem')" class="field-error">{{ questionFieldError('stem') }}</small>
            </label>

            <label>
              <span>题型 <b>*</b></span>
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
            <button class="secondary-button" type="button" @click="closeQuestionEditor">取消</button>
            <button class="primary-button" type="button" :disabled="saving" @click="submitQuestion">保存</button>
          </footer>
        </section>
      </div>
    </Teleport>

    <Teleport to="body">
      <div v-if="questionManagerOpen && activePaper" class="modal-backdrop" role="presentation" @click.self="questionManagerOpen = false">
        <section class="entity-modal compact-modal question-modal" role="dialog" aria-modal="true" aria-labelledby="question-manager-title">
          <header class="modal-header">
            <div>
              <h2 id="question-manager-title">题目管理</h2>
              <p>{{ activePaper.subject.name }} · {{ activePaper.kind_label }} · {{ activePaper.title }}</p>
            </div>
            <button class="icon-button" type="button" aria-label="关闭" @click="questionManagerOpen = false">×</button>
          </header>

          <div class="batch-modal-body">
            <div class="class-check-header">
              <span>共 {{ questions.length }} 道题</span>
              <button class="primary-button" type="button" @click="openQuestionCreate">新增题目</button>
            </div>
            <div class="question-list">
              <article v-for="item in questions" :key="item.id" class="question-item">
                <header>
                  <strong>{{ item.sort_order }}. {{ item.stem }}</strong>
                  <span>{{ item.question_type_label }} · {{ item.score }} 分</span>
                </header>
                <p v-if="item.dimension">维度：{{ item.dimension }}</p>
                <ol v-if="item.options.length">
                  <li v-for="option in item.options" :key="option.label">{{ option.label }}. {{ option.text }}</li>
                </ol>
                <footer>
                  <span>答案：{{ item.answer.length ? item.answer.join(', ') : '未设置' }}</span>
                  <div class="row-actions">
                    <button type="button" @click="editQuestion(item)">编辑</button>
                    <button type="button" class="danger-link" @click="removeQuestion(item)">删除</button>
                  </div>
                </footer>
              </article>
              <p v-if="!questions.length" class="empty">暂无题目</p>
            </div>
          </div>

          <footer class="modal-actions">
            <button class="secondary-button" type="button" @click="questionManagerOpen = false">关闭</button>
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
