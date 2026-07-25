<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError } from '@/api/client'
import {
  deleteEvaluationTrial,
  evaluationTrialExportUrl,
  getEvaluationPlan,
  getEvaluationPlans,
  getEvaluationOptions,
  getEvaluationStandard,
  getEvaluationStandards,
  getEvaluationTrial,
  getEvaluationTrials,
  publishEvaluationPlan,
  publishEvaluationStandard,
  reviewEvaluationPlan,
  reviewEvaluationStandard,
  type EvaluationPlanRow,
  type EvaluationOptions,
  type EvaluationStandardRow,
  type EvaluationTrialRow
} from '@/api/evaluation'
import EvaluationPlanEditorModal from '@/components/evaluation/EvaluationPlanEditorModal.vue'
import EvaluationAIDraftWizard from '@/components/evaluation/EvaluationAIDraftWizard.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import EvaluationStandardEditorModal from '@/components/evaluation/EvaluationStandardEditorModal.vue'
import EvaluationTrialEditorModal from '@/components/evaluation/EvaluationTrialEditorModal.vue'
import AppShell from '@/layouts/AppShell.vue'
import { teacherNav } from './nav'

const navItems = teacherNav('/teacher/evaluations')
const routeQuery = new URLSearchParams(window.location.search)
const requestedReturnPath = routeQuery.get('return') || ''
const returnToLessonPath = /^\/teacher\/lessons\/\d+\/design(?:\?.*)?$/.test(requestedReturnPath)
  ? requestedReturnPath
  : ''
const requestedCourseId = Number(routeQuery.get('course') || 0) || null
const activeTab = ref<'plans' | 'standards' | 'trials'>('plans')
const options = ref<EvaluationOptions | null>(null)
const plans = ref<EvaluationPlanRow[]>([])
const standards = ref<EvaluationStandardRow[]>([])
const trials = ref<EvaluationTrialRow[]>([])
const loading = ref(false)
const notice = ref('')
const noticeTone = ref<'success' | 'warning' | 'error' | 'info'>('info')
const planEditor = ref(false)
const aiDraftWizard = ref(false)
const standardEditor = ref(false)
const trialEditor = ref(false)
const editingPlan = ref<EvaluationPlanRow | null>(null)
const editingStandard = ref<EvaluationStandardRow | null>(null)
const editingTrial = ref<EvaluationTrialRow | null>(null)
const publishing = ref(false)
const reviewing = ref(false)
const deleting = ref(false)
const rowBusy = ref<string | null>(null)
const publishTarget = ref<{ type: 'plan' | 'standard'; id: number; title: string } | null>(null)
const reviewTarget = ref<{ type: 'plan' | 'standard'; id: number; title: string } | null>(null)
const editTarget = ref<{ type: 'plan' | 'standard'; row: EvaluationPlanRow | EvaluationStandardRow } | null>(null)
const deleteTarget = ref<EvaluationTrialRow | null>(null)

const summary = computed(() => [
  { label: '评价方案', value: plans.value.length, detail: `${plans.value.filter((item) => item.latest_version).length} 个可用于课堂` },
  { label: '学习目标', value: plans.value.reduce((sum, item) => sum + item.goal_count, 0), detail: '均应对应课程标准依据' },
  { label: '评价任务', value: plans.value.reduce((sum, item) => sum + item.evaluation_task_count, 0), detail: '测试、操作、项目等任务' },
  { label: '课堂试用', value: trials.value.length, detail: `${trials.value.filter((item) => item.status === 'completed').length} 条已完成` }
])
const reviewedPlanVersionCount = computed(() => options.value?.plan_versions.filter((item) => item.review_status === 'reviewed').length || 0)

const designSteps = [
  { number: '1', title: '确定课程内容与学习目标', description: '从已发布课程标准中选择依据，结合本节课或单元内容写出学生预期表现。' },
  { number: '2', title: '设计学习活动与评价任务', description: '根据教学情境选择测试、操作、项目、作品、答辩或混合评价，并明确形成什么材料。' },
  { number: '3', title: '制定评价标准', description: '把学习目标转化为可观察的评价指标、表现水平和评分示例。' },
  { number: '4', title: '课堂试用与改进', description: '记录学生理解、教师评分和需要修改之处，再决定是否继续使用。' }
]

function assessmentModeLabels(row: EvaluationPlanRow) {
  const labels = new Map((options.value?.assessment_modes || []).map((item) => [item.value, item.label]))
  return (row.assessment_modes || []).map((mode) => labels.get(mode) || mode)
}

