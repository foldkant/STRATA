<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError } from '@/api/client'
import {
  archiveCurriculumStandardVersion,
  deleteCurriculumNode,
  discardCurriculumStandardVersion,
  getCurriculumStandard,
  getCurriculumStandards,
  getCurriculumStandardVersion,
  publishCurriculumStandardVersion,
  restoreCurriculumStandardVersion,
  setCurriculumStandardActive,
  submitCurriculumStandardVersionReview,
  type CurriculumAuditLog,
  type CurriculumDocumentType,
  type CurriculumNode,
  type CurriculumNodeType,
  type CurriculumProcessingJob,
  type CurriculumSchoolStage,
  type CurriculumStandard,
  type CurriculumStandardVersion
} from '@/api/curriculumStandards'
import AppShell from '@/layouts/AppShell.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import CurriculumConfirmDialog from '@/components/curriculum/CurriculumConfirmDialog.vue'
import CurriculumNodeEditorModal from '@/components/curriculum/CurriculumNodeEditorModal.vue'
import CurriculumPageReviewModal from '@/components/curriculum/CurriculumPageReviewModal.vue'
import CurriculumProcessingTaskCenter from '@/components/curriculum/CurriculumProcessingTaskCenter.vue'
import CurriculumReviewModal from '@/components/curriculum/CurriculumReviewModal.vue'
import CurriculumStandardEditorModal from '@/components/curriculum/CurriculumStandardEditorModal.vue'
import CurriculumVersionEditorModal from '@/components/curriculum/CurriculumVersionEditorModal.vue'
import CurriculumVersionCompareModal from '@/components/curriculum/CurriculumVersionCompareModal.vue'
import { superAdminNav } from './nav'

const navItems = superAdminNav('/super-admin/curriculum-standards')
const rows = ref<CurriculumStandard[]>([])
const query = ref('')
const schoolStage = ref<CurriculumSchoolStage | ''>('')
const documentType = ref<CurriculumDocumentType | ''>('')
const loading = ref(false)
const detailLoading = ref(false)
const notice = ref('')
const noticeTone = ref<'success' | 'warning' | 'error' | 'info'>('info')
const selectedStandard = ref<CurriculumStandard | null>(null)
const selectedVersion = ref<CurriculumStandardVersion | null>(null)
const workspaceSection = ref<'standards' | 'tasks'>('standards')
const detailTab = ref<'nodes' | 'text' | 'versions' | 'audit'>('nodes')
const activeNodeType = ref<CurriculumNodeType>('core_competency')
const standardPage = ref(1)
const nodePage = ref(1)
const standardEditor = ref(false)
const editingStandard = ref<CurriculumStandard | null>(null)
const versionEditor = ref(false)
const editingVersion = ref<CurriculumStandardVersion | null>(null)
const replacingVersion = ref<CurriculumStandardVersion | null>(null)
const nodeEditor = ref(false)
const editingNode = ref<CurriculumNode | null>(null)
const reviewEditor = ref(false)
const pageReviewer = ref(false)
const versionComparer = ref(false)
const actionTarget = ref<{ kind: 'submit_review' | 'publish' | 'archive' | 'restore' | 'discard'; version: CurriculumStandardVersion } | null>(null)
const standardStatusTarget = ref<CurriculumStandard | null>(null)
const deleteNodeTarget = ref<CurriculumNode | null>(null)
const actionBusy = ref(false)

const STANDARD_PAGE_SIZE = 8
const NODE_PAGE_SIZE = 8
const STRUCTURED_TEXT_PREVIEW_LENGTH = 1200

const nodeTypeOrder: CurriculumNodeType[] = [
  'core_competency',
  'course_objective',
  'course_content',
  'academic_quality'
]

const summary = computed(() => {
  const published = rows.value.filter((row) => row.is_active !== false && row.current_version?.status === 'published').length
  const k1k9 = rows.value.filter((row) => row.school_stage === 'k1_k9').length
  const k10k12 = rows.value.filter((row) => row.school_stage === 'k10_k12').length
  return [
    { label: '已登记标准', value: rows.value.length, detail: '主记录' },
    { label: '当前使用', value: published, detail: '已发布版本' },
    { label: '义务教育', value: k1k9, detail: 'K1—K9' },
    { label: '普通高中', value: k10k12, detail: 'K10—K12' }
  ]
})

const groupedNodes = computed(() => nodeTypeOrder.map((type) => ({
  type,
  label: nodeTypeLabel(type),
  nodes: (selectedVersion.value?.nodes || []).filter((node) => node.node_type === type)
})))

const structureCoverage = computed(() => new Set((selectedVersion.value?.nodes || []).map((node) => node.node_type)))

const standardPageCount = computed(() => Math.max(1, Math.ceil(rows.value.length / STANDARD_PAGE_SIZE)))
const paginatedRows = computed(() => {
  const start = (standardPage.value - 1) * STANDARD_PAGE_SIZE
  return rows.value.slice(start, start + STANDARD_PAGE_SIZE)
})
const standardRangeLabel = computed(() => {
  if (!rows.value.length) return '0 项'
  const start = (standardPage.value - 1) * STANDARD_PAGE_SIZE + 1
  const end = Math.min(rows.value.length, start + STANDARD_PAGE_SIZE - 1)
  return `第 ${start}—${end} 项，共 ${rows.value.length} 项`
})

const activeNodeGroup = computed(() => (
  groupedNodes.value.find((group) => group.type === activeNodeType.value) || groupedNodes.value[0]
))
const nodePageCount = computed(() => Math.max(1, Math.ceil((activeNodeGroup.value?.nodes.length || 0) / NODE_PAGE_SIZE)))
const paginatedNodes = computed(() => {
  const start = (nodePage.value - 1) * NODE_PAGE_SIZE
  return (activeNodeGroup.value?.nodes || []).slice(start, start + NODE_PAGE_SIZE)
})

const structuredTextIsTruncated = computed(() => (
  (selectedVersion.value?.structured_text?.length || 0) > STRUCTURED_TEXT_PREVIEW_LENGTH
))
const displayedStructuredText = computed(() => {
  const text = selectedVersion.value?.structured_text || ''
  if (text.length <= STRUCTURED_TEXT_PREVIEW_LENGTH) return text
  return `${text.slice(0, STRUCTURED_TEXT_PREVIEW_LENGTH).trimEnd()}\n\n……（当前为摘要预览）`
})

const contentCoverageCount = computed(() => nodeTypeOrder.filter((type) => structureCoverage.value.has(type)).length)
const standardAuditLogs = computed(() => [...(selectedStandard.value?.audit_logs || [])].sort((left, right) => (
  new Date(right.created_at).getTime() - new Date(left.created_at).getTime()
)))

function stageLabel(value: CurriculumSchoolStage) {
  return value === 'k1_k9' ? '义务教育（K1—K9）' : '普通高中（K10—K12）'
}

function documentTypeLabel(value: CurriculumDocumentType) {
  return value === 'curriculum_plan' ? '课程方案' : '学科课程标准'
}

function nodeTypeLabel(value: CurriculumNodeType) {
  return {
    core_competency: '核心素养',
    course_objective: '课程目标',
    course_content: '课程内容',
    academic_quality: '学业质量'
  }[value]
}

function pageLabel(node: CurriculumNode) {
  if (!node.source_page_start) return '原文页码未标注'
  if (!node.source_page_end || node.source_page_end === node.source_page_start) return `第 ${node.source_page_start} 页`
  return `第 ${node.source_page_start}—${node.source_page_end} 页`
}

function formatDate(value?: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN') : '-'
}

function versionStatusLabel(version: CurriculumStandardVersion) {
  return version.status_label || {
    draft: '草稿',
    published: '当前使用',
    review_pending: '待复核',
    reviewed: '已复核',
    archived: '已归档',
    discarded: '已丢弃'
  }[version.status]
}

