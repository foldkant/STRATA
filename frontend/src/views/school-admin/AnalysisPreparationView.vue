<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import {
  createAdvancedModelComparison,
  createAnalysisDataset,
  createAnalysisDecisionPoint,
  createClassCalibration,
  createContentBandPolicy,
  createLongitudinalAnalysis,
  createModelComparison,
  getAnalysisPreparation,
  getContentBandPolicies,
  getModelValidation,
  modelReleasePackageUrl,
  publishClassCalibration,
  publishContentBandPolicy,
  refreshAnalysisOutcomes,
  rollbackModelRelease,
  trainStratificationModel,
  verifyModelRelease,
  type AnalysisDataset,
  type AnalysisPreparation,
  type ContentBandPolicy,
  type ModelValidation
} from '@/api/analytics'
import { ApiError } from '@/api/client'
import NoticeLine from '@/components/NoticeLine.vue'
import ModelOperationsOverview from '@/components/school-admin/ModelOperationsOverview.vue'
import AppShell from '@/layouts/AppShell.vue'
import { schoolAdminNav } from './nav'

const navItems = schoolAdminNav('/school-admin/models')
const data = ref<AnalysisPreparation | null>(null)
const validation = ref<ModelValidation | null>(null)
const contentBandPolicies = ref<ContentBandPolicy[]>([])
const loading = ref(true)
const working = ref(false)
const pointModalOpen = ref(false)
const datasetModalOpen = ref(false)
const policyModalOpen = ref(false)
const showAllDecisionPoints = ref(false)
const notice = ref('')
const noticeTone = ref<'success' | 'warning' | 'error' | 'info'>('info')
const activeSection = ref<'overview' | 'data' | 'standards' | 'research'>('overview')

const pointForm = reactive({
  class_id: 0,
  course_id: 0,
  title: ''
})
const datasetForm = reactive({
  subject_id: 0,
  outcome_key: ''
})
const policyForm = reactive({
  subject: 0,
  name: '',
  a_min: 0.8,
  b_min: 0.6,
  boundary_margin: 0.03,
  hysteresis_margin: 0.03,
  max_measurement_error: 0.18,
  min_common_items: 5,
  min_answered_ratio: 0.8,
  required_consecutive_windows: 2,
  cooldown_days: 14
})

const availableCourses = computed(() =>
  (data.value?.options.courses || []).filter((course) =>
    course.class_ids.includes(pointForm.class_id)
  )
)

const subjects = computed(() => {
  const rows = new Map<number, { id: number; name: string }>()
  for (const course of data.value?.options.courses || []) {
    rows.set(course.subject.id, course.subject)
  }
  return [...rows.values()].sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
})

const selectedOutcome = computed(() =>
  data.value?.outcome_definitions.find((item) => item.key === datasetForm.outcome_key)
)

const visibleDecisionPoints = computed(() => {
  const points = data.value?.decision_points || []
  return showAllDecisionPoints.value ? points : points.slice(0, 8)
})

const controlLabels: Record<string, string> = {
  label_permutation: '结果打乱检查',
  random_identifier: '随机编号检查',
  future_sentinel: '未来信息检查',
  data_availability: '技术条件检查',
  class_only: '班级身份检查'
}

watch(
  () => pointForm.class_id,
  () => {
    if (!availableCourses.value.some((item) => item.id === pointForm.course_id)) {
      pointForm.course_id = availableCourses.value[0]?.id || 0
    }
  }
)

function formatDateTime(value: string | null) {
  if (!value) return '-'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime())
    ? '-'
    : parsed.toLocaleString('zh-CN', { hour12: false })
}

function shortHash(value: string) {
  return value ? `${value.slice(0, 8)}...${value.slice(-6)}` : '-'
}

function pointStatus(point: AnalysisPreparation['decision_points'][number]) {
  if (point.status === 'planned') return { label: '等待冻结', tone: 'info' }
  if (!point.quality_checks_passed || point.snapshot_counts.blocked) {
    return { label: '记录需检查', tone: 'warning' }
  }
  return { label: '快照已冻结', tone: 'success' }
}

function datasetStatus(dataset: AnalysisDataset) {
  if (dataset.comparison_ready) return { label: '可进入下一步检查', tone: 'success' }
  return { label: '仅供流程验证', tone: 'warning' }
}

function toneClass(tone: string) {
  return `analysis-tone-${tone}`
}

function calibrationState(run: ModelValidation['calibration_runs'][number]) {
  if (run.release?.status === 'active') return '当前已发布'
  if (run.release?.status === 'superseded') return '已被新版本替代'
  if (run.release?.status === 'rolled_back') return '已停用'
  if (run.status === 'candidate') return '候选待发布'
  return run.status_label
}

async function loadData(showLoading = true) {
  if (showLoading) loading.value = true
  try {
    const [preparation, modelValidation, policies] = await Promise.all([
      getAnalysisPreparation(),
      getModelValidation(),
      getContentBandPolicies()
    ])
    data.value = preparation
    validation.value = {
      ...modelValidation,
      datasets: modelValidation.datasets || [],
      longitudinal_runs: modelValidation.longitudinal_runs || [],
      comparison_runs: modelValidation.comparison_runs || [],
      calibration_runs: modelValidation.calibration_runs || [],
      releases: modelValidation.releases || [],
      release_audits: modelValidation.release_audits || []
    }
    contentBandPolicies.value = policies
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '分析准备情况加载失败。'
    noticeTone.value = 'error'
  } finally {
    loading.value = false
  }
}

