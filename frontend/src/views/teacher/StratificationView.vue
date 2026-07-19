<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ApiError } from '@/api/client'
import {
  getLearningSummaries,
  getStratificationSuggestions,
  learningSummariesExportUrl,
  refreshLearningSummaries,
  reviewStratificationSuggestion,
  type LearningSummaryRow,
  type StratificationSuggestionRow
} from '@/api/learningAnalytics'
import { getTeacherCourseOptions, type TeacherCourseOptions } from '@/api/teacher'
import AppShell from '@/layouts/AppShell.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import { teacherNav } from './nav'

type ReviewAction = 'accept' | 'keep' | 'adjust' | 'defer'

const navItems = teacherNav('/teacher/stratification')
const options = ref<TeacherCourseOptions | null>(null)
const summaries = ref<LearningSummaryRow[]>([])
const suggestions = ref<StratificationSuggestionRow[]>([])
const loading = ref(false)
const refreshing = ref(false)
const reviewing = ref(false)
const notice = ref('')
const activeView = ref<'summaries' | 'suggestions'>('summaries')
const windowType = ref<'day' | '7d' | '30d' | 'unit'>('7d')
const classGroup = ref<number | string>('')
const course = ref<number | string>('')
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

const visibleCourses = computed(() => options.value?.courses || [])
const availableRows = computed(() => summaries.value.filter((item) => item.data_status === 'available'))
const averageCompletion = computed(() => {
  const values = summaries.value.map((item) => item.metrics.completion_rate).filter((value): value is number => value !== null)
  return values.length ? Math.round(values.reduce((sum, value) => sum + value, 0) * 100 / values.length) : null
})
const averageScore = computed(() => {
  const values = summaries.value.map((item) => item.metrics.score.score_rate).filter((value): value is number => value !== null)
  return values.length ? Math.round(values.reduce((sum, value) => sum + value, 0) * 100 / values.length) : null
})
const pendingSuggestions = computed(() => suggestions.value.filter((item) => item.status === 'pending'))
const exportUrl = computed(() => learningSummariesExportUrl({
  window: windowType.value,
  class_group: classGroup.value,
  course: course.value
}))

function percent(value: number | null | undefined) {
  return value === null || value === undefined ? '-' : `${Math.round(value * 100)}%`
}

function stars(value: number | null | undefined) {
  return value === null || value === undefined ? '-' : `${value.toFixed(1)} 星`
}

function dataStatusClass(value: string) {
  return `summary-status-${value}`
}

async function load() {
  loading.value = true
  notice.value = ''
  try {
    const [summaryResult, suggestionResult] = await Promise.all([
      getLearningSummaries({ window: windowType.value, class_group: classGroup.value, course: course.value }),
      getStratificationSuggestions({ class_group: classGroup.value, course: course.value })
    ])
    summaries.value = summaryResult.rows
    suggestions.value = suggestionResult
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '学习情况加载失败。'
  } finally {
    loading.value = false
  }
}

async function rebuild() {
  refreshing.value = true
  try {
    const result = await refreshLearningSummaries({ course: course.value })
    notice.value = `已更新 ${result.summaries} 份学习情况。`
    await load()
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '学习情况更新失败。'
  } finally {
    refreshing.value = false
  }
}

function openReview(row: StratificationSuggestionRow) {
  reviewTarget.value = row
  reviewForm.action = row.suggested_layer ? 'accept' : 'defer'
  reviewForm.layer = row.suggested_layer || row.previous_layer || 'B'
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
    notice.value = '学习安排建议已处理。'
    reviewTarget.value = null
    await load()
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '处理失败。'
  } finally {
    reviewing.value = false
  }
}

onMounted(async () => {
  try {
    options.value = await getTeacherCourseOptions()
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '筛选条件加载失败。'
  }
  await load()
})
</script>

