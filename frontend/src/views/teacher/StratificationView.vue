<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ApiError } from '@/api/client'
import {
  getLearningSummaries,
  getStratificationOverview,
  getStratificationSuggestions,
  learningSummariesExportUrl,
  refreshLearningSummaries,
  reviewStratificationSuggestion,
  stratificationOverviewExportUrl,
  type LearningSummaryRow,
  type StratificationOverviewResponse,
  type StratificationSuggestionRow
} from '@/api/learningAnalytics'
import { getTeacherCourseOptions, type TeacherCourseOptions } from '@/api/teacher'
import LayerBadge from '@/components/teacher/LayerBadge.vue'
import AppShell from '@/layouts/AppShell.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import { teacherNav } from './nav'

type MainView = 'roster' | 'pending' | 'evidence' | 'history'
type ReviewAction = 'accept' | 'keep' | 'adjust' | 'defer'

const emptyOverview = (): StratificationOverviewResponse => ({
  scope: { class_group_ids: [], course: null },
  counts: { total: 0, A: 0, B: 0, C: 0, unassigned: 0, pending: 0 },
  class_distribution: [],
  rows: []
})

const navItems = teacherNav('/teacher/stratification')
const options = ref<TeacherCourseOptions | null>(null)
const overview = ref<StratificationOverviewResponse>(emptyOverview())
const suggestions = ref<StratificationSuggestionRow[]>([])
const summaries = ref<LearningSummaryRow[]>([])
const loading = ref(false)
const evidenceLoading = ref(false)
const evidenceLoaded = ref(false)
const refreshing = ref(false)
const reviewing = ref(false)
const notice = ref('')
const activeView = ref<MainView>('roster')
const classGroup = ref<number | string>('')
const course = ref<number | string>('')
const rosterQuery = ref('')
const layerFilter = ref<'all' | 'A' | 'B' | 'C' | 'unassigned'>('all')
const rosterPage = ref(1)
const suggestionPage = ref(1)
const evidencePage = ref(1)
const historyPage = ref(1)
const pageSize = 20
const windowType = ref<'day' | '7d' | '30d' | 'unit'>('7d')
const detail = ref<LearningSummaryRow | null>(null)
const reviewTarget = ref<StratificationSuggestionRow | null>(null)
const reviewForm = reactive<{ action: ReviewAction; layer: string; note: string }>({
  action: 'accept',
  layer: 'B',
  note: ''
})

const windowOptions = [
  { value: 'day', label: '当日' },
  { value: '7d', label: '近 7 日' },
  { value: '30d', label: '近 30 日' },
  { value: 'unit', label: '单元' }
] as const

const layerOptions = [
  { key: 'all', label: '全部', short: '总计' },
  { key: 'A', label: '拓展挑战层', short: 'A 层' },
  { key: 'B', label: '核心发展层', short: 'B 层' },
  { key: 'C', label: '基础提升层', short: 'C 层' },
  { key: 'unassigned', label: '未分层', short: '未分层' }
] as const

const visibleCourses = computed(() => options.value?.courses || [])
const layerStats = computed(() => layerOptions.map((item) => ({
  ...item,
  count: item.key === 'all' ? overview.value.counts.total : overview.value.counts[item.key]
})))
const filteredRoster = computed(() => {
  const keyword = rosterQuery.value.trim().toLowerCase()
  return overview.value.rows.filter((row) => {
    const matchesLayer = layerFilter.value === 'all'
      || (layerFilter.value === 'unassigned' ? !row.current_layer : row.current_layer === layerFilter.value)
    const searchable = `${row.student.display_name} ${row.student.username} ${row.student.student_no} ${row.class_group.name}`.toLowerCase()
    return matchesLayer && (!keyword || searchable.includes(keyword))
  })
})
const rosterPageCount = computed(() => Math.max(1, Math.ceil(filteredRoster.value.length / pageSize)))
const visibleRoster = computed(() => filteredRoster.value.slice((rosterPage.value - 1) * pageSize, rosterPage.value * pageSize))
const pendingSuggestions = computed(() => suggestions.value.filter((item) => item.status === 'pending'))
const historySuggestions = computed(() => {
  const latest = new Map<string, StratificationSuggestionRow>()
  const rows = suggestions.value
    .filter((item) => item.status !== 'pending')
    .slice()
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
  for (const row of rows) {
    const key = `${row.student.id}-${row.course?.id || 0}`
    if (!latest.has(key)) latest.set(key, row)
  }
  return Array.from(latest.values())
})
const suggestionPageCount = computed(() => Math.max(1, Math.ceil(pendingSuggestions.value.length / pageSize)))
const evidencePageCount = computed(() => Math.max(1, Math.ceil(summaries.value.length / pageSize)))
const historyPageCount = computed(() => Math.max(1, Math.ceil(historySuggestions.value.length / pageSize)))
const visiblePending = computed(() => pendingSuggestions.value.slice((suggestionPage.value - 1) * pageSize, suggestionPage.value * pageSize))
const visibleEvidence = computed(() => summaries.value.slice((evidencePage.value - 1) * pageSize, evidencePage.value * pageSize))
const visibleHistory = computed(() => historySuggestions.value.slice((historyPage.value - 1) * pageSize, historyPage.value * pageSize))
const availableRows = computed(() => summaries.value.filter((item) => item.data_status === 'available'))
const averageCompletion = computed(() => averageRate(summaries.value.map((item) => item.metrics.completion_rate)))
const averageScore = computed(() => averageRate(summaries.value.map((item) => item.metrics.score.score_rate)))
const overviewExportUrl = computed(() => stratificationOverviewExportUrl({ class_group: classGroup.value, course: course.value }))
const evidenceExportUrl = computed(() => learningSummariesExportUrl({ window: windowType.value, class_group: classGroup.value, course: course.value }))

