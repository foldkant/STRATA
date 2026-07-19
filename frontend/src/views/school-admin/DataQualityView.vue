<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { EChartsCoreOption } from 'echarts/core'
import {
  getSchoolDataQuality,
  runSchoolDataQuality,
  type AnalyticsPipelineRun,
  type DataQualityReport,
  type QualityIssue,
  type QualityMetric,
  type SchoolDataQuality
} from '@/api/analytics'
import { ApiError } from '@/api/client'
import AppShell from '@/layouts/AppShell.vue'
import EChartPanel from '@/components/EChartPanel.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import { schoolAdminNav } from './nav'

const navItems = schoolAdminNav('/school-admin/data-quality')
const data = ref<SchoolDataQuality | null>(null)
const loading = ref(true)
const running = ref(false)
const notice = ref('')
const noticeTone = ref<'success' | 'warning' | 'error' | 'info'>('info')
const expandedRunId = ref<number | null>(null)
let pollTimer: number | null = null

const metricLabels: Record<string, string> = {
  duplicate_rate: '重复事件率',
  invalid_event_rate: '无效事件率',
  late_event_rate: '迟到事件率',
  semantic_missing_rate: '语义缺失率',
  opportunity_coverage_rate: '机会关联覆盖率',
  client_offline_rate: '客户端离线率',
  v1_v2_difference_rate: 'V1/V2 差异率',
  event_count: '有效事件数',
  counter_accepted_count: '摄取计数完整性'
}

const issueMessages: Record<string, string> = {
  no_events: '统计窗口内没有可用于分析的事件。',
  ingestion_telemetry_incomplete: '事件事实与摄取计数尚未完全对齐。'
}

const statusClass = (status: string) => `quality-${status}`
const current = computed(() => data.value?.current || null)
const hasActiveRun = computed(() =>
  Boolean(data.value?.runs.some((run) => run.status === 'pending' || run.status === 'running'))
)

function clearPoll() {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer)
    pollTimer = null
  }
}

function schedulePoll() {
  clearPoll()
  if (!hasActiveRun.value) return
  pollTimer = window.setTimeout(() => loadData(false), 3000)
}

async function loadData(showLoading = true) {
  if (showLoading) loading.value = true
  try {
    data.value = await getSchoolDataQuality()
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '数据质量信息加载失败。'
    noticeTone.value = 'error'
  } finally {
    loading.value = false
    schedulePoll()
  }
}

async function startQualityRun() {
  if (running.value || hasActiveRun.value) return
  running.value = true
  notice.value = ''
  try {
    await runSchoolDataQuality(7)
    notice.value = '数据质量任务已提交。'
    noticeTone.value = 'success'
    await loadData(false)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '数据质量任务提交失败。'
    noticeTone.value = 'error'
  } finally {
    running.value = false
  }
}

function formatPercent(value: number) {
  return `${(Number(value || 0) * 100).toFixed(2)}%`
}

function formatDateTime(value: string | null) {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '-' : date.toLocaleString('zh-CN', { hour12: false })
}

function formatDay(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? '-'
    : `${date.getMonth() + 1}/${date.getDate()}`
}

function metricThreshold(metric: QualityMetric) {
  const direction = metric.thresholds.direction === 'low' ? '低于' : '高于'
  const amber = formatPercent(Number(metric.thresholds.amber || 0))
  const red = formatPercent(Number(metric.thresholds.red || 0))
  return `关注 ${direction} ${amber} · 阻断 ${direction} ${red}`
}

function issueText(issue: QualityIssue) {
  if (issueMessages[issue.code]) return issueMessages[issue.code]
  return `${metricLabels[issue.metric] || issue.metric}达到${issue.level === 'red' ? '阻断' : '关注'}阈值。`
}

function issueValue(issue: QualityIssue) {
  if (issue.metric.endsWith('_rate')) {
    return `实际 ${formatPercent(issue.value)} · 阈值 ${formatPercent(issue.threshold)}`
  }
  return `实际 ${issue.value} · 阈值 ${issue.threshold}`
}

function metricValue(report: DataQualityReport, key: string) {
  return report.metrics.find((metric) => metric.key === key)?.value || 0
}