function auditActionLabel(action: string) {
  return {
    standard_created: '创建课程标准主档',
    standard_updated: '更新课程标准主档',
    created: '创建课程标准版本',
    imported: '导入课程标准版本',
    draft_metadata_updated: '更新版本基本信息',
    content_item_created: '新增内容条目',
    content_item_updated: '更新内容条目',
    content_item_deleted: '删除内容条目',
    structured_text_replaced: '更新结构化文本',
    page_text_updated: '修订逐页文本',
    text_reprocessed: '重新处理课程标准原文',
    submitted_for_review: '提交课程标准复核',
    review_approved: '课程标准复核通过',
    review_returned: '课程标准退回修改',
    published: '发布为当前使用版本',
    superseded: '由新版本取代',
    archived: '归档课程标准版本',
    restored_as_current: '恢复为当前使用版本',
    draft_discarded: '丢弃课程标准草稿',
    pages_reviewed: '完成逐页原文复核',
    processing_job_queued: '加入原文处理队列',
    processing_job_started: '开始处理课程标准原文',
    processing_job_succeeded: '课程标准原文处理完成',
    processing_job_failed: '课程标准原文处理失败',
    processing_job_cancel_requested: '申请取消原文处理任务',
    processing_job_cancelled: '取消原文处理任务',
    processing_job_recovered: '恢复原文处理任务',
    processing_job_dispatch_failed: '原文处理任务派发失败',
    processing_job_dispatch_attempted: '重新派发原文处理任务',
    processing_job_redispatch_attempted: '再次派发原文处理任务',
    retrieval_index_rebuilt: '重建课程标准检索索引'
  }[action] || action
}

function auditVersionLabel(log: CurriculumAuditLog) {
  if (!log.version) return '课程标准主档'
  return selectedStandard.value?.versions?.find((version) => version.id === log.version)?.version_label || `版本 #${log.version}`
}

function auditDetailText(detail: Record<string, unknown>) {
  return JSON.stringify(detail, null, 2)
}

function setStandardPage(page: number) {
  standardPage.value = Math.min(standardPageCount.value, Math.max(1, page))
}

function setNodePage(page: number) {
  nodePage.value = Math.min(nodePageCount.value, Math.max(1, page))
}

function selectNodeType(type: CurriculumNodeType) {
  activeNodeType.value = type
  nodePage.value = 1
}

function closeStandardDetail() {
  selectedStandard.value = null
  selectedVersion.value = null
}

function moveTabFocus(event: KeyboardEvent, direction: -1 | 1 | 'first' | 'last') {
  const tablist = event.currentTarget as HTMLElement | null
  const tabs = Array.from(tablist?.querySelectorAll<HTMLElement>('[role="tab"]') || [])
  if (!tabs.length) return
  const currentIndex = Math.max(0, tabs.indexOf(event.target as HTMLElement))
  const nextIndex = direction === 'first'
    ? 0
    : direction === 'last'
      ? tabs.length - 1
      : (currentIndex + direction + tabs.length) % tabs.length
  tabs[nextIndex]?.focus()
  tabs[nextIndex]?.click()
}

async function load(resetPage = false) {
  if (resetPage) standardPage.value = 1
  loading.value = true
  try {
    const result = await getCurriculumStandards({
      q: query.value.trim(),
      school_stage: schoolStage.value,
      document_type: documentType.value
    })
    rows.value = result.standards
    setStandardPage(standardPage.value)
    if (selectedStandard.value) {
      const matching = rows.value.find((row) => row.id === selectedStandard.value?.id)
      if (!matching) {
        selectedStandard.value = null
        selectedVersion.value = null
      }
    }
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课程标准列表加载失败。'
    noticeTone.value = 'error'
  } finally {
    loading.value = false
  }
}

async function openStandard(row: CurriculumStandard, preferredVersionId?: number) {
  detailLoading.value = true
  selectedStandard.value = row
  selectedVersion.value = null
  nodePage.value = 1
  try {
    const detail = await getCurriculumStandard(row.id)
    selectedStandard.value = detail
    const preferred = detail.versions?.find((item) => item.id === preferredVersionId)
      || detail.current_version
      || detail.versions?.[0]
      || null
    if (preferred) selectedVersion.value = await getCurriculumStandardVersion(preferred.id)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课程标准详情加载失败。'
    noticeTone.value = 'error'
  } finally {
    detailLoading.value = false
  }
}

async function selectVersion(version: CurriculumStandardVersion) {
  detailLoading.value = true
  nodePage.value = 1
  try {
    selectedVersion.value = await getCurriculumStandardVersion(version.id)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课程标准版本加载失败。'
    noticeTone.value = 'error'
  } finally {
    detailLoading.value = false
  }
}

function resetFilters() {
  query.value = ''
  schoolStage.value = ''
  documentType.value = ''
  void load(true)
}

function openCreateStandard() {
  editingStandard.value = null
  standardEditor.value = true
}

function openEditStandard(row: CurriculumStandard) {
  editingStandard.value = row
  standardEditor.value = true
}

function openCreateVersion(replaces: CurriculumStandardVersion | null = null) {
  editingVersion.value = null
  replacingVersion.value = replaces
  versionEditor.value = true
}

function openEditVersion(version: CurriculumStandardVersion) {
  editingVersion.value = version
  replacingVersion.value = null
  versionEditor.value = true
}

function openCreateNode() {
  editingNode.value = null
  nodeEditor.value = true
}

function openEditNode(node: CurriculumNode) {
  editingNode.value = node
  nodeEditor.value = true
}

async function standardSaved(row: CurriculumStandard) {
  standardEditor.value = false
  editingStandard.value = null
  notice.value = '课程标准元数据已保存。'
  noticeTone.value = 'success'
  await load()
  await openStandard(row)
}

async function versionSaved(version: CurriculumStandardVersion) {
  versionEditor.value = false
  editingVersion.value = null
  replacingVersion.value = null
  notice.value = '课程标准版本草稿已保存，请复核结构化文本和内容条目后提交复核。'
  noticeTone.value = 'success'
  await load()
  if (selectedStandard.value) await openStandard(selectedStandard.value, version.id)
}

async function nodeSaved() {
  nodeEditor.value = false
  editingNode.value = null
  notice.value = '课程标准内容条目已保存。'
  noticeTone.value = 'success'
  if (selectedVersion.value) await selectVersion(selectedVersion.value)
}

async function confirmVersionAction() {
  if (!actionTarget.value) return
  actionBusy.value = true
  const target = actionTarget.value
  try {
    const version = target.kind === 'discard'
      ? (await discardCurriculumStandardVersion(target.version.id), null)
      : target.kind === 'submit_review'
        ? await submitCurriculumStandardVersionReview(target.version.id)
        : target.kind === 'publish'
          ? await publishCurriculumStandardVersion(target.version.id)
          : target.kind === 'restore'
            ? await restoreCurriculumStandardVersion(target.version.id)
            : await archiveCurriculumStandardVersion(target.version.id)
    notice.value = target.kind === 'discard'
      ? '课程标准草稿已丢弃；原文、处理结果和审计记录仍可查看。'
      : target.kind === 'submit_review'
        ? '课程标准版本已提交复核。'
        : target.kind === 'publish'
          ? '课程标准版本已发布为当前使用版本。'
          : target.kind === 'restore'
            ? '课程标准历史版本已恢复为当前使用版本。'
            : '课程标准版本已归档；历史引用仍可查看。'
    noticeTone.value = 'success'
    actionTarget.value = null
    await load()
    if (selectedStandard.value) await openStandard(selectedStandard.value, version?.id || target.version.id)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '版本状态更新失败。'
    noticeTone.value = 'error'
    actionTarget.value = null
  } finally {
    actionBusy.value = false
  }
}

async function confirmStandardStatus() {
  if (!standardStatusTarget.value) return
  const target = standardStatusTarget.value
  const nextActive = target.is_active === false
  const preferredVersionId = selectedVersion.value?.id
  actionBusy.value = true
  try {
    const updated = await setCurriculumStandardActive(target.id, nextActive)
    notice.value = nextActive
      ? '课程标准主档已启用，可继续供教师选择当前发布版本。'
      : '课程标准主档已停用，不再供教师新选择；已有评价方案中的历史引用仍会保留。'
    noticeTone.value = nextActive ? 'success' : 'warning'
    standardStatusTarget.value = null
    await load()
    await openStandard(updated, preferredVersionId)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课程标准主档状态更新失败。'
    noticeTone.value = 'error'
    standardStatusTarget.value = null
  } finally {
    actionBusy.value = false
  }
}

async function reviewSaved(version: CurriculumStandardVersion, approved: boolean) {
  reviewEditor.value = false
  notice.value = approved ? '课程标准版本已通过复核，可以发布。' : '课程标准版本已退回修改。'
  noticeTone.value = approved ? 'success' : 'warning'
  await load()
  if (selectedStandard.value) await openStandard(selectedStandard.value, version.id)
}