function averageRate(values: Array<number | null>) {
  const available = values.filter((value): value is number => value !== null)
  return available.length ? Math.round(available.reduce((sum, value) => sum + value, 0) * 100 / available.length) : null
}

function percent(value: number | null | undefined) {
  return value === null || value === undefined ? '-' : `${Math.round(value * 100)}%`
}

function stars(value: number | null | undefined) {
  return value === null || value === undefined ? '-' : `${value.toFixed(1)} 星`
}

function formatDateTime(value: string | null) {
  if (!value) return '-'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '-' : parsed.toLocaleString('zh-CN', { hour12: false })
}

function dataStatusClass(value: string) {
  return `summary-status-${value}`
}

function decisionStatusClass(value: string) {
  return value === 'pending' ? 'summary-status-insufficient' : 'summary-status-available'
}

function layerPercent(layer: 'A' | 'B' | 'C' | 'unassigned') {
  const total = overview.value.counts.total || 1
  return `${(overview.value.counts[layer] / total) * 100}%`
}

async function loadCore() {
  loading.value = true
  notice.value = ''
  try {
    const params = { class_group: classGroup.value, course: course.value }
    const [overviewResult, suggestionResult] = await Promise.all([
      getStratificationOverview(params),
      getStratificationSuggestions(params)
    ])
    overview.value = overviewResult
    suggestions.value = suggestionResult
    rosterPage.value = 1
    suggestionPage.value = 1
    historyPage.value = 1
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '学生分层加载失败。'
  } finally {
    loading.value = false
  }
}

async function loadEvidence() {
  evidenceLoading.value = true
  try {
    const result = await getLearningSummaries({ window: windowType.value, class_group: classGroup.value, course: course.value })
    summaries.value = result.rows
    evidencePage.value = 1
    evidenceLoaded.value = true
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '学习依据加载失败。'
  } finally {
    evidenceLoading.value = false
  }
}

async function changeScope() {
  evidenceLoaded.value = false
  summaries.value = []
  await loadCore()
  if (activeView.value === 'evidence') await loadEvidence()
}

async function setView(view: MainView) {
  activeView.value = view
  if (view === 'evidence' && !evidenceLoaded.value) await loadEvidence()
}

function setLayerFilter(value: typeof layerFilter.value) {
  layerFilter.value = value
  rosterPage.value = 1
}

async function rebuild() {
  refreshing.value = true
  try {
    const result = await refreshLearningSummaries({ course: course.value })
    notice.value = `已更新 ${result.summaries} 份学习情况。`
    evidenceLoaded.value = false
    await loadCore()
    if (activeView.value === 'evidence') await loadEvidence()
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '学习情况更新失败。'
  } finally {
    refreshing.value = false
  }
}

function openReview(row: StratificationSuggestionRow) {
  reviewTarget.value = row
  reviewForm.action = row.status === 'pending' ? (row.suggested_layer ? 'accept' : 'defer') : 'defer'
  reviewForm.layer = row.suggested_layer || row.current_layer || 'B'
  reviewForm.note = row.review_note || ''
}

async function submitReview() {
  if (!reviewTarget.value) return
  reviewing.value = true
  try {
    await reviewStratificationSuggestion(reviewTarget.value.id, {
      action: reviewForm.action,
      layer: reviewForm.action === 'adjust' ? reviewForm.layer : undefined,
      note: reviewForm.note.trim()
    })
    notice.value = reviewForm.action === 'accept' || reviewForm.action === 'adjust'
      ? '分层已更新。'
      : '建议已处理。'
    reviewTarget.value = null
    await loadCore()
    if (!pendingSuggestions.value.length) activeView.value = 'roster'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '处理失败。'
  } finally {
    reviewing.value = false
  }
}

function changeRosterPage(delta: number) {
  rosterPage.value = Math.min(Math.max(rosterPage.value + delta, 1), rosterPageCount.value)
}

onMounted(async () => {
  try {
    options.value = await getTeacherCourseOptions()
    course.value = options.value.courses[0]?.id || ''
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '筛选条件加载失败。'
  }
  await loadCore()
})
</script>