const pageTitle = computed(() => activeTab.value === 'plans' ? '维护评价方案' : activeTab.value === 'standards' ? '维护评价指标与表现水平' : '记录试用与改进情况')
const pageDescription = computed(() => activeTab.value === 'plans'
  ? '课时设计是日常入口；这里集中维护可复用方案、教师复核状态和不可修改的发布版本。'
  : activeTab.value === 'standards'
    ? '依据已经发布的评价方案，为学生可观察的表现设置评价指标、表现水平、评分示例和暂不评价条件。'
    : '记录学生是否理解任务、材料是否充分、教师评分是否一致，以及后续修改安排。')

function firstApiError(error: ApiError) {
  const [field, messages] = Object.entries(error.errors)[0] || []
  const first = messages?.[0]
  if (!first) return error.message
  const labels: Record<string, string> = {
    curriculum_node_ids: '课程标准依据',
    learning_goals: '学习目标',
    learning_activities: '学习活动',
    evaluation_basis: '评价依据',
    evaluation_tasks: '评价任务',
    assessment_modes: '评价方式',
    scoring_rules: '评分规则',
    criteria: '评价指标',
    plan_version: '评价方案版本',
    non_field_errors: ''
  }
  const label = labels[field] ?? field
  return label ? `${label}：${first}` : first
}

async function load() {
  loading.value = true
  try {
    const [optionRows, planRows, standardRows, trialRows] = await Promise.all([
      getEvaluationOptions(),
      getEvaluationPlans(),
      getEvaluationStandards(),
      getEvaluationTrials()
    ])
    options.value = optionRows
    plans.value = planRows
    standards.value = standardRows
    trials.value = trialRows
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '评价管理数据加载失败。'
    noticeTone.value = 'error'
  } finally {
    loading.value = false
  }
}

async function openPlan(row?: EvaluationPlanRow) {
  if (rowBusy.value) return
  notice.value = ''
  rowBusy.value = `plan:${row?.id || 'new'}`
  try {
    editingPlan.value = row ? await getEvaluationPlan(row.id) : null
    planEditor.value = true
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '评价方案加载失败。'
    noticeTone.value = 'error'
  } finally {
    rowBusy.value = null
  }
}

async function openStandard(row?: EvaluationStandardRow) {
  if (rowBusy.value) return
  notice.value = ''
  rowBusy.value = `standard:${row?.id || 'new'}`
  try {
    editingStandard.value = row ? await getEvaluationStandard(row.id) : null
    standardEditor.value = true
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '评价标准加载失败。'
    noticeTone.value = 'error'
  } finally {
    rowBusy.value = null
  }
}

function requestEdit(type: 'plan' | 'standard', row: EvaluationPlanRow | EvaluationStandardRow) {
  if (!row.allowed_actions.edit || rowBusy.value) return
  if (row.review_status === 'reviewed') {
    editTarget.value = { type, row }
    return
  }
  if (type === 'plan') void openPlan(row as EvaluationPlanRow)
  else void openStandard(row as EvaluationStandardRow)
}

function confirmEdit() {
  const target = editTarget.value
  editTarget.value = null
  if (!target) return
  if (target.type === 'plan') void openPlan(target.row as EvaluationPlanRow)
  else void openStandard(target.row as EvaluationStandardRow)
}

function requestReview(type: 'plan' | 'standard', row: EvaluationPlanRow | EvaluationStandardRow) {
  if (!row.allowed_actions.review || rowBusy.value) return
  reviewTarget.value = { type, id: row.id, title: row.title }
}

async function confirmReview() {
  if (!reviewTarget.value || reviewing.value) return
  reviewing.value = true
  const target = reviewTarget.value
  try {
    if (target.type === 'plan') await reviewEvaluationPlan(target.id)
    else await reviewEvaluationStandard(target.id)
    notice.value = target.type === 'plan' ? '评价方案已完成复核确认。' : '评价标准已完成复核确认。'
    noticeTone.value = 'success'
    reviewTarget.value = null
    await load()
  } catch (error) {
    notice.value = error instanceof ApiError ? firstApiError(error) : '复核确认失败。'
    noticeTone.value = 'error'
    reviewTarget.value = null
  } finally {
    reviewing.value = false
  }
}

async function openTrial(row?: EvaluationTrialRow) {
  if (rowBusy.value) return
  notice.value = ''
  rowBusy.value = `trial:${row?.id || 'new'}`
  try {
    editingTrial.value = row ? await getEvaluationTrial(row.id) : null
    trialEditor.value = true
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '评价试用记录加载失败。'
    noticeTone.value = 'error'
  } finally {
    rowBusy.value = null
  }
}

