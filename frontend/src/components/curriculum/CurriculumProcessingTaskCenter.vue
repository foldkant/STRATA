<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ApiError } from '@/api/client'
import {
  cancelCurriculumProcessingJob,
  createCurriculumProcessingJob,
  getCurriculumProcessingJobs,
  resumeCurriculumProcessingJob,
  retryCurriculumProcessingJob,
  type CurriculumProcessingJob,
  type CurriculumProcessingJobMode,
  type CurriculumProcessingJobPriority,
  type CurriculumProcessingJobStatus,
  type CurriculumProcessingJobsIndex,
  type CurriculumStandardVersion
} from '@/api/curriculumStandards'
import CurriculumConfirmDialog from './CurriculumConfirmDialog.vue'

const props = defineProps<{
  selectedVersion: CurriculumStandardVersion | null
}>()

const emit = defineEmits<{
  changed: [job: CurriculumProcessingJob]
}>()

const POLL_INTERVAL_MS = 5000
const TASK_PAGE_SIZE = 6
const OVERVIEW_ACTIVE_LIMIT = 4
const OVERVIEW_HISTORY_LIMIT = 2
const activeStatuses = new Set<CurriculumProcessingJobStatus>(['queued', 'running', 'cancelling'])
const terminalSuccessStatuses = new Set<CurriculumProcessingJobStatus>(['succeeded'])
type TaskScope = 'overview' | 'active' | 'history' | 'all' | CurriculumProcessingJobStatus

const fallbackStatuses: CurriculumProcessingJobsIndex['statuses'] = [
  { value: 'queued', label: '等待中' },
  { value: 'running', label: '运行中' },
  { value: 'succeeded', label: '已成功' },
  { value: 'failed', label: '失败' },
  { value: 'cancelling', label: '取消中' },
  { value: 'cancelled', label: '已取消' }
]
const fallbackModes: CurriculumProcessingJobsIndex['modes'] = [
  { value: 'auto', label: '自动选择原文读取方式' },
  { value: 'ocr', label: '逐页扫描文字识别' }
]
const fallbackPriorities: CurriculumProcessingJobsIndex['priorities'] = [
  { value: 'low', label: '批量处理（速度较慢）' },
  { value: 'normal', label: '正常处理' },
  { value: 'high', label: '优先处理' }
]

const jobs = ref<CurriculumProcessingJob[]>([])
const summary = ref<CurriculumProcessingJobsIndex['summary'] | null>(null)
const statuses = ref(fallbackStatuses)
const modes = ref(fallbackModes)
const priorities = ref(fallbackPriorities)
const taskScope = ref<TaskScope>('overview')
const visibleCount = ref(TASK_PAGE_SIZE)
const mode = ref<CurriculumProcessingJobMode>('auto')
const priority = ref<CurriculumProcessingJobPriority>('low')
const loading = ref(false)
const polling = ref(false)
const creating = ref(false)
const actingJobId = ref<number | null>(null)
const cancelTarget = ref<CurriculumProcessingJob | null>(null)
const feedback = ref('')
const feedbackTone = ref<'success' | 'error' | 'info'>('info')
const announcement = ref('')
const highlightedJobId = ref<number | null>(null)
let pollTimer: number | null = null
let unmounted = false
let requestInFlight = false
let refreshRequested = false
let initialScopeResolved = false
let previousStatuses = new Map<number, CurriculumProcessingJobStatus>()

function createdTimestamp(job: CurriculumProcessingJob) {
  const value = Date.parse(job.created_at)
  return Number.isFinite(value) ? value : job.id
}

const newestJobs = computed(() => (
  [...jobs.value].sort((left, right) => createdTimestamp(right) - createdTimestamp(left) || right.id - left.id)
))

const activeJobs = computed(() => {
  const statusOrder: Partial<Record<CurriculumProcessingJobStatus, number>> = {
    running: 0,
    cancelling: 1,
    queued: 2
  }
  return newestJobs.value
    .filter((job) => activeStatuses.has(job.status))
    .sort((left, right) => (
      (statusOrder[left.status] ?? 9) - (statusOrder[right.status] ?? 9)
      || createdTimestamp(left) - createdTimestamp(right)
      || left.id - right.id
    ))
})

const historyJobs = computed(() => newestJobs.value.filter((job) => !activeStatuses.has(job.status)))

const prioritizedActiveJobs = computed(() => {
  const highlighted = activeJobs.value.find((job) => job.id === highlightedJobId.value)
  if (!highlighted) return activeJobs.value
  const leading = activeJobs.value.filter((job) => (
    job.id !== highlighted.id && ['running', 'cancelling'].includes(job.status)
  ))
  const remaining = activeJobs.value.filter((job) => (
    job.id !== highlighted.id && !['running', 'cancelling'].includes(job.status)
  ))
  return [...leading, highlighted, ...remaining]
})

