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
  type EvaluationPlanRow,
  type EvaluationOptions,
  type EvaluationStandardRow,
  type EvaluationTrialRow
} from '@/api/evaluation'
import EvaluationPlanEditorModal from '@/components/evaluation/EvaluationPlanEditorModal.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import NoticeLine from '@/components/NoticeLine.vue'
import EvaluationStandardEditorModal from '@/components/evaluation/EvaluationStandardEditorModal.vue'
import EvaluationTrialEditorModal from '@/components/evaluation/EvaluationTrialEditorModal.vue'
import AppShell from '@/layouts/AppShell.vue'
import { teacherNav } from './nav'

const navItems = teacherNav('/teacher/evaluations')
const activeTab = ref<'plans' | 'standards' | 'trials'>('plans')
const options = ref<EvaluationOptions | null>(null)
const plans = ref<EvaluationPlanRow[]>([])
const standards = ref<EvaluationStandardRow[]>([])
const trials = ref<EvaluationTrialRow[]>([])
const loading = ref(false)
const notice = ref('')
const noticeTone = ref<'success' | 'warning' | 'error' | 'info'>('info')
const planEditor = ref(false)
const standardEditor = ref(false)
const trialEditor = ref(false)
const editingPlan = ref<EvaluationPlanRow | null>(null)
const editingStandard = ref<EvaluationStandardRow | null>(null)
const editingTrial = ref<EvaluationTrialRow | null>(null)
const publishing = ref(false)
const publishTarget = ref<{ type: 'plan' | 'standard'; id: number; title: string } | null>(null)
const deleteTarget = ref<EvaluationTrialRow | null>(null)

const summary = computed(() => [
  { label: '评价方案', value: plans.value.length, detail: `${plans.value.filter((item) => item.latest_version).length} 个已发布` },
  { label: '评价标准', value: standards.value.length, detail: `${standards.value.reduce((sum, item) => sum + item.criterion_count, 0)} 个评价指标` },
  { label: '试用记录', value: trials.value.length, detail: `${trials.value.filter((item) => item.status === 'completed').length} 条已完成` },
  { label: '评分检查', value: trials.value.filter((item) => item.record_type === 'scoring_check').length, detail: '记录评分一致情况' }
])

const pageTitle = computed(() => activeTab.value === 'plans' ? '评价方案' : activeTab.value === 'standards' ? '评价标准' : '试用记录')
const pageDescription = computed(() => activeTab.value === 'plans'
  ? '围绕本人课程明确学习目标、评价依据和学习任务。'
  : activeTab.value === 'standards'
    ? '为每个评价指标设置具体表现、星级说明和评分示例。'
    : '记录内容审核、课堂试用、评分培训和评分一致性检查。')

function firstApiError(error: ApiError) {
  const first = Object.values(error.errors).flat()[0]
  return first || error.message
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
  notice.value = ''
  try {
    editingPlan.value = row ? await getEvaluationPlan(row.id) : null
    planEditor.value = true
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '评价方案加载失败。'
    noticeTone.value = 'error'
  }
}

async function openStandard(row?: EvaluationStandardRow) {
  notice.value = ''
  try {
    editingStandard.value = row ? await getEvaluationStandard(row.id) : null
    standardEditor.value = true
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '评价标准加载失败。'
    noticeTone.value = 'error'
  }
}