async function saved(kind: 'plan' | 'standard' | 'trial') {
  planEditor.value = false
  standardEditor.value = false
  trialEditor.value = false
  editingPlan.value = null
  editingStandard.value = null
  editingTrial.value = null
  notice.value = kind === 'plan' ? '评价方案已保存。' : kind === 'standard' ? '评价标准已保存。' : '评价试用记录已保存。'
  noticeTone.value = 'success'
  await load()
}

async function aiDraftSaved() {
  aiDraftWizard.value = false
  activeTab.value = 'plans'
  notice.value = '评价方案和评价标准均已保存为“编辑中”草稿，需教师复核；发布方案后，请再为评价标准选择明确的方案版本。'
  noticeTone.value = 'success'
  await load()
}

async function confirmDeleteTrial() {
  if (!deleteTarget.value || deleting.value) return
  deleting.value = true
  try {
    await deleteEvaluationTrial(deleteTarget.value.id)
    notice.value = '评价试用记录已删除。'
    noticeTone.value = 'success'
    deleteTarget.value = null
    await load()
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '评价试用记录删除失败。'
    noticeTone.value = 'error'
    deleteTarget.value = null
  } finally {
    deleting.value = false
  }
}

function exportTrials() {
  window.location.href = evaluationTrialExportUrl()
}

async function requestPublish(type: 'plan' | 'standard', row: EvaluationPlanRow | EvaluationStandardRow) {
  if (!row.allowed_actions.publish || rowBusy.value) return
  if (type === 'plan') {
    rowBusy.value = `publish-check:${row.id}`
    try {
      const detail = await getEvaluationPlan(row.id)
      const present = new Set((detail.curriculum_references || []).map((item) => item.node_type))
      const required = [
        ['core_competency', '核心素养'],
        ['course_objective', '课程目标'],
        ['course_content', '课程内容'],
        ['academic_quality', '学业质量']
      ] as const
      const missing = required.filter(([value]) => !present.has(value)).map(([, label]) => label)
      if (missing.length) {
        notice.value = `发布前请补充课程标准依据：${missing.join('、')}。`
        noticeTone.value = 'warning'
        return
      }
    } catch (error) {
      notice.value = error instanceof ApiError ? error.message : '课程标准依据检查失败。'
      noticeTone.value = 'error'
      return
    } finally {
      rowBusy.value = null
    }
  }
  publishTarget.value = { type, id: row.id, title: row.title }
}

async function confirmPublish() {
  if (!publishTarget.value || publishing.value) return
  publishing.value = true
  const target = publishTarget.value
  try {
    if (target.type === 'plan') await publishEvaluationPlan(target.id)
    else await publishEvaluationStandard(target.id)
    notice.value = target.type === 'plan' ? '评价方案版本已发布。' : '评价标准版本已发布。'
    noticeTone.value = 'success'
    publishTarget.value = null
    await load()
  } catch (error) {
    notice.value = error instanceof ApiError ? firstApiError(error) : '版本发布失败。'
    noticeTone.value = 'error'
    publishTarget.value = null
  } finally {
    publishing.value = false
  }
}

function versionLabel(row: EvaluationPlanRow | EvaluationStandardRow) {
  return row.latest_version ? `v${row.latest_version.version_no}` : '未发布'
}

function reviewedLabel(row: EvaluationPlanRow | EvaluationStandardRow) {
  if (!row.reviewed_at) return ''
  return `${row.reviewed_by || '复核人未记录'} · ${new Date(row.reviewed_at).toLocaleString('zh-CN')}`
}

onMounted(load)
</script>