async function pagesChanged() {
  if (selectedVersion.value) await selectVersion(selectedVersion.value)
}

async function pagesReviewed(version: CurriculumStandardVersion) {
  selectedVersion.value = version
  notice.value = '逐页原文复核记录已保存。'
  noticeTone.value = 'success'
}

async function processingTaskChanged(job: CurriculumProcessingJob) {
  if (selectedVersion.value?.id !== job.version) return
  if (job.status === 'succeeded' || job.status === 'failed' || job.status === 'cancelled') {
    await selectVersion(selectedVersion.value)
  }
}

async function confirmDeleteNode() {
  if (!deleteNodeTarget.value || !selectedVersion.value) return
  actionBusy.value = true
  try {
    await deleteCurriculumNode(deleteNodeTarget.value.id)
    deleteNodeTarget.value = null
    notice.value = '课程标准内容条目已删除。'
    noticeTone.value = 'success'
    await selectVersion(selectedVersion.value)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '课程标准内容条目删除失败。'
    noticeTone.value = 'error'
    deleteNodeTarget.value = null
  } finally {
    actionBusy.value = false
  }
}

onMounted(() => load(true))
</script>

<template>
  <AppShell title="课程标准" eyebrow="超级管理员" :nav-items="navItems" natural-scroll>
    <NoticeLine v-if="notice" :message="notice" :tone="noticeTone" floating @dismiss="notice = ''" />

    <header class="console-page-heading curriculum-page-heading">
      <div>
        <h2>课程标准管理</h2>
        <p>集中管理权威原文、结构化文本和正式版本，为评价方案提供可核验的课程标准依据。</p>
      </div>
      <button class="primary-button" type="button" @click="openCreateStandard">登记课程标准</button>
    </header>

    <section class="curriculum-principle" aria-label="课程标准内容关系">
      <strong>课程标准内容关系</strong>
      <ol>
        <li v-for="(item, index) in ['核心素养', '课程目标', '课程内容', '学业质量']" :key="item">
          <span>{{ item }}</span><i v-if="index < 3" aria-hidden="true">→</i>
        </li>
      </ol>
      <p>用于建立评价依据和适用边界，不直接换算为学生分数。</p>
    </section>

    <section class="curriculum-summary" aria-label="课程标准概况">
      <article v-for="item in summary" :key="item.label">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
        <small>{{ item.detail }}</small>
      </article>
    </section>

    <nav
      class="curriculum-section-tabs"
      role="tablist"
      aria-label="课程标准管理分区"
      @keydown.left.prevent="moveTabFocus($event, -1)"
      @keydown.right.prevent="moveTabFocus($event, 1)"
      @keydown.home.prevent="moveTabFocus($event, 'first')"
      @keydown.end.prevent="moveTabFocus($event, 'last')"
    >
      <button
        id="curriculum-standards-tab"
        type="button"
        role="tab"
        :aria-selected="workspaceSection === 'standards'"
        :tabindex="workspaceSection === 'standards' ? 0 : -1"
        aria-controls="curriculum-standards-panel"
        :class="{ active: workspaceSection === 'standards' }"
        @click="workspaceSection = 'standards'"
      >
        <strong>课标档案</strong>
        <small>查询、复核与版本管理</small>
      </button>
      <button
        id="curriculum-tasks-tab"
        type="button"
        role="tab"
        :aria-selected="workspaceSection === 'tasks'"
        :tabindex="workspaceSection === 'tasks' ? 0 : -1"
        aria-controls="curriculum-tasks-panel"
        :class="{ active: workspaceSection === 'tasks' }"
        @click="workspaceSection = 'tasks'"
      >
        <strong>后台任务</strong>
        <small>查看 OCR 与文本处理进度</small>
      </button>
    </nav>

    <section
      v-if="workspaceSection === 'tasks'"
      id="curriculum-tasks-panel"
      class="curriculum-section-panel"
      role="tabpanel"
      aria-labelledby="curriculum-tasks-tab"
      tabindex="0"
    >
      <CurriculumProcessingTaskCenter
        :selected-version="selectedVersion"
        @changed="processingTaskChanged"
      />
    </section>

    <section
      v-else
      id="curriculum-standards-panel"
      class="panel curriculum-panel curriculum-section-panel"
      role="tabpanel"
      aria-labelledby="curriculum-standards-tab"
      tabindex="0"
    >
      <div class="panel-heading">
        <h2>课程标准目录</h2>
        <p>课程标准的历史版本不会被覆盖；教师只能在评价方案中选择已发布版本。</p>
      </div>

      <form class="toolbar curriculum-toolbar" @submit.prevent="load(true)">
        <label>
          <span>关键词</span>
          <input v-model="query" placeholder="名称、学科或学科代码" />
        </label>
        <label>
          <span>学段</span>
          <AppSelect v-model="schoolStage">
            <option value="">全部学段</option>
            <option value="k1_k9">义务教育（K1—K9）</option>
            <option value="k10_k12">普通高中（K10—K12）</option>
          </AppSelect>
        </label>
        <label>
          <span>文件类型</span>
          <AppSelect v-model="documentType">
            <option value="">全部类型</option>
            <option value="subject_standard">学科课程标准</option>
            <option value="curriculum_plan">课程方案</option>
          </AppSelect>
        </label>
        <button class="primary-button" type="submit" :disabled="loading">{{ loading ? '查询中' : '查询' }}</button>
        <button class="secondary-button" type="button" @click="resetFilters">重置</button>
      </form>

      <div class="curriculum-workspace" :class="{ 'has-selection': selectedStandard }">
        <div class="curriculum-list" :aria-busy="loading">
          <button
            v-for="row in paginatedRows"
            :key="row.id"
            type="button"
            :class="{ active: selectedStandard?.id === row.id }"
            @click="openStandard(row)"
          >
            <span class="curriculum-list-heading">
              <strong>{{ row.title }}</strong>
              <em :class="row.is_active === false ? 'is-inactive' : row.current_version ? 'is-published' : 'is-draft'">
                {{ row.is_active === false ? '已停用' : row.current_version ? '当前使用' : '尚未发布' }}
              </em>
            </span>
            <span>{{ row.subject_name }} · {{ stageLabel(row.school_stage) }}</span>
            <small>
              {{ documentTypeLabel(row.document_type) }}
              <template v-if="row.current_version"> · {{ row.current_version.version_label }}</template>
            </small>
          </button>
          <p v-if="!rows.length" class="curriculum-empty">{{ loading ? '正在加载课程标准' : '没有符合条件的课程标准' }}</p>
          <nav v-else class="curriculum-list-pagination" aria-label="课程标准目录分页">
            <span aria-live="polite">{{ standardRangeLabel }}</span>
            <div>
              <button type="button" :disabled="standardPage <= 1" @click="setStandardPage(standardPage - 1)">上一页</button>
              <strong>{{ standardPage }} / {{ standardPageCount }}</strong>
              <button type="button" :disabled="standardPage >= standardPageCount" @click="setStandardPage(standardPage + 1)">下一页</button>
            </div>
          </nav>
        </div>

        <div class="curriculum-detail" :aria-busy="detailLoading">
          <button v-if="selectedStandard" class="curriculum-mobile-back" type="button" @click="closeStandardDetail">
            <span aria-hidden="true">←</span> 返回课标目录
          </button>
          <div v-if="!selectedStandard" class="curriculum-detail-empty">
            <strong>选择一项课程标准</strong>
            <p>可查看版本、结构化文本、课程标准内容条目及其原文位置。</p>
          </div>
          <template v-else>
            <header class="curriculum-detail-header">
              <div>
                <span>
                  {{ selectedStandard.subject_name }} · {{ stageLabel(selectedStandard.school_stage) }}
                  · {{ selectedStandard.is_active === false ? '已停用' : '已启用' }}
                </span>
                <h3>{{ selectedStandard.title }}</h3>
                <p>{{ documentTypeLabel(selectedStandard.document_type) }} · 学科代码 {{ selectedStandard.subject_code }}</p>
              </div>
              <div class="curriculum-detail-actions">
                <button class="secondary-button" type="button" @click="openEditStandard(selectedStandard)">编辑元数据</button>
                <button class="secondary-button" type="button" :disabled="(selectedStandard.versions?.length || 0) < 2" @click="versionComparer = true">版本比较</button>
                <button
                  :class="selectedStandard.is_active === false ? 'secondary-button' : 'danger-outline-button'"
                  type="button"
                  :aria-pressed="selectedStandard.is_active !== false"
                  @click="standardStatusTarget = selectedStandard"
                >{{ selectedStandard.is_active === false ? '启用主档' : '停用主档' }}</button>
                <button class="primary-button" type="button" @click="openCreateVersion()">新增版本</button>
              </div>
            </header>

            <nav v-if="selectedStandard.versions?.length" class="curriculum-version-strip" aria-label="课程标准版本">
              <button
                v-for="version in selectedStandard.versions"
                :key="version.id"
                type="button"
                :class="[{ active: selectedVersion?.id === version.id }, `status-${version.status}`]"
                @click="selectVersion(version)"
              >
                <strong>{{ version.version_label }}</strong>
                <small>{{ versionStatusLabel(version) }}</small>
              </button>
            </nav>

            <div v-if="detailLoading" class="curriculum-detail-empty">正在加载版本内容</div>
            <div v-else-if="!selectedVersion" class="curriculum-detail-empty">
              <strong>尚无课程标准版本</strong>
              <p>上传 PDF 原文并生成结构化文本，复核完成后再发布。</p>
              <button class="primary-button" type="button" @click="openCreateVersion()">新增首个版本</button>
            </div>
            <template v-else>
              <section class="curriculum-version-overview">
                <div>
                  <span class="curriculum-status" :class="`status-${selectedVersion.status}`">{{ versionStatusLabel(selectedVersion) }}</span>
                  <strong>{{ selectedVersion.version_label }}</strong>
                  <small>{{ selectedVersion.issued_by || '发布机构未填写' }} · {{ selectedVersion.publication_year || '年份未填写' }}</small>
                </div>
                <dl>
                  <div><dt>内容条目</dt><dd>{{ selectedVersion.nodes?.length ?? selectedVersion.node_count ?? 0 }}</dd></div>
                  <div><dt>原文校验值</dt><dd :title="selectedVersion.pdf_sha256 || ''">{{ selectedVersion.pdf_sha256?.slice(0, 12) || '待生成' }}</dd></div>
                  <div><dt>文本处理</dt><dd>{{ selectedVersion.extraction_status_label || '状态未提供' }}</dd></div>
                  <div><dt>发布时间</dt><dd>{{ formatDate(selectedVersion.published_at) }}</dd></div>
                </dl>
                <div class="curriculum-version-actions">
                  <a v-if="selectedVersion.pdf_url" class="secondary-button" :href="selectedVersion.pdf_url" target="_blank" rel="noopener">查看 PDF 原文</a>
                  <a v-if="selectedVersion.source_url" class="secondary-button" :href="selectedVersion.source_url" target="_blank" rel="noopener">查看权威来源</a>
                  <button class="secondary-button" type="button" @click="pageReviewer = true">逐页原文核对</button>
                  <button v-if="selectedVersion.status === 'draft'" class="secondary-button" type="button" @click="openEditVersion(selectedVersion)">编辑草稿</button>
                  <button v-if="selectedVersion.status === 'draft'" class="primary-button" type="button" @click="actionTarget = { kind: 'submit_review', version: selectedVersion }">提交复核</button>
                  <button v-if="selectedVersion.status === 'draft'" class="danger-outline-button" type="button" @click="actionTarget = { kind: 'discard', version: selectedVersion }">丢弃草稿</button>
                  <button
                    v-if="selectedVersion.status === 'review_pending'"
                    class="primary-button"
                    type="button"
                    :disabled="Boolean(selectedVersion.unreviewed_page_count) || Boolean(selectedVersion.page_quality_counts?.failed)"
                    :title="selectedVersion.page_quality_counts?.failed ? '仍有处理失败页，请退回草稿修复' : selectedVersion.unreviewed_page_count ? '请先完成逐页原文核对' : ''"
                    @click="reviewEditor = true"
                  >登记复核结果</button>
                  <button v-if="selectedVersion.status === 'reviewed'" class="primary-button" type="button" @click="actionTarget = { kind: 'publish', version: selectedVersion }">发布为当前版本</button>
                  <button v-if="selectedVersion.status === 'published'" class="primary-button" type="button" @click="openCreateVersion(selectedVersion)">新增取代版本</button>
                  <button v-if="selectedVersion.status === 'published'" class="danger-outline-button" type="button" @click="actionTarget = { kind: 'archive', version: selectedVersion }">归档版本</button>
                  <button v-if="selectedVersion.status === 'archived'" class="secondary-button" type="button" @click="actionTarget = { kind: 'restore', version: selectedVersion }">恢复为当前使用版本</button>
                </div>
              </section>

              <details class="curriculum-governance-details">
                <summary>
                  <span>
                    <strong>处理与内容完整性</strong>
                    <small>展开查看逐页处理、复核与四类内容覆盖情况</small>
                  </span>
                  <span class="curriculum-governance-indicators">
                    <em :class="{ attention: selectedVersion.page_quality_counts?.failed }">
                      失败 {{ selectedVersion.page_quality_counts?.failed ?? 0 }} 页
                    </em>
                    <em>待复核 {{ selectedVersion.unreviewed_page_count ?? 0 }} 页</em>
                    <em>内容覆盖 {{ contentCoverageCount }} / 4</em>
                  </span>
                </summary>

                <p v-if="selectedVersion.extraction_message" class="curriculum-extraction-message" :class="`status-${selectedVersion.extraction_status}`">
                  {{ selectedVersion.extraction_message }}
                </p>

                <section class="curriculum-page-quality" aria-label="逐页文本处理状态">
                  <div><span>总页数</span><strong>{{ selectedVersion.page_count ?? 0 }}</strong></div>
                  <div><span>待复核</span><strong>{{ selectedVersion.unreviewed_page_count ?? 0 }}</strong></div>
                  <div><span>识别置信度较低</span><strong>{{ selectedVersion.page_quality_counts?.low_confidence ?? 0 }}</strong></div>
                  <div :class="{ attention: selectedVersion.page_quality_counts?.failed }"><span>处理失败</span><strong>{{ selectedVersion.page_quality_counts?.failed ?? 0 }}</strong></div>
                  <p v-if="selectedVersion.page_quality_counts?.failed">存在处理失败页，必须退回草稿修复后重新复核，当前版本不能发布。</p>
                </section>

                <p v-if="selectedVersion.governance_waiver_note" class="curriculum-governance-notice">
                  {{ selectedVersion.governance_waiver_note }}
                </p>

                <section class="curriculum-coverage" aria-label="结构化内容覆盖情况">
                  <div v-for="type in nodeTypeOrder" :key="type" :class="{ covered: structureCoverage.has(type) }">
                    <span aria-hidden="true">{{ structureCoverage.has(type) ? '✓' : '—' }}</span>
                    <strong>{{ nodeTypeLabel(type) }}</strong>
                  </div>
                  <p>提交复核前应按原文结构完成内容条目检查；不适用的内容需要在复核记录中说明。</p>
                </section>
              </details>

              <div
                class="curriculum-detail-tabs"
                role="tablist"
                aria-label="课程标准版本内容"
                @keydown.left.prevent="moveTabFocus($event, -1)"
                @keydown.right.prevent="moveTabFocus($event, 1)"
                @keydown.home.prevent="moveTabFocus($event, 'first')"
                @keydown.end.prevent="moveTabFocus($event, 'last')"
              >
                <button id="curriculum-detail-tab-nodes" type="button" role="tab" :aria-selected="detailTab === 'nodes'" :tabindex="detailTab === 'nodes' ? 0 : -1" aria-controls="curriculum-detail-panel-nodes" :class="{ active: detailTab === 'nodes' }" @click="detailTab = 'nodes'">内容条目</button>
                <button id="curriculum-detail-tab-text" type="button" role="tab" :aria-selected="detailTab === 'text'" :tabindex="detailTab === 'text' ? 0 : -1" aria-controls="curriculum-detail-panel-text" :class="{ active: detailTab === 'text' }" @click="detailTab = 'text'">结构化文本</button>
                <button id="curriculum-detail-tab-versions" type="button" role="tab" :aria-selected="detailTab === 'versions'" :tabindex="detailTab === 'versions' ? 0 : -1" aria-controls="curriculum-detail-panel-versions" :class="{ active: detailTab === 'versions' }" @click="detailTab = 'versions'">版本记录</button>
                <button id="curriculum-detail-tab-audit" type="button" role="tab" :aria-selected="detailTab === 'audit'" :tabindex="detailTab === 'audit' ? 0 : -1" aria-controls="curriculum-detail-panel-audit" :class="{ active: detailTab === 'audit' }" @click="detailTab = 'audit'">操作记录</button>
              </div>

              <div v-if="detailTab === 'nodes'" id="curriculum-detail-panel-nodes" class="curriculum-node-area" role="tabpanel" aria-labelledby="curriculum-detail-tab-nodes" tabindex="0">
                <header>
                  <div><strong>课程标准内容条目</strong><small>条目保留类型、页码和原文内容，供评价方案只读引用。</small></div>
                  <button v-if="selectedVersion.status === 'draft'" class="secondary-button" type="button" @click="openCreateNode">新增条目</button>
                </header>

                <nav
                  class="curriculum-node-type-tabs"
                  role="tablist"
                  aria-label="课程标准内容条目类型"
                  @keydown.left.prevent="moveTabFocus($event, -1)"
                  @keydown.right.prevent="moveTabFocus($event, 1)"
                  @keydown.home.prevent="moveTabFocus($event, 'first')"
                  @keydown.end.prevent="moveTabFocus($event, 'last')"
                >
                  <button
                    v-for="group in groupedNodes"
                    :id="`curriculum-node-tab-${group.type}`"
                    :key="group.type"
                    type="button"
                    role="tab"
                    :aria-selected="activeNodeType === group.type"
                    :tabindex="activeNodeType === group.type ? 0 : -1"
                    :aria-controls="`curriculum-node-panel-${group.type}`"
                    :class="{ active: activeNodeType === group.type }"
                    @click="selectNodeType(group.type)"
                  >
                    {{ group.label }} <span>{{ group.nodes.length }}</span>
                  </button>
                </nav>

                <section
                  v-if="activeNodeGroup"
                  :id="`curriculum-node-panel-${activeNodeGroup.type}`"
                  class="curriculum-node-group"
                  role="tabpanel"
                  :aria-labelledby="`curriculum-node-tab-${activeNodeGroup.type}`"
                  tabindex="0"
                >
                  <p v-if="!activeNodeGroup.nodes.length" class="curriculum-node-empty">尚未登记{{ activeNodeGroup.label }}内容条目</p>
                  <details v-for="node in paginatedNodes" :key="node.id" class="curriculum-node-card">
                    <summary>
                      <span><strong>{{ node.code }} · {{ node.title }}</strong><small>{{ pageLabel(node) }}</small></span>
                      <em>查看原文</em>
                    </summary>
                    <p>{{ node.content }}</p>
                    <footer v-if="selectedVersion.status === 'draft'">
                      <button type="button" @click="openEditNode(node)">编辑</button>
                      <button class="danger-link" type="button" @click="deleteNodeTarget = node">删除</button>
                    </footer>
                  </details>
                  <nav v-if="nodePageCount > 1" class="curriculum-node-pagination" aria-label="课程标准内容条目分页">
                    <button type="button" :disabled="nodePage <= 1" @click="setNodePage(nodePage - 1)">上一页</button>
                    <span>第 {{ nodePage }} / {{ nodePageCount }} 页</span>
                    <button type="button" :disabled="nodePage >= nodePageCount" @click="setNodePage(nodePage + 1)">下一页</button>
                  </nav>
                </section>
              </div>

              <div v-else-if="detailTab === 'text'" id="curriculum-detail-panel-text" class="curriculum-text-area" role="tabpanel" aria-labelledby="curriculum-detail-tab-text" tabindex="0">
                <header>
                  <div><strong>便于检索的结构化文本</strong><small>以 PDF 原文为最终核验依据，结构化文本不得改变原意。</small></div>
                  <div class="curriculum-text-actions">
                    <span>{{ (selectedVersion.structured_text?.length || 0).toLocaleString('zh-CN') }} 字符</span>
                    <a v-if="selectedVersion.structured_markdown_url" :href="selectedVersion.structured_markdown_url">下载 Markdown</a>
                    <a v-if="selectedVersion.structured_jsonl_url" :href="selectedVersion.structured_jsonl_url">下载 JSONL</a>
                  </div>
                </header>
                <template v-if="selectedVersion.structured_text">
                  <pre>{{ displayedStructuredText }}</pre>
                  <p v-if="structuredTextIsTruncated" class="curriculum-text-preview-note">
                    为避免页面过长，当前仅显示前 {{ STRUCTURED_TEXT_PREVIEW_LENGTH.toLocaleString('zh-CN') }} 个字符。
                    <button class="button-link" type="button" @click="pageReviewer = true">按页查看完整文本</button>
                    ，也可下载 Markdown 或 JSONL 文件。
                  </p>
                </template>
                <p v-else class="curriculum-empty">尚未生成结构化文本，请编辑草稿补充或重新解析 PDF。</p>
              </div>

              <div v-else-if="detailTab === 'versions'" id="curriculum-detail-panel-versions" class="curriculum-history-area" role="tabpanel" aria-labelledby="curriculum-detail-tab-versions" tabindex="0">
                <table>
                  <thead><tr><th>版本</th><th>状态</th><th>发布年份</th><th>实施年份</th><th>取代版本</th><th>更新时间</th></tr></thead>
                  <tbody>
                    <tr v-for="version in selectedStandard.versions || []" :key="version.id">
                      <td data-label="版本"><button class="button-link" type="button" @click="selectVersion(version)">{{ version.version_label }}</button></td>
                      <td data-label="状态"><span class="curriculum-status" :class="`status-${version.status}`">{{ versionStatusLabel(version) }}</span></td>
                      <td data-label="发布年份">{{ version.publication_year || '-' }}</td>
                      <td data-label="实施年份">{{ version.effective_year || '-' }}</td>
                      <td data-label="取代版本">{{ selectedStandard.versions?.find((item) => item.id === version.replaces_version)?.version_label || '-' }}</td>
                      <td data-label="更新时间">{{ formatDate(version.updated_at) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <div v-else id="curriculum-detail-panel-audit" class="curriculum-audit-area" role="tabpanel" aria-labelledby="curriculum-detail-tab-audit" tabindex="0">
                <header>
                  <div>
                    <strong>课程标准操作记录</strong>
                    <small>记录主档、版本、原文处理与复核发布等关键操作，按时间倒序呈现。</small>
                  </div>
                  <span>共 {{ standardAuditLogs.length }} 条</span>
                </header>
                <ol v-if="standardAuditLogs.length" class="curriculum-audit-timeline">
                  <li v-for="log in standardAuditLogs" :key="log.id">
                    <span class="curriculum-audit-marker" aria-hidden="true"></span>
                    <article>
                      <header>
                        <strong>{{ auditActionLabel(log.action) }}</strong>
                        <time :datetime="log.created_at">{{ formatDate(log.created_at) }}</time>
                      </header>
                      <p>
                        <span>操作人：{{ log.actor || '系统任务' }}</span>
                        <span>对象：{{ auditVersionLabel(log) }}</span>
                      </p>
                      <details v-if="Object.keys(log.detail || {}).length">
                        <summary>查看记录详情</summary>
                        <pre>{{ auditDetailText(log.detail) }}</pre>
                      </details>
                    </article>
                  </li>
                </ol>
                <p v-else class="curriculum-audit-empty">尚无课程标准操作记录。</p>
              </div>
            </template>
          </template>
        </div>
      </div>
    </section>

    <CurriculumStandardEditorModal
      v-if="standardEditor"
      :draft="editingStandard"
      @close="standardEditor = false"
      @saved="standardSaved"
    />
    <CurriculumVersionEditorModal
      v-if="versionEditor && selectedStandard"
      :standard="selectedStandard"
      :draft="editingVersion"
      :replaces="replacingVersion"
      @close="versionEditor = false"
      @saved="versionSaved"
    />
    <CurriculumNodeEditorModal
      v-if="nodeEditor && selectedVersion"
      :version="selectedVersion"
      :draft="editingNode"
      @close="nodeEditor = false"
      @saved="nodeSaved"
    />
    <CurriculumConfirmDialog
      :open="Boolean(actionTarget)"
      :title="actionTarget?.kind === 'publish' ? '发布课程标准版本' : actionTarget?.kind === 'submit_review' ? '提交课程标准复核' : actionTarget?.kind === 'restore' ? '恢复为当前使用版本' : actionTarget?.kind === 'discard' ? '丢弃课程标准草稿' : '归档课程标准版本'"
      :message="actionTarget?.kind === 'publish'
        ? `确认发布“${actionTarget?.version.version_label || ''}”。发布后原文、结构化文本和内容条目将被冻结。`
        : actionTarget?.kind === 'submit_review'
          ? `确认将“${actionTarget?.version.version_label || ''}”提交复核。提交后需登记复核结果，复核通过后才能发布。`
          : actionTarget?.kind === 'restore'
            ? `确认将“${actionTarget?.version.version_label || ''}”恢复为当前使用版本。现有当前版本将转为已归档，历史记录保持不变。`
            : actionTarget?.kind === 'discard'
              ? `确认丢弃草稿“${actionTarget?.version.version_label || ''}”。丢弃后不能继续编辑或提交复核，但原文、处理结果和审计记录仍会保留。`
              : `确认归档“${actionTarget?.version.version_label || ''}”。该版本不再供新评价方案选择，但历史引用仍会保留。`"
      :confirm-label="actionTarget?.kind === 'publish' ? '确认发布' : actionTarget?.kind === 'submit_review' ? '提交复核' : actionTarget?.kind === 'restore' ? '确认恢复' : actionTarget?.kind === 'discard' ? '确认丢弃' : '确认归档'"
      :danger="actionTarget?.kind === 'archive' || actionTarget?.kind === 'discard'"
      :loading="actionBusy"
      @close="actionTarget = null"
      @confirm="confirmVersionAction"
    />
    <CurriculumConfirmDialog
      :open="Boolean(deleteNodeTarget)"
      title="删除课程标准内容条目"
      :message="`确认删除“${deleteNodeTarget?.title || ''}”。仅草稿内容条目可删除。`"
      confirm-label="确认删除"
      :danger="true"
      :loading="actionBusy"
      @close="deleteNodeTarget = null"
      @confirm="confirmDeleteNode"
    />
    <CurriculumConfirmDialog
      :open="Boolean(standardStatusTarget)"
      :title="standardStatusTarget?.is_active === false ? '启用课程标准主档' : '停用课程标准主档'"
      :message="standardStatusTarget?.is_active === false
        ? `确认启用“${standardStatusTarget?.title || ''}”。启用后，教师可重新选择其当前发布版本作为评价依据。`
        : `确认停用“${standardStatusTarget?.title || ''}”。停用后不再供教师新选择，但已有评价方案的历史引用和审计记录仍会保留。`"
      :confirm-label="standardStatusTarget?.is_active === false ? '确认启用' : '确认停用'"
      :danger="standardStatusTarget?.is_active !== false"
      :loading="actionBusy"
      @close="standardStatusTarget = null"
      @confirm="confirmStandardStatus"
    />
    <CurriculumReviewModal
      v-if="reviewEditor && selectedVersion"
      :version="selectedVersion"
      @close="reviewEditor = false"
      @saved="reviewSaved"
    />
    <CurriculumPageReviewModal
      v-if="pageReviewer && selectedVersion"
      :version="selectedVersion"
      @close="pageReviewer = false"
      @changed="pagesChanged"
      @reviewed="pagesReviewed"
    />
    <CurriculumVersionCompareModal
      v-if="versionComparer && selectedStandard"
      :standard="selectedStandard"
      @close="versionComparer = false"
    />
  </AppShell>
</template>

<style scoped>
.curriculum-page-heading {
  align-items: center;
}

.curriculum-principle {
  display: flex;
  align-items: center;
  gap: 16px;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  padding: 10px 14px;
  background: #f8fbff;
}

.curriculum-principle > strong {
  flex: 0 0 auto;
  color: #1e3a8a;
}

.curriculum-principle ol {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.curriculum-principle li {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #1d4ed8;
  font-size: 12px;
}

.curriculum-principle i {
  color: #93a4bd;
  font-style: normal;
}

.curriculum-principle p {
  margin: 0 0 0 auto;
  color: var(--muted);
  font-size: 12px;
  text-align: right;
}

.curriculum-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-top: 16px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
}

.curriculum-summary article {
  display: grid;
  gap: 4px;
  padding: 15px 18px;
  border-right: 1px solid var(--line);
}

.curriculum-summary article:last-child {
  border-right: 0;
}

.curriculum-summary span,
.curriculum-summary small {
  color: var(--muted);
}

.curriculum-summary strong {
  font-size: 24px;
  font-variant-numeric: tabular-nums;
}

.curriculum-section-tabs {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 16px;
  border-bottom: 1px solid var(--line);
}

.curriculum-section-tabs button {
  min-height: 58px;
  display: grid;
  gap: 3px;
  border: 1px solid transparent;
  border-bottom: 3px solid transparent;
  border-radius: 8px 8px 0 0;
  padding: 8px 16px;
  background: transparent;
  color: var(--muted);
  text-align: left;
  cursor: pointer;
}

.curriculum-section-tabs button:hover {
  background: #f8fafc;
}

.curriculum-section-tabs button.active {
  border-color: var(--line);
  border-bottom-color: var(--primary);
  background: #fff;
  color: var(--primary-dark);
}

.curriculum-section-tabs small {
  font-size: 12px;
  font-weight: 400;
}

.curriculum-section-panel:focus-visible {
  outline: 3px solid rgba(37, 99, 235, .28);
  outline-offset: 3px;
}

.curriculum-panel {
  margin-top: 16px;
  padding: 0;
  overflow: hidden;
}

.curriculum-panel > .panel-heading,
.curriculum-toolbar {
  padding: 18px 20px;
}

.curriculum-toolbar {
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
}

.curriculum-workspace {
  min-height: 620px;
  display: grid;
  grid-template-columns: minmax(300px, 360px) minmax(0, 1fr);
}

.curriculum-list {
  border-right: 1px solid var(--line);
  background: #f8fafc;
}

.curriculum-list > button {
  width: 100%;
  min-height: 84px;
  display: grid;
  gap: 4px;
  border: 0;
  border-bottom: 1px solid var(--line);
  border-left: 4px solid transparent;
  padding: 12px 14px 12px 10px;
  background: transparent;
  color: var(--text);
  text-align: left;
  cursor: pointer;
  transition: background-color 180ms ease, border-color 180ms ease;
}

.curriculum-list > button:hover,
.curriculum-list > button.active {
  background: #fff;
  border-left-color: var(--primary);
}

.curriculum-list-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.curriculum-list-heading strong {
  line-height: 1.45;
}

.curriculum-list-heading em {
  flex: 0 0 auto;
  border-radius: 999px;
  padding: 3px 7px;
  font-size: 11px;
  font-style: normal;
  font-weight: 600;
}

.curriculum-list-heading .is-published {
  background: #e8f7ef;
  color: #166534;
}

.curriculum-list-heading .is-draft {
  background: #f1f5f9;
  color: #64748b;
}

.curriculum-list-heading .is-inactive {
  background: #fff1f2;
  color: #be123c;
}

.curriculum-list > button > span:not(.curriculum-list-heading),
.curriculum-list > button > small {
  color: var(--muted);
  line-height: 1.45;
}

.curriculum-list-pagination {
  display: grid;
  gap: 8px;
  border-top: 1px solid var(--line);
  padding: 12px;
  background: #fff;
  color: var(--muted);
  font-size: 12px;
}

.curriculum-list-pagination > div {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: 8px;
}

.curriculum-list-pagination button,
.curriculum-node-pagination button {
  min-height: 44px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 0 12px;
  background: #fff;
  color: var(--text);
  cursor: pointer;
}

.curriculum-list-pagination button:disabled,
.curriculum-node-pagination button:disabled {
  color: #94a3b8;
  cursor: not-allowed;
}

.curriculum-empty,
.curriculum-detail-empty {
  min-height: 220px;
  display: grid;
  place-content: center;
  gap: 8px;
  margin: 0;
  padding: 24px;
  color: var(--muted);
  text-align: center;
}

.curriculum-detail-empty p {
  margin: 0;
}

.curriculum-detail {
  min-width: 0;
  background: #fff;
}

.curriculum-mobile-back {
  display: none;
}

.curriculum-detail-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 20px;
}

.curriculum-detail-header span,
.curriculum-detail-header p {
  color: var(--muted);
}

.curriculum-detail-header h3 {
  margin: 5px 0;
  font-size: 20px;
  line-height: 1.4;
}

.curriculum-detail-header p {
  margin: 0;
}

.curriculum-detail-actions,
.curriculum-version-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.curriculum-version-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  padding: 10px 20px;
  background: #f8fafc;
}