function datasetHasRun(dataset: AnalysisDataset, type: 'longitudinal' | 'comparison' | 'advanced' | 'calibration') {
  if (!validation.value) return false
  if (type === 'longitudinal') {
    return validation.value.longitudinal_runs.some((run) => run.dataset_id === dataset.id)
  }
  if (type === 'calibration') {
    return validation.value.calibration_runs.some((run) => run.dataset_id === dataset.id)
  }
  const version = type === 'advanced' ? 'model-02' : 'model-01'
  return validation.value.comparison_runs.some(
    (run) => run.dataset_id === dataset.id && run.comparison_version.startsWith(version)
  )
}

function latestComparison(datasetId: number) {
  return validation.value?.comparison_runs.find((run) => run.dataset_id === datasetId)
}

async function runValidation(dataset: AnalysisDataset, type: 'longitudinal' | 'comparison') {
  if (working.value) return
  working.value = true
  notice.value = ''
  try {
    if (type === 'longitudinal') {
      await createLongitudinalAnalysis({ dataset_id: dataset.id })
      notice.value = '重复测量统计已生成，页面只展示描述性结果。'
    } else {
      await createModelComparison({ dataset_id: dataset.id })
      notice.value = 'M00-M03 比较已生成，结果仅用于影子核查。'
    }
    noticeTone.value = 'success'
    await loadData(false)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '验证任务生成失败。'
    noticeTone.value = 'error'
  } finally {
    working.value = false
  }
}

async function runAdvancedValidation(dataset: AnalysisDataset, type: 'advanced' | 'calibration') {
  if (working.value) return
  working.value = true
  notice.value = ''
  try {
    if (type === 'advanced') {
      await createAdvancedModelComparison({ dataset_id: dataset.id })
      notice.value = 'CatBoost、LightGBM 与四种基础方法的同范围比较已生成。'
    } else {
      const result = await createClassCalibration({ dataset_id: dataset.id })
      notice.value = result.run.status === 'candidate'
        ? `已生成 ${result.run.suggestion_count} 条学习支持候选，学生层级没有自动改变。`
        : '班级校准暂未生成建议，页面已保留阻塞原因。'
    }
    noticeTone.value = 'success'
    await loadData(false)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '模型任务生成失败。'
    noticeTone.value = 'error'
  } finally {
    working.value = false
  }
}

async function runFullModelTraining(dataset: AnalysisDataset) {
  if (
    working.value
    || !window.confirm(`确认使用“${dataset.subject.name} · ${dataset.outcome.label}”开始模型训练？`)
  ) return
  working.value = true
  notice.value = ''
  try {
    const result = await trainStratificationModel({ dataset_id: dataset.id })
    notice.value = result.calibration_run.status === 'candidate'
      ? `训练完成：已选择 ${result.calibration_run.model_key}，生成 ${result.calibration_run.suggestion_count} 条学习支持候选。`
      : '训练检查已经完成，当前数据暂不能生成教师分层建议。'
    noticeTone.value = result.calibration_run.status === 'candidate' ? 'success' : 'warning'
    await loadData(false)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '模型训练失败，已有发布版本没有改变。'
    noticeTone.value = 'error'
  } finally {
    working.value = false
  }
}

async function publishCandidate(runId: number) {
  if (working.value || !window.confirm('确认发布这个候选版本？发布后教师才能看到对应的分层建议。')) return
  working.value = true
  notice.value = ''
  try {
    const result = await publishClassCalibration(runId)
    notice.value = result.release.is_test_data
      ? `测试模型 v${result.release.release_version} 已发布，仅用于本地流程验收。`
      : `模型 v${result.release.release_version} 已发布。`
    noticeTone.value = result.release.is_test_data ? 'warning' : 'success'
    await loadData(false)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '候选发布失败，当前使用版本没有改变。'
    noticeTone.value = 'error'
  } finally {
    working.value = false
  }
}

async function verifyRelease(releaseId: number) {
  if (working.value) return
  working.value = true
  notice.value = ''
  try {
    await verifyModelRelease(releaseId)
    notice.value = '模型包签名和文件校验通过。'
    noticeTone.value = 'success'
    await loadData(false)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '模型包校验失败。'
    noticeTone.value = 'error'
  } finally {
    working.value = false
  }
}

async function rollbackRelease(releaseId: number, version: number) {
  if (working.value || !window.confirm(`确认回滚到 v${version}？回滚前系统会重新校验离线模型包。`)) return
  working.value = true
  notice.value = ''
  try {
    const result = await rollbackModelRelease(releaseId)
    notice.value = `已回滚到模型 v${result.release.release_version}。`
    noticeTone.value = 'success'
    await loadData(false)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '模型回滚失败，当前使用版本没有改变。'
    noticeTone.value = 'error'
  } finally {
    working.value = false
  }
}

function openPointModal() {
  const firstClass = data.value?.options.classes.find((item) => item.student_count > 0)
    || data.value?.options.classes[0]
  pointForm.class_id = firstClass?.id || 0
  pointForm.course_id = availableCourses.value[0]?.id || 0
  pointForm.title = ''
  pointModalOpen.value = true
}

function openDatasetModal() {
  datasetForm.subject_id = subjects.value[0]?.id || 0
  datasetForm.outcome_key = data.value?.outcome_definitions[0]?.key || ''
  datasetModalOpen.value = true
}

