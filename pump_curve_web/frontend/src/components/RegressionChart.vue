<template>
  <section class="chart-panel">
    <header>
      <h4>
        <span class="chart-title-main">{{ chart?.title || '回归曲线' }}</span>
        <span v-for="(line, index) in chart?.formula_lines || []" :key="`${index}-${line}`" class="chart-formula">
          {{ line }}
        </span>
      </h4>
      <span>{{ scatterCount }} 个点</span>
    </header>
    <div ref="chartEl" class="echart"></div>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  chart: {
    type: Object,
    default: null,
  },
  assetBase: {
    type: String,
    default: 'http://127.0.0.1:8010',
  },
})

const chartEl = ref(null)
let chartInstance = null

const ACTUAL_SCATTER_COLOR = '#2563eb'

const scatterSeries = computed(() => {
  if (props.chart?.scatter_series?.length) return props.chart.scatter_series
  if (props.chart?.scatter?.length) {
    return [
      {
        name: props.chart.scatter_name || '实际散点',
        data: props.chart.scatter,
        color: ACTUAL_SCATTER_COLOR,
        symbolSize: 4.2,
        opacity: 0.34,
      },
    ]
  }
  return []
})

const scatterCount = computed(() => {
  return scatterSeries.value.reduce((sum, series) => sum + Number(series.data?.length || 0), 0)
})

function loadEcharts(assetBase) {
  if (window.echarts) return Promise.resolve(window.echarts)
  if (window.__pumpCurveEchartsLoader) return window.__pumpCurveEchartsLoader

  window.__pumpCurveEchartsLoader = new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = `${assetBase || ''}/assets/echarts.min.js`
    script.async = true
    script.onload = () => {
      if (window.echarts) {
        resolve(window.echarts)
      } else {
        window.__pumpCurveEchartsLoader = null
        reject(new Error('ECharts 加载完成但未初始化'))
      }
    }
    script.onerror = () => {
      window.__pumpCurveEchartsLoader = null
      reject(new Error('ECharts 加载失败'))
    }
    document.head.appendChild(script)
  })
  return window.__pumpCurveEchartsLoader
}

function tooltipFormatter(param) {
  const value = param.value || []
  const x = Number(value[0])
  const y = Number(value[1])
  const w = Number(value[2])
  const rows = [
    `<strong>${param.seriesName}</strong>`,
    `${props.chart?.x_name || 'X'}: ${Number.isFinite(x) ? x.toFixed(3) : '-'}`,
    `${props.chart?.y_name || 'Y'}: ${Number.isFinite(y) ? y.toFixed(3) : '-'}`,
  ]
  if (param.seriesType === 'scatter' && value.length >= 3) {
    rows.push(`w: ${Number.isFinite(w) ? w.toFixed(3) : '-'}`)
    if (value[3]) rows.push(`时间: ${value[3]}`)
  }
  return rows.join('<br/>')
}

function axisLabelFormatter(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return value
  return number.toFixed(2)
}

function buildOption() {
  const chart = props.chart || {}
  const lines = chart.lines || []
  const allScatter = scatterSeries.value
  const xValues = [
    ...allScatter.flatMap((series) => (series.data || []).map((point) => Number(point[0]))),
    ...lines.flatMap((line) => (line.points || []).map((point) => Number(point[0]))),
  ].filter(Number.isFinite)
  const yValues = [
    ...allScatter.flatMap((series) => (series.data || []).map((point) => Number(point[1]))),
    ...lines.flatMap((line) => (line.points || []).map((point) => Number(point[1]))),
  ].filter(Number.isFinite)

  const xMin = xValues.length ? Math.min(...xValues) : 0
  const xMax = xValues.length ? Math.max(...xValues) : 1
  const yMin = yValues.length ? Math.min(...yValues) : 0
  const yMax = yValues.length ? Math.max(...yValues) : 1

  const xPad = xMax === xMin ? Math.max(1, Math.abs(xMax) * 0.1) : (xMax - xMin) * 0.12
  const yPad = yMax === yMin ? Math.max(1, Math.abs(yMax) * 0.1) : (yMax - yMin) * 0.12

  const scatterEntries = allScatter.map((series) => ({
    name: series.name || '实际散点',
    type: 'scatter',
    data: series.data || [],
    symbolSize: series.symbolSize || 4.2,
    itemStyle: {
      color: series.color || ACTUAL_SCATTER_COLOR,
      opacity: series.opacity ?? 0.34,
      borderWidth: 0,
    },
    emphasis: {
      focus: 'series',
    },
  }))

  const lineEntries = lines.map((line, index) => ({
    name: line.name || `拟合曲线 ${index + 1}`,
    type: 'line',
    data: line.points || [],
    showSymbol: false,
    smooth: false,
    lineStyle: {
      color: line.color,
      width: line.line_type === 'dashed' ? 2.1 : 2.6,
      type: line.line_type || 'solid',
    },
    emphasis: {
      focus: 'series',
    },
  }))


  return {
    animationDuration: 450,
    tooltip: {
      trigger: 'item',
      axisPointer: { type: 'cross' },
      formatter: tooltipFormatter,
    },
    legend: {
      type: 'scroll',
      top: 4,
      left: 8,
      right: 70,
    },
    grid: {
      left: 62,
      right: 24,
      top: 58,
      bottom: 88,
      containLabel: true,
    },
    dataZoom: [
      { type: 'inside', xAxisIndex: 0, filterMode: 'none' },
      { type: 'slider', xAxisIndex: 0, height: 18, bottom: 12, filterMode: 'none' },
    ],
    xAxis: {
      type: 'value',
      name: chart.x_name || 'Q',
      nameLocation: 'middle',
      nameGap: 42,
      min: 0,
      max: xMax + xPad,
      scale: true,
      axisLabel: {
        formatter: axisLabelFormatter,
      },
      axisLine: { lineStyle: { color: '#708096' } },
      splitLine: { lineStyle: { color: '#e7edf4' } },
    },
    yAxis: {
      type: 'value',
      name: chart.y_name || 'Y',
      nameLocation: 'middle',
      nameGap: 48,
      min: 0,
      max: yMax + yPad,
      scale: true,
      axisLabel: {
        formatter: axisLabelFormatter,
      },
      axisLine: { lineStyle: { color: '#708096' } },
      splitLine: { lineStyle: { color: '#e7edf4' } },
    },
    series: [...scatterEntries, ...lineEntries],
  }
}

function renderChart() {
  if (!chartInstance || !props.chart) return
  chartInstance.setOption(buildOption(), true)
  chartInstance.resize()
}

function resizeChart() {
  if (chartInstance) chartInstance.resize()
}

onMounted(async () => {
  await nextTick()
  if (!chartEl.value) return
  chartInstance = echarts.init(chartEl.value, 'white', {
    renderer: 'canvas',
    locale: 'ZH',
  })
  renderChart()
  window.addEventListener('resize', resizeChart)
})

watch(
  () => props.chart,
  async () => {
    await nextTick()
    renderChart()
  },
  { deep: true },
)

onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeChart)
  if (chartInstance) {
    chartInstance.dispose()
    chartInstance = null
  }
})
</script>