const scopedJobs = computed(() => {
  if (taskScope.value === 'overview') {
    return [
      ...prioritizedActiveJobs.value.slice(0, OVERVIEW_ACTIVE_LIMIT),
      ...historyJobs.value.slice(0, OVERVIEW_HISTORY_LIMIT)
    ]
  }
  if (taskScope.value === 'active') return prioritizedActiveJobs.value
  if (taskScope.value === 'history') return historyJobs.value
  if (taskScope.value === 'all') return newestJobs.value
  return newestJobs.value.filter((job) => job.status === taskScope.value)
})

const visibleJobs = computed(() => (
  taskScope.value === 'overview'
    ? scopedJobs.value
    : scopedJobs.value.slice(0, visibleCount.value)
))

const remainingJobs = computed(() => Math.max(0, scopedJobs.value.length - visibleJobs.value.length))
const hiddenActiveJobs = computed(() => Math.max(0, activeJobs.value.length - OVERVIEW_ACTIVE_LIMIT))
const hiddenHistoryJobs = computed(() => Math.max(0, historyJobs.value.length - OVERVIEW_HISTORY_LIMIT))

const scopeSummary = computed(() => {
  if (taskScope.value === 'overview') {
    const activeShown = Math.min(activeJobs.value.length, OVERVIEW_ACTIVE_LIMIT)
    const historyShown = Math.min(historyJobs.value.length, OVERVIEW_HISTORY_LIMIT)
    return `概览显示 ${activeShown + historyShown} 项：${activeShown} 个待处理任务、${historyShown} 条最近记录`
  }
  if (!scopedJobs.value.length) return '当前筛选范围内没有任务'
  if (taskScope.value === 'active') {
    return `当前共有 ${scopedJobs.value.length} 个待处理任务，已显示 ${visibleJobs.value.length} 个`
  }
  return `当前共有 ${scopedJobs.value.length} 项，已显示 ${visibleJobs.value.length} 项`
})

watch(taskScope, () => {
  visibleCount.value = TASK_PAGE_SIZE
})

function selectTaskScope(scope: TaskScope) {
  taskScope.value = scope
}

function showMoreJobs() {
  visibleCount.value = Math.min(scopedJobs.value.length, visibleCount.value + TASK_PAGE_SIZE)
}

function collapseJobs() {
  visibleCount.value = TASK_PAGE_SIZE
}

function activeReplacementFor(job: CurriculumProcessingJob) {
  return activeJobs.value.find((candidate) => (
    candidate.version === job.version && candidate.id !== job.id
  )) || null
}

function canRetryJob(job: CurriculumProcessingJob) {
  return job.can_retry && !activeReplacementFor(job)
}

function activeReplacementStatusLabel(job: CurriculumProcessingJob) {
  const replacement = activeReplacementFor(job)
  return replacement ? statusLabel(replacement) : ''
}

async function revealJob(jobId: number) {
  highlightedJobId.value = jobId
  taskScope.value = 'active'
  visibleCount.value = TASK_PAGE_SIZE
  await nextTick()
  document.getElementById(`curriculum-processing-job-${jobId}`)?.focus({ preventScroll: false })
}

const activeJobForSelectedVersion = computed(() => {
  if (!props.selectedVersion) return null
  return jobs.value.find((job) => (
    job.version === props.selectedVersion?.id && activeStatuses.has(job.status)
  )) || null
})

const selectedVersionIsDraft = computed(() => props.selectedVersion?.status === 'draft')

const summaryItems = computed(() => {
  const source = summary.value
  return [
    { label: '正在处理', value: source?.running || 0, tone: 'running' },
    { label: '等待处理', value: source?.queued || 0, tone: 'queued' },
    { label: '处理成功', value: source?.succeeded || 0, tone: 'succeeded' },
    { label: '历史失败', value: source?.failed || 0, tone: 'failed' }
  ]
})

const selectedVersionSubmitDisabled = computed(() => {
  if (!props.selectedVersion || !selectedVersionIsDraft.value || creating.value || actingJobId.value !== null) return true
  return Boolean(activeJobForSelectedVersion.value && activeJobForSelectedVersion.value.status !== 'queued')
})

const selectedVersionSubmitLabel = computed(() => {
  if (creating.value) return '正在提交'
  if (!selectedVersionIsDraft.value && props.selectedVersion) return '该版本已冻结'
  if (activeJobForSelectedVersion.value?.status === 'queued') {
    return actingJobId.value === activeJobForSelectedVersion.value.id ? '正在继续处理' : '继续处理'
  }
  if (activeJobForSelectedVersion.value?.status === 'running') return '正在处理原文'
  if (activeJobForSelectedVersion.value?.status === 'cancelling') return '正在取消任务'
  return '开始处理原文'
})