.curriculum-version-strip button {
  min-width: 116px;
  min-height: 48px;
  display: grid;
  gap: 3px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 7px 10px;
  background: #fff;
  color: var(--text);
  text-align: left;
  cursor: pointer;
}

.curriculum-version-strip button.active {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px rgba(37, 99, 235, .12);
}

.curriculum-version-strip small {
  color: var(--muted);
}

.curriculum-version-overview {
  display: grid;
  grid-template-columns: minmax(170px, .8fr) minmax(260px, 1fr) minmax(220px, 1.2fr);
  align-items: center;
  gap: 18px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--line);
}

.curriculum-version-overview > div:first-child {
  display: grid;
  gap: 5px;
}

.curriculum-version-overview > div:first-child small {
  color: var(--muted);
  line-height: 1.4;
}

.curriculum-status {
  width: fit-content;
  display: inline-flex;
  align-items: center;
  min-height: 25px;
  border-radius: 999px;
  padding: 0 8px;
  background: #f1f5f9;
  color: #475569;
  font-size: 12px;
  font-weight: 600;
}

.curriculum-status.status-published {
  background: #e8f7ef;
  color: #166534;
}

.curriculum-status.status-draft {
  background: #fff4dd;
  color: #9a4f08;
}

.curriculum-status.status-review_pending {
  background: #fef3c7;
  color: #92400e;
}

