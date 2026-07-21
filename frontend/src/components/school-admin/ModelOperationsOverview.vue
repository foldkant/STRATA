<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { EChartsCoreOption } from 'echarts/core'
import type {
  AnalysisDataset,
  ClassCalibrationRun,
  ModelEvaluation,
  ModelValidation
} from '@/api/analytics'
import EChartPanel from '@/components/EChartPanel.vue'

const props = defineProps<{
  datasets: AnalysisDataset[]
  validation: ModelValidation
  working: boolean
}>()

const emit = defineEmits<{
  train: [dataset: AnalysisDataset]
  publish: [runId: number]
  verify: [releaseId: number]
}>()

const selectedDatasetId = ref(0)
const selectedValidation = ref('V-A')

const readyDatasets = computed(() => props.datasets.filter((item) => item.comparison_ready))

watch(
  readyDatasets,
  (datasets) => {
    if (!datasets.some((item) => item.id === selectedDatasetId.value)) {
      selectedDatasetId.value = datasets[0]?.id || 0
    }
  },
  { immediate: true }
)

const selectedDataset = computed(() =>
  readyDatasets.value.find((item) => item.id === selectedDatasetId.value) || null
)

const comparisonRun = computed(() =>
  props.validation.comparison_runs.find(
    (run) => run.dataset_id === selectedDatasetId.value && run.comparison_version.startsWith('model-02')
  ) || null
)

const calibrationRun = computed<ClassCalibrationRun | null>(() =>
  props.validation.calibration_runs.find((run) => run.dataset_id === selectedDatasetId.value) || null
)

const activeRelease = computed(() => {
  const subjectId = selectedDataset.value?.subject.id
  if (!subjectId) return null
  return props.validation.releases.find(
    (release) => release.subject.id === subjectId && release.status === 'active'
  ) || null
})

const activeCalibrationRun = computed<ClassCalibrationRun | null>(() => {
  const release = activeRelease.value
  if (!release) return null
  return props.validation.calibration_runs.find(
    (run) => run.id === release.calibration_run_id
  ) || null
})

const activeComparisonRun = computed(() => {
  const run = activeCalibrationRun.value
  if (!run) return null
  return props.validation.comparison_runs.find(
    (comparison) => comparison.id === run.comparison_run_id
  ) || null
})

const bestModelKey = computed(() => {
  const modelCardValue = comparisonRun.value?.model_card.best_advanced_model
  return typeof modelCardValue === 'string'
    ? modelCardValue
    : calibrationRun.value?.model_key || ''
})

const validationOptions = computed(() => {
  const keys = comparisonRun.value?.validation_keys || []
  return keys.map((key) => ({ key, label: validationLabel(key) }))
})

watch(comparisonRun, (run) => {
  if (run && !run.validation_keys.includes(selectedValidation.value)) {
    selectedValidation.value = run.validation_keys[0] || 'V-A'
  }
})

const selectedEvaluations = computed(() =>
  (comparisonRun.value?.evaluations || []).filter(
    (item) => item.validation_key === selectedValidation.value
      && ['CATBOOST', 'LIGHTGBM'].includes(item.model_key)
  )
)

const headlineEvaluation = computed<ModelEvaluation | null>(() => {
  const evaluations = comparisonRun.value?.evaluations || []
  const preferredOrder = [selectedValidation.value, 'V-A', 'V-B', 'V-C', 'V-D', 'V-E']
  for (const validationKey of preferredOrder) {
    const match = evaluations.find(
      (item) => item.model_key === bestModelKey.value
        && item.validation_key === validationKey
        && item.status === 'ready'
    )
    if (match) return match
  }
  return null
})

const trainingState = computed(() => {
  if (!selectedDataset.value) return { label: '尚无可训练数据', tone: 'warning' }
  const run = calibrationRun.value
  if (!run) return { label: '等待训练', tone: 'info' }
  if (run.release?.status === 'active') return { label: '当前模型已发布', tone: 'success' }
  if (run.release?.status === 'superseded') return { label: '该训练版本已被替代', tone: 'info' }
  if (run.release?.status === 'rolled_back') return { label: '该训练版本已停用', tone: 'info' }
  if (run.status === 'candidate') return { label: '本次候选待发布', tone: 'warning' }
  if (run.status === 'blocked') return { label: '训练检查未通过', tone: 'warning' }
  if (run.status === 'failed') return { label: '训练失败', tone: 'error' }
  return { label: run.status_label, tone: 'info' }
})

