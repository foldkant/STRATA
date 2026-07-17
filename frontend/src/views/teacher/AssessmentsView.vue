<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ApiError, type FieldErrors } from '@/api/client'
import {
  closeAssessment,
  createAssessment,
  deleteAssessment,
  getAssessmentOptions,
  getAssessmentResults,
  assessmentResultsExportUrl,
  getAttemptForGrade,
  getQuestionBank,
  getTeacherAssessment,
  getTeacherAssessments,
  openAssessment,
  publishAssessment,
  saveAssessmentQuestions,
  saveAttemptGrade,
  updateAssessment,
  type AssessmentOptions,
  type AssessmentResults,
  type BankQuestion,
  type TestAssessment,
  type TestAttempt,
  type TestPayload
} from '@/api/assessments'
import AppShell from '@/layouts/AppShell.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import { teacherNav } from './nav'

type PaperItem = { question: BankQuestion; score: number }

const navItems = teacherNav('/teacher/assessments')
const options = ref<AssessmentOptions | null>(null)
const rows = ref<TestAssessment[]>([])
const loading = ref(false)
const saving = ref(false)
const notice = ref('')
const statusFilter = ref('')
const editorOpen = ref(false)
const editorStep = ref<'info' | 'paper'>('info')
const editing = ref<TestAssessment | null>(null)
const errors = ref<FieldErrors>({})
const bankRows = ref<BankQuestion[]>([])
const bankQuery = ref('')
const bankType = ref('')
const paperItems = ref<PaperItem[]>([])
const resultsOpen = ref(false)
const results = ref<AssessmentResults | null>(null)
const gradeOpen = ref(false)
const gradeAttempt = ref<TestAttempt | null>(null)
const gradeDrafts = ref<Record<number, { score: number; feedback: string }>>({})
const gradeMode = ref<'subjective' | 'all'>('subjective')
const gradeTouchedIds = ref(new Set<number>())
const gradeError = ref('')

const form = reactive<TestPayload>({
  title: '', subject: '', course: '', class_ids: [], instruction: '', duration_minutes: 45,
  start_at: '', end_at: '', show_score_after_submit: false,
  randomize_question_order: false, randomize_option_order: false
})

const availableCourses = computed(() => options.value?.courses.filter((item) => !form.subject || Number(item.subject) === Number(form.subject)) || [])
const paperTotal = computed(() => paperItems.value.reduce((sum, item) => sum + Number(item.score || 0), 0))
const filteredBank = computed(() => bankRows.value.filter((item) => {
  const query = bankQuery.value.toLowerCase()
  return (!bankType.value || item.question_type === bankType.value)
    && (!query || item.stem.toLowerCase().includes(query) || item.knowledge_point.toLowerCase().includes(query))
}))
const summary = computed(() => [
  { label: '测试总数', value: rows.value.length, sub: '本人创建' },
  { label: '进行中', value: rows.value.filter((item) => item.status === 'open').length, sub: '学生可作答' },
  { label: '待开启', value: rows.value.filter((item) => item.status === 'published').length, sub: '已发布' },
  { label: '已提交答卷', value: rows.value.reduce((sum, item) => sum + item.submitted_count, 0), sub: '当前列表' }
])
const pendingGradeAttempts = computed(() => results.value?.attempts.filter((item) => item.status === 'submitted') || [])
const subjectiveGradeAnswers = computed(() => gradeAttempt.value?.answers?.filter((item) => item.question.question_type === 'text') || [])
const visibleGradeAnswers = computed(() => gradeMode.value === 'subjective' ? subjectiveGradeAnswers.value : gradeAttempt.value?.answers || [])
const completedSubjectiveCount = computed(() => subjectiveGradeAnswers.value.filter((item) => gradeTouchedIds.value.has(item.id)).length)
const subjectiveScoreTotal = computed(() => subjectiveGradeAnswers.value.reduce((sum, item) => sum + Number(gradeDrafts.value[item.id]?.score || 0), 0))

function localDate(value: string | null) {
  if (!value) return ''
  const date = new Date(value)
  const offset = date.getTimezoneOffset() * 60000
  return new Date(date.getTime() - offset).toISOString().slice(0, 16)
}