<template>
  <AppShell title="学习情况与分层建议" eyebrow="教师工作台" :nav-items="navItems">
    <NoticeLine v-if="notice" :message="notice" />

    <section class="learning-summary-heading">
      <div>
        <h2>学生学习情况</h2>
        <p>按真实任务、作答、评分、资源学习和课堂评价汇总，仅任课教师可见。</p>
      </div>
      <div class="learning-summary-heading-actions">
        <a class="secondary-button" :href="exportUrl">导出 XLSX</a>
        <button class="primary-button" type="button" :disabled="refreshing" @click="rebuild">
          {{ refreshing ? '更新中' : '重新汇总' }}
        </button>
      </div>
    </section>

    <section class="learning-summary-toolbar" aria-label="学习情况筛选">
      <div class="learning-view-tabs">
        <button type="button" :class="{ active: activeView === 'summaries' }" @click="activeView = 'summaries'">学习情况</button>
        <button type="button" :class="{ active: activeView === 'suggestions' }" @click="activeView = 'suggestions'">分层建议 {{ pendingSuggestions.length }}</button>
      </div>
      <select v-model="classGroup" aria-label="按班级筛选" @change="load">
        <option value="">全部任教班级</option>
        <option v-for="item in options?.classes" :key="item.id" :value="item.id">{{ item.grade }} {{ item.name }}</option>
      </select>
      <select v-model="course" aria-label="按课程筛选" @change="load">
        <option value="">全部课程</option>
        <option v-for="item in visibleCourses" :key="item.id" :value="item.id">{{ item.title }}</option>
      </select>
    </section>

    <template v-if="activeView === 'summaries'">
      <section class="learning-window-tabs" aria-label="汇总范围">
        <button v-for="item in windowOptions" :key="item.value" type="button" :class="{ active: windowType === item.value }" @click="windowType = item.value; load()">{{ item.label }}</button>
      </section>

      <section class="metric-grid learning-summary-metrics">
        <article class="metric-card"><span>学生</span><strong>{{ summaries.length }}</strong><small>当前筛选</small></article>
        <article class="metric-card"><span>材料可用</span><strong>{{ availableRows.length }}</strong><small>可形成参考建议</small></article>
        <article class="metric-card"><span>平均完成率</span><strong>{{ averageCompletion === null ? '-' : `${averageCompletion}%` }}</strong><small>按有效任务计算</small></article>
        <article class="metric-card"><span>平均得分率</span><strong>{{ averageScore === null ? '-' : `${averageScore}%` }}</strong><small>只统计已评分任务</small></article>
      </section>

      <section class="panel learning-summary-table-panel">
        <div class="assessment-table-wrap">
          <table class="assessment-table learning-summary-table">
            <thead><tr><th>学生</th><th>班级</th><th>课程</th><th>材料状态</th><th>有效任务</th><th>完成率</th><th>得分率</th><th>资源学习</th><th>教师评价</th><th>详情</th></tr></thead>
            <tbody>
              <tr v-for="row in summaries" :key="row.id">
                <td><strong>{{ row.student.display_name }}</strong><small>{{ row.student.student_no || row.student.username }}</small></td>
                <td>{{ row.student.class_group.name }}</td>
                <td><strong>{{ row.course.title }}</strong><small>{{ row.subject.name }}</small></td>
                <td><span class="summary-status-pill" :class="dataStatusClass(row.data_status)">{{ row.data_status_label }}</span></td>
                <td>{{ row.metrics.opportunities.eligible_count }}<small>分配 {{ row.metrics.opportunities.assigned_count }}</small></td>
                <td>{{ percent(row.metrics.completion_rate) }}</td>
                <td>{{ percent(row.metrics.score.score_rate) }}<small>{{ row.metrics.score.graded_item_count }} 项已评分</small></td>
                <td>{{ row.metrics.resources.opened_count }} / {{ row.metrics.resources.assigned_count }}</td>
                <td>{{ stars(row.metrics.evaluation.teacher.average_stars) }}</td>
                <td><button class="assessment-row-review" type="button" @click="detail = row">查看</button></td>
              </tr>
            </tbody>
          </table>
          <p v-if="loading" class="empty">正在加载学习情况</p>
          <p v-else-if="!summaries.length" class="empty">当前范围还没有汇总结果，可点击重新汇总。</p>
        </div>
      </section>
    </template>

    <section v-else class="panel stratification-suggestion-panel">
      <header class="suggestion-list-head"><div><strong>教师审核</strong><span>学生端不显示层级、参考强度和判断原因。</span></div><span>{{ pendingSuggestions.length }} 条待处理</span></header>
      <div class="assessment-table-wrap">
        <table class="assessment-table suggestion-table">
          <thead><tr><th>学生</th><th>班级</th><th>课程</th><th>当前</th><th>建议</th><th>参考强度</th><th>主要依据</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="row in suggestions" :key="row.id">
              <td><strong>{{ row.student.display_name }}</strong><small>{{ row.student.student_no || row.student.username }}</small></td>
              <td>{{ row.class_group.name }}</td>
              <td>{{ row.course?.title || '-' }}</td>
              <td>{{ row.previous_layer || '未设置' }}</td>
              <td><strong>{{ row.suggested_layer || '暂不建议调整' }}</strong></td>
              <td>{{ row.suggested_layer ? `${Math.round(row.confidence * 100)}%` : '-' }}</td>
              <td><span class="suggestion-reason">{{ row.reasons[0] || '材料不足' }}</span></td>
              <td><span class="summary-status-pill" :class="row.status === 'pending' ? 'summary-status-insufficient' : 'summary-status-available'">{{ row.status_label }}</span></td>
              <td><button class="assessment-row-review" type="button" @click="openReview(row)">{{ row.status === 'pending' ? '处理' : '查看' }}</button></td>
            </tr>
          </tbody>
        </table>
        <p v-if="!loading && !suggestions.length" class="empty">当前没有学习安排建议。</p>
      </div>
    </section>

    <div v-if="detail" class="modal-backdrop" role="presentation" @click.self="detail = null">
      <section class="entity-modal learning-summary-detail" role="dialog" aria-modal="true" aria-labelledby="summary-detail-title">
        <header class="modal-header"><div><h2 id="summary-detail-title">{{ detail.student.display_name }}的学习情况</h2><p>{{ detail.window_type_label }} · {{ detail.course.title }} · {{ detail.student.class_group.name }}</p></div><button class="icon-button" type="button" aria-label="关闭" @click="detail = null">×</button></header>
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
        <header class="modal-header"><div><h2 id="suggestion-review-title">处理学习安排建议</h2><p>{{ reviewTarget.student.display_name }} · {{ reviewTarget.course?.title }} · {{ reviewTarget.class_group.name }}</p></div><button class="icon-button" type="button" aria-label="关闭" @click="reviewTarget = null">×</button></header>
        <div class="suggestion-review-body">
          <div class="suggestion-band-line"><span>当前 {{ reviewTarget.previous_layer || '未设置' }}</span><strong>{{ reviewTarget.suggested_layer ? `建议 ${reviewTarget.suggested_layer}` : '暂不建议调整' }}</strong></div>
          <ul class="suggestion-reasons"><li v-for="item in reviewTarget.reasons" :key="item">{{ item }}</li></ul>
          <p class="support-suggestion">{{ reviewTarget.support_suggestion }}</p>
          <fieldset class="suggestion-actions"><legend>处理方式</legend><label><input v-model="reviewForm.action" type="radio" value="accept" :disabled="!reviewTarget.suggested_layer" />采纳建议</label><label><input v-model="reviewForm.action" type="radio" value="keep" />保持当前</label><label><input v-model="reviewForm.action" type="radio" value="adjust" />教师调整</label><label><input v-model="reviewForm.action" type="radio" value="defer" />暂缓处理</label></fieldset>
          <label v-if="reviewForm.action === 'adjust'" class="adjust-layer-field"><span>调整为</span><select v-model="reviewForm.layer"><option value="A">A</option><option value="B">B</option><option value="C">C</option></select></label>
          <label class="review-note-field"><span>处理说明</span><textarea v-model.trim="reviewForm.note" rows="3" maxlength="1000" placeholder="可选，记录后续任务安排或观察重点"></textarea></label>
        </div>
        <footer class="modal-actions"><button class="secondary-button" type="button" @click="reviewTarget = null">取消</button><button class="primary-button" type="button" :disabled="reviewing" @click="submitReview">{{ reviewing ? '保存中' : '确认' }}</button></footer>
      </section>
    </div>
  </AppShell>