function clearPollTimer() {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer)
    pollTimer = null
  }
}

function schedulePoll() {
  clearPollTimer()
  if (unmounted || !summary.value?.active) return
  pollTimer = window.setTimeout(() => {
    void loadJobs(true)
  }, POLL_INTERVAL_MS)
}

function announceStatusChanges(nextJobs: CurriculumProcessingJob[]) {
  const messages: string[] = []
  nextJobs.forEach((job) => {
    const previous = previousStatuses.get(job.id)
    if (previous && activeStatuses.has(previous) && !activeStatuses.has(job.status)) {
      messages.push(`${job.standard_title} ${job.version_label}${terminalSuccessStatuses.has(job.status) ? '处理完成' : job.status_label}`)
      emit('changed', job)
    }
  })
  previousStatuses = new Map(nextJobs.map((job) => [job.id, job.status]))
  if (messages.length) announcement.value = messages.join('；')
}

async function loadJobs(silent = false) {
  if (requestInFlight) {
    refreshRequested = true
    return
  }
  clearPollTimer()
  requestInFlight = true
  if (silent) polling.value = true
  else loading.value = true
  try {
    const result = await getCurriculumProcessingJobs()
    if (unmounted) return
    announceStatusChanges(result.jobs)
    jobs.value = result.jobs
    summary.value = result.summary
    statuses.value = result.statuses.length ? result.statuses : fallbackStatuses
    modes.value = result.modes.length ? result.modes : fallbackModes
    priorities.value = result.priorities.length ? result.priorities : fallbackPriorities
    if (!initialScopeResolved) {
      initialScopeResolved = true
      taskScope.value = result.summary.active ? 'active' : 'history'
    }
  } catch (error) {
    if (unmounted) return
    feedback.value = error instanceof ApiError ? error.message : '原文处理记录加载失败，请稍后重试。'
    feedbackTone.value = 'error'
  } finally {
    requestInFlight = false
    if (!unmounted) {
      loading.value = false
      polling.value = false
      if (refreshRequested) {
        refreshRequested = false
        void loadJobs(true)
      } else {
        schedulePoll()
      }
    }
  }
}

async function createJob() {
  if (!props.selectedVersion || !selectedVersionIsDraft.value || creating.value || activeJobForSelectedVersion.value) return
  creating.value = true
  feedback.value = ''
  clearPollTimer()
  try {
    const job = await createCurriculumProcessingJob(props.selectedVersion.id, {
      mode: mode.value,
      priority: priority.value
    })
    feedback.value = `“${job.standard_title} ${job.version_label}”已提交处理。`
    feedbackTone.value = 'success'
    announcement.value = feedback.value
    emit('changed', job)
    await loadJobs(true)
    await revealJob(job.id)
  } catch (error) {
    feedback.value = error instanceof ApiError ? error.message : '原文处理任务未能创建，请检查版本状态后重试。'
    feedbackTone.value = 'error'
  } finally {
    creating.value = false
    schedulePoll()
  }
}

async function submitSelectedVersionJob() {
  const activeJob = activeJobForSelectedVersion.value
  if (activeJob?.status === 'queued') {
    await resumeJob(activeJob)
    return
  }
  await createJob()
}

async function resumeJob(job: CurriculumProcessingJob) {
  if (!job.can_resume || actingJobId.value !== null) return
  actingJobId.value = job.id
  feedback.value = ''
  clearPollTimer()
  try {
    const updated = await resumeCurriculumProcessingJob(job.id)
    feedback.value = `“${job.standard_title} ${job.version_label}”已重新提交，将继续处理。`
    feedbackTone.value = 'success'
    announcement.value = feedback.value
    emit('changed', updated)
    await loadJobs(true)
    await revealJob(updated.id)
  } catch (error) {
    feedback.value = error instanceof ApiError ? error.message : '任务未能继续处理，请检查系统服务后重试。'
    feedbackTone.value = 'error'
  } finally {
    actingJobId.value = null
    schedulePoll()
  }
}

async function retryJob(job: CurriculumProcessingJob) {
  if (!canRetryJob(job) || actingJobId.value !== null) return
  actingJobId.value = job.id
  feedback.value = ''
  clearPollTimer()
  try {
    const replacement = await retryCurriculumProcessingJob(job.id)
    feedback.value = `“${job.standard_title} ${job.version_label}”已重新提交处理。`
    feedbackTone.value = 'success'
    announcement.value = feedback.value
    emit('changed', replacement)
    await loadJobs(true)
    await revealJob(replacement.id)
  } catch (error) {
    feedback.value = error instanceof ApiError ? error.message : '任务重试失败，请根据错误信息修复后再试。'
    feedbackTone.value = 'error'
  } finally {
    actingJobId.value = null
    schedulePoll()
  }
}

