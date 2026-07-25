<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ApiError } from '@/api/client'
import {
  bulkReviewStratificationSuggestions,
  getLearningSummaries,
  getStratificationOverview,
  getStratificationSuggestions,
  learningSummariesExportUrl,
  manuallyAdjustStratification,
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
import MultiSelectActions from '@/components/MultiSelectActions.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import { usePageSelection } from '@/composables/usePageSelection'
import { vModalFocus } from '@/directives/modalFocus'
import { teacherNav } from './nav'

type MainView = 'roster' | 'pending' | 'evidence' | 'history'
type ReviewAction = 'accept' | 'keep' | 'adjust' | 'defer'
type BulkReviewAction = 'accept' | 'keep' | 'defer'
type ManualAdjustmentTarget = {
  source_decision_id: number
  student: StratificationSuggestionRow['student']
  class_group: StratificationSuggestionRow['class_group']
  current_layer: string
  course: { id: number; title: string } | null
}

const emptyOverview = (): StratificationOverviewResponse => ({
  scope: { class_group_ids: [], course: null },
  counts: { total: 0, A: 0, B: 0, C: 0, unassigned: 0, pending: 0 },
  class_distribution: [],
  rows: []
})

const navItems = teacherNav('/teacher/stratification')
const route = useRoute()
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
const requestedView = String(route.query.view || '')
const activeView = ref<MainView>(
  ['roster', 'pending', 'evidence', 'history'].includes(requestedView)
    ? requestedView as MainView
    : 'roster'
)
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
const batchReviewOpen = ref(false)
const batchReviewScope = ref<'selected' | 'all'>('selected')
const manualTarget = ref<ManualAdjustmentTarget | null>(null)
const reviewForm = reactive<{ action: ReviewAction; layer: string; reason_code: string; note: string }>({
  action: 'accept',
  layer: 'B',
  reason_code: '',
  note: ''
})
const batchReviewForm = reactive<{ action: BulkReviewAction; reason_code: string; note: string }>({
  action: 'accept',
  reason_code: '',
  note: ''
})
const manualForm = reactive<{ layer: 'A' | 'B' | 'C'; reason_code: string; note: string }>({
  layer: 'B',
  reason_code: '',
  note: ''
})

const manualReasonOptions = [
  { value: 'classroom_evidence', label: '课堂表现或作品提供了补充依据' },
  { value: 'recent_change', label: '学生近期状态发生变化' },
  { value: 'support_plan', label: '已有明确的教学支持安排' },
  { value: 'task_mismatch', label: '当前任务难度或学习机会不匹配' },
  { value: 'data_issue', label: '平台材料缺失或记录需要核查' },
  { value: 'other', label: '其他经教师核实的原因' }
]

const windowOptions = [
  { value: 'day', label: '当日' },
  { value: '7d', label: '近 7 日' },
  { value: '30d', label: '近 30 日' },
  { value: 'unit', label: '单元' }
] as const

const layerOptions = [
  { key: 'all', label: '全部', short: '总计' },
  { key: 'A', label: '拓展挑战内容', short: '拓展（A）' },
  { key: 'B', label: '核心发展内容', short: '发展（B）' },
  { key: 'C', label: '基础提升内容', short: '提升（C）' },
  { key: 'unassigned', label: '尚未安排', short: '尚未安排' }
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
const pendingSupportCount = computed(() => pendingSuggestions.value.filter((item) => item.decision_kind === 'support').length)
const pendingContentBandCount = computed(() => pendingSuggestions.value.filter((item) => item.decision_kind === 'content_band').length)
const pendingDescription = computed(() => {
  if (pendingSupportCount.value && pendingContentBandCount.value) {
    return `含 ${pendingContentBandCount.value} 条学习内容安排建议和 ${pendingSupportCount.value} 条学习支持建议；两类建议都须由教师结合材料确认。`
  }
  if (pendingSupportCount.value) return '处理结果用于安排教学支持，不会改变当前学习内容安排。'
  if (pendingContentBandCount.value) return '教师查看目标级材料并确认后，才更新学习内容安排。'
  return '当前没有需要处理的建议。'
})
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
const {
  selectedIds: selectedSuggestionIds,
  selectedIdSet: selectedSuggestionIdSet,
  selectedCount: selectedSuggestionCount,
  allPageSelected: allSuggestionPageSelected,
  partiallyPageSelected: partiallySuggestionPageSelected,
  toggleRow: toggleSuggestion,
  togglePage: toggleSuggestionPage,
  clearSelection: clearSuggestionSelection
} = usePageSelection(visiblePending)
const selectedPendingRows = computed(() => pendingSuggestions.value.filter((row) => selectedSuggestionIdSet.value.has(row.id)))
const batchReviewRows = computed(() => batchReviewScope.value === 'all' ? pendingSuggestions.value : selectedPendingRows.value)
const batchReviewCount = computed(() => batchReviewRows.value.length)
const batchSupportCount = computed(() => batchReviewRows.value.filter((row) => row.decision_kind === 'support').length)
const batchContentBandCount = computed(() => batchReviewRows.value.filter((row) => row.decision_kind === 'content_band').length)
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

function supportPriorityLabel(value: StratificationSuggestionRow['support_priority']) {
  if (!value) return '学习支持'
  return {
    routine: '常规关注',
    watch: '持续关注',
    high: '优先支持'
  }[value]
}

function suggestionLabel(row: StratificationSuggestionRow) {
  if (row.decision_kind === 'support') return supportPriorityLabel(row.support_priority)
  return row.suggested_layer ? `建议 ${row.suggested_layer} 层` : '暂不建议'
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
    const availablePendingIds = new Set(suggestionResult.filter((item) => item.status === 'pending').map((item) => item.id))
    selectedSuggestionIds.value = selectedSuggestionIds.value.filter((id) => availablePendingIds.has(id))
    rosterPage.value = 1
    suggestionPage.value = 1
    historyPage.value = 1
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '学习内容安排加载失败。'
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
  reviewForm.reason_code = row.review_reason_code || ''
  reviewForm.note = row.review_note || ''
}

function openManualAdjustment(target: StratificationSuggestionRow) {
  if (!target.course || target.decision_kind !== 'content_band' || !target.target_states.length) {
    notice.value = '该记录没有可沿用的目标级学习依据，暂不能再次调整。'
    return
  }
  reviewTarget.value = null
  manualTarget.value = {
    source_decision_id: target.id,
    student: target.student,
    class_group: target.class_group,
    current_layer: target.current_layer,
    course: target.course
  }
  manualForm.layer = (target.current_layer as 'A' | 'B' | 'C') || 'B'
  manualForm.reason_code = ''
  manualForm.note = ''
}

function closeBatchReview() {
  if (!reviewing.value) batchReviewOpen.value = false
}

function closeReview() {
  if (!reviewing.value) reviewTarget.value = null
}

function closeDetail() {
  detail.value = null
}

function closeManualAdjustment() {
  if (!reviewing.value) manualTarget.value = null
}

async function submitReview() {
  if (!reviewTarget.value) return
  reviewing.value = true
  try {
    await reviewStratificationSuggestion(reviewTarget.value.id, {
      action: reviewForm.action,
      layer: reviewForm.action === 'adjust' ? reviewForm.layer : undefined,
      reason_code: reviewForm.action === 'accept' ? undefined : reviewForm.reason_code,
      note: reviewForm.note.trim()
    })
    const successMessage = reviewTarget.value.decision_kind === 'content_band'
      && (reviewForm.action === 'accept' || reviewForm.action === 'adjust')
      ? '学习内容安排已更新。'
      : '建议已处理。'
    reviewTarget.value = null
    await loadCore()
    notice.value = successMessage
    if (!pendingSuggestions.value.length) activeView.value = 'roster'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '处理失败。'
  } finally {
    reviewing.value = false
  }
}

function selectAllPendingSuggestions() {
  selectedSuggestionIds.value = pendingSuggestions.value.map((item) => item.id)
}

function resetBatchReviewForm() {
  batchReviewForm.action = 'accept'
  batchReviewForm.reason_code = ''
  batchReviewForm.note = ''
}

function openBatchReview(scope: 'selected' | 'all' = 'selected') {
  if (scope === 'selected' && !selectedSuggestionCount.value) {
    notice.value = '请先选择需要处理的建议。'
    return
  }
  if (scope === 'all' && !pendingSuggestions.value.length) {
    notice.value = '当前范围没有待处理建议。'
    return
  }
  batchReviewScope.value = scope
  resetBatchReviewForm()
  batchReviewOpen.value = true
}

async function submitBatchReview() {
  if (!batchReviewCount.value || reviewing.value) return
  if (batchReviewForm.action !== 'accept' && !batchReviewForm.reason_code) {
    notice.value = '请选择本次批量处理原因。'
    return
  }
  if (batchReviewForm.reason_code === 'other' && !batchReviewForm.note.trim()) {
    notice.value = '选择其他原因时请填写处理说明。'
    return
  }
  reviewing.value = true
  try {
    const targetIds = batchReviewRows.value.map((row) => row.id)
    const result = await bulkReviewStratificationSuggestions({
      ids: targetIds,
      action: batchReviewForm.action,
      reason_code: batchReviewForm.action === 'accept' ? undefined : batchReviewForm.reason_code,
      note: batchReviewForm.note.trim()
    })
    batchReviewOpen.value = false
    clearSuggestionSelection()
    await loadCore()
    notice.value = batchReviewScope.value === 'all'
      ? `已处理当前范围全部 ${result.updated_count} 条建议。`
      : `已批量处理 ${result.updated_count} 条建议。`
    if (!pendingSuggestions.value.length) activeView.value = 'roster'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '批量处理失败。'
  } finally {
    reviewing.value = false
  }
}

async function submitManualAdjustment() {
  if (!manualTarget.value?.course || reviewing.value) return
  if (!manualForm.reason_code) {
    notice.value = '请选择本次调整原因。'
    return
  }
  if (manualForm.reason_code === 'other' && !manualForm.note.trim()) {
    notice.value = '选择其他原因时请填写说明。'
    return
  }
  reviewing.value = true
  try {
    await manuallyAdjustStratification({
      student: manualTarget.value.student.id,
      course: manualTarget.value.course.id,
      source_decision: manualTarget.value.source_decision_id,
      layer: manualForm.layer,
      reason_code: manualForm.reason_code,
      note: manualForm.note.trim()
    })
    notice.value = `${manualTarget.value.student.display_name}已调整为 ${manualForm.layer} 层。`
    manualTarget.value = null
    await loadCore()
    activeView.value = 'roster'
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '学习内容安排调整失败。'
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
  <AppShell title="学习内容与学习支持" eyebrow="教师工作台" :nav-items="navItems">
    <NoticeLine v-if="notice" :message="notice" floating @dismiss="notice = ''" />

    <header class="stratification-page-heading">
      <div>
        <h2>学习内容与学习支持</h2>
        <p>先查看学习目标层面的材料，再由教师分别确认学习内容安排与学习支持；结果仅教师可见。</p>
      </div>
      <a class="secondary-button" :href="overviewExportUrl">导出当前学习内容与支持安排</a>
    </header>

    <section class="stratification-scope-bar" aria-label="学习内容与支持范围">
      <label>
        <span>任教班级</span>
        <AppSelect v-model="classGroup" class="stratification-select" @change="changeScope">
          <option value="">全部任教班级</option>
          <option v-for="item in options?.classes" :key="item.id" :value="item.id">{{ item.name }}</option>
        </AppSelect>
      </label>
      <label>
        <span>课程</span>
        <AppSelect v-model="course" class="stratification-select" @change="changeScope">
          <option value="" disabled>请选择课程</option>
          <option v-for="item in visibleCourses" :key="item.id" :value="item.id">{{ item.title }}</option>
        </AppSelect>
      </label>
      <div class="scope-result">
        <span>当前范围</span>
        <strong>{{ overview.counts.total }} 名学生</strong>
      </div>
    </section>

    <nav class="stratification-tabs" aria-label="学习内容与支持安排视图">
      <button type="button" :class="{ active: activeView === 'roster' }" @click="setView('roster')">当前内容安排</button>
      <button type="button" :class="{ active: activeView === 'pending' }" @click="setView('pending')">
        待处理建议 <span v-if="pendingSuggestions.length">{{ pendingSuggestions.length }}</span>
      </button>
      <button type="button" :class="{ active: activeView === 'evidence' }" @click="setView('evidence')">学习依据</button>
      <button type="button" :class="{ active: activeView === 'history' }" @click="setView('history')">处理记录</button>
    </nav>

    <template v-if="activeView === 'roster'">
      <section class="panel layer-overview-panel">
        <header>
          <div><h3>当前学习内容安排</h3><p>点击内容类型可筛选下方学生。</p></div>
          <span>尚未安排 {{ overview.counts.unassigned }}</span>
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
        <div class="layer-distribution" aria-label="当前学习内容安排分布">
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
            <thead><tr><th>学生</th><th>班级</th><th>当前内容安排</th><th>近30日完成率</th><th>近30日得分率</th><th>最新建议</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="row in visibleRoster" :key="row.id">
                <td data-label="学生"><strong>{{ row.student.display_name }}</strong><small>{{ row.student.student_no || row.student.username }}</small></td>
                <td data-label="班级">{{ row.class_group.name }}</td>
                <td data-label="当前内容安排"><LayerBadge :layer="row.current_layer" /></td>
                <td data-label="近30日完成率">{{ percent(row.learning?.completion_rate) }}</td>
                <td data-label="近30日得分率">{{ percent(row.learning?.score_rate) }}</td>
                <td data-label="最新建议">
                  <template v-if="row.latest_decision">
                    <span class="decision-inline">
                      {{ suggestionLabel(row.latest_decision) }}
                      <small>{{ row.latest_decision.status_label }}</small>
                    </span>
                  </template>
                  <span v-else class="muted-text">暂无建议</span>
                </td>
                <td data-label="操作">
                  <div class="stratification-roster-actions">
                    <button v-if="row.latest_decision" class="assessment-row-review" type="button" @click="openReview(row.latest_decision)">
                      {{ row.latest_decision.status === 'pending' ? '处理建议' : '查看记录' }}
                    </button>
                    <button
                      v-if="row.latest_decision?.decision_kind === 'content_band' && row.latest_decision.status !== 'pending' && row.latest_decision.target_states.length"
                      class="assessment-row-review secondary"
                      type="button"
                      @click="openManualAdjustment(row.latest_decision)"
                    >依据现有材料调整</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-if="loading" class="empty">正在加载学习内容安排</p>
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
        <div><h3>待处理建议</h3><p>{{ pendingDescription }}</p></div>
        <strong>{{ pendingSuggestions.length }}</strong>
      </header>
      <div class="suggestion-bulk-toolbar">
        <MultiSelectActions
          :selected-count="selectedSuggestionCount"
          :total-count="pendingSuggestions.length"
          item-label="建议"
          @select-all="selectAllPendingSuggestions"
          @clear="clearSuggestionSelection"
        />
        <div class="suggestion-bulk-actions">
          <button
            class="secondary-button"
            type="button"
            :disabled="!pendingSuggestions.length || reviewing"
            data-test="stratification-review-all"
            @click="openBatchReview('all')"
          >
            批量处理全部（{{ pendingSuggestions.length }}）
          </button>
          <button class="primary-button" type="button" :disabled="!selectedSuggestionCount || reviewing" @click="openBatchReview('selected')">
            批量处理已选<span v-if="selectedSuggestionCount">（{{ selectedSuggestionCount }}）</span>
          </button>
        </div>
      </div>
      <div class="assessment-table-wrap">
        <table class="assessment-table suggestion-table">
          <thead><tr><th class="suggestion-select-cell"><input type="checkbox" :checked="allSuggestionPageSelected" :indeterminate="partiallySuggestionPageSelected" :disabled="!visiblePending.length" aria-label="选择当前页建议" @change="toggleSuggestionPage(($event.target as HTMLInputElement).checked)" /></th><th>学生</th><th>班级</th><th>当前</th><th>建议</th><th>参考强度</th><th>主要依据</th><th>教学支持</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="row in visiblePending" :key="row.id">
              <td class="suggestion-select-cell" data-label="选择"><input type="checkbox" :checked="selectedSuggestionIdSet.has(row.id)" :aria-label="`选择 ${row.student.display_name} 的建议`" @change="toggleSuggestion(row.id, ($event.target as HTMLInputElement).checked)" /></td>
              <td data-label="学生"><strong>{{ row.student.display_name }}</strong><small>{{ row.student.student_no || row.student.username }}</small></td>
              <td data-label="班级">{{ row.class_group.name }}<small>{{ row.course?.title || '-' }}</small></td>
              <td data-label="当前"><LayerBadge :layer="row.current_layer" compact /></td>
              <td data-label="建议">
                <LayerBadge v-if="row.decision_kind === 'content_band' && row.suggested_layer" :layer="row.suggested_layer" compact />
                <span v-else-if="row.decision_kind === 'content_band'" class="summary-status-pill summary-status-insufficient">暂不建议</span>
                <span v-else class="support-priority-pill" :class="`support-${row.support_priority || 'routine'}`">{{ supportPriorityLabel(row.support_priority) }}</span>
              </td>
              <td data-label="参考强度">{{ row.decision_kind === 'content_band' && row.suggested_layer ? `${Math.round(row.confidence * 100)}%` : '-' }}</td>
              <td data-label="主要依据"><span class="reason-text">{{ row.reasons[0] || '材料不足' }}</span></td>
              <td data-label="教学支持"><span class="support-text">{{ row.support_suggestion || '-' }}</span></td>
              <td data-label="操作"><button class="primary-table-action" type="button" @click="openReview(row)">处理</button></td>
            </tr>
          </tbody>
        </table>
        <p v-if="!loading && !pendingSuggestions.length" class="empty">当前没有已发布且待处理的建议。学校管理员发布新版本后会显示在这里。</p>
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
          <thead><tr><th>学生</th><th>班级 / 课程</th><th>原安排</th><th>系统建议</th><th>教师选择</th><th>处理结果</th><th>处理时间</th><th>详情</th></tr></thead>
          <tbody>
            <tr v-for="row in visibleHistory" :key="row.id">
              <td data-label="学生"><strong>{{ row.student.display_name }}</strong><small>{{ row.student.student_no || row.student.username }}</small></td>
              <td data-label="班级 / 课程">{{ row.class_group.name }}<small>{{ row.course?.title || '-' }}</small></td>
              <td data-label="原安排"><LayerBadge :layer="row.previous_layer" compact /></td>
              <td data-label="系统建议"><LayerBadge :layer="row.suggested_layer" compact /></td>
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

    <div v-if="batchReviewOpen" class="modal-backdrop" role="presentation" @click.self="closeBatchReview">
      <form v-modal-focus="closeBatchReview" class="entity-modal suggestion-review-modal" role="dialog" aria-modal="true" aria-labelledby="batch-review-title" @submit.prevent="submitBatchReview">
        <header class="modal-header">
          <div>
            <h2 id="batch-review-title">{{ batchReviewScope === 'all' ? '批量处理全部建议' : '批量处理已选建议' }}</h2>
            <p>{{ batchReviewScope === 'all' ? '当前筛选范围' : '已选' }} {{ batchReviewCount }} 条 · 学习支持 {{ batchSupportCount }} 条 · 学习内容安排 {{ batchContentBandCount }} 条</p>
          </div>
          <button class="icon-button" type="button" aria-label="关闭" :disabled="reviewing" @click="closeBatchReview">×</button>
        </header>
        <div class="suggestion-review-body">
          <p v-if="batchReviewScope === 'all'" class="batch-review-scope">
            将处理当前班级和课程筛选范围内的全部待处理建议，不受表格分页影响。请确认处理范围和方式后再继续。
          </p>
          <p class="batch-review-note">批量采用学习内容安排建议时，系统仍按每名学生的目标级材料分别更新；学习支持只记录教师确认的支持方式，不改变学习内容安排。</p>
          <fieldset class="suggestion-actions"><legend>处理方式</legend><label><input v-model="batchReviewForm.action" type="radio" value="accept" />采用{{ batchReviewScope === 'all' ? '全部' : '所选' }}建议</label><label><input v-model="batchReviewForm.action" type="radio" value="keep" />保持当前安排</label><label><input v-model="batchReviewForm.action" type="radio" value="defer" />暂缓处理</label></fieldset>
          <label v-if="batchReviewForm.action !== 'accept'" class="adjust-layer-field"><span>处理原因 <b>*</b></span><AppSelect v-model="batchReviewForm.reason_code" class="stratification-select" required><option value="" disabled>请选择处理原因</option><option v-for="item in manualReasonOptions" :key="item.value" :value="item.value">{{ item.label }}</option></AppSelect></label>
          <label class="review-note-field"><span>处理说明</span><textarea v-model.trim="batchReviewForm.note" rows="3" maxlength="1000" placeholder="可选，记录统一的后续安排或观察重点" /></label>
        </div>
        <footer class="modal-actions"><button class="secondary-button" type="button" :disabled="reviewing" @click="closeBatchReview">取消</button><button class="primary-button" type="submit" :disabled="reviewing">{{ reviewing ? '处理中' : `确认处理${batchReviewScope === 'all' ? '全部 ' : ' '}${batchReviewCount} 条` }}</button></footer>
      </form>
    </div>

    <div v-if="detail" class="modal-backdrop" role="presentation" @click.self="detail = null">
      <section v-modal-focus="closeDetail" class="entity-modal learning-summary-detail" role="dialog" aria-modal="true" aria-labelledby="summary-detail-title">
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

    <div v-if="reviewTarget" class="modal-backdrop" role="presentation" @click.self="closeReview">
      <section v-modal-focus="closeReview" class="entity-modal suggestion-review-modal" role="dialog" aria-modal="true" aria-labelledby="suggestion-review-title">
        <header class="modal-header"><div><h2 id="suggestion-review-title">{{ reviewTarget.status === 'pending' ? (reviewTarget.decision_kind === 'support' ? '处理学习支持' : '处理学习内容安排建议') : '处理记录' }}</h2><p>{{ reviewTarget.student.display_name }} · {{ reviewTarget.course?.title }} · {{ reviewTarget.class_group.name }}</p></div><button class="icon-button" type="button" aria-label="关闭" :disabled="reviewing" @click="closeReview">×</button></header>
        <div class="suggestion-review-body">
          <div v-if="reviewTarget.decision_kind === 'content_band'" class="suggestion-layer-flow">
            <div><span>当前内容安排</span><LayerBadge :layer="reviewTarget.current_layer" /></div>
            <strong aria-hidden="true">→</strong>
            <div><span>{{ reviewTarget.status === 'pending' ? '建议内容安排' : '教师选择' }}</span><LayerBadge :layer="reviewTarget.status === 'pending' ? reviewTarget.suggested_layer : (reviewTarget.teacher_selected_layer || reviewTarget.suggested_layer)" /></div>
          </div>
          <section class="suggestion-evidence-block">
            <h3>主要依据</h3>
            <ul><li v-for="item in reviewTarget.reasons" :key="item">{{ item }}</li></ul>
          </section>
          <section v-if="reviewTarget.target_states.length" class="target-evidence-card">
            <h3>目标级学习依据（{{ reviewTarget.target_states.length }} 项）</h3>
            <article v-for="state in reviewTarget.target_states" :key="state.id" class="target-evidence-item">
              <header>
                <div><span>对应学习目标</span><strong>{{ state.learning_target_code }} · {{ state.learning_target_name }}</strong></div>
                <span class="summary-status-pill" :class="state.evidence_status === 'available' ? 'summary-status-available' : 'summary-status-insufficient'">{{ state.evidence_status === 'available' ? '材料可用' : '材料不足' }}</span>
              </header>
              <dl>
                <div><dt>材料覆盖</dt><dd>{{ percent(state.evidence_coverage) }}</dd></div>
                <div><dt>当前情况</dt><dd>{{ percent(state.estimate) }}</dd></div>
                <div><dt>不确定性</dt><dd>{{ percent(state.uncertainty) }}</dd></div>
                <div><dt>材料有效至</dt><dd>{{ formatDateTime(state.valid_until) }}</dd></div>
              </dl>
            </article>
            <p v-if="reviewTarget.target_states.some((state) => state.evidence_status !== 'available')">材料不足、设备问题或未获得学习机会时，系统只显示“暂不建议”，不会自动进入 C 层。</p>
          </section>
          <section class="suggestion-support-block"><h3>教学支持</h3><p>{{ reviewTarget.support_suggestion || '暂无具体建议。' }}</p></section>
          <template v-if="reviewTarget.status === 'pending'">
            <fieldset class="suggestion-actions"><legend>处理方式</legend><label><input v-model="reviewForm.action" type="radio" value="accept" :disabled="reviewTarget.decision_kind === 'content_band' && !reviewTarget.suggested_layer" />{{ reviewTarget.decision_kind === 'content_band' ? '采用学习内容安排建议' : '采用支持建议' }}</label><label><input v-model="reviewForm.action" type="radio" value="keep" />保持当前安排</label><label v-if="reviewTarget.decision_kind === 'content_band'"><input v-model="reviewForm.action" type="radio" value="adjust" />调整学习内容安排</label><label><input v-model="reviewForm.action" type="radio" value="defer" />暂缓处理</label></fieldset>
            <label v-if="reviewForm.action === 'adjust'" class="adjust-layer-field"><span>调整为</span><AppSelect v-model="reviewForm.layer" class="stratification-select"><option value="A">A · 拓展挑战层</option><option value="B">B · 核心发展层</option><option value="C">C · 基础提升层</option></AppSelect></label>
            <label v-if="reviewForm.action !== 'accept'" class="adjust-layer-field"><span>处理原因 <b>*</b></span><AppSelect v-model="reviewForm.reason_code" class="stratification-select" required><option value="" disabled>请选择处理原因</option><option v-for="item in manualReasonOptions" :key="item.value" :value="item.value">{{ item.label }}</option></AppSelect></label>
            <label class="review-note-field"><span>处理说明</span><textarea v-model.trim="reviewForm.note" rows="3" maxlength="1000" placeholder="可选，记录后续安排或观察重点" /></label>
          </template>
          <dl v-else class="suggestion-history-detail">
            <div><dt>处理结果</dt><dd>{{ reviewTarget.status_label }}</dd></div>
            <div><dt>教师选择</dt><dd>{{ reviewTarget.teacher_selected_layer || '未调整' }}</dd></div>
            <div><dt>处理原因</dt><dd>{{ reviewTarget.review_reason_label || '未记录' }}</dd></div>
            <div><dt>处理教师</dt><dd>{{ reviewTarget.reviewed_by || '-' }}</dd></div>
            <div><dt>处理时间</dt><dd>{{ formatDateTime(reviewTarget.reviewed_at) }}</dd></div>
            <div class="wide"><dt>处理说明</dt><dd>{{ reviewTarget.review_note || '无' }}</dd></div>
          </dl>
        </div>
        <footer class="modal-actions">
          <button :class="reviewTarget.status === 'pending' ? 'secondary-button' : 'primary-button'" type="button" :disabled="reviewing" @click="closeReview">{{ reviewTarget.status === 'pending' ? '取消' : '关闭' }}</button>
          <button
            v-if="reviewTarget.status !== 'pending' && reviewTarget.course && reviewTarget.decision_kind === 'content_band' && reviewTarget.target_states.length"
            class="secondary-button"
            type="button"
            @click="openManualAdjustment(reviewTarget)"
          >依据现有材料再次调整</button>
          <button v-if="reviewTarget.status === 'pending'" class="primary-button" type="button" :disabled="reviewing" @click="submitReview">{{ reviewing ? '保存中' : '确认处理' }}</button>
        </footer>
      </section>
    </div>

    <div v-if="manualTarget" class="modal-backdrop" role="presentation" @click.self="closeManualAdjustment">
      <form v-modal-focus="closeManualAdjustment" class="entity-modal suggestion-review-modal" role="dialog" aria-modal="true" aria-labelledby="manual-layer-title" @submit.prevent="submitManualAdjustment">
        <header class="modal-header">
          <div><h2 id="manual-layer-title">调整学习内容安排</h2><p>{{ manualTarget.student.display_name }} · {{ manualTarget.course?.title }} · {{ manualTarget.class_group.name }}</p></div>
          <button class="icon-button" type="button" aria-label="关闭" :disabled="reviewing" @click="closeManualAdjustment">×</button>
        </header>
        <div class="suggestion-review-body manual-layer-form">
          <div class="suggestion-layer-flow">
            <div><span>当前内容安排</span><LayerBadge :layer="manualTarget.current_layer" /></div>
            <strong aria-hidden="true">→</strong>
            <div><span>调整为</span><LayerBadge :layer="manualForm.layer" /></div>
          </div>
          <label class="adjust-layer-field"><span>学习内容安排 <b>*</b></span><AppSelect v-model="manualForm.layer" class="stratification-select" required><option value="A">A · 拓展挑战内容</option><option value="B">B · 核心发展内容</option><option value="C">C · 基础提升内容</option></AppSelect></label>
          <label class="adjust-layer-field"><span>调整原因 <b>*</b></span><AppSelect v-model="manualForm.reason_code" class="stratification-select" required><option value="" disabled>请选择调整原因</option><option v-for="item in manualReasonOptions" :key="item.value" :value="item.value">{{ item.label }}</option></AppSelect></label>
          <label class="review-note-field"><span>补充说明 <b v-if="manualForm.reason_code === 'other'">*</b></span><textarea v-model.trim="manualForm.note" rows="4" maxlength="1000" :required="manualForm.reason_code === 'other'" placeholder="记录教学依据、支持安排或后续观察重点" /></label>
          <p class="manual-layer-note">本次调整沿用所选记录中的目标级学习依据，并形成新的有效安排；原建议和历史处理记录不会被覆盖。</p>
        </div>
        <footer class="modal-actions">
          <button class="secondary-button" type="button" :disabled="reviewing" @click="closeManualAdjustment">取消</button>
          <button class="primary-button" type="submit" :disabled="reviewing || manualForm.layer === manualTarget.current_layer">{{ reviewing ? '保存中' : '确认调整' }}</button>
        </footer>
      </form>
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
}
.roster-search input,
.review-note-field textarea {
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fff;
  color: var(--ink);
  padding: 9px 11px;
  font: inherit;
  transition: border-color 160ms ease-out, box-shadow 160ms ease-out;
}
.stratification-select { color-scheme: light; }
.stratification-select:hover :deep(.app-select-trigger),
.roster-search input:hover,
.review-note-field textarea:hover { border-color: #9bafa6; }
.stratification-select:focus-within :deep(.app-select-trigger),
.roster-search input:focus,
.review-note-field textarea:focus {
  border-color: var(--primary);
  outline: 3px solid rgba(23, 72, 63, 0.14);
}
.review-note-field textarea { min-height: 96px; line-height: 1.55; resize: vertical; }
.target-evidence-card {
  display: grid;
  gap: 12px;
  border: 1px solid #c5d6cc;
  border-radius: 8px;
  background: #f4f7f4;
  padding: 14px;
}
.target-evidence-card > h3 { margin: 0; font-size: 14px; }
.target-evidence-item {
  display: grid;
  gap: 10px;
  border-top: 1px solid #d8e4dc;
  padding-top: 12px;
}
.target-evidence-item > header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.target-evidence-item > header div { display: grid; gap: 4px; }
.target-evidence-item > header div span,
.target-evidence-card dt { color: var(--muted); font-size: 12px; }
.target-evidence-card dl {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin: 0;
}
.target-evidence-card dl div {
  display: grid;
  gap: 4px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fff;
  padding: 9px;
}
.target-evidence-card dd { margin: 0; font-weight: 700; }
.target-evidence-card p { margin: 0; color: #92400e; line-height: 1.55; }
.scope-result { margin-left: auto; text-align: right; }
.scope-result span, .scope-result strong { display: block; }
.scope-result span { color: var(--muted); font-size: 12px; }
.scope-result strong { margin-top: 4px; font-size: 17px; }

.stratification-tabs {
  display: flex;
  gap: 2px;
  margin: 14px 0;
  border-bottom: 1px solid #d6ded8;
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
  color: #526a61;
  font-weight: 700;
  cursor: pointer;
}
.stratification-tabs button.active { border-bottom-color: #b94f3d; color: #0d352e; }
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
.layer-stat-grid button:hover, .layer-stat-grid button.active { background: #f1f5f1; box-shadow: inset 0 -3px #b94f3d; }
.layer-stat-grid span, .layer-stat-grid strong, .layer-stat-grid small { display: block; }
.layer-stat-grid span, .layer-stat-grid small { color: var(--muted); }
.layer-stat-grid span { font-size: 12px; font-weight: 700; }
.layer-stat-grid strong { margin: 5px 0 2px; font-size: 25px; font-variant-numeric: tabular-nums; }
.layer-stat-grid small { font-size: 12px; overflow-wrap: anywhere; }
.layer-distribution { display: flex; width: 100%; height: 8px; background: #dce4df; }
.layer-distribution span { display: block; min-width: 0; transition: width 180ms ease-out; }
.segment-A { background: #0f766e; }
.segment-B { background: #6f9186; }
.segment-C { background: #b7791f; }
.segment-unassigned { background: #a5b1ac; }

.stratification-roster-panel, .suggestion-panel, .learning-summary-table-panel { min-width: 0; padding: 0; overflow: hidden; }
.roster-panel-head, .suggestion-panel-head { border-bottom: 1px solid var(--line); padding: 14px 16px; }
.roster-search { display: grid; gap: 5px; width: min(300px, 100%); min-width: 0; }
.suggestion-panel-head > strong { font-size: 24px; font-variant-numeric: tabular-nums; }
.suggestion-bulk-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 58px; border-bottom: 1px solid var(--line); background: #f5f7f3; padding: 9px 16px; }
.suggestion-bulk-actions { display: flex; align-items: center; gap: 8px; }
.suggestion-bulk-actions button { min-height: 40px; white-space: nowrap; }
.suggestion-bulk-toolbar :deep(.multi-select-actions) { justify-content: flex-start; }
.suggestion-bulk-toolbar :deep(.multi-select-actions button) { min-height: 40px; }
.batch-review-scope { margin: 0; border: 1px solid #c5d6cc; border-radius: 8px; background: #eef5f1; color: #315f50; padding: 10px 12px; line-height: 1.6; }
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
.suggestion-table th:nth-child(1) { width: 4%; }
.suggestion-table th:nth-child(2) { width: 11%; }
.suggestion-table th:nth-child(3) { width: 12%; }
.suggestion-table th:nth-child(4), .suggestion-table th:nth-child(5) { width: 7%; }
.suggestion-table th:nth-child(6) { width: 8%; }
.suggestion-table th:nth-child(7) { width: 17%; }
.suggestion-table th:nth-child(8) { width: 25%; }
.suggestion-table th:nth-child(9) { width: 9%; }
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
.suggestion-select-cell { text-align: center; }
.suggestion-select-cell input { width: 18px; height: 18px; margin: 0; accent-color: var(--primary); cursor: pointer; }
.decision-inline { display: block; font-weight: 700; }
.muted-text { color: var(--muted); }
.primary-table-action, .assessment-row-review { max-width: 100%; min-height: 36px; border-radius: 4px; padding: 0 11px; font-weight: 700; white-space: nowrap; cursor: pointer; }
.primary-table-action { border: 1px solid #17483f; background: #17483f; color: #fff; }
.assessment-row-review { border: 1px solid #b9cbc2; background: #fff; color: #315f50; }
.stratification-roster-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.assessment-row-review.secondary { color: #475569; font-weight: 600; }
.reason-text, .support-text { display: block; max-width: 100%; line-height: 1.5; overflow-wrap: anywhere; word-break: break-word; }
.summary-status-pill { display: inline-flex; align-items: center; min-height: 28px; border-radius: 4px; padding: 0 9px; font-size: 12px; font-weight: 700; white-space: nowrap; }
.support-priority-pill { display: inline-flex; align-items: center; min-height: 28px; border: 1px solid transparent; border-radius: 4px; padding: 0 9px; font-size: 12px; font-weight: 700; white-space: nowrap; }
.support-routine { border-color: #b8d6c8; background: #eef8f3; color: #17633a; }
.support-watch { border-color: #e5c978; background: #fff8e4; color: #7a5510; }
.support-high { border-color: #e5b5af; background: #fff1ef; color: #9b2c24; }
.summary-status-available { background: #e8f7ef; color: #17633a; }
.summary-status-insufficient { background: #fff4dd; color: #8a4b08; }
.summary-status-no_opportunity { background: #eef2ef; color: #526a61; }
.summary-status-quality_blocked { background: #fdeaea; color: #9f2626; }
.stratification-pagination { display: flex; align-items: center; justify-content: flex-end; gap: 12px; border-top: 1px solid var(--line); padding: 11px 14px; }
.stratification-pagination span { color: var(--muted); font-size: 13px; font-variant-numeric: tabular-nums; }

.evidence-toolbar { margin-bottom: 12px; }
.learning-window-tabs, .evidence-actions { display: flex; gap: 6px; }
.learning-window-tabs button { min-height: 40px; border: 1px solid #d6ded8; background: #fff; padding: 0 15px; color: #526a61; font-weight: 700; cursor: pointer; }
.learning-window-tabs button.active { border-color: #78978c; background: #edf4f0; color: #0d352e; }
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
.suggestion-layer-flow { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 14px; border: 1px solid var(--line); background: #f7f8f4; padding: 14px; }
.suggestion-layer-flow > div { display: grid; gap: 7px; }
.suggestion-layer-flow > div > span { color: var(--muted); font-size: 12px; font-weight: 700; }
.suggestion-layer-flow > strong { color: #687a73; font-size: 22px; }
.suggestion-evidence-block, .suggestion-support-block { margin-top: 14px; border: 1px solid var(--line); padding: 13px 14px; }
.suggestion-evidence-block h3, .suggestion-support-block h3 { margin: 0; font-size: 14px; }
.suggestion-evidence-block ul { margin: 8px 0 0; padding-left: 20px; line-height: 1.65; }
.suggestion-support-block { border-left: 3px solid #17483f; background: #f1f5f1; }
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
  color: #334a43;
  font-weight: 700;
  cursor: pointer;
  transition: border-color 160ms ease-out, background-color 160ms ease-out, box-shadow 160ms ease-out;
}
.suggestion-actions label:hover { border-color: #8ba59b; background: #f3f6f3; }
.suggestion-actions label:has(input:checked) { border-color: #78978c; background: #edf4f0; color: #0d352e; box-shadow: inset 0 0 0 1px #b8cdc4; }
.suggestion-actions label:has(input:focus-visible) { outline: 3px solid rgba(23, 72, 63, 0.15); outline-offset: 1px; }
.suggestion-actions label:has(input:disabled) { background: #f3f5f3; color: #8b9994; cursor: not-allowed; }
.suggestion-actions input { width: 18px; height: 18px; margin: 0; accent-color: var(--primary); flex: 0 0 auto; }
.adjust-layer-field, .review-note-field { display: grid; gap: 6px; margin-top: 12px; }
.adjust-layer-field b, .review-note-field b { color: var(--danger); }
.manual-layer-form { display: grid; }
.manual-layer-note { margin: 14px 0 0; border-left: 3px solid #b94f3d; background: #fbefec; padding: 10px 12px; color: #526a61; line-height: 1.55; }
.batch-review-note { margin: 0; border-left: 3px solid #b94f3d; background: #fbefec; padding: 11px 13px; color: #526a61; line-height: 1.55; }
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
  .suggestion-table td.suggestion-select-cell { display: flex; align-items: center; gap: 8px; text-align: left; }
  .suggestion-table td.suggestion-select-cell::before { margin: 0; }
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
  .suggestion-bulk-toolbar { align-items: stretch; flex-direction: column; }
  .suggestion-bulk-actions { display: grid; grid-template-columns: 1fr; }
  .suggestion-bulk-actions button { width: 100%; min-height: 44px; }
  .suggestion-bulk-toolbar :deep(.multi-select-actions) { justify-content: space-between; flex-wrap: wrap; }
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
