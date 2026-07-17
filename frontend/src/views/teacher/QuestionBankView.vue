<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ApiError, type FieldErrors } from '@/api/client'
import {
  confirmQuestionBankDrafts,
  createBankQuestion,
  deleteBankQuestion,
  getAssessmentOptions,
  getQuestionBank,
  generateQuestionBankDrafts,
  importQuestionBank,
  questionBankExportUrl,
  questionBankTemplateUrl,
  updateBankQuestion,
  type AssessmentOptions,
  type AiQuestionDraft,
  type AiQuestionGenerationPayload,
  type BankQuestion,
  type BankQuestionPayload
} from '@/api/assessments'
import AppShell from '@/layouts/AppShell.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import { teacherNav } from './nav'

const navItems = teacherNav('/teacher/question-bank')
const options = ref<AssessmentOptions | null>(null)
const rows = ref<BankQuestion[]>([])
const loading = ref(false)
const saving = ref(false)
const notice = ref('')
const scope = ref('shared')
const query = ref('')
const subject = ref('')
const questionType = ref('')
const difficulty = ref('')
const modalOpen = ref(false)
const editing = ref<BankQuestion | null>(null)
const errors = ref<FieldErrors>({})
const optionDrafts = ref(['', '', '', ''])
const answerDrafts = ref<string[]>([])
const importInput = ref<HTMLInputElement | null>(null)
const aiOpen = ref(false)
const aiLoading = ref(false)
const aiSaving = ref(false)
const aiErrors = ref<FieldErrors>({})
const aiNotice = ref('')
const aiDrafts = ref<AiQuestionDraft[]>([])
const aiForm = reactive<AiQuestionGenerationPayload>({
  subject: '',
  direction: '',
  knowledge_point: '',
  question_type: 'mixed',
  difficulty: 'normal',
  count: 5,
  requirement: ''
})

const form = reactive<BankQuestionPayload>({
  subject: '',
  stem: '',
  question_type: 'single',
  options: [],
  answer: [],
  analysis: '',
  difficulty: 'normal',
  knowledge_point: '',
  default_score: 2
})

const isChoice = computed(() => ['single', 'multiple'].includes(form.question_type))
const isJudge = computed(() => form.question_type === 'judge')
const needsAnswerText = computed(() => form.question_type === 'blank')
const summary = computed(() => [
  { label: '当前题目', value: rows.value.length, sub: scope.value === 'mine' ? '本人创建' : '学校共享' },
  { label: '我的题目', value: rows.value.filter((item) => item.is_owner).length, sub: '可编辑维护' },
  { label: '启用题目', value: rows.value.filter((item) => item.status === 'active').length, sub: '可用于组卷' },
  { label: '累计使用', value: rows.value.reduce((sum, item) => sum + item.usage_count, 0), sub: '组卷引用次数' }
])
const selectedAiDrafts = computed(() => aiDrafts.value.filter((item) => item.selected))

function openAiGenerate() {
  aiErrors.value = {}
  aiNotice.value = ''
  aiDrafts.value = []
  aiForm.subject = subject.value || options.value?.subjects[0]?.id || ''
  aiForm.direction = ''
  aiForm.knowledge_point = ''
  aiForm.question_type = 'mixed'
  aiForm.difficulty = 'normal'
  aiForm.count = 5
  aiForm.requirement = ''
  aiOpen.value = true
}

function validateAiForm() {
  const next: FieldErrors = {}
  if (!aiForm.subject) next.subject = ['请选择学科。']
  if (aiForm.direction.trim().length < 4 || aiForm.direction.trim().length > 1500) next.direction = ['出题方向需为 4-1500 个字符。']
  if (aiForm.knowledge_point.trim().length > 128) next.knowledge_point = ['知识点不能超过 128 个字符。']
  if (Number(aiForm.count) < 1 || Number(aiForm.count) > 20) next.count = ['生成数量需为 1-20 道。']
  if (aiForm.requirement.trim().length > 1000) next.requirement = ['补充要求不能超过 1000 个字符。']
  aiErrors.value = next
  return !Object.keys(next).length
}