async function confirmCancel() {
  const job = cancelTarget.value
  if (!job || actingJobId.value !== null) return
  actingJobId.value = job.id
  feedback.value = ''
  clearPollTimer()
  try {
    const updated = await cancelCurriculumProcessingJob(job.id)
    feedback.value = `“${job.standard_title} ${job.version_label}”正在安全取消。`
    feedbackTone.value = 'info'
    announcement.value = feedback.value
    cancelTarget.value = null
    emit('changed', updated)
    await loadJobs(true)
  } catch (error) {
    feedback.value = error instanceof ApiError ? error.message : '任务取消失败，请刷新任务状态后重试。'
    feedbackTone.value = 'error'
    cancelTarget.value = null
  } finally {
    actingJobId.value = null
    schedulePoll()
  }
}

function formatDate(value: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN') : '-'
}

function statusLabel(job: CurriculumProcessingJob) {
  return job.status_label || statuses.value.find((item) => item.value === job.status)?.label || job.status
}

function choiceLabel<T extends string>(choices: Array<{ value: T; label: string }>, value: T) {
  return choices.find((item) => item.value === value)?.label || value
}

function progressValue(job: CurriculumProcessingJob) {
  if (Number.isFinite(job.progress_percent)) return Math.min(100, Math.max(0, job.progress_percent))
  if (!job.progress_total) return 0
  return Math.min(100, Math.max(0, Math.round(job.progress_current / job.progress_total * 100)))
}

function displayResourceValue(value: unknown) {
  if (Array.isArray(value)) return value.join('、')
  if (value && typeof value === 'object') return Object.values(value).join('、')
  if (typeof value === 'boolean') return value ? '是' : '否'
  return String(value ?? '-')
}

function resourceLabel(job: CurriculumProcessingJob) {
  const labels: Record<string, string> = {
    queue: '处理通道',
    worker_concurrency: '同时处理数量',
    concurrency: '同时处理数量',
    cpu_cores: '使用的处理核心',
    cpu_affinity: '使用的处理核心',
    priority_class: '系统优先级',
    memory_limit: '内存上限',
    one_pdf_per_task: '每份 PDF 独立任务',
    result_state: '状态记录'
  }
  const entries = Object.entries(job.resource_limit || {})
  if (!entries.length) return '由系统统一安排'
  return entries.map(([key, value]) => {
    const displayValue = key === 'result_state' && value === 'database' ? '数据库' : displayResourceValue(value)
    return `${labels[key] || key}：${displayValue}`
  }).join('；')
}

onMounted(() => {
  void loadJobs()
})

onBeforeUnmount(() => {
  unmounted = true
  clearPollTimer()
})
</script>