async function openTrial(row?: EvaluationTrialRow) {
  notice.value = ''
  try {
    editingTrial.value = row ? await getEvaluationTrial(row.id) : null
    trialEditor.value = true
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '评价试用记录加载失败。'
    noticeTone.value = 'error'
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

async function confirmDeleteTrial() {
  if (!deleteTarget.value) return
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
  }
}

function exportTrials() {
  window.location.href = evaluationTrialExportUrl()
}

function requestPublish(type: 'plan' | 'standard', row: EvaluationPlanRow | EvaluationStandardRow) {
  publishTarget.value = { type, id: row.id, title: row.title }
}

async function confirmPublish() {
  if (!publishTarget.value) return
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

onMounted(load)
</script>

<template>
  <AppShell title="评价标准" eyebrow="教师工作台" :nav-items="navItems">
    <NoticeLine v-if="notice" :message="notice" :tone="noticeTone" />

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
            :disabled="!options?.courses.length || (activeTab === 'standards' && !plans.length) || (activeTab === 'trials' && !options?.standard_versions.length)"
            @click="activeTab === 'plans' ? openPlan() : activeTab === 'standards' ? openStandard() : openTrial()"
          >
            {{ activeTab === 'plans' ? '新建方案' : activeTab === 'standards' ? '新建标准' : '新增记录' }}
          </button>
        </div>
      </header>

      <div class="evaluation-tabs" role="tablist" aria-label="评价管理类型">
        <button role="tab" type="button" :aria-selected="activeTab === 'plans'" :class="{ active: activeTab === 'plans' }" @click="activeTab = 'plans'">
          评价方案 <span>{{ plans.length }}</span>
        </button>
        <button role="tab" type="button" :aria-selected="activeTab === 'standards'" :class="{ active: activeTab === 'standards' }" @click="activeTab = 'standards'">
          评价标准 <span>{{ standards.length }}</span>
        </button>
        <button role="tab" type="button" :aria-selected="activeTab === 'trials'" :class="{ active: activeTab === 'trials' }" @click="activeTab = 'trials'">
          试用记录 <span>{{ trials.length }}</span>
        </button>
      </div>

      <div v-if="loading" class="evaluation-empty">正在加载</div>

      <div v-else-if="activeTab === 'plans'" class="evaluation-table-wrap">
        <p v-if="!plans.length" class="evaluation-empty">
          尚无评价方案。先选择一门课程，填写学习目标、评价依据和学习任务。
        </p>
        <table v-else class="evaluation-table">
          <thead><tr><th>方案</th><th>课程</th><th>内容</th><th>范围</th><th>版本</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="row in plans" :key="row.id">
              <td data-label="方案"><strong>{{ row.title }}</strong><small>内容版本 {{ row.content_version || '未填写' }}</small></td>
              <td data-label="课程"><strong>{{ row.course?.title || '未绑定课程' }}</strong><small>{{ row.subject.name }}</small></td>
              <td data-label="内容"><span>{{ row.goal_count }} 个目标</span><span>{{ row.basis_count }} 条依据</span><span>{{ row.task_count }} 个任务</span></td>
              <td data-label="范围">{{ row.scope_label }}</td>
              <td data-label="版本"><span class="evaluation-version" :class="{ published: row.latest_version }">{{ versionLabel(row) }}</span></td>
              <td data-label="操作">
                <div class="evaluation-row-actions">
                  <button type="button" @click="openPlan(row)">编辑</button>
                  <button type="button" @click="requestPublish('plan', row)">发布版本</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-else-if="activeTab === 'standards'" class="evaluation-table-wrap">
        <p v-if="!standards.length" class="evaluation-empty">
          尚无评价标准。评价标准需要绑定一个已发布的评价方案。
        </p>
        <table v-else class="evaluation-table">
          <thead><tr><th>评价标准</th><th>评价方案</th><th>评价对象</th><th>指标</th><th>版本</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="row in standards" :key="row.id">
              <td data-label="评价标准"><strong>{{ row.title }}</strong><small>{{ row.subject.name }} · {{ row.scope_label }}</small></td>
              <td data-label="评价方案">{{ row.plan.title }}</td>
              <td data-label="评价对象" class="evaluation-wrap-cell">{{ row.evaluation_target || '未填写' }}</td>
              <td data-label="指标">{{ row.criterion_count }} 项</td>
              <td data-label="版本"><span class="evaluation-version" :class="{ published: row.latest_version }">{{ versionLabel(row) }}</span></td>
              <td data-label="操作">
                <div class="evaluation-row-actions">
                  <button type="button" @click="openStandard(row)">编辑</button>
                  <button type="button" @click="requestPublish('standard', row)">发布版本</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-else class="evaluation-table-wrap">
        <p v-if="!trials.length" class="evaluation-empty">
          尚无试用记录。先发布评价标准，再记录审核、课堂试用或评分检查。
        </p>
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
                  <button type="button" @click="openTrial(row)">{{ row.status === 'completed' ? '查看' : '编辑' }}</button>
                  <button v-if="row.status !== 'completed'" class="danger-link" type="button" @click="deleteTarget = row">删除</button>
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
    <EvaluationStandardEditorModal
      v-if="standardEditor && options"
      :draft="editingStandard"
      :options="options"
      :plans="plans"
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
      @close="deleteTarget = null"
      @confirm="confirmDeleteTrial"
    />
  </AppShell>
</template>

<style scoped>
.evaluation-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
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
  background: #f8fafc;
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
  background: #e8f1ff;
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

.evaluation-wrap-cell {
  max-width: 320px;
  white-space: normal;
  line-height: 1.5;
}

.evaluation-version {
  display: inline-flex;
  align-items: center;
  min-height: 26px;
  border-radius: 999px;
  padding: 0 9px;
  background: #f1f5f9;
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
  background: #f1f5f9;
  color: #475569;
  font-size: 12px;
  font-weight: 600;
}

.evaluation-status.in_progress {
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

@media (max-width: 1000px) {
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