<template>
  <AppShell title="评价方案库" eyebrow="教师工作台" :nav-items="navItems">
    <NoticeLine v-if="notice" :message="notice" :tone="noticeTone" floating @dismiss="notice = ''" />

    <section class="evaluation-guide" aria-labelledby="evaluation-guide-title">
      <header>
        <div>
          <span>低频维护与质量管理</span>
          <h2 id="evaluation-guide-title">课时中完成评价设计，方案库中管理复用与版本</h2>
          <p>教师为具体课时新建、AI辅助起草、复核和绑定评价，均应在课时设计中完成。本页只用于集中查看可复用方案、历史版本、质量记录和停用内容。</p>
        </div>
        <div class="evaluation-guide-actions">
          <RouterLink v-if="returnToLessonPath" class="secondary-button" :to="returnToLessonPath">返回课时设计</RouterLink>
          <button class="secondary-button" type="button" :disabled="Boolean(rowBusy) || !options?.courses.length" data-test="open-ai-draft" @click="aiDraftWizard = true">AI 辅助起草可复用方案</button>
          <button class="primary-button" type="button" :disabled="Boolean(rowBusy) || !options?.courses.length" @click="openPlan()">新建可复用方案</button>
        </div>
      </header>
      <ol class="evaluation-design-steps">
        <li v-for="item in designSteps" :key="item.number">
          <span>{{ item.number }}</span>
          <div><strong>{{ item.title }}</strong><small>{{ item.description }}</small></div>
        </li>
      </ol>
      <p class="evaluation-boundary">发布只表示内容与版本已经冻结，并不表示课堂材料会自动改变学生后续的学习内容、支持方式或分组安排。没有获得评价机会、设备故障或材料不足时，应标记为“暂不评价”，不能按低表现处理。</p>
    </section>

    <section class="evaluation-summary" aria-label="评价管理概况">
      <article v-for="item in summary" :key="item.label">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
        <small>{{ item.detail }}</small>
      </article>
    </section>

    <section class="evaluation-workspace">
      <header class="evaluation-page-header">
        <div>
          <h2>{{ pageTitle }}</h2>
          <p>{{ pageDescription }}</p>
        </div>
        <div class="evaluation-heading-actions">
          <button v-if="activeTab === 'trials'" class="secondary-button" type="button" :disabled="!trials.length" @click="exportTrials">导出 XLSX</button>
          <button
            class="primary-button"
            type="button"
            :disabled="Boolean(rowBusy) || !options?.courses.length || (activeTab === 'standards' && !reviewedPlanVersionCount) || (activeTab === 'trials' && !options?.standard_versions.length)"
            @click="activeTab === 'plans' ? openPlan() : activeTab === 'standards' ? openStandard() : openTrial()"
          >
            {{ activeTab === 'plans' ? '新建方案' : activeTab === 'standards' ? '新建标准' : '新增记录' }}
          </button>
        </div>
      </header>

      <div class="evaluation-tabs" role="tablist" aria-label="评价管理类型">
        <button role="tab" type="button" :aria-selected="activeTab === 'plans'" :class="{ active: activeTab === 'plans' }" @click="activeTab = 'plans'">
          1 评价方案 <span>{{ plans.length }}</span>
        </button>
        <button role="tab" type="button" :aria-selected="activeTab === 'standards'" :class="{ active: activeTab === 'standards' }" @click="activeTab = 'standards'">
          2 评价指标与表现水平 <span>{{ standards.length }}</span>
        </button>
        <button role="tab" type="button" :aria-selected="activeTab === 'trials'" :class="{ active: activeTab === 'trials' }" @click="activeTab = 'trials'">
          3 试用与质量记录 <span>{{ trials.length }}</span>
        </button>
      </div>

      <div v-if="loading" class="evaluation-empty">正在加载</div>

      <div v-else-if="activeTab === 'plans'" class="evaluation-table-wrap">
        <div v-if="!plans.length" class="evaluation-empty evaluation-empty-action">
          <strong>还没有评价方案</strong>
          <p>先选择课程和课程内容，再按“课程标准依据—学习目标—学习活动—评价任务”的顺序建立第一份方案。</p>
          <button class="primary-button" type="button" :disabled="!options?.courses.length" @click="openPlan()">建立第一份评价方案</button>
        </div>
        <table v-else class="evaluation-table">
          <thead><tr><th>方案与学习目标</th><th>课程</th><th>评价方式</th><th>设计完整性</th><th>使用状态</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="row in plans" :key="row.id">
              <td data-label="方案与学习目标"><strong>{{ row.title }}</strong><small>{{ row.learning_goal || `适用内容：${row.content_version || '未填写'}` }}</small></td>
              <td data-label="课程"><strong>{{ row.course?.title || '未绑定课程' }}</strong><small>{{ row.subject.name }}</small></td>
              <td data-label="评价方式"><span v-for="label in assessmentModeLabels(row)" :key="label" class="evaluation-mode-chip">{{ label }}</span><small v-if="!assessmentModeLabels(row).length">尚未选择</small></td>
              <td data-label="设计完整性"><span>{{ row.goal_count }} 个学习目标</span><span>{{ row.activity_count }} 个学习活动</span><span>{{ row.evaluation_task_count }} 个评价任务</span><small>{{ row.curriculum_reference_count ?? row.curriculum_references?.length ?? 0 }} 条课程标准依据</small></td>
              <td data-label="使用状态"><span class="evaluation-status" :class="row.review_status">{{ row.review_status_label }}</span><span class="evaluation-version" :class="{ published: row.latest_version }">{{ versionLabel(row) }}</span><small v-if="reviewedLabel(row)">{{ reviewedLabel(row) }}</small></td>
              <td data-label="操作">
                <div class="evaluation-row-actions">
                  <button type="button" :disabled="Boolean(rowBusy) || !row.allowed_actions.edit" @click="requestEdit('plan', row)">{{ rowBusy === `plan:${row.id}` ? '加载中' : '编辑' }}</button>
                  <button v-if="row.allowed_actions.review" type="button" :disabled="Boolean(rowBusy)" @click="requestReview('plan', row)">复核确认</button>
                  <button type="button" :disabled="Boolean(rowBusy) || !row.allowed_actions.publish" @click="requestPublish('plan', row)">{{ rowBusy === `publish-check:${row.id}` ? '检查中' : '发布版本' }}</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-else-if="activeTab === 'standards'" class="evaluation-table-wrap">
        <div v-if="!standards.length" class="evaluation-empty evaluation-empty-action">
          <strong>还没有评价标准</strong>
          <p>先完成评价方案的教师复核并发布，再为任务中的可观察表现制定评价指标和表现水平。</p>
          <button class="primary-button" type="button" :disabled="!reviewedPlanVersionCount" @click="openStandard()">制定评价标准</button>
        </div>
        <table v-else class="evaluation-table">
          <thead><tr><th>评价标准</th><th>评价方案版本</th><th>评价内容</th><th>复核状态</th><th>版本</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="row in standards" :key="row.id">
              <td data-label="评价标准">
                <strong>{{ row.title }} <em v-if="row.ai_assisted" class="evaluation-ai-source">AI 起草 · 待教师审阅</em></strong>
                <small>{{ row.subject.name }} · {{ row.scope_label }}</small>
              </td>
              <td data-label="评价方案版本"><span>{{ row.plan_version?.title || row.plan.title }}</span><small v-if="row.plan_version">第 {{ row.plan_version.version_no }} 版</small></td>
              <td data-label="评价内容" class="evaluation-wrap-cell">{{ row.evaluation_target || '未填写' }}<small>{{ row.criterion_count }} 项评价指标</small></td>
              <td data-label="复核状态"><span class="evaluation-status" :class="row.review_status">{{ row.review_status_label }}</span><small v-if="reviewedLabel(row)">{{ reviewedLabel(row) }}</small></td>
              <td data-label="版本"><span class="evaluation-version" :class="{ published: row.latest_version }">{{ versionLabel(row) }}</span></td>
              <td data-label="操作">
                <div class="evaluation-row-actions">
                  <button type="button" :disabled="Boolean(rowBusy) || !row.allowed_actions.edit" @click="requestEdit('standard', row)">{{ rowBusy === `standard:${row.id}` ? '加载中' : '编辑' }}</button>
                  <button v-if="row.allowed_actions.review" type="button" :disabled="Boolean(rowBusy)" @click="requestReview('standard', row)">复核确认</button>
                  <button type="button" :disabled="Boolean(rowBusy) || !row.allowed_actions.publish" @click="requestPublish('standard', row)">发布版本</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-else class="evaluation-table-wrap">
        <div v-if="!trials.length" class="evaluation-empty evaluation-empty-action">
          <strong>还没有课堂试用记录</strong>
          <p>评价标准发布后，可记录学生是否理解任务要求、材料是否足以判断学习表现，以及教师评分需要统一的地方。</p>
          <button class="primary-button" type="button" :disabled="!options?.standard_versions.length" @click="openTrial()">记录一次课堂试用</button>
        </div>
        <table v-else class="evaluation-table evaluation-trial-table">
          <thead><tr><th>记录</th><th>评价标准</th><th>日期与人数</th><th>状态</th><th>处理结论</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="row in trials" :key="row.id">
              <td data-label="记录"><strong>{{ row.title }}</strong><small>{{ row.record_type_label }}</small></td>
              <td data-label="评价标准"><strong>{{ row.standard_version.title }} v{{ row.standard_version.version_no }}</strong><small>{{ row.standard_version.subject.name }} · {{ row.standard_version.course?.title || '校级通用' }}</small></td>
              <td data-label="日期与人数"><span>{{ row.activity_date }}</span><small>{{ row.participant_count }} 人参与<span v-if="row.agreement_rate !== null"> · 一致率 {{ row.agreement_rate }}%</span></small></td>
              <td data-label="状态"><span class="evaluation-status" :class="row.status">{{ row.status_label }}</span></td>
              <td data-label="处理结论"><span class="evaluation-conclusion" :class="row.conclusion">{{ row.conclusion_label }}</span></td>
              <td data-label="操作">
                <div class="evaluation-row-actions">
                  <button type="button" :disabled="Boolean(rowBusy)" @click="openTrial(row)">{{ rowBusy === `trial:${row.id}` ? '加载中' : row.status === 'completed' ? '查看' : '编辑' }}</button>
                  <button v-if="row.status !== 'completed'" class="danger-link" type="button" :disabled="Boolean(rowBusy) || deleting" @click="deleteTarget = row">删除</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <EvaluationPlanEditorModal
      v-if="planEditor && options"
      :draft="editingPlan"
      :options="options"
      @close="planEditor = false"
      @saved="saved('plan')"
    />
    <EvaluationAIDraftWizard
      v-if="aiDraftWizard && options"
      :options="options"
      :initial-course-id="requestedCourseId"
      @close="aiDraftWizard = false"
      @saved="aiDraftSaved"
    />
    <EvaluationStandardEditorModal
      v-if="standardEditor && options"
      :draft="editingStandard"
      :options="options"
      :assisted-by-ai="Boolean(editingStandard?.ai_assisted)"
      @close="standardEditor = false"
      @saved="saved('standard')"
    />
    <EvaluationTrialEditorModal
      v-if="trialEditor && options"
      :draft="editingTrial"
      :options="options"
      @close="trialEditor = false"
      @saved="saved('trial')"
    />
    <ConfirmDialog
      :open="Boolean(editTarget)"
      title="编辑已复核内容"
      :message="`继续编辑“${editTarget?.row.title || ''}”会将工作副本恢复为编辑中；已经发布的历史版本不受影响。`"
      confirm-label="继续编辑"
      @close="editTarget = null"
      @confirm="confirmEdit"
    />
    <ConfirmDialog
      :open="Boolean(reviewTarget)"
      title="复核确认"
      :message="`确认复核“${reviewTarget?.title || ''}”。系统将检查内容完整性、对应关系和评价材料设置；确认后才能发布版本。`"
      confirm-label="确认复核"
      :loading="reviewing"
      @close="reviewTarget = null"
      @confirm="confirmReview"
    />
    <ConfirmDialog
      :open="Boolean(publishTarget)"
      title="发布新版本"
      :message="`发布“${publishTarget?.title || ''}”当前内容。发布后保留该版本，后续修改将生成下一版本。`"
      confirm-label="确认发布"
      :loading="publishing"
      @close="publishTarget = null"
      @confirm="confirmPublish"
    />
    <ConfirmDialog
      :open="Boolean(deleteTarget)"
      title="删除试用记录"
      :message="`确认删除“${deleteTarget?.title || ''}”。已完成记录不允许删除。`"
      confirm-label="确认删除"
      :danger="true"
      :loading="deleting"
      @close="deleteTarget = null"
      @confirm="confirmDeleteTrial"
    />
  </AppShell>