<template>
  <section class="panel curriculum-task-center" aria-labelledby="curriculum-task-center-title" :aria-busy="loading || polling">
    <header class="task-center-heading">
      <div>
        <h2 id="curriculum-task-center-title">课程标准原文处理</h2>
        <p>系统逐份读取课程标准 PDF，必要时进行扫描文字识别，并生成便于检索和 AI 辅助读取的文本。离开本页面不会中断处理。</p>
      </div>
      <button class="secondary-button" type="button" :disabled="loading || polling" @click="loadJobs()">
        {{ loading ? '加载中' : polling ? '更新中' : '刷新状态' }}
      </button>
    </header>

    <div class="task-summary" aria-label="课程标准原文处理概况">
      <article v-for="item in summaryItems" :key="item.label" :class="`tone-${item.tone}`">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
      </article>
      <p>
        <strong>{{ summary?.active ? '当前有等待或正在处理的课程标准' : '当前没有待处理的课程标准' }}</strong>
        <span>{{ summary?.active ? '页面会自动更新进度。等待时间过长时，可以使用“继续处理”再次提交。' : '没有处理任务时，页面不会反复刷新。' }}</span>
      </p>
    </div>

    <form class="task-create-form" @submit.prevent="submitSelectedVersionJob">
      <div class="task-version-context">
        <span>待处理版本</span>
        <strong v-if="selectedVersion">{{ selectedVersion.official_title || selectedVersion.title }} · {{ selectedVersion.version_label }}</strong>
        <strong v-else>请先在“课程标准档案”中选择一个版本</strong>
        <small v-if="selectedVersion && !selectedVersionIsDraft">只有草稿版本可以重新处理原文。已提交复核或已经发布的版本不能修改。</small>
        <small v-else-if="activeJobForSelectedVersion?.status === 'queued'">该版本正在等待处理。如果长时间没有进度，可点击“继续处理”再次提交，原有记录仍会保留。</small>
        <small v-else-if="activeJobForSelectedVersion">该版本已有{{ statusLabel(activeJobForSelectedVersion) }}任务，无需重复创建。</small>
        <small v-else>批量导入时建议选择“批量处理”；需要尽快完成单份课标时再选择“优先处理”。</small>
      </div>
      <label>
        <span>处理方式</span>
        <AppSelect v-model="mode" :disabled="creating">
          <option v-for="item in modes" :key="item.value" :value="item.value">{{ item.label }}</option>
        </AppSelect>
      </label>
      <label>
        <span>处理顺序</span>
        <AppSelect v-model="priority" :disabled="creating">
          <option v-for="item in priorities" :key="item.value" :value="item.value">{{ item.label }}</option>
        </AppSelect>
      </label>
      <button
        class="primary-button"
        type="submit"
        :disabled="selectedVersionSubmitDisabled"
      >
        {{ selectedVersionSubmitLabel }}
      </button>
    </form>

    <p v-if="feedback" class="task-feedback" :class="`tone-${feedbackTone}`" :role="feedbackTone === 'error' ? 'alert' : 'status'">
      {{ feedback }}
    </p>
    <p class="sr-only" aria-live="polite" aria-atomic="true">{{ announcement }}</p>

    <div class="task-list-toolbar">
      <label>
        <span>显示范围</span>
        <AppSelect v-model="taskScope" aria-label="筛选原文处理记录显示范围">
          <option value="overview">当前任务与最近记录</option>
          <option value="active">全部待处理任务</option>
          <option value="history">全部历史记录</option>
          <option value="all">全部任务</option>
          <option v-for="item in statuses" :key="item.value" :value="item.value">{{ item.label }}</option>
        </AppSelect>
      </label>
      <div class="task-list-summary" aria-live="polite" aria-atomic="true">
        <strong>{{ scopeSummary }}</strong>
        <span>每项对应一个课程标准版本；详细信息按需展开。</span>
      </div>
    </div>

    <div class="task-list" aria-live="off">
      <article
        v-for="job in visibleJobs"
        :id="`curriculum-processing-job-${job.id}`"
        :key="job.id"
        class="task-card"
        :class="[`status-${job.status}`, { 'is-highlighted': highlightedJobId === job.id }]"
        tabindex="-1"
      >
        <header>
          <div>
            <span>{{ job.subject_name }} · {{ job.version_label }}</span>
            <h3>{{ job.standard_title }}</h3>
          </div>
          <span class="task-status" :class="`status-${job.status}`">
            <i aria-hidden="true"></i>{{ statusLabel(job) }}
          </span>
        </header>

        <div class="task-progress-block">
          <div>
            <strong>{{ job.stage_label || '等待处理原文' }}</strong>
            <span>{{ job.progress_current }} / {{ job.progress_total || '?' }} 页 · {{ progressValue(job) }}%</span>
          </div>
          <progress
            :value="progressValue(job)"
            max="100"
            :aria-label="`${job.standard_title} ${job.version_label}处理进度 ${progressValue(job)}%`"
          >{{ progressValue(job) }}%</progress>
        </div>

        <details class="task-details">
          <summary>
            <span>任务详情</span>
            <small>处理方式、时间和系统安排</small>
          </summary>
          <dl>
            <div><dt>处理方式</dt><dd>{{ job.mode_label || choiceLabel(modes, job.mode) }}</dd></div>
            <div><dt>优先级</dt><dd>{{ job.priority_label || choiceLabel(priorities, job.priority) }}</dd></div>
            <div><dt>操作人</dt><dd>{{ job.created_by_display || '-' }}</dd></div>
            <div><dt>创建时间</dt><dd>{{ formatDate(job.created_at) }}</dd></div>
            <div><dt>开始时间</dt><dd>{{ formatDate(job.started_at) }}</dd></div>
            <div><dt>完成时间</dt><dd>{{ formatDate(job.finished_at) }}</dd></div>
            <div class="task-resource"><dt>系统安排</dt><dd>{{ resourceLabel(job) }}</dd></div>
            <div v-if="job.retry_count"><dt>重试次数</dt><dd>{{ job.retry_count }}</dd></div>
          </dl>
        </details>

        <div v-if="job.status === 'failed'" class="task-error" role="alert">
          <strong>任务未完成{{ job.error_code ? `（${job.error_code}）` : '' }}</strong>
          <p>{{ job.error_message || '原文处理未完成，请检查 PDF 文件和系统服务后重试。' }}</p>
          <small>处理问题解决后可使用“重新提交”，原课程标准版本和操作记录不会被删除。</small>
        </div>

        <footer v-if="job.can_cancel || canRetryJob(job) || job.can_resume || activeReplacementFor(job)">
          <p v-if="activeReplacementFor(job)" class="task-retry-state" role="status">
            已重新提交，当前任务为“{{ activeReplacementStatusLabel(job) }}”。取消记录保留用于过程追溯。
          </p>
          <button
            v-if="job.can_resume"
            class="secondary-button"
            type="button"
            :disabled="actingJobId !== null"
            @click="resumeJob(job)"
          >{{ actingJobId === job.id ? '正在继续处理' : '继续处理' }}</button>
          <button
            v-if="canRetryJob(job)"
            class="secondary-button"
            type="button"
            :disabled="actingJobId !== null"
            @click="retryJob(job)"
          >{{ actingJobId === job.id ? '正在重新提交' : '重新提交' }}</button>
          <button
            v-if="job.can_cancel"
            class="danger-outline-button"
            type="button"
            :disabled="actingJobId !== null"
            @click="cancelTarget = job"
          >取消任务</button>
        </footer>
      </article>

      <div v-if="!visibleJobs.length" class="task-empty">
        <strong>{{ loading ? '正在加载原文处理记录' : '没有符合条件的原文处理记录' }}</strong>
        <p>{{ loading ? '加载完成后会自动显示。' : '选择课程标准版本并开始处理后，可以在这里查看逐页进度。' }}</p>
      </div>
    </div>

    <nav
      v-if="taskScope === 'overview' ? hiddenActiveJobs || hiddenHistoryJobs : scopedJobs.length > TASK_PAGE_SIZE"
      class="task-list-navigation"
      aria-label="原文处理记录翻页"
    >
      <p v-if="taskScope === 'overview'">概览保持精简；可按任务阶段查看完整记录。</p>
      <p v-else>已显示 {{ visibleJobs.length }} / {{ scopedJobs.length }} 项</p>
      <div>
        <template v-if="taskScope === 'overview'">
          <button
            v-if="hiddenActiveJobs"
            type="button"
            class="secondary-button"
            data-task-scope="active"
            @click="selectTaskScope('active')"
          >查看全部待处理任务（{{ activeJobs.length }}）</button>
          <button
            v-if="hiddenHistoryJobs"
            type="button"
            class="secondary-button"
            data-task-scope="history"
            @click="selectTaskScope('history')"
          >查看全部历史记录（{{ historyJobs.length }}）</button>
        </template>
        <template v-else>
          <button
            v-if="visibleJobs.length > TASK_PAGE_SIZE"
            type="button"
            class="secondary-button"
            @click="collapseJobs"
          >收起到前 {{ TASK_PAGE_SIZE }} 项</button>
          <button
            v-if="remainingJobs"
            type="button"
            class="secondary-button"
            data-action="show-more"
            @click="showMoreJobs"
          >查看更多（还有 {{ remainingJobs }} 项）</button>
        </template>
      </div>
    </nav>

    <CurriculumConfirmDialog
      :open="Boolean(cancelTarget)"
      title="取消课程标准原文处理"
      :message="`确认取消“${cancelTarget?.standard_title || ''} ${cancelTarget?.version_label || ''}”的原文处理？已经保存的逐页结果会保留，停止后可以重新提交。`"
      confirm-label="确认取消任务"
      :danger="true"
      :loading="actingJobId !== null"
      @close="cancelTarget = null"
      @confirm="confirmCancel"
    />
  </section>
