import type { EChartsCoreOption } from 'echarts/core'

export type ChartRow = {
  label: string
  count: number
  value?: string
}

export type ChartTheme = {
  palette: string[]
  axisText: string
  axisLine: string
  splitLine: string
  labelText: string
  fontFamily: string
  fontSize: number
}

const defaultTheme: ChartTheme = {
  palette: ['#1f6feb', '#16a34a', '#f59e0b', '#dc2626', '#7c3aed', '#0891b2', '#64748b', '#f97316'],
  axisText: '#64748b',
  axisLine: '#d8e1ec',
  splitLine: '#e2e8f0',
  labelText: '#162033',
  fontFamily: '"Microsoft YaHei UI", "Microsoft YaHei", sans-serif',
  fontSize: 12
}

export const governanceChartTheme: ChartTheme = {
  palette: ['#183d37', '#52786f', '#8fa89f', '#b54a3a', '#c99b78', '#6e827b', '#aebbb5', '#d2dad5'],
  axisText: '#687872',
  axisLine: '#cbd5ce',
  splitLine: '#e1e7e2',
  labelText: '#253530',
  fontFamily: '"STRATA WenKai UI", "STKaiti", "KaiTi", serif',
  fontSize: 13
}

export const teacherChartTheme: ChartTheme = {
  ...governanceChartTheme,
  palette: ['#17483f', '#bd5543', '#6f9186', '#d0a36f', '#406f66', '#9e7762', '#8a9e96', '#c87967']
}

export const governanceChartTextStyle = {
  color: governanceChartTheme.axisText,
  fontFamily: governanceChartTheme.fontFamily,
  fontSize: governanceChartTheme.fontSize
}

function axisText(theme: ChartTheme) {
  return {
    color: theme.axisText,
    fontFamily: theme.fontFamily,
    fontSize: theme.fontSize
  }
}

export function total(rows: ChartRow[]) {
  return rows.reduce((sum, item) => sum + Number(item.count || 0), 0)
}

function emptyGraphic(rows: ChartRow[], theme: ChartTheme) {
  return rows.some((item) => Number(item.count || 0) > 0)
    ? undefined
    : {
        type: 'text',
        left: 'center',
        top: 'middle',
        style: {
          text: '暂无数据',
          fill: theme.axisText,
          fontFamily: theme.fontFamily,
          fontSize: theme.fontSize + 1
        }
      }
}

export function pieOption(rows: ChartRow[], theme: ChartTheme = defaultTheme): EChartsCoreOption {
  const visibleRows = rows.filter((item) => Number(item.count || 0) > 0)
  return {
    color: theme.palette,
    textStyle: axisText(theme),
    graphic: emptyGraphic(rows, theme),
    tooltip: {
      trigger: 'item',
      formatter: '{b}<br/>{c} ({d}%)'
    },
    legend: {
      bottom: 0,
      left: 'center',
      itemWidth: 10,
      itemHeight: 10,
      textStyle: axisText(theme)
    },
    series: [
      {
        type: 'pie',
        showEmptyCircle: false,
        radius: ['46%', '72%'],
        center: ['50%', '44%'],
        avoidLabelOverlap: true,
        label: {
          color: theme.labelText,
          fontFamily: theme.fontFamily,
          fontSize: theme.fontSize,
          formatter: '{b}\n{c}'
        },
        labelLine: {
          length: 10,
          length2: 8
        },
        data: visibleRows.map((item) => ({ name: item.label, value: item.count }))
      }
    ]
  }
}

export function barOption(rows: ChartRow[], horizontal = false, theme: ChartTheme = defaultTheme): EChartsCoreOption {
  const labels = rows.map((item) => item.label)
  const values = rows.map((item) => item.count)
  return {
    color: [theme.palette[0]],
    textStyle: axisText(theme),
    graphic: emptyGraphic(rows, theme),
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
          splitNumber: 4,
          axisLabel: axisText(theme),
          splitLine: { lineStyle: { color: theme.splitLine } }
        }
      : {
          type: 'category',
          data: labels,
          axisLabel: { ...axisText(theme), interval: 0, rotate: labels.length > 6 ? 30 : 0 },
          axisTick: { show: false },
          axisLine: { lineStyle: { color: theme.axisLine } }
        },
    yAxis: horizontal
      ? {
          type: 'category',
          data: labels,
          axisLabel: { ...axisText(theme), width: 84, overflow: 'truncate' },
          axisTick: { show: false },
          axisLine: { lineStyle: { color: theme.axisLine } }
        }
      : {
          type: 'value',
          axisLabel: axisText(theme),
          splitLine: { lineStyle: { color: theme.splitLine } }
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

export function lineOption(
  series: Array<{ name: string; rows: ChartRow[] }>,
  theme: ChartTheme = defaultTheme
): EChartsCoreOption {
  const labels = series[0]?.rows.map((item) => item.label) || []
  const hasValue = series.some((item) => item.rows.some((point) => Number(point.count || 0) > 0))
  return {
    color: theme.palette,
    textStyle: axisText(theme),
    graphic: hasValue
      ? undefined
      : {
          type: 'text',
          left: 'center',
          top: 'middle',
          style: {
            text: '暂无数据',
            fill: theme.axisText,
            fontFamily: theme.fontFamily,
            fontSize: theme.fontSize + 1
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
      textStyle: axisText(theme)
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
      axisLabel: axisText(theme),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: theme.axisLine } }
    },
    yAxis: {
      type: 'value',
      axisLabel: axisText(theme),
      splitLine: { lineStyle: { color: theme.splitLine } }
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

export function stackedBarOption(
  series: Array<{ name: string; rows: ChartRow[] }>,
  theme: ChartTheme = defaultTheme
): EChartsCoreOption {
  const labels = series[0]?.rows.map((item) => item.label) || []
  const hasValue = series.some((item) => item.rows.some((point) => Number(point.count || 0) > 0))
  return {
    color: theme.palette,
    textStyle: axisText(theme),
    graphic: hasValue
      ? undefined
      : {
          type: 'text',
          left: 'center',
          top: 'middle',
          style: {
            text: '暂无数据',
            fill: theme.axisText,
            fontFamily: theme.fontFamily,
            fontSize: theme.fontSize + 1
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
      textStyle: axisText(theme)
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
      axisLabel: axisText(theme),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: theme.axisLine } }
    },
    yAxis: {
      type: 'value',
      axisLabel: axisText(theme),
      splitLine: { lineStyle: { color: theme.splitLine } }
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