</template>

<style scoped>
.evaluation-guide {
  overflow: hidden;
  border: 1px solid #cbdad2;
  border-radius: 10px;
  background: linear-gradient(135deg, #f4f7f4 0%, #ffffff 70%);
  box-shadow: 0 12px 28px rgba(15, 23, 42, .04);
}

.evaluation-guide > header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  padding: 22px 24px 18px;
}

.evaluation-guide header span {
  color: var(--primary);
  font-size: 13px;
  font-weight: 700;
  letter-spacing: .06em;
}

.evaluation-guide h2 {
  max-width: 780px;
  margin: 6px 0 8px;
  font-size: clamp(20px, 2vw, 28px);
  line-height: 1.35;
}

.evaluation-guide header p {
  max-width: 880px;
  margin: 0;
  color: var(--muted);
  line-height: 1.7;
}

.evaluation-guide-actions {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 10px;
}

.evaluation-design-steps {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin: 0;
  padding: 0 24px 20px;
  list-style: none;
}

.evaluation-design-steps li {
  position: relative;
  min-width: 0;
  display: flex;
  gap: 10px;
  padding: 14px 16px;
  border: 1px solid var(--line);
  border-right: 0;
  background: #fff;
}

.evaluation-design-steps li:first-child {
  border-radius: 8px 0 0 8px;
}