.curriculum-status.status-reviewed {
  background: #e0e7ff;
  color: #3730a3;
}

.curriculum-status.status-archived {
  background: #f1f5f9;
  color: #64748b;
}

.curriculum-status.status-discarded {
  border-color: #cbd5e1;
  background: #f1f5f9;
  color: #475569;
}

.curriculum-version-overview dl {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin: 0;
}

.curriculum-governance-details {
  border-bottom: 1px solid var(--line);
  background: #fbfdff;
}

.curriculum-governance-details > summary {
  min-height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 20px;
  cursor: pointer;
}

.curriculum-governance-details > summary::marker {
  color: var(--primary);
}

.curriculum-governance-details > summary > span:first-child {
  display: grid;
  gap: 3px;
}

.curriculum-governance-details > summary small {
  color: var(--muted);
}

.curriculum-governance-indicators {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
}

.curriculum-governance-indicators em {
  border-radius: 999px;
  padding: 5px 9px;
  background: #eef2f7;
  color: #475569;
  font-size: 12px;
  font-style: normal;
  white-space: nowrap;
}

.curriculum-governance-indicators em.attention {
  background: #fee2e2;
  color: #b42318;
}

.curriculum-extraction-message {
  margin: 0;
  border-bottom: 1px solid var(--line);
  padding: 10px 20px;
  background: #f8fafc;
  color: var(--muted);
  line-height: 1.55;
}