function modelLabel(key: string) {
  return {
    CATBOOST: 'CatBoost',
    LIGHTGBM: 'LightGBM',
    M00: '总体平均',
    M01: '透明规则',
    M02: '正则化模型',
    M03: '班级调整'
  }[key] || key
}

function validationLabel(key: string) {
  return {
    'V-A': '按时间检验',
    'V-B': '留出学生检验',
    'V-C': '留出班级检验',
    'V-D': '跨学校检验',
    'V-E': '跨版本检验'
  }[key] || key
}

function metric(value: number | null | undefined, digits = 4) {
  return value === null || value === undefined || !Number.isFinite(Number(value))
    ? '-'
    : Number(value).toFixed(digits)
}

function percent(value: number | null | undefined) {
  return value === null || value === undefined || !Number.isFinite(Number(value))
    ? '-'
    : `${(Number(value) * 100).toFixed(1)}%`
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return '-'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime())
    ? '-'
    : parsed.toLocaleString('zh-CN', { hour12: false })
}

function chartToolbox(name: string) {
  return {
    right: 8,
    feature: {
      saveAsImage: {
        name,
        title: '下载图片',
        pixelRatio: 2,
        backgroundColor: '#ffffff'
      }
    }
  }
}

const errorChart = computed<EChartsCoreOption>(() => {
  const rows = selectedEvaluations.value.filter((item) => item.status === 'ready')
  return {
    color: ['#1f6feb', '#0f766e'],
    toolbox: chartToolbox(`STRATA-${selectedValidation.value}-误差比较`),
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { top: 4, left: 0, data: ['MAE', 'RMSE'] },
    grid: { top: 48, right: 18, bottom: 28, left: 44, containLabel: true },
    xAxis: {
      type: 'category',
      data: rows.map((item) => modelLabel(item.model_key)),
      axisTick: { show: false }
    },
    yAxis: { type: 'value', name: '误差', splitLine: { lineStyle: { color: '#e2e8f0' } } },
    series: [
      { name: 'MAE', type: 'bar', data: rows.map((item) => item.mae), barMaxWidth: 32 },
      { name: 'RMSE', type: 'bar', data: rows.map((item) => item.rmse), barMaxWidth: 32 }
    ]
  }
})

const fitChart = computed<EChartsCoreOption>(() => {
  const rows = selectedEvaluations.value.filter((item) => item.status === 'ready')
  return {
    color: ['#7c3aed', '#b45309'],
    toolbox: chartToolbox(`STRATA-${selectedValidation.value}-拟合与覆盖率`),
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { top: 4, left: 0, data: ['R²', '预测覆盖率'] },
    grid: { top: 48, right: 18, bottom: 28, left: 44, containLabel: true },
    xAxis: {
      type: 'category',
      data: rows.map((item) => modelLabel(item.model_key)),
      axisTick: { show: false }
    },
    yAxis: {
      type: 'value',
      name: '比例',
      max: 1,
      axisLabel: { formatter: '{value}' },
      splitLine: { lineStyle: { color: '#e2e8f0' } }
    },
    series: [
      { name: 'R²', type: 'bar', data: rows.map((item) => item.r_squared), barMaxWidth: 32 },
      { name: '预测覆盖率', type: 'bar', data: rows.map((item) => item.coverage), barMaxWidth: 32 }
    ]
  }
})