.evaluation-design-steps li:last-child {
  border-right: 1px solid var(--line);
  border-radius: 0 8px 8px 0;
}

.evaluation-design-steps li > span {
  flex: 0 0 28px;
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: #e5ede8;
  color: var(--primary-dark);
  font-weight: 700;
}

.evaluation-design-steps strong,
.evaluation-design-steps small {
  display: block;
}

.evaluation-design-steps small {
  margin-top: 5px;
  color: var(--muted);
  line-height: 1.5;
}

.evaluation-boundary {
  margin: 0;
  border-top: 1px solid #d8e3dc;
  padding: 12px 24px;
  background: #f1f5f1;
  color: #526a61;
  font-size: 13px;
  line-height: 1.6;
}

.evaluation-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-top: 16px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 12px 28px rgba(15, 23, 42, .04);
}

.evaluation-summary article {
  min-width: 0;
  min-height: 104px;
  display: grid;
  align-content: center;
  gap: 5px;
  padding: 16px 20px;
  border-right: 1px solid var(--line);
}

.evaluation-summary article:last-child {
  border-right: 0;
}

.evaluation-summary span,
.evaluation-summary small {
  color: var(--muted);
}

.evaluation-summary strong {
  font-size: 24px;
  line-height: 1.2;
  overflow-wrap: anywhere;
}