</template>

<style scoped>
.curriculum-task-center {
  margin-top: 16px;
  padding: 0;
  overflow: hidden;
}

.task-center-heading,
.task-create-form,
.task-list-toolbar {
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 20px;
}

.task-center-heading > div,
.task-version-context {
  min-width: 0;
  display: grid;
  gap: 4px;
}

.task-center-heading h2,
.task-card h3,
.task-error p {
  margin: 0;
}

.task-center-heading p,
.task-list-summary span,
.task-version-context span,
.task-version-context small,
.task-card header > div > span,
.task-progress-block span,
.task-card dt,
.task-details summary small,
.task-list-navigation p,
.task-empty p {
  color: var(--muted);
}

.task-center-heading p {
  max-width: 760px;
  line-height: 1.55;
}

.task-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(110px, 1fr)) minmax(250px, 1.8fr);
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--primary) 3%, #fff);
}

.task-summary article,
.task-summary p {
  min-width: 0;
  margin: 0;
  border-right: 1px solid var(--line);
  padding: 10px 14px;
}

.task-summary article {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  border-left: 3px solid color-mix(in srgb, var(--primary) 38%, var(--line));
}

.task-summary article.tone-running { border-left-color: var(--primary); }
.task-summary article.tone-succeeded { border-left-color: #16a34a; }
.task-summary article.tone-failed { border-left-color: var(--danger); }

.task-summary article strong {
  font-size: 20px;
  font-variant-numeric: tabular-nums;
}

.task-summary p {
  display: grid;
  gap: 4px;
  border-right: 0;
  line-height: 1.45;
}

.task-summary p span {
  color: var(--muted);
  font-size: 12px;
}

.task-create-form {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) minmax(190px, .55fr) minmax(180px, .5fr) auto;
  align-items: end;
  background: #fff;
}