function trendOption(keys: Array<{ key: string; label: string; inverse?: boolean }>): EChartsCoreOption {
  const reports = [...(data.value?.history || [])].reverse()
  const colors = ['#1f6feb', '#b45309', '#b42318', '#6d28d9', '#0f766e']
  return {
    color: colors,
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value: unknown) => `${Number(value).toFixed(2)}%`
    },
    legend: {
      top: 0,
      right: 0,
      itemWidth: 18,
      itemHeight: 3,
      textStyle: { color: '#64748b', fontSize: 12 }
    },
    grid: { top: 44, right: 18, bottom: 26, left: 48, containLabel: true },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: reports.map((report) => formatDay(report.window_end)),
      axisTick: { show: false },
      axisLabel: { color: '#64748b', fontSize: 12 },
      axisLine: { lineStyle: { color: '#d8e1ec' } }
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      axisLabel: { color: '#64748b', formatter: '{value}%' },
      splitLine: { lineStyle: { color: '#e2e8f0' } }
    },
    series: keys.map((item, index) => ({
      name: item.label,
      type: 'line',
      symbol: 'circle',
      symbolSize: 6,
      lineStyle: { width: 2, type: index % 2 ? 'dashed' : 'solid' },
      data: reports.map((report) => {
        const raw = metricValue(report, item.key)
        return Number(((item.inverse ? 1 - raw : raw) * 100).toFixed(2))
      })
    }))
  }
}

const anomalyTrendOption = computed(() =>
  trendOption([
    { key: 'duplicate_rate', label: '重复' },
    { key: 'invalid_event_rate', label: '无效' },
    { key: 'late_event_rate', label: '迟到' },
    { key: 'semantic_missing_rate', label: '语义缺失' },
    { key: 'client_offline_rate', label: '离线' }
  ])
)

const integrityTrendOption = computed(() =>
  trendOption([
    { key: 'opportunity_coverage_rate', label: '机会覆盖' },
    { key: 'v1_v2_difference_rate', label: 'V1/V2 一致', inverse: true }
  ])
)

function toggleRun(run: AnalyticsPipelineRun) {
  expandedRunId.value = expandedRunId.value === run.id ? null : run.id
}

onMounted(loadData)
onBeforeUnmount(clearPoll)
</script>