.evaluation-workspace {
  min-width: 0;
  margin-top: 16px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 12px 28px rgba(15, 23, 42, .04);
}

.evaluation-page-header {
  min-height: 86px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--line);
}

.evaluation-page-header h2,
.evaluation-page-header p {
  margin: 0;
}

.evaluation-heading-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 0 0 auto;
}

.evaluation-page-header p {
  margin-top: 5px;
  color: var(--muted);
  line-height: 1.5;
}

.evaluation-tabs {
  display: flex;
  padding: 0 20px;
  border-bottom: 1px solid var(--line);
  background: #f5f7f3;
}

.evaluation-tabs button {
  min-height: 48px;
  border: 0;
  border-bottom: 3px solid transparent;
  padding: 0 18px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
}

.evaluation-tabs button.active {
  border-bottom-color: var(--primary);
  color: var(--primary-dark);
  font-weight: 700;
}

.evaluation-tabs span {
  display: inline-grid;
  place-items: center;
  min-width: 22px;
  height: 22px;
  margin-left: 6px;
  border-radius: 999px;
  background: #e4ede8;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.evaluation-table-wrap {
  min-width: 0;
  overflow: auto;
}

.evaluation-table {
  min-width: 900px;
}

.evaluation-table th,
.evaluation-table td {
  padding: 13px 16px;
  vertical-align: middle;
}

.evaluation-table td:first-child,
.evaluation-table td:nth-child(2) {
  white-space: normal;
}

.evaluation-table td strong,
.evaluation-table td small {
  display: block;
}

.evaluation-table td small {
  margin-top: 4px;
  color: var(--muted);
  line-height: 1.4;
}

.evaluation-table td:nth-child(3) > span {
  display: inline-block;
  margin: 2px 6px 2px 0;
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 3px 7px;
  color: var(--muted);
  font-size: 12px;
}

.evaluation-table td:nth-child(4) > span {
  display: block;
  margin: 2px 0;
  color: #475569;
  font-size: 13px;
}

.evaluation-table td:nth-child(5) .evaluation-status,
.evaluation-table td:nth-child(5) .evaluation-version {
  display: inline-flex;
  margin: 2px 5px 2px 0;
}

.evaluation-mode-chip {
  border-color: #c5d6cc !important;
  background: #eef5f1;
  color: #315f50 !important;
}

.evaluation-wrap-cell {
  max-width: 320px;
  white-space: normal;
  line-height: 1.5;
}

.evaluation-ai-source {
  display: inline-flex;
  margin-left: 6px;
  border-radius: 999px;
  padding: 2px 7px;
  color: #315f50;
  background: #e4ede8;
  font-size: 11px;
  font-style: normal;
  font-weight: 700;
  white-space: nowrap;
}

.evaluation-version {
  display: inline-flex;
  align-items: center;
  min-height: 26px;
  border-radius: 999px;
  padding: 0 9px;
  background: #f1f4f1;
  color: #64748b;
  font-size: 12px;
}

.evaluation-version.published {
  background: #e8f7ef;
  color: #166534;
}

.evaluation-status,
.evaluation-conclusion {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  border-radius: 999px;
  padding: 0 9px;
  background: #f1f4f1;
  color: #475569;
  font-size: 12px;
  font-weight: 600;
}

.evaluation-status.in_progress {
  background: #fff4dd;
  color: #9a4f08;
}

.evaluation-status.reviewed {
  background: #e8f7ef;
  color: #166534;
}

.evaluation-status.legacy_unverified {
  background: #fff4dd;
  color: #9a4f08;
}

.evaluation-status.completed,
.evaluation-conclusion.ready {
  background: #e8f7ef;
  color: #166534;
}

.evaluation-conclusion.revise {
  background: #fff4dd;
  color: #9a4f08;
}