.curriculum-extraction-message.status-failed,
.curriculum-extraction-message.status-needs_ocr {
  background: #fff7ed;
  color: #9a3412;
}

.curriculum-page-quality {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  padding: 12px 20px;
  border-bottom: 1px solid var(--line);
  background: #fbfdff;
}

.curriculum-page-quality > div {
  display: grid;
  gap: 3px;
  border-left: 3px solid #cbd5e1;
  padding: 6px 10px;
}

.curriculum-page-quality > div.attention {
  border-left-color: #dc2626;
  background: #fef2f2;
  color: #b42318;
}

.curriculum-page-quality span {
  color: var(--muted);
  font-size: 12px;
}

.curriculum-page-quality strong {
  font-size: 18px;
  font-variant-numeric: tabular-nums;
}

.curriculum-page-quality p {
  grid-column: 1 / -1;
  margin: 0;
  color: #b42318;
  font-size: 12px;
}

.curriculum-governance-notice {
  margin: 0;
  border-bottom: 1px solid #fed7aa;
  padding: 10px 20px;
  background: #fff7ed;
  color: #9a3412;
  line-height: 1.55;
}

.curriculum-version-overview dl > div {
  min-width: 0;
  display: grid;
  gap: 3px;
  border-left: 1px solid var(--line);
  padding-left: 12px;
}

