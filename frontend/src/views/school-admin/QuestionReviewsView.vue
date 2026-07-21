<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ApiError } from '@/api/client'
import {
  archiveCommonQuestionSet,
  commonQuestionSetsExportUrl,
  createCommonQuestionSet,
  getCommonQuestionSets,
  getQuestionReviewDetail,
  getQuestionReviews,
  questionReviewsExportUrl,
  reviewQuestion,
  type BankQuestion,
  type BankQuestionSource,
  type BankQuestionStatus,
  type CommonQuestionSetRow
} from '@/api/assessments'
import { getSubjects, type SubjectRow } from '@/api/management'
import AppShell from '@/layouts/AppShell.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import { schoolAdminNav } from './nav'

const navItems = schoolAdminNav('/school-admin/question-reviews')
const loading = ref(false)
const reviewing = ref(false)
const notice = ref('')
const rows = ref<BankQuestion[]>([])
const subjects = ref<SubjectRow[]>([])
const count = ref(0)
const page = ref(1)
const pageSize = 30
const status = ref<BankQuestionStatus | ''>('pending_review')
const source = ref<BankQuestionSource | ''>('')
const subject = ref('')
const query = ref('')
const detail = ref<BankQuestion | null>(null)
const detailLoading = ref(false)
const noteAction = ref<'return' | 'disable' | null>(null)
const note = ref('')
const commonSetOpen = ref(false)
const commonSetSaving = ref(false)
const commonSets = ref<CommonQuestionSetRow[]>([])
const commonCandidates = ref<Array<{ question: BankQuestion; selected: boolean; comparison_code: string; required: boolean; anchor_source_id: number | null }>>([])
const commonSetForm = reactive({ subject: '', title: '', grade_scope: '', term: '', previous_version: null as number | null })

const statusTabs: Array<{ value: BankQuestionStatus | ''; label: string }> = [
  { value: 'pending_review', label: '待审核' },
  { value: 'trial', label: '可试用' },
  { value: 'active', label: '已启用' },
  { value: 'draft', label: '已退回' },
  { value: 'disabled', label: '已停用' },
  { value: '', label: '全部' }
]

const sources: Array<{ value: BankQuestionSource | ''; label: string }> = [
  { value: '', label: '全部来源' },
  { value: 'manual', label: '教师新建' },
  { value: 'xlsx', label: '表格导入' },
  { value: 'ai', label: 'AI 生成' },
  { value: 'copy', label: '复制修改' },
  { value: 'existing', label: '原有题目' }
]

const totalPages = computed(() => Math.max(1, Math.ceil(count.value / pageSize)))
const maxDistribution = computed(() => Math.max(1, ...(detail.value?.option_distribution || []).map((item) => item.count)))

function formatDate(value: string | null) {
  if (!value) return '-'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'
  }).format(new Date(value))
}

function adminStatusLabel(item: BankQuestion) {
  return item.status === 'draft' ? '已退回' : item.status_label
}

function selectStatus(value: BankQuestionStatus | '') {
  status.value = value
  page.value = 1
  loadRows()
}

async function loadRows() {
  loading.value = true
  try {
    const result = await getQuestionReviews({
      page: page.value,
      page_size: pageSize,
      status: status.value,
      source: source.value,
      subject: subject.value,
      q: query.value
    })
    rows.value = result.results
    count.value = result.count
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '题目审核列表加载失败。'
  } finally {
    loading.value = false
  }
}

async function openDetail(item: BankQuestion) {
  detail.value = item
  detailLoading.value = true
  try {
    detail.value = await getQuestionReviewDetail(item.id)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '题目详情加载失败。'
  } finally {
    detailLoading.value = false
  }
}

async function runDirectAction(action: 'approve_trial' | 'activate') {
  if (!detail.value) return
  const prompt = action === 'approve_trial'
    ? '确认审核通过并允许创建教师试用这道题？'
    : '确认正式启用并加入学校共享题库？'
  if (!window.confirm(prompt)) return
  reviewing.value = true
  try {
    detail.value = await reviewQuestion(detail.value.id, action)
    notice.value = action === 'approve_trial' ? '题目已通过审核，可以试用。' : '题目已正式启用。'
    await loadRows()
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '审核操作失败。'
  } finally {
    reviewing.value = false
  }
}

function openNoteAction(action: 'return' | 'disable') {
  noteAction.value = action
  note.value = ''
}

