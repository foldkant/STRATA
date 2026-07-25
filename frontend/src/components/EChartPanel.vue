<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import {
  GraphicComponent,
  GridComponent,
  LegendComponent,
  ToolboxComponent,
  TitleComponent,
  TooltipComponent
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsCoreOption } from 'echarts/core'

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  GraphicComponent,
  GridComponent,
  LegendComponent,
  ToolboxComponent,
  TitleComponent,
  TooltipComponent,
  CanvasRenderer
])

const props = defineProps<{
  title: string
  subtitle?: string
  total?: number | string
  option: EChartsCoreOption
  wide?: boolean
  tall?: boolean
}>()

const chartEl = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null
let observer: ResizeObserver | null = null
let resizeFrame = 0
let lastWidth = 0
let lastHeight = 0

function renderChart() {
  if (!chartEl.value) return
  if (!chart) {
    chart = echarts.init(chartEl.value)
  }
  chart.setOption(props.option, true)
}

function resizeChart() {
  if (!chartEl.value || !chart) return
  const { width, height } = chartEl.value.getBoundingClientRect()
  if (width === lastWidth && height === lastHeight) return
  lastWidth = width
  lastHeight = height
  window.cancelAnimationFrame(resizeFrame)
  resizeFrame = window.requestAnimationFrame(() => chart?.resize())
}

onMounted(() => {
  renderChart()
  void document.fonts?.ready.then(renderChart)
  if (chartEl.value) {
    const rect = chartEl.value.getBoundingClientRect()
    lastWidth = rect.width
    lastHeight = rect.height
    observer = new ResizeObserver(resizeChart)
    observer.observe(chartEl.value)
  }
})

watch(() => props.option, renderChart, { deep: true })

onBeforeUnmount(() => {
  window.cancelAnimationFrame(resizeFrame)
  observer?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<template>
  <article class="chart-card echarts-card" :class="{ 'chart-card-wide': wide, 'chart-card-tall': tall }">
    <header>
      <div>
        <h3>{{ title }}</h3>
        <p v-if="subtitle">{{ subtitle }}</p>
      </div>
      <span v-if="total !== undefined">{{ total }}</span>
    </header>
    <div ref="chartEl" class="echarts-canvas" aria-hidden="true" />
  </article>
</template>