.curriculum-version-overview dt {
  color: var(--muted);
  font-size: 12px;
}

.curriculum-version-overview dd {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.danger-outline-button {
  min-height: 42px;
  border: 1px solid #fecaca;
  border-radius: 6px;
  padding: 0 14px;
  background: #fff;
  color: #b42318;
  cursor: pointer;
}

.curriculum-coverage {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  padding: 14px 20px;
  border-bottom: 1px solid var(--line);
  background: #fbfdff;
}

.curriculum-coverage > div {
  display: flex;
  align-items: center;
  gap: 7px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 8px 10px;
  color: var(--muted);
}

.curriculum-coverage > div.covered {
  border-color: #bbf7d0;
  background: #f0fdf4;
  color: #166534;
}

.curriculum-coverage p {
  grid-column: 1 / -1;
  margin: 2px 0 0;
  color: var(--muted);
  font-size: 12px;
}

.curriculum-detail-tabs {
  display: flex;
  border-bottom: 1px solid var(--line);
  padding: 0 20px;
}

.curriculum-detail-tabs button {
  min-height: 48px;
  border: 0;
  border-bottom: 3px solid transparent;
  padding: 0 16px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
}

.curriculum-detail-tabs button.active {
  border-bottom-color: var(--primary);
  color: var(--primary-dark);
  font-weight: 700;
}

.curriculum-node-area,
.curriculum-text-area,
.curriculum-history-area,
.curriculum-audit-area {
  min-width: 0;
  padding: 18px 20px 24px;
}

.curriculum-node-area > header,
.curriculum-text-area > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.curriculum-node-area > header div,
.curriculum-text-area > header div {
  display: grid;
  gap: 4px;
}

.curriculum-node-area > header small,
.curriculum-text-area > header small,
.curriculum-text-area > header > span {
  color: var(--muted);
}

.curriculum-text-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--muted);
  font-size: 12px;
}

.curriculum-text-actions a {
  color: var(--primary);
}

.curriculum-node-type-tabs {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 16px;
}

.curriculum-node-type-tabs button {
  min-height: 46px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 6px 10px;
  background: #fff;
  color: var(--muted);
  cursor: pointer;
}

.curriculum-node-type-tabs button.active {
  border-color: var(--primary);
  background: #eff6ff;
  color: var(--primary-dark);
  font-weight: 700;
}

.curriculum-node-type-tabs span {
  display: inline-grid;
  place-items: center;
  min-width: 21px;
  height: 21px;
  margin-left: 4px;
  border-radius: 999px;
  background: #e8f1ff;
  font-size: 11px;
}

.curriculum-node-group + .curriculum-node-group {
  margin-top: 20px;
}

.curriculum-node-group h4 {
  margin: 0 0 9px;
}

.curriculum-node-group h4 span {
  display: inline-grid;
  place-items: center;
  min-width: 22px;
  height: 22px;
  margin-left: 5px;
  border-radius: 999px;
  background: #e8f1ff;
  color: var(--primary-dark);
  font-size: 12px;
}

.curriculum-node-empty {
  margin: 0;
  border: 1px dashed var(--line);
  border-radius: 6px;
  padding: 14px;
  color: var(--muted);
}

.curriculum-node-card {
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #fff;
}

.curriculum-node-card + .curriculum-node-card {
  margin-top: 8px;
}

.curriculum-node-card summary {
  min-height: 54px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  cursor: pointer;
}

.curriculum-node-card summary > span {
  display: grid;
  gap: 3px;
}

.curriculum-node-card summary small,
.curriculum-node-card summary em {
  color: var(--muted);
  font-size: 12px;
  font-style: normal;
}