function displayDate(value: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '-'
}

function resetForm() {
  editing.value = null
  errors.value = {}
  Object.assign(form, { title: '', subject: options.value?.subjects[0]?.id || '', course: '', class_ids: [], instruction: '', duration_minutes: 45, start_at: '', end_at: '', show_score_after_submit: false, randomize_question_order: false, randomize_option_order: false })
  paperItems.value = []
  editorStep.value = 'info'
}

function openCreate() {
  resetForm()
  editorOpen.value = true
}

async function openEdit(row: TestAssessment) {
  try {
    const detail = await getTeacherAssessment(row.id)
    editing.value = detail
    Object.assign(form, {
      title: detail.title, subject: detail.subject.id, course: detail.course?.id || '',
      class_ids: detail.target_classes.map((item) => item.id), instruction: detail.instruction,
      duration_minutes: detail.duration_minutes, start_at: localDate(detail.start_at), end_at: localDate(detail.end_at),
      show_score_after_submit: detail.show_score_after_submit,
      randomize_question_order: detail.randomize_question_order,
      randomize_option_order: detail.randomize_option_order
    })
    await loadBank(Number(detail.subject.id))
    paperItems.value = (detail.questions || []).map((question) => {
      const bank = bankRows.value.find((item) => item.id === question.source_question)
      return bank ? { question: bank, score: question.score } : {
        question: {
          id: Number(question.source_question || -question.id), subject: detail.subject, creator: detail.teacher,
          stem: question.stem, question_type: question.question_type, question_type_label: question.question_type_label,
          options: question.options, answer: question.answer || [], analysis: question.analysis || '', difficulty: 'normal',
          difficulty_label: '快照', knowledge_point: question.knowledge_point, default_score: question.score,
          status: 'active', status_label: '启用', usage_count: 0, is_owner: false, created_at: '', updated_at: ''
        }, score: question.score
      }
    })
    editorStep.value = 'info'
    editorOpen.value = true
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '测试详情加载失败。'
  }
}

function toggleClass(id: number, checked: boolean) {
  form.class_ids = checked ? Array.from(new Set([...form.class_ids, id])) : form.class_ids.filter((item) => item !== id)
}

function validateInfo() {
  const next: FieldErrors = {}
  if (form.title.trim().length < 2) next.title = ['测试名称至少 2 个字符。']
  if (!form.subject) next.subject = ['请选择学科。']
  if (!form.class_ids.length) next.class_ids = ['至少选择一个任教班级。']
  if (form.duration_minutes < 1 || form.duration_minutes > 300) next.duration_minutes = ['时长应为 1-300 分钟。']
  if (form.start_at && form.end_at && new Date(form.end_at) <= new Date(form.start_at)) next.end_at = ['结束时间必须晚于开始时间。']
  errors.value = next
  return !Object.keys(next).length
}