.task-create-form label,
.task-list-toolbar label {
  min-width: 0;
  display: grid;
  gap: 6px;
}

.task-create-form label > span,
.task-list-toolbar label > span {
  color: var(--muted);
  font-size: 12px;
  font-weight: 600;
}

.task-create-form :deep(.app-select),
.task-list-toolbar :deep(.app-select) {
  width: 100%;
  min-height: 44px;
}

.task-create-form > button,
.task-center-heading > button,
.task-list-toolbar button,
.task-card footer button {
  min-height: 44px;
}

.task-feedback {
  margin: 0;
  border-top: 1px solid var(--line);
  padding: 10px 20px;
  line-height: 1.5;
}

.task-feedback.tone-success { background: var(--success-bg); color: var(--success-text); }
.task-feedback.tone-error { background: #fef2f2; color: var(--danger); }
.task-feedback.tone-info {
  background: color-mix(in srgb, var(--primary) 7%, #fff);
  color: var(--primary-dark);
}

.task-list-toolbar {
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--primary) 3%, #fff);
}

.task-list-toolbar label {
  grid-template-columns: auto minmax(150px, 220px);
  align-items: center;
}

.task-list-summary {
  min-width: 0;
  display: grid;
  justify-items: end;
  gap: 3px;
  line-height: 1.4;
  text-align: right;
}

.task-list-summary span {
  font-size: 12px;
}

.task-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 420px), 1fr));
  gap: 12px;
  padding: 16px 20px 20px;
  background: color-mix(in srgb, var(--primary) 3%, #fff);
}

.task-card {
  min-width: 0;
  align-self: start;
  border: 1px solid var(--line);
  border-left: 4px solid color-mix(in srgb, var(--primary) 38%, var(--line));
  border-radius: 8px;
  background: #fff;
  overflow: hidden;
}