</template>

<style scoped>
.learning-summary-heading,
.learning-summary-toolbar,
.suggestion-list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.learning-summary-heading { margin-bottom: 16px; }
.learning-summary-heading h2 { margin: 0 0 4px; font-size: 22px; }
.learning-summary-heading p { margin: 0; color: var(--muted); font-size: 14px; }
.learning-summary-heading-actions { display: flex; align-items: center; gap: 8px; }

.learning-summary-toolbar {
  flex-wrap: wrap;
  padding: 10px 12px;
  border: 1px solid var(--line);
  background: #fff;
}

.learning-summary-toolbar select { width: min(220px, 100%); min-height: 40px; }
.learning-view-tabs, .learning-window-tabs { display: flex; gap: 4px; }
.learning-view-tabs button, .learning-window-tabs button { min-height: 40px; padding: 0 15px; border: 0; background: transparent; color: #475569; font-weight: 700; }
.learning-view-tabs button.active, .learning-window-tabs button.active { background: #eaf3ff; color: #1557a6; }
.learning-window-tabs { margin: 12px 0; }
.learning-window-tabs button { border: 1px solid #dbe3ec; background: #fff; }

.learning-summary-metrics { margin-bottom: 14px; }
.learning-summary-table-panel, .stratification-suggestion-panel { overflow: hidden; }
.learning-summary-table td strong, .learning-summary-table td small, .suggestion-table td strong, .suggestion-table td small { display: block; }
.learning-summary-table td small, .suggestion-table td small { margin-top: 3px; color: var(--muted); font-size: 12px; }
.summary-status-pill { display: inline-flex; align-items: center; min-height: 28px; padding: 0 9px; border-radius: 4px; font-size: 12px; font-weight: 700; white-space: nowrap; }
.summary-status-available { background: #e8f7ef; color: #17633a; }
.summary-status-insufficient { background: #fff4dd; color: #8a4b08; }
.summary-status-no_opportunity { background: #eef2f7; color: #475569; }
.summary-status-quality_blocked { background: #fdeaea; color: #9f2626; }
.suggestion-list-head { padding: 16px 18px; border-bottom: 1px solid var(--line); }
.suggestion-list-head div strong, .suggestion-list-head div span { display: block; }
.suggestion-list-head div span { margin-top: 4px; color: var(--muted); font-size: 13px; }
.suggestion-reason { display: block; max-width: 320px; line-height: 1.5; }

.learning-summary-detail { width: min(780px, calc(100vw - 24px)); }
.summary-detail-body, .suggestion-review-body { padding: 18px; overflow-y: auto; }
.summary-detail-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1px; margin: 0; background: var(--line); border: 1px solid var(--line); }
.summary-detail-grid div { padding: 14px; background: #fff; }
.summary-detail-grid dt { color: var(--muted); font-size: 12px; }
.summary-detail-grid dd { margin: 6px 0 0; font-size: 20px; font-weight: 750; }
.summary-evaluation-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-top: 16px; }
.summary-evaluation-grid article { padding: 14px; border: 1px solid var(--line); border-radius: 6px; }
.summary-evaluation-grid span, .summary-evaluation-grid strong, .summary-evaluation-grid small { display: block; }
.summary-evaluation-grid strong { margin: 6px 0; font-size: 18px; }
.summary-evaluation-grid small { color: var(--muted); line-height: 1.5; }
.summary-missing-list { margin-top: 16px; padding: 14px; border-left: 3px solid #d69228; background: #fff8e8; }
.summary-missing-list ul { margin: 8px 0 0; padding-left: 20px; line-height: 1.7; }

.suggestion-review-modal { width: min(680px, calc(100vw - 24px)); }
.suggestion-band-line { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px; background: #eef5ff; }
.suggestion-band-line strong { color: #1557a6; }
.suggestion-reasons { margin: 16px 0; padding-left: 22px; line-height: 1.7; }
.support-suggestion { padding: 12px 14px; border-left: 3px solid #2f73bd; background: #f7fafc; line-height: 1.65; }
.suggestion-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin: 16px 0; padding: 14px; border: 1px solid var(--line); }
.suggestion-actions legend { padding: 0 6px; font-weight: 700; }
.suggestion-actions label { display: flex; align-items: center; min-height: 40px; gap: 8px; }
.adjust-layer-field, .review-note-field { display: grid; gap: 7px; margin-top: 12px; }
.adjust-layer-field select { width: 160px; }

@media (max-width: 760px) {
  .learning-summary-heading { align-items: flex-start; }
  .learning-summary-heading, .learning-summary-toolbar { flex-direction: column; }
  .learning-summary-heading > button, .learning-summary-toolbar select, .learning-view-tabs { width: 100%; }
  .learning-summary-heading-actions { width: 100%; }
  .learning-summary-heading-actions > * { flex: 1; }
  .learning-view-tabs button { flex: 1; }
  .learning-window-tabs { overflow-x: auto; }
  .learning-window-tabs button { flex: 0 0 auto; }
  .summary-detail-grid, .summary-evaluation-grid { grid-template-columns: 1fr; }
  .suggestion-actions { grid-template-columns: 1fr; }
}
</style>