.evaluation-conclusion.hold {
  background: #fff0f0;
  color: #b42318;
}

.evaluation-trial-table td:nth-child(3) > span {
  margin: 0;
  border: 0;
  padding: 0;
  color: inherit;
  font-size: inherit;
}

.evaluation-row-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.evaluation-row-actions button {
  min-height: 40px;
  border: 0;
  background: transparent;
  color: var(--primary);
  cursor: pointer;
  white-space: nowrap;
}

.evaluation-row-actions button:hover {
  color: var(--primary-dark);
}

.evaluation-row-actions button:disabled {
  color: var(--muted);
  cursor: not-allowed;
  opacity: .55;
}

.evaluation-row-actions .danger-link {
  color: #b42318;
}

.evaluation-row-actions .danger-link:hover {
  color: #7f1d1d;
}

.evaluation-empty {
  min-height: 220px;
  display: grid;
  place-items: center;
  margin: 0;
  padding: 24px;
  color: var(--muted);
  text-align: center;
}

.evaluation-empty-action {
  justify-items: center;
  align-content: center;
  gap: 10px;
}

.evaluation-empty-action strong {
  color: var(--text);
  font-size: 18px;
}

.evaluation-empty-action p {
  max-width: 600px;
  margin: 0;
  line-height: 1.65;
}

@media (max-width: 1000px) {
  .evaluation-guide > header {
    align-items: stretch;
    flex-direction: column;
  }

  .evaluation-guide > header > div:first-child {
    width: 100%;
    max-width: none;
  }

  .evaluation-guide-actions {
    width: 100%;
    flex-wrap: wrap;
    justify-content: flex-start;
  }

  .evaluation-design-steps {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 10px;
  }

  .evaluation-design-steps li,
  .evaluation-design-steps li:first-child,
  .evaluation-design-steps li:last-child {
    border: 1px solid var(--line);
    border-radius: 8px;
  }

  .evaluation-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .evaluation-summary article:nth-child(2) {
    border-right: 0;
  }

  .evaluation-summary article:nth-child(-n + 2) {
    border-bottom: 1px solid var(--line);
  }
}

@media (max-width: 640px) {
  .evaluation-guide > header {
    flex-direction: column;
    padding: 18px;
  }

  .evaluation-guide-actions {
    width: 100%;
    flex-direction: column-reverse;
    align-items: stretch;
  }

  .evaluation-guide-actions button {
    width: 100%;
  }

  .evaluation-design-steps {
    grid-template-columns: 1fr;
    padding: 0 18px 18px;
  }

  .evaluation-boundary {
    padding: 12px 18px;
  }

  .evaluation-summary {
    grid-template-columns: 1fr;
  }

  .evaluation-summary article,
  .evaluation-summary article:nth-child(2) {
    min-height: 88px;
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }

  .evaluation-summary article:last-child {
    border-bottom: 0;
  }

  .evaluation-page-header {
    align-items: stretch;
    flex-direction: column;
  }

  .evaluation-heading-actions {
    align-items: stretch;
    flex-direction: column-reverse;
  }

  .evaluation-tabs {
    padding: 0;
  }

  .evaluation-tabs button {
    flex: 1;
    padding: 0 8px;
  }

  .evaluation-table-wrap {
    overflow: visible;
    padding: 14px;
  }

  .evaluation-table,
  .evaluation-table tbody {
    min-width: 0;
    display: grid;
    gap: 12px;
  }

  .evaluation-table thead {
    display: none;
  }

  .evaluation-table tr {
    min-width: 0;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
    border: 1px solid var(--line);
    border-radius: 6px;
    padding: 14px;
    background: #fbfdff;
  }

  .evaluation-table td {
    min-width: 0;
    display: grid;
    align-content: start;
    gap: 4px;
    border: 0;
    padding: 0;
    white-space: normal;
    overflow-wrap: anywhere;
  }

  .evaluation-table td::before {
    content: attr(data-label);
    color: var(--muted);
    font-size: 12px;
    font-weight: 500;
  }

  .evaluation-table td:first-child,
  .evaluation-table td:last-child,
  .evaluation-wrap-cell {
    grid-column: 1 / -1;
    max-width: none;
  }

  .evaluation-table td:first-child {
    padding-bottom: 12px;
    border-bottom: 1px solid var(--line);
  }

  .evaluation-row-actions {
    align-items: stretch;
  }

  .evaluation-row-actions button {
    min-height: 44px;
    flex: 1;
    border: 1px solid var(--line);
    border-radius: 6px;
    background: #fff;
  }
}
</style>