<template>
  <AppShell title="数据质量" eyebrow="学校管理员" :nav-items="navItems" natural-scroll>
    <section class="quality-page-heading">
      <div>
        <h2>分析数据质量闸门</h2>
        <p>每日检查事件摄取、语义映射、机会关联与 V1/V2 对账。红色状态会阻止后续分析。</p>
      </div>
      <div class="quality-page-actions">
        <a class="secondary-button" href="/api/v1/school-admin/analytics/quality/export/">导出 XLSX</a>
        <button
          class="primary-button"
          type="button"
          :disabled="running || hasActiveRun"
          :aria-busy="running || hasActiveRun"
          @click="startQualityRun"
        >
          {{ hasActiveRun ? '任务运行中' : running ? '正在提交' : '检查最近完整 7 日' }}
        </button>
      </div>
    </section>

    <NoticeLine v-if="notice" :message="notice" :tone="noticeTone" />

    <section v-if="loading" class="panel quality-loading" aria-live="polite">
      <strong>正在加载数据质量信息</strong>
      <span>请稍候</span>
    </section>

    <template v-else-if="data">
      <section v-if="!current" class="quality-empty-state">
        <div>
          <span>尚无报告</span>
          <h2>当前学校还没有数据质量基线</h2>
          <p>执行一次完整日检查后，质量指标和流水线记录会显示在这里。</p>
        </div>
        <button class="primary-button" type="button" :disabled="running || hasActiveRun" @click="startQualityRun">
          开始检查
        </button>
      </section>

      <template v-else>
        <section class="quality-gate-banner" :class="statusClass(current.status)">
          <div class="quality-gate-state">
            <span>当前质量闸门</span>
            <strong>{{ current.gate_passed ? '已通过' : '已阻断' }}</strong>
            <small>{{ current.status_label }} · {{ current.methodology_version }}</small>
          </div>
          <dl>
            <div><dt>统计窗口</dt><dd>{{ formatDateTime(current.window_start) }} 至 {{ formatDateTime(current.window_end) }}</dd></div>
            <div><dt>有效事件</dt><dd>{{ current.event_count }}</dd></div>
            <div><dt>摄取尝试</dt><dd>{{ current.ingestion_attempt_count }}</dd></div>
            <div><dt>生成时间</dt><dd>{{ formatDateTime(current.generated_at) }}</dd></div>
          </dl>
        </section>

        <section class="quality-metric-grid" aria-label="数据质量指标">
          <article v-for="metric in current.metrics" :key="metric.key" :class="statusClass(metric.level)">
            <header>
              <span>{{ metric.label }}</span>
              <b>{{ metric.level === 'green' ? '正常' : metric.level === 'amber' ? '关注' : '阻断' }}</b>
            </header>
            <strong>{{ formatPercent(metric.value) }}</strong>
            <small>{{ metricThreshold(metric) }}</small>
          </article>
        </section>

        <section v-if="data.history.length >= 2" class="quality-trend-grid">
          <EChartPanel
            title="异常率趋势"
            subtitle="重复、无效、迟到、语义缺失与客户端离线"
            :option="anomalyTrendOption"
            tall
          />
          <EChartPanel
            title="完整性趋势"
            subtitle="学习机会覆盖与 V1/V2 一致率"
            :option="integrityTrendOption"
            tall
          />
        </section>
        <section v-else class="quality-trend-pending">
          <strong>趋势数据正在积累</strong>
          <span>至少生成 2 期完整日质量报告后显示趋势图。</span>
        </section>

        <section class="quality-detail-grid">
          <article class="panel quality-issue-panel">
            <div class="panel-heading">
              <h2>当前问题</h2>
              <p>{{ current.issues.length ? `共 ${current.issues.length} 项需要处理` : '当前窗口未发现阈值问题' }}</p>
            </div>
            <div v-if="current.issues.length" class="quality-issue-list">
              <div v-for="issue in current.issues" :key="issue.code" :class="statusClass(issue.level)">
                <span>{{ issue.level === 'red' ? '阻断' : '关注' }}</span>
                <div>
                  <strong>{{ issueText(issue) }}</strong>
                  <small>{{ issueValue(issue) }}</small>
                </div>
              </div>
            </div>
            <p v-else class="quality-empty-copy">无需处理。</p>
          </article>

          <article class="panel quality-count-panel">
            <div class="panel-heading">
              <h2>对账计数</h2>
              <p>用于追踪问题来源，不作为学生评价依据。</p>
            </div>
            <dl>
              <div><dt>拒绝事件</dt><dd>{{ current.rejection_count }}</dd></div>
              <div><dt>语义未映射</dt><dd>{{ current.legacy_unmapped_count }}</dd></div>
              <div><dt>未关联 V1</dt><dd>{{ current.unlinked_legacy_count }}</dd></div>
              <div><dt>V1/V2 差异</dt><dd>{{ current.counts.v1_v2_difference_count || 0 }}</dd></div>
            </dl>
          </article>
        </section>
      </template>

      <section class="panel quality-run-panel">
        <div class="panel-heading split">
          <div>
            <h2>流水线运行记录</h2>
            <p>保留定时、手动和重试运行及各阶段结果。</p>
          </div>
          <span>{{ data.runs.length }} 条</span>
        </div>
        <div class="table-wrap">
          <table class="quality-run-table">
            <thead>
              <tr><th>触发</th><th>统计窗口</th><th>状态</th><th>尝试</th><th>完成时间</th><th>阶段</th></tr>
            </thead>
            <tbody>
              <template v-for="run in data.runs" :key="run.id">
                <tr>
                  <td>{{ run.trigger_label }}</td>
                  <td>{{ formatDay(run.window_start) }} 至 {{ formatDay(run.window_end) }}</td>
                  <td><span class="quality-status-pill" :class="statusClass(run.status)">{{ run.status_label }}</span></td>
                  <td>{{ run.attempt_no }}</td>
                  <td>{{ formatDateTime(run.finished_at) }}</td>
                  <td>
                    <button
                      class="quality-detail-button"
                      type="button"
                      :aria-expanded="expandedRunId === run.id"
                      @click="toggleRun(run)"
                    >
                      {{ expandedRunId === run.id ? '收起' : `查看 ${run.tasks.length}` }}
                    </button>
                  </td>
                </tr>
                <tr v-if="expandedRunId === run.id" class="quality-task-row">
                  <td colspan="6">
                    <div v-if="run.tasks.length" class="quality-task-list">
                      <div v-for="task in run.tasks" :key="task.id">
                        <span>{{ task.task_name }}</span>
                        <strong :class="statusClass(task.status)">{{ task.status_label }}</strong>
                        <small>{{ formatDateTime(task.finished_at) }}</small>
                      </div>
                    </div>
                    <p v-else>任务尚未开始执行。</p>
                    <p v-if="run.error_message" class="quality-run-error">{{ run.error_code }}：{{ run.error_message }}</p>
                  </td>
                </tr>
              </template>
              <tr v-if="!data.runs.length"><td colspan="6" class="empty">暂无流水线运行记录</td></tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </AppShell>
</template>