async function generateAiDrafts() {
  if (!validateAiForm()) return
  aiLoading.value = true
  aiNotice.value = ''
  try {
    const result = await generateQuestionBankDrafts({
      ...aiForm,
      direction: aiForm.direction.trim(),
      knowledge_point: aiForm.knowledge_point.trim(),
      requirement: aiForm.requirement.trim(),
      count: Number(aiForm.count)
    })
    aiDrafts.value = result.questions.map((item) => ({ ...item, subject: result.subject.id, selected: true }))
    aiNotice.value = `AI 返回 ${result.valid_count} 道有效草稿。请检查题干、答案和解析后再入库。`
  } catch (error) {
    if (error instanceof ApiError) {
      aiNotice.value = error.message
      aiErrors.value = error.errors
    } else aiNotice.value = 'AI 出题失败，请检查接入配置后重试。'
  } finally {
    aiLoading.value = false
  }
}

function aiDraftOptions(draft: AiQuestionDraft) {
  if (draft.question_type === 'judge') return ['正确', '错误']
  return draft.options
}

function setAiDraftType(draft: AiQuestionDraft, type: string) {
  draft.question_type = type
  draft.answer = []
  if (type === 'judge') draft.options = ['正确', '错误']
  else if (['single', 'multiple'].includes(type) && draft.options.length < 2) draft.options = ['', '', '', '']
  else if (!['single', 'multiple'].includes(type)) draft.options = []
  draft.default_score = type === 'text' ? 5 : type === 'blank' ? 3 : 2
}

function addAiDraftOption(draft: AiQuestionDraft) {
  if (draft.options.length < 10) draft.options.push('')
}

function removeAiDraftOption(draft: AiQuestionDraft, index: number) {
  const value = draft.options[index]
  draft.options.splice(index, 1)
  draft.answer = draft.answer.filter((item) => item !== value)
}

function updateAiDraftOption(draft: AiQuestionDraft, index: number, value: string) {
  const previous = draft.options[index]
  draft.options[index] = value
  if (previous && draft.answer.includes(previous)) {
    draft.answer = draft.answer.map((item) => item === previous ? value : item).filter(Boolean)
  }
}

function toggleAiDraftAnswer(draft: AiQuestionDraft, value: string, checked: boolean) {
  if (!value.trim()) return
  if (draft.question_type !== 'multiple') {
    draft.answer = checked ? [value] : []
    return
  }
  draft.answer = checked ? Array.from(new Set([...draft.answer, value])) : draft.answer.filter((item) => item !== value)
}

function removeAiDraft(index: number) {
  aiDrafts.value.splice(index, 1)
}

function validateAiDrafts() {
  const messages: string[] = []
  selectedAiDrafts.value.forEach((draft, index) => {
    if (draft.stem.trim().length < 2) messages.push(`第 ${index + 1} 题题干不能为空。`)
    const optionValues = aiDraftOptions(draft).map((item) => item.trim()).filter(Boolean)
    if (['single', 'multiple', 'judge'].includes(draft.question_type) && optionValues.length < 2) messages.push(`第 ${index + 1} 题至少需要两个选项。`)
    if (draft.question_type !== 'text' && !draft.answer.some((item) => item.trim())) messages.push(`第 ${index + 1} 题缺少参考答案。`)
    if (draft.default_score <= 0 || draft.default_score > 100) messages.push(`第 ${index + 1} 题分值不正确。`)
  })
  if (!selectedAiDrafts.value.length) messages.push('请至少选择一道题目。')
  aiErrors.value = messages.length ? { questions: messages } : {}
  return !messages.length
}

async function confirmAiDrafts() {
  if (!validateAiDrafts()) return
  aiSaving.value = true
  try {
    const cleaned = selectedAiDrafts.value.map((draft) => ({
      ...draft,
      stem: draft.stem.trim(),
      options: aiDraftOptions(draft).map((item) => item.trim()).filter(Boolean),
      answer: draft.question_type === 'text' ? [] : draft.answer.map((item) => item.trim()).filter(Boolean),
      analysis: draft.analysis.trim(),
      knowledge_point: draft.knowledge_point.trim()
    }))
    const result = await confirmQuestionBankDrafts(aiForm.subject, cleaned)
    aiOpen.value = false
    notice.value = `已将 ${result.created_count} 道 AI 题目加入学校共享题库。`
    scope.value = 'mine'
    await load()
  } catch (error) {
    if (error instanceof ApiError) {
      aiNotice.value = error.message
      aiErrors.value = error.errors
    } else aiNotice.value = 'AI 题目入库失败。'
  } finally {
    aiSaving.value = false
  }
}

