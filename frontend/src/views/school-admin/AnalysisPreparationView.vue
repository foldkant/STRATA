<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import {
  createAdvancedModelComparison,
  createAnalysisDataset,
  createAnalysisDecisionPoint,
  createClassCalibration,
  createLongitudinalAnalysis,
  createModelComparison,
  getAnalysisPreparation,
  getModelValidation,
  refreshAnalysisOutcomes,
  type AnalysisDataset,
  type AnalysisPreparation,
  type ModelValidation
} from '@/api/analytics'
import { ApiError } from '@/api/client'
import NoticeLine from '@/components/NoticeLine.vue'
import AppShell from '@/layouts/AppShell.vue'
import { schoolAdminNav } from './nav'

const navItems = schoolAdminNav('/school-admin/models')
const data = ref<AnalysisPreparation | null>(null)
const validation = ref<ModelValidation | null>(null)
const loading = ref(true)
const working = ref(false)
const pointModalOpen = ref(false)
const datasetModalOpen = ref(false)
const showAllDecisionPoints = ref(false)
const notice = ref('')
const noticeTone = ref<'success' | 'warning' | 'error' | 'info'>('info')

const pointForm = reactive({
  class_id: 0,
  course_id: 0,
  title: ''
})
const datasetForm = reactive({
  subject_id: 0,
  outcome_key: ''
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
  if (dataset.comparison_ready) return { label: '可进入模型比较', tone: 'success' }
  return { label: '仅供流程验证', tone: 'warning' }
}

function toneClass(tone: string) {
  return `analysis-tone-${tone}`
}

async function loadData(showLoading = true) {
  if (showLoading) loading.value = true
  try {
    const [preparation, modelValidation] = await Promise.all([
      getAnalysisPreparation(),
      getModelValidation()
    ])
    data.value = preparation
    validation.value = modelValidation
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
        ? `已生成 ${result.run.suggestion_count} 条教师审核候选，学生层级没有自动改变。`
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
      ? '数据版本已冻结，可以进入后续模型比较。'
      : '数据版本已冻结，目前只用于流程验证，页面已列出暂不能比较的原因。'
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
  <AppShell title="分层分析" eyebrow="学校管理员" :nav-items="navItems" natural-scroll>
    <section class="analysis-page-heading">
      <div>
        <h2>分析准备情况</h2>
        <p>按固定时间保存当时可用的学习记录，等待随后学习结果，再生成可重复的数据版本。</p>
      </div>
      <div class="analysis-page-actions">
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
    </section>

    <NoticeLine v-if="notice" :message="notice" :tone="noticeTone" />
    <NoticeLine
      v-if="data?.test_data_visible"
      message="当前为本地测试环境，页面会显示带测试标记的数据；正式部署默认排除。"
      tone="warning"
    />

    <section v-if="loading" class="panel analysis-loading" aria-live="polite">
      <strong>正在加载分析准备情况</strong>
      <span>请稍候</span>
    </section>

    <template v-else-if="data">
      <section class="analysis-summary-grid" aria-label="分析准备汇总">
        <article>
          <span>已登记学习指标</span>
          <strong>{{ data.summary.feature_definition_count }}</strong>
          <small>{{ data.summary.model_input_feature_count }} 项可作为首期模型输入</small>
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
          <small>{{ data.summary.comparison_ready_dataset_count }} 个可进入模型比较</small>
        </article>
      </section>

      <section v-if="data.blockers.length" class="analysis-blocker-band" aria-label="当前待处理事项">
        <strong>当前还不能开始正式模型比较</strong>
        <div>
          <span v-for="item in data.blockers" :key="item">{{ item }}</span>
        </div>
      </section>
      <section v-else class="analysis-ready-band">
        <strong>准备数据已经齐全</strong>
        <span>可以进入下一阶段的模型比较，但仍需通过独立测试和人工审核。</span>
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

      <section class="analysis-validation-section" aria-label="统计验证">
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
          <header><div><h3>班级校准候选</h3><p>只生成教师审核建议，不改写学生当前层级。</p></div></header>
          <article v-for="run in validation.calibration_runs" :key="run.id">
            <div><strong>{{ run.subject.name }} · {{ run.model_key || '暂未选择模型' }}</strong><small>{{ run.calibration_version }} · {{ run.status_label }}</small></div>
            <div><span>班级参数 {{ Object.keys(run.class_parameters).length }} 组</span><strong>教师候选 {{ run.suggestion_count }} 条</strong></div>
          </article>
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
            <select v-model.number="pointForm.class_id" required>
              <option :value="0" disabled>请选择班级</option>
              <option v-for="item in data?.options.classes || []" :key="item.id" :value="item.id">
                {{ item.grade }} {{ item.name }}（{{ item.student_count }} 人）
              </option>
            </select>
          </label>
          <label>
            <span>课程 <b>*</b></span>
            <select v-model.number="pointForm.course_id" required>
              <option :value="0" disabled>请选择课程</option>
              <option v-for="item in availableCourses" :key="item.id" :value="item.id">
                {{ item.subject.name }} · {{ item.title }} · {{ item.teacher_name }}
              </option>
            </select>
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
            <select v-model.number="datasetForm.subject_id" required>
              <option :value="0" disabled>请选择学科</option>
              <option v-for="item in subjects" :key="item.id" :value="item.id">{{ item.name }}</option>
            </select>
          </label>
          <label>
            <span>随后结果 <b>*</b></span>
            <select v-model="datasetForm.outcome_key" required>
              <option value="" disabled>请选择未来结果</option>
              <option v-for="item in data?.outcome_definitions || []" :key="item.key" :value="item.key">
                {{ item.label }}
              </option>
            </select>
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
  </AppShell>
</template>