function openPolicyModal() {
  policyForm.subject = subjects.value[0]?.id || 0
  policyForm.name = subjects.value[0] ? `${subjects.value[0].name}学习内容层级标准` : ''
  policyForm.a_min = 0.8
  policyForm.b_min = 0.6
  policyForm.boundary_margin = 0.03
  policyForm.hysteresis_margin = 0.03
  policyForm.max_measurement_error = 0.18
  policyForm.min_common_items = 5
  policyForm.min_answered_ratio = 0.8
  policyForm.required_consecutive_windows = 2
  policyForm.cooldown_days = 14
  policyModalOpen.value = true
}

async function saveContentBandPolicy() {
  if (!policyForm.subject || working.value) return
  working.value = true
  notice.value = ''
  try {
    await createContentBandPolicy({ ...policyForm })
    policyModalOpen.value = false
    notice.value = '层级标准草稿已保存，启用前可继续核对参数。'
    noticeTone.value = 'success'
    await loadData(false)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '层级标准保存失败。'
    noticeTone.value = 'error'
  } finally {
    working.value = false
  }
}

async function activateContentBandPolicy(policy: ContentBandPolicy) {
  if (working.value || !window.confirm(`确认启用“${policy.name} v${policy.version_no}”？原有启用版本将转为历史记录。`)) return
  working.value = true
  notice.value = ''
  try {
    await publishContentBandPolicy(policy.id)
    notice.value = '层级标准已启用。后续共同测试将按这个版本生成教师审核建议。'
    noticeTone.value = 'success'
    await loadData(false)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '层级标准启用失败。'
    noticeTone.value = 'error'
  } finally {
    working.value = false
  }
}

async function saveDecisionPoint() {
  if (!pointForm.class_id || !pointForm.course_id || working.value) return
  working.value = true
  notice.value = ''
  try {
    await createAnalysisDecisionPoint({
      class_id: pointForm.class_id,
      course_id: pointForm.course_id,
      title: pointForm.title.trim() || undefined
    })
    pointModalOpen.value = false
    notice.value = '分析时间点已建立，学习记录已按当前时间冻结。'
    noticeTone.value = 'success'
    await loadData(false)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '分析时间点建立失败。'
    noticeTone.value = 'error'
  } finally {
    working.value = false
  }
}

async function refreshOutcomes() {
  if (working.value) return
  working.value = true
  notice.value = ''
  try {
    const result = await refreshAnalysisOutcomes()
    notice.value = `已更新到期结果：可用 ${result.observed || 0}，无可用材料 ${result.unobserved || 0}，仍在等待 ${result.pending || 0}。`
    noticeTone.value = 'success'
    await loadData(false)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '到期结果更新失败。'
    noticeTone.value = 'error'
  } finally {
    working.value = false
  }
}

async function saveDataset() {
  if (!datasetForm.subject_id || !datasetForm.outcome_key || working.value) return
  working.value = true
  notice.value = ''
  try {
    const result = await createAnalysisDataset({ ...datasetForm })
    datasetModalOpen.value = false
    notice.value = result.dataset.comparison_ready
      ? '数据版本已冻结，可以进入下一步技术复核。'
      : '数据版本已冻结，目前只用于流程验证，页面已列出暂不能进入下一步的原因。'
    noticeTone.value = result.dataset.comparison_ready ? 'success' : 'warning'
    await loadData(false)
  } catch (error) {
    notice.value = error instanceof ApiError ? error.message : '数据版本生成失败。'
    noticeTone.value = 'error'
  } finally {
    working.value = false
  }
}

onMounted(loadData)
</script>