function resetForm() {
  editing.value = null
  errors.value = {}
  form.subject = subject.value || options.value?.subjects[0]?.id || ''
  form.stem = ''
  form.question_type = 'single'
  form.analysis = ''
  form.difficulty = 'normal'
  form.knowledge_point = ''
  form.default_score = 2
  optionDrafts.value = ['', '', '', '']
  answerDrafts.value = []
}

function openCreate() {
  resetForm()
  modalOpen.value = true
}

function openEdit(row: BankQuestion) {
  if (!row.is_owner) return
  editing.value = row
  errors.value = {}
  Object.assign(form, {
    subject: row.subject.id,
    stem: row.stem,
    question_type: row.question_type,
    analysis: row.analysis,
    difficulty: row.difficulty,
    knowledge_point: row.knowledge_point,
    default_score: row.default_score
  })
  optionDrafts.value = row.question_type === 'judge' ? ['正确', '错误'] : [...row.options, '', '', '', ''].slice(0, Math.max(row.options.length, 4))
  answerDrafts.value = [...row.answer]
  modalOpen.value = true
}

function setType(value: string) {
  form.question_type = value
  answerDrafts.value = []
  if (value === 'judge') optionDrafts.value = ['正确', '错误']
  else if (['single', 'multiple'].includes(value) && optionDrafts.value.length < 2) optionDrafts.value = ['', '', '', '']
  form.default_score = value === 'text' ? 5 : value === 'blank' ? 3 : 2
}

function cleanOptions() {
  return optionDrafts.value.map((item) => item.trim()).filter((item, index, all) => item && all.indexOf(item) === index)
}

function toggleAnswer(value: string, checked: boolean) {
  if (form.question_type !== 'multiple') {
    answerDrafts.value = checked ? [value] : []
    return
  }
  answerDrafts.value = checked
    ? Array.from(new Set([...answerDrafts.value, value]))
    : answerDrafts.value.filter((item) => item !== value)
}

function addOption() {
  if (optionDrafts.value.length < 10) optionDrafts.value.push('')
}

function removeOption(index: number) {
  const removed = optionDrafts.value[index]
  optionDrafts.value.splice(index, 1)
  answerDrafts.value = answerDrafts.value.filter((item) => item !== removed)
}

function validate() {
  const next: FieldErrors = {}
  if (!form.subject) next.subject = ['请选择学科。']
  if (form.stem.trim().length < 2) next.stem = ['题干至少 2 个字符。']
  const cleaned = cleanOptions()
  if ((isChoice.value || isJudge.value) && cleaned.length < 2) next.options = ['至少设置两个选项。']
  if (form.question_type !== 'text' && !answerDrafts.value.length) next.answer = ['请设置参考答案。']
  if (form.default_score <= 0 || form.default_score > 100) next.default_score = ['分值应在 0-100 之间。']
  errors.value = next
  return !Object.keys(next).length
}

async function save() {
  if (!validate()) return
  saving.value = true
  try {
    const payload: BankQuestionPayload = {
      ...form,
      stem: form.stem.trim(),
      options: isJudge.value ? ['正确', '错误'] : isChoice.value ? cleanOptions() : [],
      answer: form.question_type === 'text' ? [] : answerDrafts.value.map((item) => item.trim()).filter(Boolean),
      analysis: form.analysis.trim(),
      knowledge_point: form.knowledge_point.trim()
    }
    await (editing.value ? updateBankQuestion(editing.value.id, payload) : createBankQuestion(payload))
    notice.value = editing.value ? '题目已更新。' : '题目已加入学校共享题库。'
    modalOpen.value = false
    await load()
  } catch (error) {
    if (error instanceof ApiError) {
      notice.value = error.message
      errors.value = error.errors
    } else notice.value = '保存失败。'
  } finally {
    saving.value = false
  }
}