.task-card.status-running { border-left-color: var(--primary); }
.task-card.status-succeeded { border-left-color: #16a34a; }
.task-card.status-failed { border-left-color: var(--danger); }
.task-card.status-cancelling,
.task-card.status-cancelled { border-left-color: #64748b; }

.task-card.is-highlighted {
  outline: 3px solid var(--primary);
  outline-offset: 2px;
}

.task-card:focus-visible {
  outline: 3px solid var(--primary);
  outline-offset: 2px;
}

.task-card > header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px 10px;
}

.task-card header > div {
  min-width: 0;
  display: grid;
  gap: 4px;
}

.task-card h3 {
  font-size: 16px;
  line-height: 1.45;
}

.task-status {
  flex: 0 0 auto;
  min-height: 28px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border-radius: 999px;
  padding: 0 9px;
  background: color-mix(in srgb, var(--primary) 5%, #fff);
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
}

.task-status i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}

.task-status.status-running {
  background: color-mix(in srgb, var(--primary) 12%, #fff);
  color: var(--primary-dark);
}
.task-status.status-succeeded { background: var(--success-bg); color: var(--success-text); }
.task-status.status-failed { background: #fef2f2; color: var(--danger); }
.task-status.status-queued { background: #fff7ed; color: #9a3412; }

.task-progress-block {
  display: grid;
  gap: 8px;
  padding: 8px 16px 14px;
}

.task-progress-block > div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  line-height: 1.4;
}

.task-progress-block span {
  flex: 0 0 auto;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.task-progress-block progress {
  width: 100%;
  height: 8px;
  border: 0;
  border-radius: 999px;
  overflow: hidden;
  accent-color: var(--primary);
}

.task-progress-block progress::-webkit-progress-bar { background: #e2e8f0; }
.task-progress-block progress::-webkit-progress-value { background: var(--primary); }
.task-progress-block progress::-moz-progress-bar { background: var(--primary); }

.task-details {
  border-top: 1px solid var(--line);
}

.task-details summary {
  min-height: 44px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 16px;
  color: var(--primary-dark);
  cursor: pointer;
  list-style: none;
}

.task-details summary::-webkit-details-marker {
  display: none;
}

.task-details summary::before {
  content: '';
  flex: 0 0 auto;
  width: 7px;
  height: 7px;
  border-right: 2px solid currentColor;
  border-bottom: 2px solid currentColor;
  transform: rotate(-45deg);
  transition: transform 160ms ease;
}

.task-details[open] summary::before {
  transform: rotate(45deg);
}

.task-details summary:hover {
  background: color-mix(in srgb, var(--primary) 3%, #fff);
}

.task-details summary span {
  font-weight: 700;
}

.task-details summary small {
  margin-left: auto;
  font-size: 12px;
}

.task-details dl {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin: 0;
  border-top: 1px solid var(--line);
  padding: 12px 16px;
  gap: 10px 12px;
}

.task-details dl > div {
  min-width: 0;
  display: grid;
  gap: 3px;
}

.task-card dd {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
  line-height: 1.4;
  font-size: 13px;
}

.task-card .task-resource {
  grid-column: 1 / -1;
}

.task-error {
  border-top: 1px solid #fecaca;
  padding: 12px 16px;
  background: #fef2f2;
  color: var(--danger);
  line-height: 1.5;
}

.task-error p {
  margin-top: 4px;
  overflow-wrap: anywhere;
}

.task-error small {
  display: block;
  margin-top: 4px;
}

.task-card footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  border-top: 1px solid var(--line);
  padding: 10px 16px;
}

.task-retry-state {
  flex: 1 1 100%;
  margin: 0;
  color: var(--success-text);
  line-height: 1.5;
}

.task-list-navigation {
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border-top: 1px solid var(--line);
  padding: 12px 20px;
  background: #fff;
}

.task-list-navigation p {
  margin: 0;
  line-height: 1.45;
}

.task-list-navigation > div {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.task-list-navigation button {
  min-height: 44px;
}

.danger-outline-button {
  min-height: 44px;
  border: 1px solid #fecaca;
  border-radius: 6px;
  padding: 0 14px;
  background: #fff;
  color: var(--danger);
  cursor: pointer;
}

.task-empty {
  grid-column: 1 / -1;
  min-height: 150px;
  display: grid;
  place-content: center;
  gap: 5px;
  color: var(--muted);
  text-align: center;
}

.task-empty p {
  margin: 0;
}

button:focus-visible,
:where(.task-details summary):focus-visible,
:deep(.app-select:focus-within) {
  outline: 3px solid color-mix(in srgb, var(--primary) 28%, transparent);
  outline-offset: 2px;
}

button:disabled {
  cursor: not-allowed;
  opacity: .55;
}

@media (max-width: 1100px) {
  .task-summary {
    grid-template-columns: repeat(4, minmax(100px, 1fr));
  }

  .task-summary p {
    grid-column: 1 / -1;
    border-top: 1px solid var(--line);
  }

  .task-create-form {
    grid-template-columns: minmax(240px, 1fr) repeat(2, minmax(180px, .7fr));
  }

  .task-create-form > button {
    grid-column: 1 / -1;
    justify-self: end;
  }

}

@media (max-width: 700px) {
  .task-center-heading,
  .task-list-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .task-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .task-summary article:nth-child(2n) {
    border-right: 0;
  }

  .task-create-form {
    grid-template-columns: 1fr;
  }

  .task-create-form > button {
    grid-column: auto;
    justify-self: stretch;
  }

  .task-list-toolbar label {
    grid-template-columns: 1fr;
  }

  .task-list-summary {
    justify-items: start;
    text-align: left;
  }

  .task-list-navigation {
    align-items: stretch;
    flex-direction: column;
  }

  .task-list-navigation > div {
    justify-content: flex-start;
  }
}

@media (max-width: 420px) {
  .task-center-heading,
  .task-create-form,
  .task-list-toolbar,
  .task-list,
  .task-list-navigation {
    padding-right: 14px;
    padding-left: 14px;
  }

  .task-summary article {
    border-bottom: 1px solid var(--line);
  }

  .task-summary p {
    grid-column: 1 / -1;
  }

  .task-card > header,
  .task-progress-block > div {
    align-items: flex-start;
    flex-direction: column;
  }

  .task-details summary small {
    display: none;
  }

  .task-details dl {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .task-card footer {
    align-items: stretch;
    flex-direction: column;
  }

  .task-list-navigation > div,
  .task-list-navigation button {
    width: 100%;
  }
}

@media (prefers-reduced-motion: reduce) {
  * {
    scroll-behavior: auto !important;
    transition: none !important;
  }

  .task-details summary::before {
    transition: none !important;
  }
}
</style>