async function saveInfoAndCompose() {
  if (!validateInfo()) return
  saving.value = true
  try {
    const payload = { ...form, title: form.title.trim(), instruction: form.instruction.trim() }
    const saved = editing.value ? await updateAssessment(editing.value.id, payload) : await createAssessment(payload)
    editing.value = saved
    await loadBank(Number(saved.subject.id))
    editorStep.value = 'paper'
    notice.value = '基本信息已保存，请继续组卷。'
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

async function loadBank(subjectId: number) {
  bankRows.value = await getQuestionBank({ subject: subjectId, scope: 'shared' })
}

function inPaper(id: number) {
  return paperItems.value.some((item) => item.question.id === id)
}

function addQuestion(question: BankQuestion) {
  if (!inPaper(question.id)) paperItems.value.push({ question, score: question.default_score })
}

function removeQuestion(id: number) {
  paperItems.value = paperItems.value.filter((item) => item.question.id !== id)
}

function moveQuestion(index: number, delta: number) {
  const next = index + delta
  if (next < 0 || next >= paperItems.value.length) return
  const items = [...paperItems.value]
  ;[items[index], items[next]] = [items[next], items[index]]
  paperItems.value = items
}

async function savePaper() {
  if (!editing.value || !paperItems.value.length) {
    notice.value = '请至少加入一道题目。'
    return
  }
  saving.value = true
  try {
    await saveAssessmentQuestions(
      editing.value.id,
      paperItems.value.map((item) => ({ question_id: item.question.id, score: Number(item.score) })),
      {
        randomize_question_order: form.randomize_question_order,
        randomize_option_order: form.randomize_option_order
      }
    )
    notice.value = '试卷已保存。'
    editorOpen.value = false
    await load()
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '组卷保存失败。'
  } finally {
    saving.value = false
  }
}

async function action(row: TestAssessment, type: 'publish' | 'open' | 'close' | 'delete') {
  const labels = { publish: '发布', open: '开启', close: '结束', delete: '删除' }
  if (!window.confirm(`确认${labels[type]}测试“${row.title}”？`)) return
  try {
    if (type === 'publish') await publishAssessment(row.id)
    else if (type === 'open') await openAssessment(row.id)
    else if (type === 'close') await closeAssessment(row.id)
    else await deleteAssessment(row.id)
    notice.value = `测试已${labels[type]}。`
    await load()
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '操作失败。'
  }
}

async function openResults(row: TestAssessment) {
  resultsOpen.value = true
  results.value = null
  try {
    results.value = await getAssessmentResults(row.id)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '成绩加载失败。'
  }
}

async function openGrade(attempt: TestAttempt) {
  try {
    gradeAttempt.value = await getAttemptForGrade(attempt.id)
    gradeDrafts.value = {}
    gradeTouchedIds.value = new Set(
      gradeAttempt.value.answers?.filter((item) => item.manual_score !== null).map((item) => item.id) || []
    )
    gradeError.value = ''
    gradeAttempt.value.answers?.forEach((item) => {
      gradeDrafts.value[item.id] = { score: item.manual_score ?? item.auto_score, feedback: item.feedback || '' }
    })
    gradeMode.value = gradeAttempt.value.answers?.some((item) => item.question.question_type === 'text') ? 'subjective' : 'all'
    gradeOpen.value = true
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '答卷加载失败。'
  }
}

function markGrade(answerId: number) {
  gradeError.value = ''
  gradeTouchedIds.value = new Set([...gradeTouchedIds.value, answerId])
}

function setGradeScore(answerId: number, score: number) {
  if (!gradeDrafts.value[answerId]) return
  gradeDrafts.value[answerId].score = score
  markGrade(answerId)
}

async function saveGrade(openNext = false) {
  if (!gradeAttempt.value) return
  if (gradeAttempt.value.status === 'submitted' && completedSubjectiveCount.value < subjectiveGradeAnswers.value.length) {
    gradeError.value = `还有 ${subjectiveGradeAnswers.value.length - completedSubjectiveCount.value} 道主观题未评分。`
    return
  }
  const currentAttemptId = gradeAttempt.value.id
  const nextAttempt = openNext ? pendingGradeAttempts.value.find((item) => item.id !== currentAttemptId) : null
  saving.value = true
  try {
    const subjectiveIds = new Set(subjectiveGradeAnswers.value.map((item) => item.id))
    gradeAttempt.value = await saveAttemptGrade(
      gradeAttempt.value.id,
      Object.entries(gradeDrafts.value)
        .filter(([id]) => subjectiveIds.has(Number(id)))
        .map(([id, value]) => ({ answer_id: Number(id), ...value }))
    )
    notice.value = '评分已保存。'
    gradeOpen.value = false
    if (results.value) results.value = await getAssessmentResults(results.value.assessment.id)
    if (nextAttempt) {
      const refreshed = results.value?.attempts.find((item) => item.id === nextAttempt.id)
      if (refreshed) await openGrade(refreshed)
    }
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '评分保存失败。'
  } finally {
    saving.value = false
  }
}

async function load() {
  loading.value = true
  try { rows.value = await getTeacherAssessments(statusFilter.value) }
  catch (error) { notice.value = error instanceof ApiError ? error.message : '测试列表加载失败。' }
  finally { loading.value = false }
}

onMounted(async () => {
  options.value = await getAssessmentOptions()
  await load()
})
</script>

<template>
  <AppShell title="测试管理" eyebrow="教师工作台" :nav-items="navItems">
    <NoticeLine v-if="notice" :message="notice" />
    <section class="metric-grid assessment-metric-grid"><article v-for="item in summary" :key="item.label" class="metric-card"><span>{{ item.label }}</span><strong>{{ item.value }}</strong><small>{{ item.sub }}</small></article></section>
    <section class="panel assessment-management-panel">
      <div class="panel-heading split"><div><h2>测试安排</h2><p>从学校共享题库组卷，发布并开启后学生才能进入测试。</p></div><button class="primary-button" type="button" @click="openCreate">新建测试</button></div>
      <div class="assessment-filter-bar compact"><select v-model="statusFilter" @change="load"><option value="">全部状态</option><option value="draft">草稿</option><option value="published">待开启</option><option value="open">进行中</option><option value="closed">已结束</option></select><button class="secondary-button" type="button" @click="load">刷新</button></div>
      <div class="assessment-table-wrap"><table class="assessment-table"><thead><tr><th>测试</th><th>班级</th><th>试卷</th><th>时长</th><th>状态</th><th>答卷</th><th>开放时间</th><th>操作</th></tr></thead><tbody>
        <tr v-for="item in rows" :key="item.id"><td><strong>{{ item.title }}</strong><small>{{ item.subject.name }}{{ item.course ? ` · ${item.course.title}` : '' }}</small></td><td><div class="class-chip-list"><span v-for="group in item.target_classes" :key="group.id" class="class-chip">{{ group.grade }} {{ group.name }}</span></div></td><td>{{ item.question_count }} 题 · {{ item.total_score }} 分</td><td>{{ item.duration_minutes }} 分钟</td><td><span class="status-pill" :class="`status-${item.status}`">{{ item.status_label }}</span></td><td>{{ item.submitted_count }} / {{ item.attempt_count }}</td><td><small>{{ displayDate(item.start_at) }}<br />{{ displayDate(item.end_at) }}</small></td><td><div class="row-actions"><button v-if="item.status === 'draft'" type="button" @click="openEdit(item)">编辑组卷</button><button v-if="item.status === 'draft'" type="button" @click="action(item, 'publish')">发布</button><button v-if="item.status === 'published' || item.status === 'closed'" type="button" @click="action(item, 'open')">开启</button><button v-if="item.status === 'open'" type="button" @click="action(item, 'close')">结束</button><button v-if="item.status !== 'draft' || item.attempt_count" type="button" @click="openResults(item)">成绩</button><button v-if="item.status === 'draft'" class="danger-link" type="button" @click="action(item, 'delete')">删除</button></div></td></tr>
      </tbody></table><p v-if="!loading && !rows.length" class="empty">暂无测试安排。</p></div>
    </section>

    <div v-if="editorOpen" class="modal-backdrop" @click.self="editorOpen = false"><section class="entity-modal assessment-builder-modal" role="dialog" aria-modal="true">
      <header class="modal-header"><div><h2>{{ editing ? `编辑：${editing.title}` : '新建测试' }}</h2><p>{{ editorStep === 'info' ? '第一步：测试信息与班级' : '第二步：从共享题库组卷' }}</p></div><button class="icon-button" type="button" aria-label="关闭" @click="editorOpen = false">×</button></header>
      <div class="assessment-builder-steps"><button :class="{ active: editorStep === 'info' }" type="button" @click="editorStep = 'info'">1 基本信息</button><button :class="{ active: editorStep === 'paper' }" type="button" :disabled="!editing" @click="editorStep = 'paper'">2 选择题目</button></div>
      <div v-if="editorStep === 'info'" class="assessment-modal-body">
        <div class="assessment-form-grid"><label><span>测试名称 <b class="required-mark" aria-hidden="true">*</b></span><input v-model.trim="form.title" maxlength="128" placeholder="例如 第一单元检测" required /><small v-if="errors.title" class="field-error">{{ errors.title[0] }}</small></label><label><span>学科 <b class="required-mark" aria-hidden="true">*</b></span><select v-model="form.subject" :disabled="Boolean(editing)" required><option value="">请选择</option><option v-for="item in options?.subjects" :key="item.id" :value="item.id">{{ item.name }}</option></select><small v-if="errors.subject" class="field-error">{{ errors.subject[0] }}</small></label><label><span>关联课程</span><select v-model="form.course"><option value="">不关联课程</option><option v-for="item in availableCourses" :key="item.id" :value="item.id">{{ item.title }}</option></select></label><label><span>作答时长 <b class="required-mark" aria-hidden="true">*</b></span><input v-model.number="form.duration_minutes" type="number" min="1" max="300" required /><small v-if="errors.duration_minutes" class="field-error">{{ errors.duration_minutes[0] }}</small></label><label><span>计划开始</span><input v-model="form.start_at" type="datetime-local" /></label><label><span>计划结束</span><input v-model="form.end_at" type="datetime-local" /><small v-if="errors.end_at" class="field-error">{{ errors.end_at[0] }}</small></label></div>
        <section class="assessment-class-selector"><header><strong>安排班级 <b class="required-mark" aria-hidden="true">*</b></strong><button type="button" @click="form.class_ids = options?.classes.map((item) => item.id) || []">全选</button></header><div><label v-for="item in options?.classes" :key="item.id"><input type="checkbox" :checked="form.class_ids.includes(item.id)" @change="toggleClass(item.id, ($event.target as HTMLInputElement).checked)" /><span>{{ item.grade }} {{ item.name }}</span></label></div><small v-if="errors.class_ids" class="field-error">{{ errors.class_ids[0] }}</small></section>
        <label class="assessment-wide-field"><span>作答说明</span><textarea v-model.trim="form.instruction" rows="3" maxlength="2000" placeholder="学生进入测试前看到的说明"></textarea></label><label class="check-row"><input v-model="form.show_score_after_submit" type="checkbox" /><span>学生提交后立即显示当前得分</span></label>
      </div>
      <div v-else class="assessment-paper-builder">
        <section class="assessment-bank-picker"><header><div><strong>共享题库</strong><span>{{ filteredBank.length }} 道可选</span></div><div><input v-model.trim="bankQuery" placeholder="搜索题干或知识点" /><select v-model="bankType"><option value="">全部题型</option><option v-for="item in options?.question_types" :key="item.value" :value="item.value">{{ item.label }}</option></select></div></header><div class="assessment-picker-list"><article v-for="item in filteredBank" :key="item.id"><div><span>{{ item.question_type_label }} · {{ item.difficulty_label }} · {{ item.default_score }} 分</span><strong>{{ item.stem }}</strong><small>{{ item.knowledge_point || '未设置知识点' }}</small></div><button type="button" :disabled="inPaper(item.id)" @click="addQuestion(item)">{{ inPaper(item.id) ? '已加入' : '加入' }}</button></article></div></section>
        <section class="assessment-paper-list"><header><div><strong>当前试卷</strong><span>{{ paperItems.length }} 题 · {{ paperTotal }} 分</span></div></header><div class="assessment-random-settings"><label><input v-model="form.randomize_question_order" type="checkbox" /><span><strong>随机题目顺序</strong><small>每位学生使用不同题序，刷新后保持不变</small></span></label><label><input v-model="form.randomize_option_order" type="checkbox" /><span><strong>随机选项顺序</strong><small>单选、多选和判断题选项独立随机</small></span></label></div><div class="assessment-paper-items"><article v-for="(item, index) in paperItems" :key="item.question.id"><em>{{ index + 1 }}</em><div><span>{{ item.question.question_type_label }} · {{ item.question.knowledge_point || '未设置知识点' }}</span><strong>{{ item.question.stem }}</strong></div><label><span>分值</span><input v-model.number="item.score" type="number" min="0.5" max="100" step="0.5" /></label><div class="assessment-sort-actions"><button type="button" :disabled="index === 0" @click="moveQuestion(index, -1)">↑</button><button type="button" :disabled="index === paperItems.length - 1" @click="moveQuestion(index, 1)">↓</button><button type="button" @click="removeQuestion(item.question.id)">×</button></div></article><p v-if="!paperItems.length" class="empty">从左侧选择题目加入试卷。</p></div></section>
      </div>
      <footer class="modal-actions"><button class="secondary-button" type="button" @click="editorOpen = false">取消</button><button v-if="editorStep === 'info'" class="primary-button" type="button" :disabled="saving" @click="saveInfoAndCompose">保存并开始组卷</button><button v-else class="primary-button" type="button" :disabled="saving || !paperItems.length" @click="savePaper">保存试卷</button></footer>
    </section></div>

    <div v-if="resultsOpen" class="modal-backdrop" @click.self="resultsOpen = false"><section class="entity-modal assessment-results-modal"><header class="modal-header"><div><h2>{{ results?.assessment.title || '测试成绩' }}</h2><p>完成情况、答卷批阅和逐题统计。</p></div><div class="assessment-results-header-actions"><a v-if="results" class="secondary-button" :href="assessmentResultsExportUrl(results.assessment.id)">导出 XLSX</a><button class="icon-button" type="button" aria-label="关闭" @click="resultsOpen = false">×</button></div></header><div v-if="results" class="assessment-modal-body assessment-results-body"><section class="assessment-result-summary"><article><span>应考</span><strong>{{ results.summary.assigned_count }}</strong></article><article><span>已提交</span><strong>{{ results.summary.submitted_count }}</strong></article><article :class="{ attention: pendingGradeAttempts.length }"><span>待批阅</span><strong>{{ results.summary.pending_grade_count }}</strong></article><article><span>平均分</span><strong>{{ results.summary.average_score }}</strong></article></section><section v-if="pendingGradeAttempts.length" class="assessment-pending-queue"><header><div><strong>待批阅答卷</strong><span>优先处理主观题，批阅后计入最终成绩</span></div><b>{{ pendingGradeAttempts.length }} 份</b></header><div><button v-for="item in pendingGradeAttempts" :key="item.id" type="button" @click="openGrade(item)"><span><strong>{{ item.student.display_name }}</strong><small>{{ item.class_group.name }} · 已提交</small></span><em>开始批阅</em></button></div></section><div class="assessment-result-grid"><section><h3>学生成绩</h3><div class="assessment-table-wrap"><table class="assessment-table assessment-result-table"><thead><tr><th>学生</th><th>班级</th><th>状态</th><th>得分</th><th>答卷</th></tr></thead><tbody><tr v-for="item in results.attempts" :key="item.id"><td>{{ item.student.display_name }}</td><td>{{ item.class_group.name }}</td><td><span class="status-pill" :class="item.status === 'submitted' ? 'status-published' : 'status-closed'">{{ item.status_label }}</span></td><td>{{ item.total_score ?? '-' }}</td><td><button class="assessment-row-review" type="button" @click="openGrade(item)">{{ item.status === 'submitted' ? '批阅' : '查看答卷' }}</button></td></tr></tbody></table></div></section><section><h3>逐题表现</h3><div class="assessment-stat-list"><article v-for="(item, index) in results.question_stats" :key="item.question.id"><span>第 {{ index + 1 }} 题 · {{ item.question.question_type_label }}</span><strong>{{ item.question.stem }}</strong><div><b>{{ item.correct_rate }}%</b><i><em :style="{ width: `${item.correct_rate}%` }"></em></i><small>{{ item.correct_count }} / {{ item.answered_count }} 正确</small></div></article></div></section></div></div><p v-else class="empty">正在加载成绩</p><footer class="modal-actions"><button class="secondary-button" type="button" @click="resultsOpen = false">关闭</button></footer></section></div>

    <div v-if="gradeOpen && gradeAttempt" class="modal-backdrop"><section class="entity-modal assessment-grade-modal"><header class="modal-header assessment-grade-header"><div><h2>{{ gradeAttempt.student.display_name }}的答卷</h2><p>{{ gradeAttempt.class_group.name }} · {{ gradeAttempt.status_label }} · 当前 {{ gradeAttempt.total_score ?? 0 }} 分</p></div><button class="icon-button" type="button" aria-label="关闭" @click="gradeOpen = false">×</button></header><div class="assessment-grade-toolbar"><div class="assessment-grade-tabs"><button :class="{ active: gradeMode === 'subjective' }" type="button" :disabled="!subjectiveGradeAnswers.length" @click="gradeMode = 'subjective'">主观题 {{ subjectiveGradeAnswers.length }}</button><button :class="{ active: gradeMode === 'all' }" type="button" @click="gradeMode = 'all'">全部答题 {{ gradeAttempt.answers?.length || 0 }}</button></div><div v-if="subjectiveGradeAnswers.length" class="assessment-grade-progress"><span>已评 {{ completedSubjectiveCount }} / {{ subjectiveGradeAnswers.length }}</span><strong>主观题 {{ subjectiveScoreTotal }} 分</strong></div></div><div class="assessment-modal-body assessment-grade-list"><div v-if="gradeError" class="assessment-grade-error" role="alert">{{ gradeError }}</div><article v-for="(item, index) in visibleGradeAnswers" :key="item.id" :class="{ 'objective-answer': item.question.question_type !== 'text' }"><header><div><span>第 {{ index + 1 }} 题 · {{ item.question.question_type_label }}</span><small v-if="item.question.knowledge_point">{{ item.question.knowledge_point }}</small></div><b>{{ item.question.score }} 分</b></header><h3>{{ item.question.stem }}</h3><section class="assessment-answer-comparison"><div><span>学生答案</span><p :class="{ empty: !item.answer.length }">{{ item.answer.join('、') || '未作答' }}</p></div><div v-if="item.question.answer?.length || item.question.analysis"><span>{{ item.question.question_type === 'text' ? '评分参考' : '参考答案' }}</span><p>{{ item.question.answer?.join('、') || item.question.analysis || '未设置' }}</p><small v-if="item.question.answer?.length && item.question.analysis">{{ item.question.analysis }}</small></div></section><section v-if="item.question.question_type === 'text'" class="assessment-grade-fields"><label><span>本题得分</span><div class="assessment-score-control"><input v-model.number="gradeDrafts[item.id].score" type="number" min="0" :max="item.question.score" step="0.5" @input="markGrade(item.id)" /><small>/ {{ item.question.score }}</small></div><div class="assessment-score-shortcuts"><button type="button" @click="setGradeScore(item.id, item.question.score)">满分</button><button type="button" @click="setGradeScore(item.id, 0)">零分</button></div></label><label><span>教师评语</span><textarea v-model.trim="gradeDrafts[item.id].feedback" rows="3" maxlength="1000" placeholder="填写改进建议或评价" @input="markGrade(item.id)"></textarea></label></section><footer v-else class="assessment-objective-result"><span :class="item.is_correct ? 'correct' : 'incorrect'">{{ item.is_correct ? '回答正确' : item.is_correct === false ? '回答错误' : '未自动判断' }}</span><strong>自动得分 {{ item.auto_score }} / {{ item.question.score }}</strong></footer></article><p v-if="!visibleGradeAnswers.length" class="empty">当前答卷没有需要人工评分的主观题。</p></div><footer class="modal-actions assessment-grade-actions"><div v-if="subjectiveGradeAnswers.length"><span>主观题批阅进度</span><strong>{{ completedSubjectiveCount }} / {{ subjectiveGradeAnswers.length }}</strong></div><button class="secondary-button" type="button" @click="gradeOpen = false">取消</button><button v-if="pendingGradeAttempts.length > 1 && gradeAttempt.status === 'submitted'" class="secondary-button" type="button" :disabled="saving" @click="saveGrade(true)">保存并批阅下一份</button><button class="primary-button" type="button" :disabled="saving" @click="saveGrade(false)">{{ saving ? '保存中' : gradeAttempt.status === 'submitted' ? '完成批阅' : '保存修改' }}</button></footer></section></div>
  </AppShell>
</template>