async function toggleStatus(row: BankQuestion) {
  try {
    await updateBankQuestion(row.id, { status: row.status === 'active' ? 'disabled' : 'active' })
    notice.value = row.status === 'active' ? '题目已停用。' : '题目已启用。'
    await load()
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '状态更新失败。'
  }
}

async function remove(row: BankQuestion) {
  if (row.status !== 'disabled') {
    notice.value = '请先停用题目，再执行删除。'
    return
  }
  if (!window.confirm(`确认删除题目“${row.stem.slice(0, 30)}”？`)) return
  try {
    await deleteBankQuestion(row.id)
    notice.value = '题目已删除。'
    await load()
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '删除失败。'
  }
}

async function importFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  saving.value = true
  try {
    const result = await importQuestionBank(file)
    notice.value = `题库导入完成：成功 ${result.created} 道，失败 ${result.failed} 道。${result.errors[0] ? ` 第一个错误：第 ${result.errors[0].row} 行 ${result.errors[0].message}` : ''}`
    await load()
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '题库导入失败。'
  } finally {
    saving.value = false
    input.value = ''
  }
}

async function load() {
  loading.value = true
  try {
    rows.value = await getQuestionBank({ scope: scope.value, q: query.value, subject: subject.value, question_type: questionType.value, difficulty: difficulty.value })
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '题库加载失败。'
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  options.value = await getAssessmentOptions()
  await load()
})
</script>

