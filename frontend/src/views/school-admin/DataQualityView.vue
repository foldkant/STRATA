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
  unconverted_old_event_rate: '旧事件未转换比例',
  learning_task_link_rate: '学习任务关联率',
  client_offline_rate: '客户端离线率',
  old_new_event_difference_rate: '新旧记录差异率',
  event_count: '有效事件数',
  recorded_accepted_event_count: '接收记录完整性'
}

const issueMessages: Record<string, string> = {
  no_events: '统计窗口内没有可用于分析的事件。',
  receive_counts_incomplete: '学习记录数量与接收记录数量尚未完全一致。'
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
    notice.value = error instanceof ApiError ? error.message : '学习数据检查结果加载失败。'
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
    notice.value = '学习数据检查任务已提交。'
    noticeTone.value = 'success'
    await loadData(false)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '学习数据检查任务提交失败。'
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
  return `提醒 ${direction} ${amber} · 不通过 ${direction} ${red}`
}

function issueText(issue: QualityIssue) {
  if (issueMessages[issue.code]) return issueMessages[issue.code]
  return `${metricLabels[issue.metric] || issue.metric}达到${issue.level === 'red' ? '不通过' : '提醒'}标准。`
}

function issueValue(issue: QualityIssue) {
  if (issue.metric.endsWith('_rate')) {
    return `实际 ${formatPercent(issue.value)} · 判断标准 ${formatPercent(issue.threshold)}`
  }
  return `实际 ${issue.value} · 判断标准 ${issue.threshold}`
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
    { key: 'unconverted_old_event_rate', label: '旧事件未转换' },
    { key: 'client_offline_rate', label: '离线' }
  ])
)

const integrityTrendOption = computed(() =>
  trendOption([
    { key: 'learning_task_link_rate', label: '任务关联' },
    { key: 'old_new_event_difference_rate', label: '新旧记录一致', inverse: true }
  ])
)

function toggleRun(run: AnalyticsPipelineRun) {
  expandedRunId.value = expandedRunId.value === run.id ? null : run.id
}

onMounted(loadData)
onBeforeUnmount(clearPoll)
</script>

<template>
  <AppShell title="数据检查" eyebrow="学校管理员" :nav-items="navItems" natural-scroll>
    <section class="quality-page-heading">
      <div>
        <h2>学习数据检查</h2>
        <p>检查学习记录是否完整、是否能正确转换，以及是否关联到对应课程和任务。</p>
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
      <strong>正在加载检查结果</strong>
      <span>请稍候</span>
    </section>

    <template v-else-if="data">
      <section v-if="!current" class="quality-empty-state">
        <div>
          <span>尚无报告</span>
          <h2>当前学校还没有检查记录</h2>
          <p>执行一次检查后，结果和自动检查记录会显示在这里。</p>
        </div>
        <button class="primary-button" type="button" :disabled="running || hasActiveRun" @click="startQualityRun">
          开始检查
        </button>
      </section>

      <template v-else>
        <section class="quality-gate-banner" :class="statusClass(current.status)">
          <div class="quality-gate-state">
            <span>当前检查结果</span>
            <strong>{{ current.checks_passed ? '通过' : '未通过' }}</strong>
            <small>{{ current.status_label }} · 最近一次完整检查</small>
          </div>
          <dl>
            <div><dt>统计窗口</dt><dd>{{ formatDateTime(current.window_start) }} 至 {{ formatDateTime(current.window_end) }}</dd></div>
            <div><dt>有效事件</dt><dd>{{ current.event_count }}</dd></div>
            <div><dt>接收尝试</dt><dd>{{ current.receive_attempt_count }}</dd></div>
            <div><dt>生成时间</dt><dd>{{ formatDateTime(current.generated_at) }}</dd></div>
          </dl>
        </section>

        <section class="quality-metric-grid" aria-label="学习数据检查指标">
          <article v-for="metric in current.metrics" :key="metric.key" :class="statusClass(metric.level)">
            <header>
              <span>{{ metric.label }}</span>
              <b>{{ metric.level === 'green' ? '正常' : metric.level === 'amber' ? '提醒' : '未通过' }}</b>
            </header>
            <strong>{{ formatPercent(metric.value) }}</strong>
            <small>{{ metricThreshold(metric) }}</small>
          </article>
        </section>

        <section v-if="data.history.length >= 2" class="quality-trend-grid">
          <EChartPanel
            title="异常率趋势"
            subtitle="重复、无效、延迟、旧事件未转换与客户端离线"
            :option="anomalyTrendOption"
            tall
          />
          <EChartPanel
            title="完整程度趋势"
            subtitle="学习任务关联与新旧记录一致率"
            :option="integrityTrendOption"
            tall
          />
        </section>
        <section v-else class="quality-trend-pending">
          <strong>趋势数据正在积累</strong>
          <span>至少生成 2 期完整日检查报告后显示趋势图。</span>
        </section>

        <section class="quality-detail-grid">
          <article class="panel quality-issue-panel">
            <div class="panel-heading">
              <h2>当前问题</h2>
              <p>{{ current.issues.length ? `共 ${current.issues.length} 项需要处理` : '当前时间范围未发现问题' }}</p>
            </div>
            <div v-if="current.issues.length" class="quality-issue-list">
              <div v-for="issue in current.issues" :key="issue.code" :class="statusClass(issue.level)">
                <span>{{ issue.level === 'red' ? '未通过' : '提醒' }}</span>
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
              <h2>数据核对</h2>
              <p>用于追踪问题来源，不作为学生评价依据。</p>
            </div>
            <dl>
              <div><dt>未接收记录</dt><dd>{{ current.rejected_event_count }}</dd></div>
              <div><dt>旧事件未转换</dt><dd>{{ current.unconverted_old_event_count }}</dd></div>
              <div><dt>未关联旧记录</dt><dd>{{ current.unlinked_old_event_count }}</dd></div>
              <div><dt>新旧记录差异</dt><dd>{{ current.counts.old_new_event_difference_count || 0 }}</dd></div>
            </dl>
          </article>
        </section>
      </template>

      <section class="panel quality-run-panel">
        <div class="panel-heading split">
          <div>
            <h2>自动检查记录</h2>
            <p>保留定时检查、手动检查和失败重试结果。</p>
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
                        <span>{{ task.task_label }}</span>
                        <strong :class="statusClass(task.status)">{{ task.status_label }}</strong>
                        <small>{{ formatDateTime(task.finished_at) }}</small>
                      </div>
                    </div>
                    <p v-else>任务尚未开始执行。</p>
                    <p v-if="run.error_message" class="quality-run-error">{{ run.error_code }}：{{ run.error_message }}</p>
                  </td>
                </tr>
              </template>
              <tr v-if="!data.runs.length"><td colspan="6" class="empty">暂无自动检查记录</td></tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </AppShell>
</template>
