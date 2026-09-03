<template>
  <section class="chart-panel">
    <header>
      <h4>{{ chart?.title || '回归曲线' }}</h4>
      <span>{{ scatterCount }} 个点</span>
    </header>
    <div ref="chartEl" class="echart"></div>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

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
const THEORY_SCATTER_COLOR = '#f97316'

const scatterCount = computed(() => props.chart?.scatter?.length || 0)

function loadEcharts(assetBase) {
  if (window.echarts) return Promise.resolve(window.echarts)
  if (window.__pumpCurveEchartsLoader) return window.__pumpCurveEchartsLoader

  window.__pumpCurveEchartsLoader = new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = `${assetBase}/assets/echarts.min.js`
    script.async = true
    script.onload = () => {
      if (window.echarts) {
        resolve(window.echarts)
      } else {
        window.__pumpCurveEchartsLoader = null
        reject(new Error('ECharts 未正确初始化'))
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
  if (param.seriesType === 'scatter') {
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
  const scatter = chart.scatter || []
  const lines = chart.lines || []
  const xValues = [
    ...scatter.map((point) => Number(point[0])),
    ...lines.flatMap((line) => (line.points || []).map((point) => Number(point[0]))),
  ].filter(Number.isFinite)
  const yValues = [
    ...scatter.map((point) => Number(point[1])),
    ...lines.flatMap((line) => (line.points || []).map((point) => Number(point[1]))),
  ].filter(Number.isFinite)

  const xMin = xValues.length ? Math.min(...xValues) : 0
  const xMax = xValues.length ? Math.max(...xValues) : 1
  const yMin = yValues.length ? Math.min(...yValues) : 0
  const yMax = yValues.length ? Math.max(...yValues) : 1

  const xPad = xMax === xMin ? Math.max(1, Math.abs(xMax) * 0.1) : (xMax - xMin) * 0.12
  const yPad = yMax === yMin ? Math.max(1, Math.abs(yMax) * 0.1) : (yMax - yMin) * 0.12

  const xAxisMin = xMin - xPad
  const xAxisMax = xMax + xPad
  const yAxisMin = yMin - yPad
  const yAxisMax = yMax + yPad
  const theoryScatterSeries = lines
    .filter((line) => line.line_type === 'dashed')
    .map((line) => ({
      name: `${line.name || '理论曲线'}散点`,
      type: 'scatter',
      data: line.points || [],
      symbolSize: 3.5,
      itemStyle: {
        color: THEORY_SCATTER_COLOR,
        opacity: 0.48,
        borderColor: '#7c2d12',
        borderWidth: 0,
      },
      emphasis: {
        focus: 'series',
      },
    }))

  const series = [
    {
      name: chart.scatter_name || '有效散点',
      type: 'scatter',
      data: scatter,
      symbolSize: 4,
      itemStyle: {
        color: ACTUAL_SCATTER_COLOR,
        opacity: 0.46,
        borderColor: '#223044',
        borderWidth: 0,
      },
      emphasis: {
        focus: 'series',
      },
    },
    ...lines.map((line, index) => {
      const isTheory = line.line_type === 'dashed'
      return {
        name: line.name || `fit ${index + 1}`,
        type: 'line',
        data: line.points || [],
        showSymbol: false,
        smooth: false,
        lineStyle: {
          width: isTheory ? 2.2 : index === 0 && lines.length === 1 ? 2.8 : 2.1,
          type: line.line_type || 'solid',
        },
        emphasis: {
          focus: 'series',
        },
      }
    }),
    ...theoryScatterSeries,
  ]

  return {
    color: ['#0f766e', '#2563eb', '#dc2626', '#9333ea', '#ea580c', '#0891b2'],
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
      top: 56,
      bottom: 86,
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
      min: xAxisMin,
      max: xAxisMax,
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
      min: yAxisMin,
      max: yAxisMax,
      scale: true,
      axisLabel: {
        formatter: axisLabelFormatter,
      },
      axisLine: { lineStyle: { color: '#708096' } },
      splitLine: { lineStyle: { color: '#e7edf4' } },
    },
    series,
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
  await loadEcharts(props.assetBase)
  await nextTick()
  if (!chartEl.value) return
  chartInstance = window.echarts.init(chartEl.value, 'white', {
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
