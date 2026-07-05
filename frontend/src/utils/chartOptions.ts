import type { EChartsCoreOption } from 'echarts/core'

export type ChartRow = {
  label: string
  count: number
  value?: string
}

const palette = ['#1f6feb', '#16a34a', '#f59e0b', '#dc2626', '#7c3aed', '#0891b2', '#64748b', '#f97316']

const axisText = {
  color: '#64748b',
  fontSize: 12
}

export function total(rows: ChartRow[]) {
  return rows.reduce((sum, item) => sum + Number(item.count || 0), 0)
}

function emptyGraphic(rows: ChartRow[]) {
  return rows.some((item) => Number(item.count || 0) > 0)
    ? undefined
    : {
        type: 'text',
        left: 'center',
        top: 'middle',
        style: {
          text: '暂无数据',
          fill: '#64748b',
          fontSize: 13
        }
      }
}

export function pieOption(rows: ChartRow[]): EChartsCoreOption {
  return {
    color: palette,
    graphic: emptyGraphic(rows),
    tooltip: {
      trigger: 'item',
      formatter: '{b}<br/>{c} ({d}%)'
    },
    legend: {
      bottom: 0,
      left: 'center',
      itemWidth: 10,
      itemHeight: 10,
      textStyle: axisText
    },
    series: [
      {
        type: 'pie',
        radius: ['46%', '72%'],
        center: ['50%', '44%'],
        avoidLabelOverlap: true,
        label: {
          color: '#162033',
          formatter: '{b}\n{c}'
        },
        labelLine: {
          length: 10,
          length2: 8
        },
        data: rows.map((item) => ({ name: item.label, value: item.count }))
      }
    ]
  }
}

export function barOption(rows: ChartRow[], horizontal = false): EChartsCoreOption {
  const labels = rows.map((item) => item.label)
  const values = rows.map((item) => item.count)
  return {
    color: ['#1f6feb'],
    graphic: emptyGraphic(rows),
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' }
    },
    grid: {
      top: 18,
      right: 14,
      bottom: horizontal ? 16 : 42,
      left: horizontal ? 72 : 34,
      containLabel: true
    },
    xAxis: horizontal
      ? {
          type: 'value',
          axisLabel: axisText,
          splitLine: { lineStyle: { color: '#e2e8f0' } }
        }
      : {
          type: 'category',
          data: labels,
          axisLabel: { ...axisText, interval: 0, rotate: labels.length > 6 ? 30 : 0 },
          axisTick: { show: false },
          axisLine: { lineStyle: { color: '#d8e1ec' } }
        },
    yAxis: horizontal
      ? {
          type: 'category',
          data: labels,
          axisLabel: { ...axisText, width: 84, overflow: 'truncate' },
          axisTick: { show: false },
          axisLine: { lineStyle: { color: '#d8e1ec' } }
        }
      : {
          type: 'value',
          axisLabel: axisText,
          splitLine: { lineStyle: { color: '#e2e8f0' } }
        },
    series: [
      {
        type: 'bar',
        data: values,
        barMaxWidth: 28,
        itemStyle: {
          borderRadius: horizontal ? [0, 6, 6, 0] : [6, 6, 0, 0]
        }
      }
    ]
  }
}

export function lineOption(series: Array<{ name: string; rows: ChartRow[] }>): EChartsCoreOption {
  const labels = series[0]?.rows.map((item) => item.label) || []
  const hasValue = series.some((item) => item.rows.some((point) => Number(point.count || 0) > 0))
  return {
    color: palette,
    graphic: hasValue
      ? undefined
      : {
          type: 'text',
          left: 'center',
          top: 'middle',
          style: {
            text: '暂无数据',
            fill: '#64748b',
            fontSize: 13
          }
        },
    tooltip: {
      trigger: 'axis'
    },
    legend: {
      top: 0,
      right: 0,
      itemWidth: 10,
      itemHeight: 10,
      textStyle: axisText
    },
    grid: {
      top: 34,
      right: 14,
      bottom: 24,
      left: 36,
      containLabel: true
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: labels,
      axisLabel: axisText,
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#d8e1ec' } }
    },
    yAxis: {
      type: 'value',
      axisLabel: axisText,
      splitLine: { lineStyle: { color: '#e2e8f0' } }
    },
    series: series.map((item) => ({
      name: item.name,
      type: 'line',
      smooth: true,
      symbolSize: 7,
      data: item.rows.map((point) => point.count),
      areaStyle: { opacity: 0.08 }
    }))
  }
}

export function stackedBarOption(series: Array<{ name: string; rows: ChartRow[] }>): EChartsCoreOption {
  const labels = series[0]?.rows.map((item) => item.label) || []
  const hasValue = series.some((item) => item.rows.some((point) => Number(point.count || 0) > 0))
  return {
    color: palette,
    graphic: hasValue
      ? undefined
      : {
          type: 'text',
          left: 'center',
          top: 'middle',
          style: {
            text: '暂无数据',
            fill: '#64748b',
            fontSize: 13
          }
        },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' }
    },
    legend: {
      top: 0,
      right: 0,
      itemWidth: 10,
      itemHeight: 10,
      textStyle: axisText
    },
    grid: {
      top: 34,
      right: 14,
      bottom: 24,
      left: 36,
      containLabel: true
    },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: axisText,
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#d8e1ec' } }
    },
    yAxis: {
      type: 'value',
      axisLabel: axisText,
      splitLine: { lineStyle: { color: '#e2e8f0' } }
    },
    series: series.map((item) => ({
      name: item.name,
      type: 'bar',
      stack: 'total',
      emphasis: { focus: 'series' },
      data: item.rows.map((point) => point.count),
      barMaxWidth: 30,
      itemStyle: {
        borderRadius: [4, 4, 0, 0]
      }
    }))
  }
}