<template>
  <AppShell title="题库管理" eyebrow="教师工作台" :nav-items="navItems">
    <NoticeLine v-if="notice" :message="notice" />
    <section class="metric-grid assessment-metric-grid">
      <article v-for="item in summary" :key="item.label" class="metric-card"><span>{{ item.label }}</span><strong>{{ item.value }}</strong><small>{{ item.sub }}</small></article>
    </section>

    <section class="panel assessment-library-panel">
      <div class="panel-heading split">
        <div><h2>学校共享题库</h2><p>同校教师可检索和组卷；本人创建的题目可编辑、停用和删除。</p></div>
        <div class="heading-actions assessment-heading-actions">
          <a class="secondary-button" :href="questionBankExportUrl">导出 XLSX</a>
          <a class="secondary-button" :href="questionBankTemplateUrl">下载模板</a>
          <button class="secondary-button" type="button" :disabled="saving" @click="importInput?.click()">批量导入</button>
          <input ref="importInput" class="assessment-hidden-input" type="file" accept=".xlsx" @change="importFile" />
          <button class="secondary-button assessment-ai-button" type="button" @click="openAiGenerate">AI 批量出题</button>
          <button class="primary-button" type="button" @click="openCreate">新增题目</button>
        </div>
      </div>
      <div class="assessment-filter-bar">
        <div class="assessment-segmented">
          <button :class="{ active: scope === 'shared' }" type="button" @click="scope = 'shared'; load()">共享题库</button>
          <button :class="{ active: scope === 'mine' }" type="button" @click="scope = 'mine'; load()">我的题目</button>
        </div>
        <input v-model.trim="query" placeholder="搜索题干或知识点" @keyup.enter="load" />
        <select v-model="subject" @change="load"><option value="">全部学科</option><option v-for="item in options?.subjects" :key="item.id" :value="item.id">{{ item.name }}</option></select>
        <select v-model="questionType" @change="load"><option value="">全部题型</option><option v-for="item in options?.question_types" :key="item.value" :value="item.value">{{ item.label }}</option></select>
        <select v-model="difficulty" @change="load"><option value="">全部难度</option><option v-for="item in options?.difficulties" :key="item.value" :value="item.value">{{ item.label }}</option></select>
        <button class="secondary-button" type="button" @click="load">查询</button>
      </div>

      <div class="assessment-question-library">
        <article v-for="item in rows" :key="item.id" class="assessment-bank-card" :class="{ disabled: item.status === 'disabled' }">
          <header>
            <div><span>{{ item.subject.name }} · {{ item.question_type_label }} · {{ item.difficulty_label }}</span><strong>{{ item.stem }}</strong></div>
            <b>{{ item.default_score }} 分</b>
          </header>
          <div v-if="item.options.length" class="assessment-option-preview"><span v-for="(option, index) in item.options" :key="option">{{ String.fromCharCode(65 + index) }}. {{ option }}</span></div>
          <footer>
            <span>{{ item.knowledge_point || '未设置知识点' }} · {{ item.creator.display_name }} · 使用 {{ item.usage_count }} 次</span>
            <div v-if="item.is_owner">
              <button type="button" @click="openEdit(item)">编辑</button>
              <button type="button" @click="toggleStatus(item)">{{ item.status === 'active' ? '停用' : '启用' }}</button>
              <button v-if="item.status === 'disabled'" class="danger-link" type="button" @click="remove(item)">删除</button>
            </div>
            <small v-else>共享只读</small>
          </footer>
        </article>
        <p v-if="!loading && !rows.length" class="empty">当前筛选下暂无题目。</p>
      </div>
    </section>

    <div v-if="modalOpen" class="modal-backdrop" @click.self="modalOpen = false">
      <section class="entity-modal assessment-question-modal" role="dialog" aria-modal="true">
        <header class="modal-header"><div><h2>{{ editing ? '编辑题目' : '新增题目' }}</h2><p>保存后进入本校共享题库。</p></div><button class="icon-button" type="button" aria-label="关闭" @click="modalOpen = false">×</button></header>
        <div class="assessment-modal-body">
          <div class="assessment-form-grid">
            <label><span>所属学科 <b class="required-mark" aria-hidden="true">*</b></span><select v-model="form.subject" required><option value="">请选择</option><option v-for="item in options?.subjects" :key="item.id" :value="item.id">{{ item.name }}</option></select><small v-if="errors.subject" class="field-error">{{ errors.subject[0] }}</small></label>
            <label><span>题型 <b class="required-mark" aria-hidden="true">*</b></span><select :value="form.question_type" required @change="setType(($event.target as HTMLSelectElement).value)"><option v-for="item in options?.question_types" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
            <label><span>难度</span><select v-model="form.difficulty"><option v-for="item in options?.difficulties" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
            <label><span>默认分值 <b class="required-mark" aria-hidden="true">*</b></span><input v-model.number="form.default_score" type="number" min="0.5" max="100" step="0.5" required /><small v-if="errors.default_score" class="field-error">{{ errors.default_score[0] }}</small></label>
          </div>
          <label class="assessment-wide-field"><span>题干 <b class="required-mark" aria-hidden="true">*</b></span><textarea v-model.trim="form.stem" rows="4" maxlength="2000" placeholder="请输入题目内容" required></textarea><small v-if="errors.stem" class="field-error">{{ errors.stem[0] }}</small></label>

          <section v-if="isChoice || isJudge" class="assessment-option-editor">
            <header><strong>选项与答案</strong><button v-if="isChoice" type="button" @click="addOption">增加选项</button></header>
            <label v-for="(_, index) in optionDrafts" :key="index">
              <input :type="form.question_type === 'multiple' ? 'checkbox' : 'radio'" name="correct-answer" :checked="answerDrafts.includes(optionDrafts[index].trim()) && Boolean(optionDrafts[index].trim())" @change="toggleAnswer(optionDrafts[index].trim(), ($event.target as HTMLInputElement).checked)" />
              <b>{{ String.fromCharCode(65 + index) }}</b>
              <input v-model="optionDrafts[index]" :disabled="isJudge" maxlength="300" :placeholder="`选项 ${String.fromCharCode(65 + index)}`" />
              <button v-if="isChoice && optionDrafts.length > 2" type="button" aria-label="删除选项" @click="removeOption(index)">×</button>
            </label>
            <small v-if="errors.options" class="field-error">{{ errors.options[0] }}</small><small v-if="errors.answer" class="field-error">{{ errors.answer[0] }}</small>
          </section>

          <label v-if="needsAnswerText" class="assessment-wide-field"><span>参考答案 <b class="required-mark" aria-hidden="true">*</b></span><input :value="answerDrafts[0] || ''" maxlength="500" placeholder="请输入参考答案" required @input="answerDrafts = [($event.target as HTMLInputElement).value]" /><small v-if="errors.answer" class="field-error">{{ errors.answer[0] }}</small></label>
          <div class="assessment-form-grid">
            <label><span>知识点</span><input v-model.trim="form.knowledge_point" maxlength="128" placeholder="例如 二进制编码" /></label>
            <label class="assessment-analysis-field"><span>答案解析</span><textarea v-model.trim="form.analysis" rows="3" maxlength="4000" placeholder="可选"></textarea></label>
          </div>
        </div>
        <footer class="modal-actions"><button class="secondary-button" type="button" @click="modalOpen = false">取消</button><button class="primary-button" type="button" :disabled="saving" @click="save">{{ saving ? '保存中' : '保存题目' }}</button></footer>
      </section>
    </div>

    <div v-if="aiOpen" class="modal-backdrop" @click.self="!aiLoading && !aiSaving && (aiOpen = false)">
      <section class="entity-modal assessment-ai-modal" role="dialog" aria-modal="true" aria-labelledby="assessment-ai-title">
        <header class="modal-header">
          <div><h2 id="assessment-ai-title">AI 批量出题</h2><p>使用教师自己的 DeepSeek 接口生成草稿，确认后才进入学校共享题库。</p></div>
          <button class="icon-button" type="button" aria-label="关闭" :disabled="aiLoading || aiSaving" @click="aiOpen = false">×</button>
        </header>

        <div class="assessment-ai-workspace">
          <aside class="assessment-ai-settings">
            <div class="assessment-ai-settings-head">
              <strong>生成设置</strong>
              <a href="/app/teacher/ai" target="_blank" rel="noopener">AI 接入</a>
            </div>
            <label><span>所属学科 <b class="required-mark" aria-hidden="true">*</b></span><select v-model="aiForm.subject" required><option value="">请选择</option><option v-for="item in options?.subjects" :key="item.id" :value="item.id">{{ item.name }}</option></select><small v-if="aiErrors.subject" class="field-error">{{ aiErrors.subject[0] }}</small></label>
            <label><span>出题方向 <b class="required-mark" aria-hidden="true">*</b></span><textarea v-model.trim="aiForm.direction" rows="5" maxlength="1500" placeholder="例如：围绕二进制与十进制转换，考查位权理解和实际换算" required></textarea><small v-if="aiErrors.direction" class="field-error">{{ aiErrors.direction[0] }}</small></label>
            <label><span>知识点</span><input v-model.trim="aiForm.knowledge_point" maxlength="128" placeholder="例如 二进制编码" /><small v-if="aiErrors.knowledge_point" class="field-error">{{ aiErrors.knowledge_point[0] }}</small></label>
            <div class="assessment-ai-setting-grid">
              <label><span>题型</span><select v-model="aiForm.question_type"><option value="mixed">混合题型</option><option v-for="item in options?.question_types" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
              <label><span>难度</span><select v-model="aiForm.difficulty"><option v-for="item in options?.difficulties" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
              <label><span>数量</span><input v-model.number="aiForm.count" type="number" min="1" max="20" /><small v-if="aiErrors.count" class="field-error">{{ aiErrors.count[0] }}</small></label>
            </div>
            <label><span>补充要求</span><textarea v-model.trim="aiForm.requirement" rows="3" maxlength="1000" placeholder="可选：情境、语言风格、避免内容等"></textarea><small v-if="aiErrors.requirement" class="field-error">{{ aiErrors.requirement[0] }}</small></label>
            <button class="primary-button wide" type="button" :disabled="aiLoading || aiSaving" @click="generateAiDrafts">{{ aiLoading ? 'AI 生成中' : aiDrafts.length ? '重新生成草稿' : '生成题目草稿' }}</button>
          </aside>

          <main class="assessment-ai-drafts">
            <header>
              <div><strong>题目草稿</strong><span>{{ selectedAiDrafts.length }} / {{ aiDrafts.length }} 道已选择</span></div>
              <div v-if="aiDrafts.length"><button type="button" @click="aiDrafts.forEach((item) => item.selected = true)">全选</button><button type="button" @click="aiDrafts.forEach((item) => item.selected = false)">取消全选</button></div>
            </header>
            <NoticeLine v-if="aiNotice" :message="aiNotice" :tone="aiDrafts.length ? 'success' : 'warning'" />
            <div v-if="aiLoading" class="assessment-ai-loading"><strong>正在生成题目草稿</strong><span>复杂批量出题可能需要几十秒，请勿关闭窗口。</span></div>
            <div v-else-if="aiDrafts.length" class="assessment-ai-draft-list">
              <article v-for="(draft, draftIndex) in aiDrafts" :key="draft.draft_id" :class="{ unselected: !draft.selected }">
                <header>
                  <label><input v-model="draft.selected" type="checkbox" /><span>第 {{ draftIndex + 1 }} 题</span></label>
                  <button type="button" aria-label="删除草稿" @click="removeAiDraft(draftIndex)">×</button>
                </header>
                <div class="assessment-ai-draft-meta">
                  <label><span>题型</span><select :value="draft.question_type" @change="setAiDraftType(draft, ($event.target as HTMLSelectElement).value)"><option v-for="item in options?.question_types" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
                  <label><span>难度</span><select v-model="draft.difficulty"><option v-for="item in options?.difficulties" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
                  <label><span>分值</span><input v-model.number="draft.default_score" type="number" min="0.5" max="100" step="0.5" /></label>
                  <label><span>知识点</span><input v-model.trim="draft.knowledge_point" maxlength="128" /></label>
                </div>
                <label class="assessment-ai-wide"><span>题干</span><textarea v-model.trim="draft.stem" rows="3" maxlength="2000"></textarea></label>
                <section v-if="['single', 'multiple', 'judge'].includes(draft.question_type)" class="assessment-ai-option-list">
                  <header><strong>选项与答案</strong><button v-if="draft.question_type !== 'judge'" type="button" @click="addAiDraftOption(draft)">增加选项</button></header>
                  <label v-for="(option, optionIndex) in aiDraftOptions(draft)" :key="optionIndex">
                    <input :type="draft.question_type === 'multiple' ? 'checkbox' : 'radio'" :name="`ai-answer-${draft.draft_id}`" :checked="draft.answer.includes(option) && Boolean(option.trim())" @change="toggleAiDraftAnswer(draft, option, ($event.target as HTMLInputElement).checked)" />
                    <b>{{ String.fromCharCode(65 + optionIndex) }}</b>
                    <input :value="option" :disabled="draft.question_type === 'judge'" maxlength="300" @input="updateAiDraftOption(draft, optionIndex, ($event.target as HTMLInputElement).value)" />
                    <button v-if="draft.question_type !== 'judge' && draft.options.length > 2" type="button" aria-label="删除选项" @click="removeAiDraftOption(draft, optionIndex)">×</button>
                  </label>
                </section>
                <label v-if="draft.question_type === 'blank'" class="assessment-ai-wide"><span>参考答案</span><input :value="draft.answer[0] || ''" maxlength="500" @input="draft.answer = [($event.target as HTMLInputElement).value]" /></label>
                <label class="assessment-ai-wide"><span>{{ draft.question_type === 'text' ? '评分要点' : '答案解析' }}</span><textarea v-model.trim="draft.analysis" rows="3" maxlength="4000"></textarea></label>
              </article>
            </div>
            <div v-else class="assessment-ai-empty"><strong>填写出题方向后生成草稿</strong><span>AI 结果不会自动入库，教师可以逐题修改和选择。</span></div>
            <div v-if="aiErrors.questions" class="assessment-ai-error-list" role="alert"><span v-for="message in aiErrors.questions" :key="message">{{ message }}</span></div>
          </main>
        </div>
        <footer class="modal-actions"><button class="secondary-button" type="button" :disabled="aiLoading || aiSaving" @click="aiOpen = false">关闭</button><button class="primary-button" type="button" :disabled="aiLoading || aiSaving || !selectedAiDrafts.length" @click="confirmAiDrafts">{{ aiSaving ? '正在入库' : `确认 ${selectedAiDrafts.length} 道并入库` }}</button></footer>
      </section>
    </div>
  </AppShell>
</template>