async function submitNoteAction() {
  if (!detail.value || !noteAction.value) return
  if (!note.value.trim()) {
    notice.value = noteAction.value === 'return' ? '请填写退回说明。' : '请填写停用原因。'
    return
  }
  reviewing.value = true
  try {
    detail.value = await reviewQuestion(detail.value.id, noteAction.value, note.value.trim())
    notice.value = noteAction.value === 'return' ? '题目已退回教师修改。' : '题目已停用。'
    noteAction.value = null
    note.value = ''
    await loadRows()
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '审核操作失败。'
  } finally {
    reviewing.value = false
  }
}

async function changePage(next: number) {
  if (next < 1 || next > totalPages.value || next === page.value) return
  page.value = next
  await loadRows()
}

async function loadCommonCandidates() {
  commonCandidates.value = []
  if (!commonSetForm.subject) return
  const result = await getQuestionReviews({
    page: 1,
    page_size: 200,
    status: 'active',
    subject: commonSetForm.subject
  })
  commonCandidates.value = result.results.map((question) => ({
    question,
    selected: false,
    comparison_code: question.comparison_code || '',
    required: true,
    anchor_source_id: null
  }))
}

async function openCommonSetManager() {
  commonSetOpen.value = true
  commonSetForm.subject = subject.value || String(subjects.value[0]?.id || '')
  commonSetForm.title = ''
  commonSetForm.grade_scope = ''
  commonSetForm.term = ''
  commonSetForm.previous_version = null
  try {
    commonSets.value = await getCommonQuestionSets()
    await loadCommonCandidates()
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '共同题集合加载失败。'
  }
}

async function saveCommonSet() {
  const selected = commonCandidates.value.filter((item) => item.selected)
  if (commonSetForm.title.trim().length < 2 || !selected.length) {
    notice.value = '请填写集合名称并选择共同题。'
    return
  }
  if (selected.some((item) => !item.comparison_code.trim())) {
    notice.value = '每道共同题都要填写比较编号。'
    return
  }
  commonSetSaving.value = true
  try {
    await createCommonQuestionSet({
      subject: commonSetForm.subject,
      title: commonSetForm.title.trim(),
      grade_scope: commonSetForm.grade_scope.trim(),
      term: commonSetForm.term.trim(),
      previous_version: commonSetForm.previous_version,
      items: selected.map((item) => ({
        question_id: item.question.id,
        comparison_code: item.comparison_code.trim().toUpperCase(),
        required: item.required,
        anchor_source_id: item.anchor_source_id
      }))
    })
    commonSets.value = await getCommonQuestionSets()
    notice.value = '共同题集合已发布。'
    await loadCommonCandidates()
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '共同题集合保存失败。'
  } finally {
    commonSetSaving.value = false
  }
}

async function prepareNextVersion(row: CommonQuestionSetRow) {
  commonSetForm.subject = String(row.subject.id)
  commonSetForm.title = `${row.title} 后续版`
  commonSetForm.grade_scope = row.grade_scope
  commonSetForm.term = row.term
  commonSetForm.previous_version = row.id
  await loadCommonCandidates()
  const sourceByQuestion = new Map(row.items.map((item) => [item.question_id, item]))
  for (const candidate of commonCandidates.value) {
    const sourceItem = sourceByQuestion.get(candidate.question.id)
    if (!sourceItem) continue
    candidate.selected = true
    candidate.comparison_code = sourceItem.comparison_code
    candidate.required = sourceItem.required
    candidate.anchor_source_id = sourceItem.id
  }
  notice.value = `已载入 v${row.version_no} 的题目。保持内容不变的题目将作为锚题，新题可继续勾选。`
}

async function archiveSet(row: CommonQuestionSetRow) {
  if (!window.confirm(`确认归档“${row.title}”版本 ${row.version_no}？`)) return
  try {
    await archiveCommonQuestionSet(row.id)
    commonSets.value = await getCommonQuestionSets()
    notice.value = '共同题集合已归档。'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '归档失败。'
  }
}

onMounted(async () => {
  try {
    subjects.value = await getSubjects()
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '学科列表加载失败。'
  }
  await loadRows()
})
</script>