.curriculum-node-card > p {
  margin: 0;
  border-top: 1px solid var(--line);
  padding: 14px;
  line-height: 1.75;
  white-space: pre-wrap;
}

.curriculum-node-card footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  border-top: 1px solid var(--line);
  padding: 7px 12px;
}

.curriculum-node-card footer button {
  min-height: 38px;
  border: 0;
  background: transparent;
  color: var(--primary);
  cursor: pointer;
}

.curriculum-node-card footer .danger-link {
  color: #b42318;
}

.curriculum-node-pagination {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 14px;
  color: var(--muted);
  font-size: 12px;
}

.curriculum-text-area pre {
  margin: 0;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 18px;
  background: #fbfdff;
  color: var(--text);
  font-family: inherit;
  font-size: 14px;
  line-height: 1.8;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.curriculum-text-preview-note {
  margin: 10px 0 0;
  border-left: 3px solid #93c5fd;
  padding: 9px 12px;
  background: #eff6ff;
  color: #475569;
  font-size: 12px;
  line-height: 1.6;
}

.curriculum-history-area {
  overflow: auto;
}

.curriculum-history-area table {
  min-width: 720px;
}

.curriculum-audit-area > header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.curriculum-audit-area > header > div {
  display: grid;
  gap: 4px;
}

.curriculum-audit-area > header small,
.curriculum-audit-area > header > span {
  color: var(--muted);
  font-size: 12px;
}

.curriculum-audit-timeline {
  display: grid;
  gap: 10px;
  margin: 0 0 0 7px;
  border-left: 2px solid #dbe7f5;
  padding: 0 0 0 18px;
  list-style: none;
}

.curriculum-audit-timeline > li {
  position: relative;
}

.curriculum-audit-marker {
  position: absolute;
  top: 17px;
  left: -25px;
  width: 12px;
  height: 12px;
  border: 3px solid #dbeafe;
  border-radius: 999px;
  background: var(--primary);
}

.curriculum-audit-timeline article {
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: #fff;
}

.curriculum-audit-timeline article > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 11px 13px 7px;
}

.curriculum-audit-timeline time,
.curriculum-audit-timeline article > p {
  color: var(--muted);
  font-size: 12px;
}

.curriculum-audit-timeline time {
  white-space: nowrap;
}

.curriculum-audit-timeline article > p {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 18px;
  margin: 0;
  padding: 0 13px 11px;
}

.curriculum-audit-timeline details {
  border-top: 1px solid var(--line);
}

.curriculum-audit-timeline summary {
  min-height: 42px;
  display: flex;
  align-items: center;
  padding: 0 13px;
  color: var(--primary-dark);
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
}

.curriculum-audit-timeline pre {
  max-height: 240px;
  margin: 0;
  overflow: auto;
  border-top: 1px solid var(--line);
  padding: 12px 13px;
  background: #f8fafc;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.curriculum-audit-empty {
  margin: 0;
  border: 1px dashed var(--line);
  border-radius: 7px;
  padding: 20px;
  color: var(--muted);
  text-align: center;
}

:where(
  .curriculum-section-tabs button,
  .curriculum-list > button,
  .curriculum-list-pagination button,
  .curriculum-mobile-back,
  .curriculum-version-strip button,
  .curriculum-governance-details > summary,
  .curriculum-detail-tabs button,
  .curriculum-node-type-tabs button,
  .curriculum-node-card summary,
  .curriculum-node-pagination button,
  .curriculum-audit-timeline summary
):focus-visible {
  outline: 3px solid rgba(37, 99, 235, .32);
  outline-offset: 2px;
}

@media (max-width: 1100px) {
  .curriculum-workspace {
    grid-template-columns: minmax(260px, 310px) minmax(0, 1fr);
  }

  .curriculum-version-overview {
    grid-template-columns: 1fr;
  }

  .curriculum-version-actions {
    justify-content: flex-start;
  }
}

@media (max-width: 800px) {
  .curriculum-principle {
    flex-wrap: wrap;
  }

  .curriculum-principle p {
    flex-basis: 100%;
    margin-left: 0;
    text-align: left;
  }

  .curriculum-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .curriculum-summary article:nth-child(2) {
    border-right: 0;
  }

  .curriculum-summary article:nth-child(-n + 2) {
    border-bottom: 1px solid var(--line);
  }

  .curriculum-workspace {
    grid-template-columns: 1fr;
  }

  .curriculum-workspace.has-selection .curriculum-list,
  .curriculum-workspace:not(.has-selection) .curriculum-detail {
    display: none;
  }

  .curriculum-list {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }

  .curriculum-list-pagination,
  .curriculum-empty {
    grid-column: 1 / -1;
  }

  .curriculum-list > button:nth-child(odd) {
    border-right: 1px solid var(--line);
  }

  .curriculum-mobile-back {
    width: 100%;
    min-height: 48px;
    display: flex;
    align-items: center;
    gap: 8px;
    border: 0;
    border-bottom: 1px solid var(--line);
    padding: 0 16px;
    background: #f8fafc;
    color: var(--primary-dark);
    font-weight: 700;
    cursor: pointer;
  }

  .curriculum-governance-details > summary {
    align-items: flex-start;
    flex-direction: column;
  }

  .curriculum-governance-indicators {
    justify-content: flex-start;
  }

  .curriculum-node-type-tabs {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .curriculum-page-heading,
  .curriculum-detail-header {
    align-items: stretch;
    flex-direction: column;
  }

  .curriculum-principle {
    align-items: flex-start;
    flex-direction: column;
    gap: 8px;
  }

  .curriculum-principle ol {
    flex-wrap: wrap;
  }

  .curriculum-principle p {
    margin: 0;
  }

  .curriculum-coverage {
    grid-template-columns: 1fr;
  }

  .curriculum-detail-actions,
  .curriculum-version-actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    align-items: stretch;
  }

  .curriculum-detail-actions > *,
  .curriculum-version-actions > * {
    width: 100%;
    justify-content: center;
  }

  .curriculum-detail-actions > .primary-button:last-child {
    grid-column: 1 / -1;
  }

  .curriculum-version-overview dl {
    grid-template-columns: 1fr;
    gap: 8px;
  }

  .curriculum-version-overview dl > div {
    grid-template-columns: 120px 1fr;
  }

  .curriculum-coverage p {
    grid-column: auto;
  }

  .curriculum-page-quality {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .curriculum-page-quality p {
    grid-column: 1 / -1;
  }

  .curriculum-detail-tabs {
    padding: 0;
  }

  .curriculum-detail-tabs button {
    flex: 1;
    padding: 0 7px;
  }

  .curriculum-text-area > header,
  .curriculum-node-area > header,
  .curriculum-audit-area > header {
    align-items: stretch;
    flex-direction: column;
  }

  .curriculum-audit-timeline article > header {
    align-items: flex-start;
    flex-direction: column;
    gap: 4px;
  }

  .curriculum-text-actions {
    flex-wrap: wrap;
  }

  .curriculum-history-area {
    overflow: visible;
  }

  .curriculum-history-area table {
    width: 100%;
    min-width: 0;
  }

  .curriculum-history-area thead {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    clip-path: inset(50%);
    white-space: nowrap;
  }

  .curriculum-history-area tbody,
  .curriculum-history-area tr,
  .curriculum-history-area td {
    display: block;
  }

  .curriculum-history-area tr {
    border: 1px solid var(--line);
    border-radius: 8px;
    background: #fff;
  }

  .curriculum-history-area tr + tr {
    margin-top: 10px;
  }

  .curriculum-history-area td {
    display: grid;
    grid-template-columns: minmax(82px, 34%) 1fr;
    gap: 12px;
    border: 0;
    border-bottom: 1px solid var(--line);
    padding: 10px 12px;
  }

  .curriculum-history-area td:last-child {
    border-bottom: 0;
  }

  .curriculum-history-area td::before {
    content: attr(data-label);
    color: var(--muted);
    font-size: 12px;
    font-weight: 600;
  }
}

@media (max-width: 460px) {
  .curriculum-section-tabs small {
    display: none;
  }

  .curriculum-list-heading {
    display: grid;
    justify-content: stretch;
  }

  .curriculum-list-heading em {
    width: fit-content;
  }
}

@media (prefers-reduced-motion: reduce) {
  .curriculum-list > button {
    transition: none;
  }
}
</style>