const residualChart = computed<EChartsCoreOption>(() => {
  const histogram = Array.isArray(headlineEvaluation.value?.metrics.residual_histogram)
    ? headlineEvaluation.value?.metrics.residual_histogram as Array<{ label: string; count: number }>
    : []
  return {
    color: ['#2563eb'],
    toolbox: chartToolbox(`STRATA-${bestModelKey.value || '模型'}-残差分布`),
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { top: 40, right: 18, bottom: 58, left: 44, containLabel: true },
    xAxis: {
      type: 'category',
      data: histogram.map((item) => item.label),
      axisLabel: {
        interval: histogram.length > 6 ? 1 : 0,
        rotate: histogram.length > 6 ? 28 : 0,
        fontSize: 10,
        showMaxLabel: false
      },
      axisTick: { show: false }
    },
    yAxis: { type: 'value', name: '记录数', splitLine: { lineStyle: { color: '#e2e8f0' } } },
    series: [{ type: 'bar', data: histogram.map((item) => item.count), barMaxWidth: 42 }]
  }
})
</script>

<template>
  <section class="model-operations" aria-label="模型运行概览">
    <section class="model-run-band">
      <div class="model-run-copy">
        <span>当前操作</span>
        <h2>训练分层模型</h2>
        <p>选择已经准备好的学习数据，一次完成模型比较、班级调整和教师建议生成。</p>
      </div>
      <label class="model-dataset-select">
        <span>训练数据</span>
        <AppSelect v-model.number="selectedDatasetId" :disabled="working || !readyDatasets.length">
          <option v-if="!readyDatasets.length" :value="0">暂无可训练数据</option>
          <option v-for="dataset in readyDatasets" :key="dataset.id" :value="dataset.id">
            {{ dataset.subject.name }} · {{ dataset.outcome.label }} · {{ dataset.row_count }} 条
          </option>
        </AppSelect>
      </label>
      <div class="model-run-action">
        <span class="analysis-status" :class="`analysis-tone-${trainingState.tone}`">{{ trainingState.label }}</span>
        <small>{{ calibrationRun ? `最近完成：${formatDateTime(calibrationRun.finished_at || calibrationRun.created_at)}` : '尚无训练记录' }}</small>
        <button
          class="primary-button"
          type="button"
          :disabled="working || !selectedDataset"
          @click="selectedDataset && emit('train', selectedDataset)"
        >{{ working ? '正在训练' : calibrationRun ? '重新检查训练' : '开始模型训练' }}</button>
      </div>
    </section>

    <section class="model-current-strip" aria-label="当前模型状态">
      <article>
        <span>当前使用模型</span>
        <strong>{{ modelLabel(activeCalibrationRun?.model_key || '-') }}</strong>
        <small>{{ activeComparisonRun ? `${activeComparisonRun.comparison_version} · ${formatDateTime(activeComparisonRun.finished_at || activeComparisonRun.created_at)}` : '尚未发布' }}</small>
      </article>
      <article>
        <span>当前训练记录</span>
        <strong>{{ activeComparisonRun?.row_count || 0 }}</strong>
        <small>冻结、已观察记录</small>
      </article>
      <article>
        <span>班级参数</span>
        <strong>{{ Object.keys(activeCalibrationRun?.class_parameters || {}).length }}</strong>
        <small>按班级修正</small>
      </article>
      <article>
        <span>学习支持</span>
        <strong>{{ activeCalibrationRun?.suggestion_count || 0 }}</strong>
        <small>发布后教师可见</small>
      </article>
      <article>
        <span>当前发布版本</span>
        <strong>{{ activeRelease ? `v${activeRelease.release_version}` : '-' }}</strong>
        <small>{{ activeRelease ? `${activeRelease.status_label} · ${formatDateTime(activeRelease.released_at)}` : '尚未发布' }}</small>
      </article>
    </section>

    <section v-if="calibrationRun" class="model-release-band" :class="`model-release-band-${trainingState.tone}`">
      <div>
        <strong>{{ calibrationRun.subject.name }} · {{ trainingState.label }}</strong>
        <span>训练完成：{{ formatDateTime(calibrationRun.finished_at || calibrationRun.created_at) }}<template v-if="calibrationRun.release"> · 发布时间：{{ formatDateTime(calibrationRun.release.released_at) }}</template></span>
      </div>
      <div class="model-release-band-actions">
        <button
          v-if="calibrationRun.status === 'candidate' && !calibrationRun.release"
          class="primary-button compact-action"
          type="button"
          :disabled="working"
          @click="emit('publish', calibrationRun.id)"
        >发布给教师</button>
        <button
          v-if="calibrationRun.release"
          class="secondary-button compact-action"
          type="button"
          :disabled="working"
          @click="emit('verify', calibrationRun.release.id)"
        >校验模型包</button>
      </div>
    </section>

    <template v-if="comparisonRun">
      <section class="model-metric-heading">
        <div>
          <h2>模型指标</h2>
          <p>{{ modelLabel(bestModelKey) }} · {{ validationLabel(headlineEvaluation?.validation_key || selectedValidation) }} · {{ formatDateTime(comparisonRun.finished_at || comparisonRun.created_at) }}</p>
        </div>
        <label>
          <span>检查范围</span>
          <AppSelect v-model="selectedValidation">
            <option v-for="item in validationOptions" :key="item.key" :value="item.key">{{ item.label }}</option>
          </AppSelect>
        </label>
      </section>

      <section class="model-metric-grid" aria-label="核心模型指标">
        <article><span>平均残差</span><strong>{{ metric(headlineEvaluation?.mean_residual) }}</strong><small>越接近 0 越好</small></article>
        <article><span>MAE</span><strong>{{ metric(headlineEvaluation?.mae) }}</strong><small>平均绝对误差</small></article>
        <article><span>MSE</span><strong>{{ metric(headlineEvaluation?.mse) }}</strong><small>均方误差</small></article>
        <article><span>RMSE</span><strong>{{ metric(headlineEvaluation?.rmse) }}</strong><small>均方根误差</small></article>
        <article><span>R²</span><strong>{{ metric(headlineEvaluation?.r_squared) }}</strong><small>决定系数</small></article>
        <article><span>预测覆盖率</span><strong>{{ percent(headlineEvaluation?.coverage) }}</strong><small>实际输出预测的比例</small></article>
      </section>

      <section class="model-chart-grid">
        <EChartPanel title="误差指标比较" :subtitle="validationLabel(selectedValidation)" :option="errorChart" />
        <EChartPanel title="拟合与预测覆盖" :subtitle="validationLabel(selectedValidation)" :option="fitChart" />
        <EChartPanel class="model-chart-wide" title="残差分布" :subtitle="`${modelLabel(bestModelKey)} · ${headlineEvaluation ? validationLabel(headlineEvaluation.validation_key) : '暂无可用结果'}`" :option="residualChart" wide />
      </section>

      <section class="panel model-metric-table-panel">
        <div class="panel-heading split">
          <div><h2>精确指标</h2><p>网页图表用于查看，论文分析请使用导出的匿名数据和模型结果。</p></div>
          <a class="secondary-button compact-action" :href="`/api/v1/school-admin/analytics/models/${comparisonRun.id}/export/?include_test_data=1`">导出 XLSX</a>
        </div>
        <div class="analysis-table-wrap">
          <table class="analysis-table model-metric-table">
            <thead><tr><th>模型</th><th>范围</th><th>MAE</th><th>MSE</th><th>RMSE</th><th>R²</th><th>覆盖率</th></tr></thead>
            <tbody>
              <tr v-for="item in selectedEvaluations" :key="item.id">
                <td data-label="模型"><strong>{{ modelLabel(item.model_key) }}</strong></td>
                <td data-label="范围">{{ item.status === 'ready' ? validationLabel(item.validation_key) : item.status_label }}</td>
                <td data-label="MAE">{{ metric(item.mae) }}</td>
                <td data-label="MSE">{{ metric(item.mse) }}</td>
                <td data-label="RMSE">{{ metric(item.rmse) }}</td>
                <td data-label="R²">{{ metric(item.r_squared) }}</td>
                <td data-label="覆盖率">{{ percent(item.coverage) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>

    <p v-else class="panel analysis-empty-copy">请选择可训练数据并开始训练，完成后这里会显示模型指标和图表。</p>
  </section>
</template>