<template>
  <AppShell title="题库审核" eyebrow="学校管理员" :nav-items="navItems">
    <NoticeLine v-if="notice" :message="notice" floating @dismiss="notice = ''" />

    <section class="question-review-head">
      <div>
        <h2>学校题库审核</h2>
        <p>教师负责出题和修改，学校管理员负责审核、试用确认和共享范围管理。</p>
      </div>
      <div class="heading-actions">
        <button class="primary-button" type="button" @click="openCommonSetManager">共同题集合</button>
        <a class="secondary-button" :href="questionReviewsExportUrl">导出 XLSX</a>
      </div>
    </section>

    <nav class="question-review-tabs" aria-label="题目状态">
      <button
        v-for="tab in statusTabs"
        :key="tab.value || 'all'"
        type="button"
        :class="{ active: status === tab.value }"
        @click="selectStatus(tab.value)"
      >
        {{ tab.label }}
      </button>
    </nav>

    <section class="question-review-filters">
      <input v-model.trim="query" aria-label="搜索题目" placeholder="搜索题干、知识点或教师" @keyup.enter="page = 1; loadRows()" />
      <AppSelect v-model="subject" aria-label="按学科筛选" @change="page = 1; loadRows()">
        <option value="">全部学科</option>
        <option v-for="item in subjects" :key="item.id" :value="item.id">{{ item.name }}</option>
      </AppSelect>
      <AppSelect v-model="source" aria-label="按来源筛选" @change="page = 1; loadRows()">
        <option v-for="item in sources" :key="item.value || 'all'" :value="item.value">{{ item.label }}</option>
      </AppSelect>
      <button class="secondary-button" type="button" :disabled="loading" @click="page = 1; loadRows()">查询</button>
    </section>

    <section class="question-review-table-wrap">
      <table class="question-review-table">
        <thead><tr><th>题目</th><th>教师</th><th>来源</th><th>状态</th><th>试用情况</th><th>更新时间</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="item in rows" :key="item.id">
            <td data-label="题目">
              <strong>{{ item.stem }}</strong>
              <small>{{ item.subject.name }} · {{ item.question_type_label }} · {{ item.difficulty_label }} · {{ item.default_score }} 分</small>
            </td>
            <td data-label="教师">{{ item.creator.display_name }}</td>
            <td data-label="来源">{{ item.source_label }}<small>版本 {{ item.version_no }}</small></td>
            <td data-label="状态"><span class="question-status-badge" :class="`question-status-${item.status}`">{{ adminStatusLabel(item) }}</span></td>
            <td data-label="试用情况"><span>{{ item.trial_response_count }} 人次</span><small>正确率 {{ item.trial_correct_rate === null ? '-' : `${item.trial_correct_rate}%` }}</small></td>
            <td data-label="更新时间">{{ formatDate(item.updated_at) }}</td>
            <td data-label="操作"><button class="assessment-row-review" type="button" @click="openDetail(item)">查看审核</button></td>
          </tr>
        </tbody>
      </table>
      <p v-if="loading" class="empty">正在加载题目</p>
      <p v-else-if="!rows.length" class="empty">当前没有符合条件的题目。</p>
    </section>

    <footer v-if="count > pageSize" class="question-review-pagination">
      <span>共 {{ count }} 道题</span>
      <div>
        <button type="button" :disabled="page <= 1" @click="changePage(page - 1)">上一页</button>
        <b>{{ page }} / {{ totalPages }}</b>
        <button type="button" :disabled="page >= totalPages" @click="changePage(page + 1)">下一页</button>
      </div>
    </footer>

    <div v-if="detail" class="modal-backdrop" role="presentation" @click.self="detail = null">
      <section class="entity-modal question-review-modal" role="dialog" aria-modal="true" aria-labelledby="question-review-title">
        <header class="modal-header">
          <div><h2 id="question-review-title">题目审核</h2><p>{{ detail.subject.name }} · {{ detail.creator.display_name }} · 版本 {{ detail.version_no }}</p></div>
          <button class="icon-button" type="button" aria-label="关闭" @click="detail = null">×</button>
        </header>
        <div class="question-review-modal-body">
          <main>
            <section class="question-review-content">
              <div class="question-review-content-head">
                <span class="question-status-badge" :class="`question-status-${detail.status}`">{{ adminStatusLabel(detail) }}</span>
                <span>{{ detail.source_label }}</span><span>{{ detail.question_type_label }}</span><span>{{ detail.difficulty_label }}</span><b>{{ detail.default_score }} 分</b>
              </div>
              <h3>{{ detail.stem }}</h3>
              <ol v-if="detail.options.length"><li v-for="(option, index) in detail.options" :key="option"><b>{{ String.fromCharCode(65 + index) }}</b><span>{{ option }}</span></li></ol>
              <dl>
                <div><dt>参考答案</dt><dd>{{ detail.answer.length ? detail.answer.join('、') : '主观题由教师批阅' }}</dd></div>
                <div><dt>答案解析</dt><dd>{{ detail.analysis || '未填写' }}</dd></div>
                <div><dt>知识点</dt><dd>{{ detail.knowledge_point || '未填写' }}</dd></div>
              </dl>
            </section>

            <section class="question-review-data">
              <header><strong>使用情况</strong><span>数据来自真实试卷与学生答卷</span></header>
              <div class="question-review-metrics">
                <article><span>组卷</span><strong>{{ detail.usage_count }}</strong><small>次</small></article>
                <article><span>总作答</span><strong>{{ detail.response_count }}</strong><small>人次</small></article>
                <article><span>试用作答</span><strong>{{ detail.trial_response_count }}</strong><small>人次</small></article>
                <article><span>试用正确率</span><strong>{{ detail.trial_correct_rate ?? '-' }}</strong><small>{{ detail.trial_correct_rate === null ? '' : '%' }}</small></article>
              </div>
              <div v-if="detail.option_distribution?.length" class="question-option-distribution">
                <div v-for="item in detail.option_distribution" :key="item.option">
                  <span>{{ item.option }}</span><i><em :style="{ width: `${item.count * 100 / maxDistribution}%` }"></em></i><b>{{ item.count }}</b>
                </div>
              </div>
            </section>
          </main>

          <aside>
            <section>
              <h3>审核记录</h3>
              <div v-if="detail.lifecycle?.length" class="question-lifecycle-list">
                <article v-for="item in detail.lifecycle" :key="item.id">
                  <span>{{ item.to_status_label }}</span><strong>{{ item.actor.display_name }}</strong><small>{{ formatDate(item.created_at) }}</small><p v-if="item.note">{{ item.note }}</p>
                </article>
              </div>
              <p v-else class="empty">暂无审核记录。</p>
            </section>
            <section>
              <h3>版本记录</h3>
              <div class="question-version-list">
                <article v-for="item in detail.versions" :key="item.id"><strong>版本 {{ item.version_no }}</strong><span>{{ item.source_label }} · {{ item.status_snapshot_label }}</span><small>{{ formatDate(item.created_at) }}</small></article>
              </div>
            </section>
          </aside>
        </div>
        <footer class="modal-actions question-review-actions">
          <span v-if="detail.status === 'trial' && detail.trial_response_count < 1">至少有 1 次试用作答后才能正式启用。</span>
          <div>
            <button class="secondary-button" type="button" @click="detail = null">关闭</button>
            <button v-if="['pending_review', 'trial'].includes(detail.status)" class="secondary-button danger" type="button" :disabled="reviewing" @click="openNoteAction('return')">退回修改</button>
            <button v-if="detail.status !== 'disabled'" class="secondary-button danger" type="button" :disabled="reviewing" @click="openNoteAction('disable')">停用</button>
            <button v-if="detail.status === 'pending_review'" class="primary-button" type="button" :disabled="reviewing" @click="runDirectAction('approve_trial')">通过并试用</button>
            <button v-if="detail.status === 'trial'" class="primary-button" type="button" :disabled="reviewing || detail.trial_response_count < 1" @click="runDirectAction('activate')">正式启用</button>
          </div>
        </footer>
        <div v-if="detailLoading" class="question-review-loading">正在加载完整记录</div>
      </section>
    </div>

    <div v-if="noteAction && detail" class="modal-backdrop modal-backdrop-nested" role="presentation" @click.self="noteAction = null">
      <section class="entity-modal compact-modal" role="dialog" aria-modal="true" aria-labelledby="question-review-note-title">
        <header class="modal-header">
          <div><h2 id="question-review-note-title">{{ noteAction === 'return' ? '退回题目' : '停用题目' }}</h2><p>{{ detail.stem }}</p></div>
          <button class="icon-button" type="button" aria-label="关闭" @click="noteAction = null">×</button>
        </header>
        <div class="question-review-note-form">
          <label><span>{{ noteAction === 'return' ? '修改说明' : '停用原因' }} <b class="required-mark">*</b></span><textarea v-model.trim="note" rows="5" maxlength="1000" placeholder="请填写明确原因，教师可在题目记录中查看。"></textarea></label>
        </div>
        <footer class="modal-actions"><button class="secondary-button" type="button" @click="noteAction = null">取消</button><button class="primary-button" type="button" :disabled="reviewing" @click="submitNoteAction">确认</button></footer>
      </section>
    </div>

    <div v-if="commonSetOpen" class="modal-backdrop" role="presentation" @click.self="commonSetOpen = false">
      <section class="entity-modal common-question-set-modal" role="dialog" aria-modal="true" aria-labelledby="common-set-title">
        <header class="modal-header">
          <div><h2 id="common-set-title">共同题集合</h2><p>共同题用于跨班级、跨学期和跨学校保持相同的比较基础。</p></div>
          <div class="heading-actions"><a class="secondary-button" :href="commonQuestionSetsExportUrl">导出 XLSX</a><button class="icon-button" type="button" aria-label="关闭" @click="commonSetOpen = false">×</button></div>
        </header>
        <div class="common-set-body">
          <section class="common-set-form">
            <div class="assessment-form-grid">
              <label><span>学科 <b class="required-mark">*</b></span><AppSelect v-model="commonSetForm.subject" @change="loadCommonCandidates"><option v-for="item in subjects" :key="item.id" :value="item.id">{{ item.name }}</option></AppSelect></label>
              <label><span>集合名称 <b class="required-mark">*</b></span><input v-model.trim="commonSetForm.title" maxlength="128" placeholder="例如 高一第一单元共同题" /></label>
              <label><span>年级范围</span><input v-model.trim="commonSetForm.grade_scope" maxlength="32" placeholder="例如 高一" /></label>
              <label><span>学期</span><input v-model.trim="commonSetForm.term" maxlength="32" placeholder="例如 第一学期" /></label>
            </div>
            <div v-if="commonSetForm.previous_version" class="common-version-note">
              <strong>正在准备后续版本</strong>
              <span>锚题必须保持题目内容和比较编号不变；发布后仍需真实作答数据才能进行版本比较。</span>
              <button type="button" @click="openCommonSetManager">取消继承</button>
            </div>
            <header class="common-candidate-head"><strong>选择已启用题目</strong><span>{{ commonCandidates.filter((item) => item.selected).length }} / {{ commonCandidates.length }}</span></header>
            <div class="common-candidate-list">
              <article v-for="item in commonCandidates" :key="item.question.id" :class="{ selected: item.selected }">
                <label class="common-candidate-select"><input v-model="item.selected" type="checkbox" /><span>{{ item.question.stem }}</span></label>
                <div><input v-model.trim="item.comparison_code" :disabled="!item.selected" maxlength="64" placeholder="比较编号，例如 IT-G10-U1-Q01" /><label><input v-model="item.required" :disabled="!item.selected" type="checkbox" />必备题</label></div>
                <small v-if="item.anchor_source_id" class="common-anchor-label">与上一版本内容一致 · 锚题</small>
              </article>
              <p v-if="!commonCandidates.length" class="empty">当前学科还没有已启用的共享题目。</p>
            </div>
          </section>
          <aside class="common-set-history">
            <h3>已发布版本</h3>
            <article v-for="item in commonSets.filter((row) => !commonSetForm.subject || row.subject.id === Number(commonSetForm.subject))" :key="item.id">
              <div><strong>{{ item.title }}</strong><span>v{{ item.version_no }} · {{ item.question_count }} 题</span></div>
              <small>{{ item.grade_scope || '全部年级' }} · {{ item.term || '未限定学期' }} · {{ item.status_label }}</small>
              <small>锚题 {{ item.readiness.anchor_count || 0 }} · 知识点 {{ item.readiness.knowledge_mapped_count || 0 }}/{{ item.question_count }}</small>
              <div class="common-set-row-actions">
                <button type="button" @click="prepareNextVersion(item)">准备下一版本</button>
                <button v-if="item.status === 'active'" type="button" @click="archiveSet(item)">归档</button>
              </div>
            </article>
            <p v-if="!commonSets.length" class="empty">暂无已发布集合。</p>
          </aside>
        </div>
        <footer class="modal-actions"><button class="secondary-button" type="button" @click="commonSetOpen = false">关闭</button><button class="primary-button" type="button" :disabled="commonSetSaving" @click="saveCommonSet">{{ commonSetSaving ? '发布中' : '发布新版本' }}</button></footer>
      </section>
    </div>
  </AppShell>
</template>