<template>
  <AppShell title="学习情况与支持建议" eyebrow="学校教学管理" :nav-items="navItems" shell-variant="school-admin" natural-scroll>
    <section class="analysis-page-heading">
      <div>
        <h2>学习情况分析管理</h2>
        <p>检查学习材料是否充分，更新分析结果并供任课教师确认后续教学安排；学生端不显示内部层级。</p>
      </div>
    </section>

    <NoticeLine v-if="notice" :message="notice" :tone="noticeTone" floating @dismiss="notice = ''" />
    <NoticeLine
      v-if="data?.test_data_visible"
      message="当前为本地测试环境，页面会显示带测试标记的数据；正式部署默认排除。"
      tone="warning"
    />

    <div v-if="!loading && data" class="analysis-section-toolbar">
      <nav class="analysis-section-tabs" aria-label="学习情况分析页面">
        <button type="button" :class="{ active: activeSection === 'overview' }" @click="activeSection = 'overview'">分析概览</button>
        <button type="button" :class="{ active: activeSection === 'data' }" @click="activeSection = 'data'">材料准备</button>
        <button type="button" :class="{ active: activeSection === 'standards' }" @click="activeSection = 'standards'">层级参考</button>
        <button type="button" :class="{ active: activeSection === 'research' }" @click="activeSection = 'research'">技术复核</button>
      </nav>
      <div v-if="activeSection === 'data'" class="analysis-page-actions">
        <button class="secondary-button" type="button" :disabled="working" @click="refreshOutcomes">
          更新到期结果
        </button>
        <button class="secondary-button" type="button" :disabled="working" @click="openDatasetModal">
          生成数据版本
        </button>
        <button class="primary-button" type="button" :disabled="working" @click="openPointModal">
          建立分析时间点
        </button>
      </div>
      <div v-else-if="activeSection === 'standards'" class="analysis-page-actions">
        <button class="primary-button" type="button" :disabled="working || !subjects.length" @click="openPolicyModal">
          新建层级标准
        </button>
      </div>
    </div>

    <section v-if="loading" class="panel analysis-loading" aria-live="polite">
      <strong>正在加载分析准备情况</strong>
      <span>请稍候</span>
    </section>

    <template v-else-if="data">
      <ModelOperationsOverview
        v-if="activeSection === 'overview' && validation"
        :datasets="data.datasets"
        :validation="validation"
        :working="working"
        @train="runFullModelTraining"
        @publish="publishCandidate"
        @verify="verifyRelease"
      />

      <template v-if="activeSection === 'data'">
      <section class="analysis-summary-grid" aria-label="分析准备汇总">
        <article>
          <span>已登记学习指标</span>
          <strong>{{ data.summary.feature_definition_count }}</strong>
          <small>{{ data.summary.model_input_feature_count }} 项满足首期分析条件</small>
        </article>
        <article>
          <span>分析时间点</span>
          <strong>{{ data.summary.decision_point_count }}</strong>
          <small>每次固定班级、课程和时间</small>
        </article>
        <article>
          <span>学习记录快照</span>
          <strong>{{ data.summary.snapshot_count }}</strong>
          <small>{{ data.summary.ready_snapshot_count }} 条学习记录检查通过</small>
        </article>
        <article>
          <span>已到期学习结果</span>
          <strong>{{ data.summary.observed_outcome_count }}</strong>
          <small>{{ data.summary.pending_outcome_count }} 条仍在等待</small>
        </article>
        <article>
          <span>冻结数据版本</span>
          <strong>{{ data.summary.dataset_count }}</strong>
          <small>{{ data.summary.comparison_ready_dataset_count }} 个可进入下一步检查</small>
        </article>
      </section>

      <section v-if="data.blockers.length" class="analysis-blocker-band" aria-label="当前待处理事项">
        <strong>当前还不能进入下一步分析</strong>
        <div>
          <span v-for="item in data.blockers" :key="item">{{ item }}</span>
        </div>
      </section>
      <section v-else class="analysis-ready-band">
        <strong>准备数据已经齐全</strong>
        <span>可以进入下一阶段分析，但仍需通过独立测试和人工审核。</span>
      </section>

      <section class="analysis-definition-strip">
        <header>
          <div>
            <h2>当前学习指标版本</h2>
            <p>{{ data.feature_set?.label || '尚未建立' }} · {{ data.feature_set?.version || '-' }}</p>
          </div>
          <small :title="data.feature_set?.manifest_hash || ''">{{ shortHash(data.feature_set?.manifest_hash || '') }}</small>
        </header>
        <div>
          <article v-for="group in data.feature_groups" :key="group.key">
            <span>{{ group.label }}</span>
            <strong>{{ group.count }}</strong>
          </article>
        </div>
      </section>

      <section class="panel analysis-table-panel">
        <div class="panel-heading split">
          <div>
            <h2>分析时间点</h2>
            <p>已冻结记录不会因后续补交、教师操作或页面刷新而改变。</p>
          </div>
          <button class="secondary-button" type="button" @click="openPointModal">新增</button>
        </div>
        <div v-if="data.decision_points.length" class="analysis-table-wrap">
          <table class="analysis-table">
            <thead>
              <tr>
                <th>班级与课程</th>
                <th>时间</th>
                <th>学习记录</th>
                <th>随后结果</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="point in visibleDecisionPoints" :key="point.id">
                <td data-label="班级与课程">
                  <strong>{{ point.class_group.name }} · {{ point.course?.title || point.subject.name }}</strong>
                  <small>{{ point.subject.name }} · {{ point.purpose_label }}</small>
                </td>
                <td data-label="时间">{{ formatDateTime(point.scheduled_for) }}</td>
                <td data-label="学习记录">
                  <strong>{{ point.student_count }} 人</strong>
                  <small>可用 {{ point.snapshot_counts.ready || 0 }} · 需检查 {{ point.snapshot_counts.blocked || 0 }}</small>
                </td>
                <td data-label="随后结果">
                  <strong>已到期 {{ point.outcome_counts.observed || 0 }}</strong>
                  <small>等待 {{ point.outcome_counts.pending || 0 }} · 无可用材料 {{ point.outcome_counts.unobserved || 0 }}</small>
                </td>
                <td data-label="状态">
                  <span class="analysis-status" :class="toneClass(pointStatus(point).tone)">
                    {{ pointStatus(point).label }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="data.decision_points.length > 8" class="analysis-table-more">
          <button class="secondary-button" type="button" @click="showAllDecisionPoints = !showAllDecisionPoints">
            {{ showAllDecisionPoints ? '收起较早记录' : `显示全部 ${data.decision_points.length} 个时间点` }}
          </button>
        </div>
        <p v-if="!data.decision_points.length" class="analysis-empty-copy">尚未建立分析时间点。</p>
      </section>

      <section class="panel analysis-table-panel">
        <div class="panel-heading split">
          <div>
            <h2>冻结数据版本</h2>
            <p>每个版本固定学习指标、未来结果、学生分组、时间分组和来源摘要。</p>
          </div>
          <button class="secondary-button" type="button" @click="openDatasetModal">生成</button>
        </div>
        <div v-if="data.datasets.length" class="analysis-table-wrap">
          <table class="analysis-table dataset-table">
            <thead>
              <tr>
                <th>学科与结果</th>
                <th>范围</th>
                <th>记录</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="dataset in data.datasets" :key="dataset.id">
                <td data-label="学科与结果">
                  <strong>{{ dataset.subject.name }} · {{ dataset.outcome.label }}</strong>
                  <small :title="dataset.manifest_hash">
                    {{ dataset.is_test_data ? '测试数据 · ' : '' }}版本 {{ dataset.feature_set.version }} · {{ shortHash(dataset.manifest_hash) }}
                  </small>
                </td>
                <td data-label="范围">
                  <span>{{ formatDateTime(dataset.decision_start) }}</span>
                  <small>至 {{ formatDateTime(dataset.decision_end) }}</small>
                </td>
                <td data-label="记录">
                  <strong>{{ dataset.row_count }} 条</strong>
                  <small>可用结果 {{ dataset.observed_count }} · 无结果 {{ dataset.unobserved_count }}</small>
                </td>
                <td data-label="状态">
                  <span class="analysis-status" :class="toneClass(datasetStatus(dataset).tone)">
                    {{ datasetStatus(dataset).label }}
                  </span>
                  <small v-if="dataset.blockers.length" :title="dataset.blockers.join('；')">
                    {{ dataset.blockers[0] }}
                  </small>
                </td>
                <td data-label="操作">
                  <a class="secondary-button compact-action" :href="`/api/v1/school-admin/analytics/preparation/datasets/${dataset.id}/export/?include_test_data=1`">
                    导出 XLSX
                  </a>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="analysis-empty-copy">随后学习结果到期后，才能生成冻结数据版本。</p>
      </section>
      </template>

      <section v-if="activeSection === 'standards'" class="panel analysis-table-panel">
        <div class="panel-heading split">
          <div>
            <h2>学习内容层级标准</h2>
            <p>按学科设置共同测试的 A、B、C 参考范围；完成率和逾期情况只用于安排学习支持。</p>
          </div>
          <button class="primary-button" type="button" :disabled="working || !subjects.length" @click="openPolicyModal">新建</button>
        </div>
        <div v-if="contentBandPolicies.length" class="analysis-table-wrap">
          <table class="analysis-table content-band-policy-table">
            <thead>
              <tr><th>学科与版本</th><th>层级范围</th><th>变化保护</th><th>状态</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="policy in contentBandPolicies" :key="policy.id">
                <td data-label="学科与版本">
                  <strong>{{ policy.subject.name }} · v{{ policy.version_no }}</strong>
                  <small>{{ policy.course?.title || '本学科通用' }}</small>
                </td>
                <td data-label="层级范围">
                  <strong>A ≥ {{ Math.round(policy.a_min * 100) }}% · B ≥ {{ Math.round(policy.b_min * 100) }}%</strong>
                  <small>边界范围 ±{{ Math.round(policy.boundary_margin * 100) }}%</small>
                </td>
                <td data-label="变化保护">
                  <span>连续 {{ policy.required_consecutive_windows }} 次 · 冷却 {{ policy.cooldown_days }} 天</span>
                  <small>至少 {{ policy.min_common_items }} 道共同题 · 完成 {{ Math.round(policy.min_answered_ratio * 100) }}%</small>
                </td>
                <td data-label="状态">
                  <span class="analysis-status" :class="toneClass(policy.status === 'active' ? 'success' : policy.status === 'draft' ? 'warning' : 'info')">
                    {{ policy.status_label }}
                  </span>
                  <small>{{ formatDateTime(policy.published_at) }}</small>
                </td>
                <td data-label="操作">
                  <button
                    v-if="policy.status === 'draft'"
                    class="primary-button compact-action"
                    type="button"
                    :disabled="working"
                    @click="activateContentBandPolicy(policy)"
                  >启用</button>
                  <span v-else>{{ policy.status === 'active' ? '当前使用' : '历史版本' }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="analysis-empty-copy">尚未建立层级标准。新建后先核对，再手动启用。</p>
      </section>

      <section v-if="activeSection === 'research'" class="analysis-validation-section" aria-label="详细模型检查">
        <header class="analysis-validation-heading">
          <div>
            <h2>统计验证</h2>
            <p>依次检查重复测量、透明基线、结构化模型和班级校准。所有结果均需教师确认。</p>
          </div>
          <span class="analysis-validation-badge">M00-M03 · 影子比较</span>
        </header>

        <div v-if="data.datasets.length" class="analysis-validation-datasets">
          <article v-for="dataset in data.datasets" :key="dataset.id" class="analysis-validation-card">
            <div class="analysis-validation-card-head">
              <div>
                <span>{{ dataset.subject.name }}</span>
                <strong>{{ dataset.outcome.label }}</strong>
                <small>{{ dataset.row_count }} 条记录 · {{ dataset.comparison_ready ? '满足基础数据条件' : '仅用于流程验证' }}</small>
              </div>
              <span class="analysis-status" :class="toneClass(dataset.comparison_ready ? 'success' : 'warning')">
                {{ dataset.comparison_ready ? '可核查' : '数据不足' }}
              </span>
            </div>
            <div class="analysis-validation-card-actions">
              <button
                class="secondary-button compact-action"
                type="button"
                :disabled="working || datasetHasRun(dataset, 'longitudinal')"
                @click="runValidation(dataset, 'longitudinal')"
              >
                {{ datasetHasRun(dataset, 'longitudinal') ? '已生成重复测量' : '重复测量统计' }}
              </button>
              <button
                class="primary-button compact-action"
                type="button"
                :disabled="working || datasetHasRun(dataset, 'comparison')"
                @click="runValidation(dataset, 'comparison')"
              >
                {{ datasetHasRun(dataset, 'comparison') ? '已生成模型比较' : '运行 M00-M03' }}
              </button>
              <button
                class="secondary-button compact-action"
                type="button"
                :disabled="working || datasetHasRun(dataset, 'advanced') || !dataset.comparison_ready"
                @click="runAdvancedValidation(dataset, 'advanced')"
              >
                {{ datasetHasRun(dataset, 'advanced') ? '结构化模型已比较' : '比较 CatBoost / LightGBM' }}
              </button>
              <button
                class="primary-button compact-action"
                type="button"
                :disabled="working || datasetHasRun(dataset, 'calibration') || !datasetHasRun(dataset, 'advanced')"
                @click="runAdvancedValidation(dataset, 'calibration')"
              >
                {{ datasetHasRun(dataset, 'calibration') ? '班级候选已生成' : '生成班级校准候选' }}
              </button>
            </div>
            <p v-if="latestComparison(dataset.id)?.manifest.blockers?.length" class="analysis-validation-note">
              {{ latestComparison(dataset.id)?.manifest.blockers?.[0] }}
            </p>
          </article>
        </div>
        <p v-else class="analysis-empty-copy">先生成冻结数据版本，再运行统计验证。</p>

        <div v-if="validation?.comparison_runs.length" class="analysis-validation-results">
          <div class="panel-heading split">
            <div>
              <h3>最近模型比较</h3>
              <p>数据不足、验证不适用和拒绝预测会单独标记，不用假设填补。</p>
            </div>
          </div>
          <div class="analysis-table-wrap">
            <table class="analysis-table validation-result-table">
              <thead>
                <tr><th>学科与结果</th><th>验证折</th><th>M00-M03</th><th>负对照</th><th>操作</th></tr>
              </thead>
              <tbody>
                <tr v-for="run in validation.comparison_runs" :key="run.id">
                  <td data-label="学科与结果">
                    <strong>{{ run.subject.name }} · {{ run.model_card.title || '模型比较' }}</strong>
                    <small>{{ run.row_count }} 条已观察结果 · {{ run.status_label }}</small>
                    <small>完成时间：{{ formatDateTime(run.finished_at || run.created_at) }}</small>
                  </td>
                  <td data-label="检查方式"><span>{{ run.validation_keys.join('、') }}</span><small>测试样本不足时不输出指标</small></td>
                  <td data-label="比较方法">
                    <strong>{{ run.evaluations.filter((item) => item.status === 'ready').length }} 个可报告单元</strong>
                    <small>{{ run.model_keys.join('、') }}</small>
                  </td>
                  <td data-label="防误判检查">
                    <span v-for="control in run.negative_controls" :key="control.control_key" class="analysis-control-chip" :class="toneClass(control.status === 'passed' ? 'success' : control.status === 'failed' ? 'warning' : 'info')">
                      {{ controlLabels[control.control_key] || control.control_key }} · {{ control.status_label }}
                    </span>
                  </td>
                  <td data-label="操作"><a class="secondary-button compact-action" :href="`/api/v1/school-admin/analytics/models/${run.id}/export/?include_test_data=1`">导出 XLSX</a></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div v-if="validation?.calibration_runs.length" class="analysis-calibration-results">
          <header><div><h3>候选与发布</h3><p>发布后教师可处理建议，学生端不显示层级。</p></div></header>
          <article v-for="run in validation.calibration_runs" :key="run.id" class="analysis-calibration-row">
            <div class="analysis-calibration-main">
              <strong>{{ run.subject.name }} · {{ run.model_key || '暂未选择模型' }}</strong>
              <small>{{ run.calibration_version }} · {{ calibrationState(run) }}<template v-if="run.release"> · v{{ run.release.release_version }}</template></small>
              <small>开始：{{ formatDateTime(run.created_at) }} · 完成：{{ formatDateTime(run.finished_at) }}</small>
            </div>
            <div class="analysis-calibration-counts">
              <span>班级参数 {{ Object.keys(run.class_parameters).length }} 组</span>
              <strong>支持候选 {{ run.suggestion_count }} 条</strong>
            </div>
            <div class="analysis-release-actions">
              <span v-if="run.release?.is_test_data" class="analysis-status analysis-tone-warning">测试版本</span>
              <button
                v-if="run.status === 'candidate' && !run.release"
                class="primary-button compact-action"
                type="button"
                :disabled="working"
                @click="publishCandidate(run.id)"
              >发布候选</button>
              <button
                v-if="run.release"
                class="secondary-button compact-action"
                type="button"
                :disabled="working"
                @click="verifyRelease(run.release.id)"
              >校验模型包</button>
              <a
                v-if="run.release"
                class="secondary-button compact-action"
                :href="modelReleasePackageUrl(run.release.id)"
              >下载模型包</a>
            </div>
          </article>
        </div>

        <div v-if="validation?.releases.length" class="analysis-release-history">
          <header>
            <div><h3>发布历史</h3><p>历史版本保留签名包和操作记录；回滚不会重新训练模型。</p></div>
          </header>
          <div class="analysis-table-wrap">
            <table class="analysis-table release-history-table">
              <thead><tr><th>学科与版本</th><th>状态</th><th>签名</th><th>发布时间</th><th>操作</th></tr></thead>
              <tbody>
                <tr v-for="release in validation.releases" :key="release.id">
                  <td data-label="学科与版本">
                    <strong>{{ release.subject.name }} · v{{ release.release_version }}</strong>
                    <small>{{ release.model_key }}<template v-if="release.is_test_data"> · 测试数据</template></small>
                  </td>
                  <td data-label="状态"><span class="analysis-status" :class="toneClass(release.status === 'active' ? 'success' : 'info')">{{ release.status_label }}</span></td>
                  <td data-label="签名"><span :title="release.signing_key_id">Ed25519 · {{ shortHash(release.signing_key_id) }}</span><small :title="release.package_hash">包 {{ shortHash(release.package_hash) }}</small></td>
                  <td data-label="发布时间"><span>{{ formatDateTime(release.released_at) }}</span><small>{{ release.released_by }}</small></td>
                  <td data-label="操作" class="analysis-history-actions">
                    <button class="secondary-button compact-action" type="button" :disabled="working" @click="verifyRelease(release.id)">校验</button>
                    <button v-if="release.status !== 'active'" class="secondary-button compact-action" type="button" :disabled="working" @click="rollbackRelease(release.id, release.release_version)">回滚</button>
                    <a class="secondary-button compact-action" :href="modelReleasePackageUrl(release.id)">下载</a>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </template>

    <div v-if="pointModalOpen" class="modal-backdrop" role="presentation" @click.self="pointModalOpen = false">
      <form class="entity-modal compact-modal analysis-form-modal" role="dialog" aria-modal="true" aria-labelledby="analysis-point-title" @submit.prevent="saveDecisionPoint">
        <header class="modal-header">
          <div>
            <h2 id="analysis-point-title">建立分析时间点</h2>
            <p>保存此刻系统已经掌握的学习记录，随后 7 日结果单独观察。</p>
          </div>
          <button class="icon-button" type="button" aria-label="关闭" @click="pointModalOpen = false">×</button>
        </header>
        <div class="form-grid analysis-form-grid">
          <label>
            <span>班级 <b>*</b></span>
            <AppSelect v-model.number="pointForm.class_id" required>
              <option :value="0" disabled>请选择班级</option>
              <option v-for="item in data?.options.classes || []" :key="item.id" :value="item.id">
                {{ item.grade }} {{ item.name }}（{{ item.student_count }} 人）
              </option>
            </AppSelect>
          </label>
          <label>
            <span>课程 <b>*</b></span>
            <AppSelect v-model.number="pointForm.course_id" required>
              <option :value="0" disabled>请选择课程</option>
              <option v-for="item in availableCourses" :key="item.id" :value="item.id">
                {{ item.subject.name }} · {{ item.title }} · {{ item.teacher_name }}
              </option>
            </AppSelect>
            <small v-if="pointForm.class_id && !availableCourses.length">所选班级暂没有已启用课程。</small>
          </label>
          <label class="wide-field">
            <span>名称</span>
            <input v-model.trim="pointForm.title" maxlength="160" placeholder="留空时自动使用班级和课程名称">
          </label>
        </div>
        <footer class="modal-actions">
          <button class="secondary-button" type="button" :disabled="working" @click="pointModalOpen = false">取消</button>
          <button class="primary-button" type="submit" :disabled="working || !pointForm.class_id || !pointForm.course_id">
            {{ working ? '正在建立' : '建立并冻结' }}
          </button>
        </footer>
      </form>
    </div>

    <div v-if="datasetModalOpen" class="modal-backdrop" role="presentation" @click.self="datasetModalOpen = false">
      <form class="entity-modal compact-modal analysis-form-modal" role="dialog" aria-modal="true" aria-labelledby="analysis-dataset-title" @submit.prevent="saveDataset">
        <header class="modal-header">
          <div>
            <h2 id="analysis-dataset-title">生成冻结数据版本</h2>
            <p>只使用已经冻结的当时数据和已经到期的未来结果。</p>
          </div>
          <button class="icon-button" type="button" aria-label="关闭" @click="datasetModalOpen = false">×</button>
        </header>
        <div class="form-grid analysis-form-grid">
          <label>
            <span>学科 <b>*</b></span>
            <AppSelect v-model.number="datasetForm.subject_id" required>
              <option :value="0" disabled>请选择学科</option>
              <option v-for="item in subjects" :key="item.id" :value="item.id">{{ item.name }}</option>
            </AppSelect>
          </label>
          <label>
            <span>随后结果 <b>*</b></span>
            <AppSelect v-model="datasetForm.outcome_key" required>
              <option value="" disabled>请选择未来结果</option>
              <option v-for="item in data?.outcome_definitions || []" :key="item.key" :value="item.key">
                {{ item.label }}
              </option>
            </AppSelect>
          </label>
          <div v-if="selectedOutcome" class="analysis-form-note wide-field">
            <strong>{{ selectedOutcome.label }}</strong>
            <span>观察 {{ selectedOutcome.horizon_days }} 日；至少需要 {{ selectedOutcome.min_denominator }} 个符合条件的任务机会。</span>
          </div>
        </div>
        <footer class="modal-actions">
          <button class="secondary-button" type="button" :disabled="working" @click="datasetModalOpen = false">取消</button>
          <button class="primary-button" type="submit" :disabled="working || !datasetForm.subject_id || !datasetForm.outcome_key">
            {{ working ? '正在生成' : '生成数据版本' }}
          </button>
        </footer>
      </form>
    </div>

    <div v-if="policyModalOpen" class="modal-backdrop" role="presentation" @click.self="policyModalOpen = false">
      <form class="entity-modal analysis-policy-modal" role="dialog" aria-modal="true" aria-labelledby="analysis-policy-title" @submit.prevent="saveContentBandPolicy">
        <header class="modal-header">
          <div>
            <h2 id="analysis-policy-title">新建学习内容层级标准</h2>
            <p>新版本保存为草稿，核对后再启用。</p>
          </div>
          <button class="icon-button" type="button" aria-label="关闭" @click="policyModalOpen = false">×</button>
        </header>
        <div class="form-grid analysis-policy-form">
          <label>
            <span>学科 <b>*</b></span>
            <AppSelect v-model.number="policyForm.subject" required>
              <option :value="0" disabled>请选择学科</option>
              <option v-for="item in subjects" :key="item.id" :value="item.id">{{ item.name }}</option>
            </AppSelect>
          </label>
          <label>
            <span>名称 <b>*</b></span>
            <input v-model.trim="policyForm.name" maxlength="128" required />
          </label>
          <label>
            <span>A 层起点 <b>*</b></span>
            <input v-model.number="policyForm.a_min" type="number" min="0.01" max="1" step="0.01" required />
            <small>0.80 表示 80%</small>
          </label>
          <label>
            <span>B 层起点 <b>*</b></span>
            <input v-model.number="policyForm.b_min" type="number" min="0" max="0.99" step="0.01" required />
            <small>低于此值进入 C 层建议范围</small>
          </label>
          <label>
            <span>边界范围</span>
            <input v-model.number="policyForm.boundary_margin" type="number" min="0" max="0.1" step="0.01" />
          </label>
          <label>
            <span>变化缓冲</span>
            <input v-model.number="policyForm.hysteresis_margin" type="number" min="0" max="0.1" step="0.01" />
          </label>
          <label>
            <span>最多测量误差</span>
            <input v-model.number="policyForm.max_measurement_error" type="number" min="0" max="1" step="0.01" />
          </label>
          <label>
            <span>最少共同题</span>
            <input v-model.number="policyForm.min_common_items" type="number" min="1" max="100" step="1" />
          </label>
          <label>
            <span>最低作答比例</span>
            <input v-model.number="policyForm.min_answered_ratio" type="number" min="0" max="1" step="0.05" />
          </label>
          <label>
            <span>连续材料次数</span>
            <input v-model.number="policyForm.required_consecutive_windows" type="number" min="1" max="10" step="1" />
          </label>
          <label>
            <span>变化冷却天数</span>
            <input v-model.number="policyForm.cooldown_days" type="number" min="0" max="365" step="1" />
          </label>
        </div>
        <footer class="modal-actions">
          <button class="secondary-button" type="button" :disabled="working" @click="policyModalOpen = false">取消</button>
          <button class="primary-button" type="submit" :disabled="working || !policyForm.subject || !policyForm.name">保存草稿</button>
        </footer>
      </form>
    </div>
  </AppShell>
</template>

<style scoped>
.analysis-policy-modal {
  width: min(820px, calc(100vw - 32px));
  max-height: calc(100dvh - 32px);
  grid-template-rows: auto minmax(0, 1fr) auto;
}

.analysis-policy-form {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  overflow: auto;
  padding: 18px;
}

.analysis-policy-form label {
  min-width: 0;
}

.analysis-policy-form input,
.analysis-policy-form select {
  min-width: 0;
  width: 100%;
}

.content-band-policy-table td strong,
.content-band-policy-table td span,
.content-band-policy-table td small {
  overflow-wrap: anywhere;
}

.analysis-calibration-results > .analysis-calibration-row {
  display: grid;
  grid-template-columns: minmax(190px, 1.2fr) minmax(180px, 0.8fr) minmax(220px, auto);
  align-items: center;
}

.analysis-calibration-main,
.analysis-calibration-counts {
  min-width: 0;
  display: grid;
  gap: 4px;
}

.analysis-calibration-main strong,
.analysis-calibration-main small,
.analysis-calibration-counts span {
  overflow-wrap: anywhere;
}

.analysis-release-actions,
.analysis-history-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
}

.analysis-release-history {
  min-width: 0;
  display: grid;
  gap: 12px;
  border-top: 1px solid var(--line);
  padding-top: 18px;
}

.analysis-release-history > header h3,
.analysis-release-history > header p {
  margin: 0;
}

.analysis-release-history > header p {
  margin-top: 4px;
  color: var(--muted);
  font-size: 13px;
}

@media (max-width: 1024px) {
  .analysis-calibration-results > .analysis-calibration-row {
    grid-template-columns: minmax(0, 1fr) minmax(170px, auto);
  }

  .analysis-release-actions {
    grid-column: 1 / -1;
    justify-content: flex-start;
  }
}

@media (max-width: 640px) {
  .analysis-policy-modal {
    width: calc(100vw - 18px);
    max-height: calc(100dvh - 18px);
  }

  .analysis-policy-form {
    grid-template-columns: 1fr;
  }

  .analysis-calibration-results > .analysis-calibration-row {
    grid-template-columns: 1fr;
  }

  .analysis-release-actions,
  .analysis-history-actions {
    justify-content: flex-start;
  }
}
</style>