<template>
  <AppShell title="学生分层" eyebrow="教师工作台" :nav-items="navItems">
    <NoticeLine v-if="notice" :message="notice" />

    <header class="stratification-page-heading">
      <div>
        <h2>学生分层</h2>
        <p>查看当前分层并处理本人课程的最新建议，分层结果仅教师可见。</p>
      </div>
      <a class="secondary-button" :href="overviewExportUrl">导出当前分层</a>
    </header>

    <section class="stratification-scope-bar" aria-label="分层范围">
      <label>
        <span>任教班级</span>
        <select v-model="classGroup" class="stratification-select" @change="changeScope">
          <option value="">全部任教班级</option>
          <option v-for="item in options?.classes" :key="item.id" :value="item.id">{{ item.name }}</option>
        </select>
      </label>
      <label>
        <span>课程</span>
        <select v-model="course" class="stratification-select" @change="changeScope">
          <option value="" disabled>请选择课程</option>
          <option v-for="item in visibleCourses" :key="item.id" :value="item.id">{{ item.title }}</option>
        </select>
      </label>
      <div class="scope-result">
        <span>当前范围</span>
        <strong>{{ overview.counts.total }} 名学生</strong>
      </div>
    </section>

    <nav class="stratification-tabs" aria-label="学生分层视图">
      <button type="button" :class="{ active: activeView === 'roster' }" @click="setView('roster')">当前分层</button>
      <button type="button" :class="{ active: activeView === 'pending' }" @click="setView('pending')">
        待处理建议 <span v-if="pendingSuggestions.length">{{ pendingSuggestions.length }}</span>
      </button>
      <button type="button" :class="{ active: activeView === 'evidence' }" @click="setView('evidence')">学习依据</button>
      <button type="button" :class="{ active: activeView === 'history' }" @click="setView('history')">处理记录</button>
    </nav>

    <template v-if="activeView === 'roster'">
      <section class="panel layer-overview-panel">
        <header>
          <div><h3>当前分布</h3><p>点击层级可筛选下方学生。</p></div>
          <span>未分层 {{ overview.counts.unassigned }}</span>
        </header>
        <div class="layer-stat-grid">
          <button
            v-for="item in layerStats"
            :key="item.key"
            type="button"
            :class="[`stat-${item.key}`, { active: layerFilter === item.key }]"
            @click="setLayerFilter(item.key)"
          >
            <span>{{ item.short }}</span>
            <strong>{{ item.count }}</strong>
            <small>{{ item.label }}</small>
          </button>
        </div>
        <div class="layer-distribution" aria-label="当前层级分布">
          <span class="segment-A" :style="{ width: layerPercent('A') }" />
          <span class="segment-B" :style="{ width: layerPercent('B') }" />
          <span class="segment-C" :style="{ width: layerPercent('C') }" />
          <span class="segment-unassigned" :style="{ width: layerPercent('unassigned') }" />
        </div>
      </section>

      <section class="panel stratification-roster-panel">
        <header class="roster-panel-head">
          <div><h3>学生名单</h3><p>显示 {{ filteredRoster.length }} 名学生</p></div>
          <label class="roster-search">
            <span>搜索学生</span>
            <input v-model.trim="rosterQuery" type="search" placeholder="姓名、账号、学号或班级" @input="rosterPage = 1" />
          </label>
        </header>
        <div class="assessment-table-wrap">
          <table class="assessment-table stratification-roster-table">
            <thead><tr><th>学生</th><th>班级</th><th>当前分层</th><th>近30日完成率</th><th>近30日得分率</th><th>最新建议</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="row in visibleRoster" :key="row.id">
                <td data-label="学生"><strong>{{ row.student.display_name }}</strong><small>{{ row.student.student_no || row.student.username }}</small></td>
                <td data-label="班级">{{ row.class_group.name }}</td>
                <td data-label="当前分层"><LayerBadge :layer="row.current_layer" :label="row.current_layer_label" /></td>
                <td data-label="近30日完成率">{{ percent(row.learning?.completion_rate) }}</td>
                <td data-label="近30日得分率">{{ percent(row.learning?.score_rate) }}</td>
                <td data-label="最新建议">
                  <template v-if="row.latest_decision">
                    <span class="decision-inline">
                      {{ row.latest_decision.suggested_layer ? `建议 ${row.latest_decision.suggested_layer}` : '暂不调整' }}
                      <small>{{ row.latest_decision.status_label }}</small>
                    </span>
                  </template>
                  <span v-else class="muted-text">暂无建议</span>
                </td>
                <td data-label="操作">
                  <button v-if="row.latest_decision" class="assessment-row-review" type="button" @click="openReview(row.latest_decision)">
                    {{ row.latest_decision.status === 'pending' ? '处理' : '查看' }}
                  </button>
                  <span v-else>-</span>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-if="loading" class="empty">正在加载学生分层</p>
          <p v-else-if="!visibleRoster.length" class="empty">当前筛选下没有学生。</p>
        </div>
        <footer v-if="rosterPageCount > 1" class="stratification-pagination">
          <button class="secondary-button" type="button" :disabled="rosterPage <= 1" @click="changeRosterPage(-1)">上一页</button>
          <span>第 {{ rosterPage }} / {{ rosterPageCount }} 页</span>
          <button class="secondary-button" type="button" :disabled="rosterPage >= rosterPageCount" @click="changeRosterPage(1)">下一页</button>
        </footer>
      </section>
    </template>

    <section v-else-if="activeView === 'pending'" class="panel suggestion-panel">
      <header class="suggestion-panel-head">
        <div><h3>待处理建议</h3><p>确认后才更新当前分层。</p></div>
        <strong>{{ pendingSuggestions.length }}</strong>
      </header>
      <div class="assessment-table-wrap">
        <table class="assessment-table suggestion-table">
          <thead><tr><th>学生</th><th>班级</th><th>当前</th><th>建议</th><th>参考强度</th><th>主要依据</th><th>教学支持</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="row in visiblePending" :key="row.id">
              <td data-label="学生"><strong>{{ row.student.display_name }}</strong><small>{{ row.student.student_no || row.student.username }}</small></td>
              <td data-label="班级">{{ row.class_group.name }}<small>{{ row.course?.title || '-' }}</small></td>
              <td data-label="当前"><LayerBadge :layer="row.current_layer" compact /></td>
              <td data-label="建议"><LayerBadge :layer="row.suggested_layer" compact /></td>
              <td data-label="参考强度">{{ row.suggested_layer ? `${Math.round(row.confidence * 100)}%` : '-' }}</td>
              <td data-label="主要依据"><span class="reason-text">{{ row.reasons[0] || '材料不足' }}</span></td>
              <td data-label="教学支持"><span class="support-text">{{ row.support_suggestion || '-' }}</span></td>
              <td data-label="操作"><button class="primary-table-action" type="button" @click="openReview(row)">处理</button></td>
            </tr>
          </tbody>
        </table>
        <p v-if="!loading && !pendingSuggestions.length" class="empty">当前没有待处理建议。</p>
      </div>
      <footer v-if="suggestionPageCount > 1" class="stratification-pagination">
        <button class="secondary-button" type="button" :disabled="suggestionPage <= 1" @click="suggestionPage -= 1">上一页</button>
        <span>第 {{ suggestionPage }} / {{ suggestionPageCount }} 页</span>
        <button class="secondary-button" type="button" :disabled="suggestionPage >= suggestionPageCount" @click="suggestionPage += 1">下一页</button>
      </footer>
    </section>

    <template v-else-if="activeView === 'evidence'">
      <section class="evidence-toolbar">
        <div class="learning-window-tabs" aria-label="学习依据范围">
          <button v-for="item in windowOptions" :key="item.value" type="button" :class="{ active: windowType === item.value }" @click="windowType = item.value; loadEvidence()">{{ item.label }}</button>
        </div>
        <div class="evidence-actions">
          <a class="secondary-button" :href="evidenceExportUrl">导出学习依据</a>
          <button class="primary-button" type="button" :disabled="refreshing" @click="rebuild">{{ refreshing ? '更新中' : '重新汇总' }}</button>
        </div>
      </section>
      <section class="evidence-summary-strip">
        <div><span>学生</span><strong>{{ summaries.length }}</strong></div>
        <div><span>材料可用</span><strong>{{ availableRows.length }}</strong></div>
        <div><span>平均完成率</span><strong>{{ averageCompletion === null ? '-' : `${averageCompletion}%` }}</strong></div>
        <div><span>平均得分率</span><strong>{{ averageScore === null ? '-' : `${averageScore}%` }}</strong></div>
      </section>
      <section class="panel learning-summary-table-panel">
        <div class="assessment-table-wrap">
          <table class="assessment-table learning-summary-table">
            <thead><tr><th>学生</th><th>班级</th><th>课程</th><th>材料状态</th><th>有效任务</th><th>完成率</th><th>得分率</th><th>资源学习</th><th>教师评价</th><th>详情</th></tr></thead>
            <tbody>
              <tr v-for="row in visibleEvidence" :key="row.id">
                <td data-label="学生"><strong>{{ row.student.display_name }}</strong><small>{{ row.student.student_no || row.student.username }}</small></td>
                <td data-label="班级">{{ row.student.class_group.name }}</td>
                <td data-label="课程"><strong>{{ row.course.title }}</strong><small>{{ row.subject.name }}</small></td>
                <td data-label="材料状态"><span class="summary-status-pill" :class="dataStatusClass(row.data_status)">{{ row.data_status_label }}</span></td>
                <td data-label="有效任务">{{ row.metrics.opportunities.eligible_count }}<small>分配 {{ row.metrics.opportunities.assigned_count }}</small></td>
                <td data-label="完成率">{{ percent(row.metrics.completion_rate) }}</td>
                <td data-label="得分率">{{ percent(row.metrics.score.score_rate) }}</td>
                <td data-label="资源学习">{{ row.metrics.resources.opened_count }} / {{ row.metrics.resources.assigned_count }}</td>
                <td data-label="教师评价">{{ stars(row.metrics.evaluation.teacher.average_stars) }}</td>
                <td data-label="详情"><button class="assessment-row-review" type="button" @click="detail = row">查看</button></td>
              </tr>
            </tbody>
          </table>
          <p v-if="evidenceLoading" class="empty">正在加载学习依据</p>
          <p v-else-if="!summaries.length" class="empty">当前范围还没有学习汇总。</p>
        </div>
        <footer v-if="evidencePageCount > 1" class="stratification-pagination">
          <button class="secondary-button" type="button" :disabled="evidencePage <= 1" @click="evidencePage -= 1">上一页</button>
          <span>第 {{ evidencePage }} / {{ evidencePageCount }} 页</span>
          <button class="secondary-button" type="button" :disabled="evidencePage >= evidencePageCount" @click="evidencePage += 1">下一页</button>
        </footer>
      </section>
    </template>

    <section v-else class="panel suggestion-panel history-panel">
      <header class="suggestion-panel-head">
        <div><h3>处理记录</h3><p>每名学生、每门课程只显示最新一条记录。</p></div>
        <strong>{{ historySuggestions.length }}</strong>
      </header>
      <div class="assessment-table-wrap">
        <table class="assessment-table history-table">
          <thead><tr><th>学生</th><th>班级 / 课程</th><th>原层级</th><th>模型建议</th><th>教师选择</th><th>处理结果</th><th>处理时间</th><th>详情</th></tr></thead>
          <tbody>
            <tr v-for="row in visibleHistory" :key="row.id">
              <td data-label="学生"><strong>{{ row.student.display_name }}</strong><small>{{ row.student.student_no || row.student.username }}</small></td>
              <td data-label="班级 / 课程">{{ row.class_group.name }}<small>{{ row.course?.title || '-' }}</small></td>
              <td data-label="原层级"><LayerBadge :layer="row.previous_layer" compact /></td>
              <td data-label="模型建议"><LayerBadge :layer="row.suggested_layer" compact /></td>
              <td data-label="教师选择"><LayerBadge :layer="row.teacher_selected_layer" compact /></td>
              <td data-label="处理结果"><span class="summary-status-pill" :class="decisionStatusClass(row.status)">{{ row.status_label }}</span></td>
              <td data-label="处理时间">{{ formatDateTime(row.reviewed_at) }}</td>
              <td data-label="详情"><button class="assessment-row-review" type="button" @click="openReview(row)">查看</button></td>
            </tr>
          </tbody>
        </table>
        <p v-if="!loading && !historySuggestions.length" class="empty">当前没有处理记录。</p>
      </div>
      <footer v-if="historyPageCount > 1" class="stratification-pagination">
        <button class="secondary-button" type="button" :disabled="historyPage <= 1" @click="historyPage -= 1">上一页</button>
        <span>第 {{ historyPage }} / {{ historyPageCount }} 页</span>
        <button class="secondary-button" type="button" :disabled="historyPage >= historyPageCount" @click="historyPage += 1">下一页</button>
      </footer>
    </section>

    <div v-if="detail" class="modal-backdrop" role="presentation" @click.self="detail = null">
      <section class="entity-modal learning-summary-detail" role="dialog" aria-modal="true" aria-labelledby="summary-detail-title">
        <header class="modal-header"><div><h2 id="summary-detail-title">{{ detail.student.display_name }}的学习依据</h2><p>{{ detail.window_type_label }} · {{ detail.course.title }} · {{ detail.student.class_group.name }}</p></div><button class="icon-button" type="button" aria-label="关闭" @click="detail = null">×</button></header>
        <div class="summary-detail-body">
          <dl class="summary-detail-grid">
            <div><dt>有效任务</dt><dd>{{ detail.metrics.opportunities.eligible_count }}</dd></div>
            <div><dt>已提交</dt><dd>{{ detail.metrics.opportunities.submitted_count }}</dd></div>
            <div><dt>已评分</dt><dd>{{ detail.metrics.score.graded_item_count }}</dd></div>
            <div><dt>按时提交</dt><dd>{{ percent(detail.metrics.on_time_rate) }}</dd></div>
            <div><dt>课堂互动</dt><dd>{{ detail.metrics.participation.interaction_count }}</dd></div>
            <div><dt>课堂积分变化</dt><dd>{{ detail.metrics.participation.point_delta }}</dd></div>
          </dl>
          <section class="summary-evaluation-grid">
            <article v-for="type in (['self', 'peer', 'teacher'] as const)" :key="type"><span>{{ { self: '自评', peer: '互评', teacher: '师评' }[type] }}</span><strong>{{ stars(detail.metrics.evaluation[type].average_stars) }}</strong><small>已评 {{ detail.metrics.evaluation[type].rated_item_count }} 项 · 暂不评价 {{ detail.metrics.evaluation[type].not_assessed_item_count }} 项</small></article>
          </section>
          <section v-if="detail.missing_data.length" class="summary-missing-list"><strong>需要补充</strong><ul><li v-for="item in detail.missing_data" :key="item">{{ item }}</li></ul></section>
        </div>
        <footer class="modal-actions"><button class="primary-button" type="button" @click="detail = null">关闭</button></footer>
      </section>
    </div>

    <div v-if="reviewTarget" class="modal-backdrop" role="presentation" @click.self="reviewTarget = null">
      <section class="entity-modal suggestion-review-modal" role="dialog" aria-modal="true" aria-labelledby="suggestion-review-title">
        <header class="modal-header"><div><h2 id="suggestion-review-title">{{ reviewTarget.status === 'pending' ? '处理分层建议' : '分层处理记录' }}</h2><p>{{ reviewTarget.student.display_name }} · {{ reviewTarget.course?.title }} · {{ reviewTarget.class_group.name }}</p></div><button class="icon-button" type="button" aria-label="关闭" @click="reviewTarget = null">×</button></header>
        <div class="suggestion-review-body">
          <div class="suggestion-layer-flow">
            <div><span>当前分层</span><LayerBadge :layer="reviewTarget.current_layer" :label="reviewTarget.current_layer_label" /></div>
            <strong aria-hidden="true">→</strong>
            <div><span>建议分层</span><LayerBadge :layer="reviewTarget.suggested_layer" /></div>
          </div>
          <section class="suggestion-evidence-block">
            <h3>主要依据</h3>
            <ul><li v-for="item in reviewTarget.reasons" :key="item">{{ item }}</li></ul>
          </section>
          <section class="suggestion-support-block"><h3>教学支持</h3><p>{{ reviewTarget.support_suggestion || '暂无具体建议。' }}</p></section>
          <template v-if="reviewTarget.status === 'pending'">
            <fieldset class="suggestion-actions"><legend>处理方式</legend><label><input v-model="reviewForm.action" type="radio" value="accept" :disabled="!reviewTarget.suggested_layer" />采纳建议</label><label><input v-model="reviewForm.action" type="radio" value="keep" />保持当前</label><label><input v-model="reviewForm.action" type="radio" value="adjust" />教师调整</label><label><input v-model="reviewForm.action" type="radio" value="defer" />暂缓处理</label></fieldset>
            <label v-if="reviewForm.action === 'adjust'" class="adjust-layer-field"><span>调整为</span><select v-model="reviewForm.layer" class="stratification-select"><option value="A">A · 拓展挑战层</option><option value="B">B · 核心发展层</option><option value="C">C · 基础提升层</option></select></label>
            <label class="review-note-field"><span>处理说明</span><textarea v-model.trim="reviewForm.note" rows="3" maxlength="1000" placeholder="可选，记录后续安排或观察重点" /></label>
          </template>
          <dl v-else class="suggestion-history-detail">
            <div><dt>处理结果</dt><dd>{{ reviewTarget.status_label }}</dd></div>
            <div><dt>教师选择</dt><dd>{{ reviewTarget.teacher_selected_layer || '未调整' }}</dd></div>
            <div><dt>处理教师</dt><dd>{{ reviewTarget.reviewed_by || '-' }}</dd></div>
            <div><dt>处理时间</dt><dd>{{ formatDateTime(reviewTarget.reviewed_at) }}</dd></div>
            <div class="wide"><dt>处理说明</dt><dd>{{ reviewTarget.review_note || '无' }}</dd></div>
          </dl>
        </div>
        <footer class="modal-actions">
          <button :class="reviewTarget.status === 'pending' ? 'secondary-button' : 'primary-button'" type="button" @click="reviewTarget = null">{{ reviewTarget.status === 'pending' ? '取消' : '关闭' }}</button>
          <button v-if="reviewTarget.status === 'pending'" class="primary-button" type="button" :disabled="reviewing" @click="submitReview">{{ reviewing ? '保存中' : '确认处理' }}</button>
        </footer>
      </section>
    </div>
  </AppShell>
</template>

<style scoped>
.stratification-page-heading,
.stratification-scope-bar,
.roster-panel-head,
.suggestion-panel-head,
.evidence-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.stratification-page-heading { margin-bottom: 14px; }
.stratification-page-heading h2,
.roster-panel-head h3,
.suggestion-panel-head h3,
.layer-overview-panel h3 { margin: 0; }
.stratification-page-heading h2 { font-size: 22px; }
.stratification-page-heading p,
.roster-panel-head p,
.suggestion-panel-head p,
.layer-overview-panel p { margin: 4px 0 0; color: var(--muted); font-size: 13px; }

.stratification-scope-bar {
  justify-content: flex-start;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fff;
  padding: 12px 14px;
}
.stratification-scope-bar label { display: grid; gap: 5px; width: min(260px, 100%); min-width: 0; }
.stratification-scope-bar label span,
.roster-search span,
.adjust-layer-field > span,
.review-note-field > span { color: var(--muted); font-size: 12px; font-weight: 700; }
.stratification-select,
.roster-search input,
.review-note-field textarea {
  width: 100%;
  min-height: 42px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fff;
  color: var(--ink);
  padding: 9px 11px;
  font: inherit;
  transition: border-color 160ms ease-out, box-shadow 160ms ease-out;
}
.stratification-select { color-scheme: light; cursor: pointer; }
.stratification-select option { background: #fff; color: var(--ink); }
.stratification-select:hover,
.roster-search input:hover,
.review-note-field textarea:hover { border-color: #aebed0; }
.stratification-select:focus,
.roster-search input:focus,
.review-note-field textarea:focus {
  border-color: var(--primary);
  outline: 3px solid rgba(37, 99, 235, 0.14);
}
.review-note-field textarea { min-height: 96px; line-height: 1.55; resize: vertical; }
.scope-result { margin-left: auto; text-align: right; }
.scope-result span, .scope-result strong { display: block; }
.scope-result span { color: var(--muted); font-size: 12px; }
.scope-result strong { margin-top: 4px; font-size: 17px; }

.stratification-tabs {
  display: flex;
  gap: 2px;
  margin: 14px 0;
  border-bottom: 1px solid #cfd9e6;
}
.stratification-tabs button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-height: 44px;
  border: 0;
  border-bottom: 3px solid transparent;
  background: transparent;
  padding: 0 18px;
  color: #526174;
  font-weight: 700;
  cursor: pointer;
}
.stratification-tabs button.active { border-bottom-color: #1f6feb; color: #1557a6; }
.stratification-tabs button span { min-width: 22px; border-radius: 10px; background: #b42318; padding: 2px 6px; color: #fff; font-size: 11px; }

.layer-overview-panel { margin-bottom: 14px; padding: 0; overflow: hidden; }
.layer-overview-panel > header { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 16px; border-bottom: 1px solid var(--line); }
.layer-overview-panel > header > span { color: var(--muted); font-size: 13px; }
.layer-stat-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); }
.layer-stat-grid button {
  min-width: 0;
  min-height: 92px;
  border: 0;
  border-right: 1px solid var(--line);
  background: #fff;
  padding: 13px 15px;
  text-align: left;
  cursor: pointer;
}
.layer-stat-grid button:last-child { border-right: 0; }
.layer-stat-grid button:hover, .layer-stat-grid button.active { background: #f5f9fd; box-shadow: inset 0 -3px #1f6feb; }
.layer-stat-grid span, .layer-stat-grid strong, .layer-stat-grid small { display: block; }
.layer-stat-grid span, .layer-stat-grid small { color: var(--muted); }
.layer-stat-grid span { font-size: 12px; font-weight: 700; }
.layer-stat-grid strong { margin: 5px 0 2px; font-size: 25px; font-variant-numeric: tabular-nums; }
.layer-stat-grid small { font-size: 12px; overflow-wrap: anywhere; }
.layer-distribution { display: flex; width: 100%; height: 8px; background: #e2e8f0; }
.layer-distribution span { display: block; min-width: 0; transition: width 180ms ease-out; }
.segment-A { background: #0f766e; }
.segment-B { background: #2563a9; }
.segment-C { background: #b7791f; }
.segment-unassigned { background: #94a3b8; }

.stratification-roster-panel, .suggestion-panel, .learning-summary-table-panel { min-width: 0; padding: 0; overflow: hidden; }
.roster-panel-head, .suggestion-panel-head { border-bottom: 1px solid var(--line); padding: 14px 16px; }
.roster-search { display: grid; gap: 5px; width: min(300px, 100%); min-width: 0; }
.suggestion-panel-head > strong { font-size: 24px; font-variant-numeric: tabular-nums; }
.assessment-table-wrap { width: 100%; min-width: 0; overflow-x: hidden; }
.stratification-roster-table, .suggestion-table, .history-table, .learning-summary-table { width: 100%; min-width: 0; table-layout: fixed; }
.stratification-roster-table th,
.stratification-roster-table td,
.suggestion-table th,
.suggestion-table td,
.history-table th,
.history-table td,
.learning-summary-table th,
.learning-summary-table td { min-width: 0; vertical-align: middle; white-space: normal; overflow-wrap: anywhere; word-break: break-word; }
.assessment-table td:first-child { min-width: 0; }
.stratification-roster-table th:nth-child(1) { width: 15%; }
.stratification-roster-table th:nth-child(2) { width: 17%; }
.stratification-roster-table th:nth-child(3) { width: 17%; }
.stratification-roster-table th:nth-child(4), .stratification-roster-table th:nth-child(5) { width: 11%; }
.stratification-roster-table th:nth-child(6) { width: 18%; }
.stratification-roster-table th:nth-child(7) { width: 11%; }
.suggestion-table th:nth-child(1) { width: 12%; }
.suggestion-table th:nth-child(2) { width: 13%; }
.suggestion-table th:nth-child(3), .suggestion-table th:nth-child(4) { width: 7%; }
.suggestion-table th:nth-child(5) { width: 9%; }
.suggestion-table th:nth-child(6) { width: 18%; }
.suggestion-table th:nth-child(7) { width: 25%; }
.suggestion-table th:nth-child(8) { width: 9%; }
.history-table th:nth-child(1) { width: 13%; }
.history-table th:nth-child(2) { width: 20%; }
.history-table th:nth-child(3),
.history-table th:nth-child(4),
.history-table th:nth-child(5) { width: 10%; }
.history-table th:nth-child(6) { width: 12%; }
.history-table th:nth-child(7) { width: 15%; }
.history-table th:nth-child(8) { width: 10%; }
.learning-summary-table th:nth-child(1) { width: 12%; }
.learning-summary-table th:nth-child(2) { width: 11%; }
.learning-summary-table th:nth-child(3) { width: 13%; }
.learning-summary-table th:nth-child(4) { width: 11%; }
.learning-summary-table th:nth-child(5),
.learning-summary-table th:nth-child(6),
.learning-summary-table th:nth-child(7),
.learning-summary-table th:nth-child(8),
.learning-summary-table th:nth-child(9) { width: 8%; }
.learning-summary-table th:nth-child(10) { width: 12%; }
.assessment-table td { overflow-wrap: anywhere; }
.assessment-table td strong, .assessment-table td small { display: block; }
.assessment-table td small { margin-top: 3px; color: var(--muted); font-size: 12px; }
.decision-inline { display: block; font-weight: 700; }
.muted-text { color: var(--muted); }
.primary-table-action, .assessment-row-review { max-width: 100%; min-height: 36px; border-radius: 4px; padding: 0 11px; font-weight: 700; white-space: nowrap; cursor: pointer; }
.primary-table-action { border: 1px solid #1f6feb; background: #1f6feb; color: #fff; }
.assessment-row-review { border: 1px solid #b9c8da; background: #fff; color: #24527d; }
.reason-text, .support-text { display: block; max-width: 100%; line-height: 1.5; overflow-wrap: anywhere; word-break: break-word; }
.summary-status-pill { display: inline-flex; align-items: center; min-height: 28px; border-radius: 4px; padding: 0 9px; font-size: 12px; font-weight: 700; white-space: nowrap; }
.summary-status-available { background: #e8f7ef; color: #17633a; }
.summary-status-insufficient { background: #fff4dd; color: #8a4b08; }
.summary-status-no_opportunity { background: #eef2f7; color: #475569; }
.summary-status-quality_blocked { background: #fdeaea; color: #9f2626; }
.stratification-pagination { display: flex; align-items: center; justify-content: flex-end; gap: 12px; border-top: 1px solid var(--line); padding: 11px 14px; }
.stratification-pagination span { color: var(--muted); font-size: 13px; font-variant-numeric: tabular-nums; }

.evidence-toolbar { margin-bottom: 12px; }
.learning-window-tabs, .evidence-actions { display: flex; gap: 6px; }
.learning-window-tabs button { min-height: 40px; border: 1px solid #d6e0ec; background: #fff; padding: 0 15px; color: #475569; font-weight: 700; cursor: pointer; }
.learning-window-tabs button.active { border-color: #79aee8; background: #eaf3ff; color: #1557a6; }
.evidence-summary-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); margin-bottom: 12px; border: 1px solid var(--line); border-radius: 6px; background: #fff; overflow: hidden; }
.evidence-summary-strip div { border-right: 1px solid var(--line); padding: 13px 16px; }
.evidence-summary-strip div:last-child { border-right: 0; }
.evidence-summary-strip span, .evidence-summary-strip strong { display: block; }
.evidence-summary-strip span { color: var(--muted); font-size: 12px; }
.evidence-summary-strip strong { margin-top: 5px; font-size: 22px; font-variant-numeric: tabular-nums; }

.learning-summary-detail { width: min(780px, calc(100vw - 24px)); }
.suggestion-review-modal { width: min(700px, calc(100vw - 24px)); }
.summary-detail-body, .suggestion-review-body { padding: 18px; overflow-y: auto; }
.summary-detail-grid, .suggestion-history-detail { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1px; margin: 0; border: 1px solid var(--line); background: var(--line); }
.summary-detail-grid div, .suggestion-history-detail div { padding: 13px; background: #fff; }
.summary-detail-grid dt, .suggestion-history-detail dt { color: var(--muted); font-size: 12px; }
.summary-detail-grid dd, .suggestion-history-detail dd { margin: 5px 0 0; font-weight: 700; }
.summary-evaluation-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
.summary-evaluation-grid article { border: 1px solid var(--line); border-radius: 6px; padding: 13px; }
.summary-evaluation-grid span, .summary-evaluation-grid strong, .summary-evaluation-grid small { display: block; }
.summary-evaluation-grid strong { margin: 5px 0; }
.summary-evaluation-grid small { color: var(--muted); line-height: 1.5; }
.summary-missing-list { margin-top: 14px; border-left: 3px solid #b7791f; background: #fff8e9; padding: 12px 14px; }
.suggestion-layer-flow { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 14px; border: 1px solid var(--line); background: #f8fafc; padding: 14px; }
.suggestion-layer-flow > div { display: grid; gap: 7px; }
.suggestion-layer-flow > div > span { color: var(--muted); font-size: 12px; font-weight: 700; }
.suggestion-layer-flow > strong { color: #64748b; font-size: 22px; }
.suggestion-evidence-block, .suggestion-support-block { margin-top: 14px; border: 1px solid var(--line); padding: 13px 14px; }
.suggestion-evidence-block h3, .suggestion-support-block h3 { margin: 0; font-size: 14px; }
.suggestion-evidence-block ul { margin: 8px 0 0; padding-left: 20px; line-height: 1.65; }
.suggestion-support-block { border-left: 3px solid #1f6feb; background: #f7fbff; }
.suggestion-support-block p { margin: 7px 0 0; line-height: 1.65; }
.suggestion-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin: 14px 0 0; border: 0; padding: 0; }
.suggestion-actions legend { grid-column: 1 / -1; margin-bottom: 2px; padding: 0; color: var(--muted); font-size: 12px; font-weight: 700; }
.suggestion-actions label {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
  min-height: 44px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fff;
  padding: 9px 12px;
  color: #334155;
  font-weight: 700;
  cursor: pointer;
  transition: border-color 160ms ease-out, background-color 160ms ease-out, box-shadow 160ms ease-out;
}
.suggestion-actions label:hover { border-color: #8db4df; background: #f7fbff; }
.suggestion-actions label:has(input:checked) { border-color: #5696da; background: #eaf3ff; color: #1557a6; box-shadow: inset 0 0 0 1px #9bc0e9; }
.suggestion-actions label:has(input:focus-visible) { outline: 3px solid rgba(37, 99, 235, 0.14); outline-offset: 1px; }
.suggestion-actions label:has(input:disabled) { background: #f3f5f8; color: #94a3b8; cursor: not-allowed; }
.suggestion-actions input { width: 18px; height: 18px; margin: 0; accent-color: var(--primary); flex: 0 0 auto; }
.adjust-layer-field, .review-note-field { display: grid; gap: 6px; margin-top: 12px; }
.suggestion-history-detail { grid-template-columns: repeat(2, minmax(0, 1fr)); margin-top: 14px; }
.suggestion-history-detail .wide { grid-column: 1 / -1; }

@media (max-width: 1280px) {
  .stratification-roster-table,
  .suggestion-table,
  .history-table,
  .learning-summary-table,
  .stratification-roster-table tbody,
  .suggestion-table tbody,
  .history-table tbody,
  .learning-summary-table tbody,
  .stratification-roster-table tr,
  .suggestion-table tr,
  .history-table tr,
  .learning-summary-table tr,
  .stratification-roster-table td,
  .suggestion-table td,
  .history-table td,
  .learning-summary-table td { display: block; width: 100%; min-width: 0; }
  .stratification-roster-table thead, .suggestion-table thead, .history-table thead, .learning-summary-table thead { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
  .stratification-roster-table tbody, .suggestion-table tbody, .history-table tbody, .learning-summary-table tbody { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; padding: 10px; }
  .stratification-roster-table tr, .suggestion-table tr, .history-table tr, .learning-summary-table tr { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 12px; border: 1px solid var(--line); border-radius: 6px; background: #fff; padding: 10px; }
  .assessment-table td { max-width: none; border: 0; padding: 7px 4px; }
  .assessment-table td::before { content: attr(data-label); display: block; margin-bottom: 4px; color: var(--muted); font-size: 12px; font-weight: 700; }
  .assessment-table td:first-child, .assessment-table td:nth-last-child(2), .assessment-table td:last-child { grid-column: 1 / -1; }
  .stratification-roster-table td:nth-child(2), .stratification-roster-table td:nth-child(3) { grid-column: 1 / -1; }
  .assessment-table td:last-child button { width: 100%; min-height: 42px; }
}

@media (max-width: 820px) {
  .stratification-page-heading, .stratification-scope-bar, .roster-panel-head, .evidence-toolbar { align-items: stretch; flex-direction: column; }
  .stratification-page-heading > a, .stratification-scope-bar label, .roster-search { width: 100%; }
  .scope-result { margin-left: 0; text-align: left; }
  .stratification-tabs { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0; overflow: visible; border: 1px solid var(--line); background: #fff; }
  .stratification-tabs button { min-width: 0; border-bottom: 3px solid transparent; padding: 0 8px; }
  .layer-stat-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .layer-stat-grid button { border-bottom: 1px solid var(--line); }
  .layer-stat-grid button:nth-child(even) { border-right: 0; }
  .layer-stat-grid button:first-child { grid-column: 1 / -1; }
  .evidence-summary-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .evidence-summary-strip div:nth-child(2) { border-right: 0; }
  .evidence-summary-strip div:nth-child(-n+2) { border-bottom: 1px solid var(--line); }
  .evidence-actions > *, .learning-window-tabs button { min-height: 44px; }
}

@media (max-width: 620px) {
  .layer-stat-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .layer-stat-grid button, .layer-stat-grid button:first-child { grid-column: auto; min-height: 76px; padding: 9px; }
  .layer-stat-grid button:nth-child(even) { border-right: 1px solid var(--line); }
  .layer-stat-grid button:nth-child(3n) { border-right: 0; }
  .layer-stat-grid strong { font-size: 21px; }
  .stratification-roster-table tbody, .suggestion-table tbody, .history-table tbody, .learning-summary-table tbody { grid-template-columns: 1fr; }
  .stratification-roster-table tr, .suggestion-table tr, .history-table tr, .learning-summary-table tr { grid-template-columns: 1fr; }
  .assessment-table td, .assessment-table td:first-child, .assessment-table td:nth-last-child(2), .assessment-table td:last-child { grid-column: auto; }
  .learning-window-tabs, .evidence-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); width: 100%; overflow: visible; }
  .evidence-actions > * { width: 100%; min-width: 0; }
  .stratification-pagination { justify-content: space-between; }
  .summary-detail-grid, .summary-evaluation-grid, .suggestion-history-detail { grid-template-columns: 1fr; }
  .suggestion-history-detail .wide { grid-column: auto; }
  .suggestion-layer-flow { grid-template-columns: 1fr; }
  .suggestion-layer-flow > strong { transform: rotate(90deg); text-align: center; }
  .suggestion-actions { grid-template-columns: 1fr; }
}

@media (prefers-reduced-motion: reduce) {
  .layer-distribution span { transition: none; }
}
</style>
