<template>
  <main class="app-shell">
    <section class="workspace">
      <header class="page-header">
        <div class="title-block">
          <p class="eyebrow">Pump Curve Regression</p>
          <h1>
            <span>水泵扬程及效率</span>
            <span>与水泵流量 Q 的归一化回归曲线</span>
          </h1>
        </div>
        <div class="health" :class="{ ok: apiOk, bad: apiOk === false }">
          <span></span>
          {{ apiOk ? '后端已连接' : '后端未连接' }}
        </div>
      </header>

      <section class="control-band">
        <div class="control-topline">
          <div>
            <h2>分析条件</h2>
            <p>选择一个或两个时间段，后台会计算全部分组下的水泵样本，前端按组展示曲线。</p>
          </div>
          <label class="dataset-field">
            <span>数据集名称</span>
            <input v-model="form.dataset_name" type="text" @change="reloadDataset" />
          </label>
        </div>

        <div class="time-ranges">
          <div class="time-card primary-range" :class="{ complete: form.start_time && form.end_time }">
            <div class="range-heading">
              <div class="range-title">
                <span class="range-index">1</span>
                <div>
                  <h2>时间段 1</h2>
                  <small>Range A</small>
                </div>
              </div>
              <span class="range-badge">必选</span>
            </div>
            <div class="range-grid">
              <label class="time-field">
                <span>开始时间</span>
                <input v-model="form.start_time" type="datetime-local" @change="handleTimeChange" />
              </label>
              <label class="time-field">
                <span>结束时间</span>
                <input v-model="form.end_time" type="datetime-local" @change="handleTimeChange" />
              </label>
            </div>
          </div>

          <div class="range-connector" aria-hidden="true">
            <span></span>
          </div>

          <div class="time-card optional-range" :class="{ complete: hasCompleteSecondRange }">
            <div class="range-heading">
              <div class="range-title">
                <span class="range-index">2</span>
                <div>
                  <h2>时间段 2</h2>
                  <small>Range B</small>
                </div>
              </div>
              <button type="button" :disabled="!hasSecondInput" @click="clearSecondRange">清空</button>
            </div>
            <div class="range-grid">
              <label class="time-field">
                <span>开始时间</span>
                <input v-model="form.second_start_time" type="datetime-local" @change="handleTimeChange" />
              </label>
              <label class="time-field">
                <span>结束时间</span>
                <input v-model="form.second_end_time" type="datetime-local" @change="handleTimeChange" />
              </label>
            </div>
          </div>
        </div>

        <div class="confirm-row">
          <div>
            <strong>确认后开始分析</strong>
            <span>{{ confirmHintText }}</span>
          </div>
          <button type="button" class="confirm-button" :disabled="!canRunRegression" @click="runAllRegression">
            {{ loading ? '正在计算...' : '确认生成图像' }}
          </button>
        </div>
      </section>

      <section v-if="baseResult" class="selection-layout group-pump-layout">
        <div class="selection-panel">
          <div class="panel-heading">
            <h2>曲线展示范围</h2>
          </div>
          <div class="selector-grid single-selector">
            <label class="select-field">
              <span>组别</span>
              <select v-model="selectedGroupId">
                <option v-for="group in groupOptions" :key="group.id" :value="group.id">
                  {{ group.name }} / {{ group.id }}
                </option>
              </select>
            </label>
          </div>
          <div v-if="selectedGroup" class="selected-pump">
            <strong>{{ selectedGroup.name }}</strong>
            <span>组号 {{ selectedGroup.id }}</span>
            <span>来源 {{ selectedGroup.source_label }}</span>
            <span>组内水泵 {{ groupPumpItems.length }} 台</span>
          </div>
        </div>

        <aside class="summary-panel">
          <h2>分析概况</h2>
          <dl>
            <div>
              <dt>时间段数量</dt>
              <dd>{{ visiblePayloads.length }}</dd>
            </div>
            <div>
              <dt>有效样本</dt>
              <dd>{{ totalValidSamples }}</dd>
            </div>
            <div>
              <dt>剔除样本</dt>
              <dd>{{ totalRejects }}</dd>
            </div>
            <div>
              <dt>未拟合水泵</dt>
              <dd>{{ totalSkipped }}</dd>
            </div>
          </dl>
          <p v-if="loading" class="hint-text">正在重新计算并整理曲线...</p>
          <p v-if="error" class="error-text">{{ error }}</p>
        </aside>
      </section>

      <section v-if="baseResult && selectedGroupId && coefficientRows.length" class="coefficient-panel">
        <div class="coefficient-header">
          <div>
            <h2>回归系数表</h2>
            <p>每行对应选中组内某台水泵在某个时间段的最终拟合结果。</p>
          </div>
          <span>{{ coefficientRows.length }} 条结果</span>
        </div>
        <div class="coefficient-table-wrap">
          <table class="coefficient-table">
            <thead>
              <tr>
                <th>水泵名称</th>
                <th>时间段</th>
                <th>H-Q 参数 a</th>
                <th>H-Q 参数 b</th>
                <th>H-Q 参数 c</th>
                <th>η-Q 参数 j</th>
                <th>η-Q 参数 k</th>
                <th>η-Q 参数 l</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in coefficientRows" :key="`${row.periodKey}-${row.pumpId}`">
                <td class="pump-cell">{{ row.pumpName }}</td>
                <td>{{ row.periodLabel }}</td>
                <td>{{ coefficientText(row.a) }}</td>
                <td>{{ coefficientText(row.b) }}</td>
                <td>{{ coefficientText(row.c) }}</td>
                <td>{{ coefficientText(row.j) }}</td>
                <td>{{ coefficientText(row.k) }}</td>
                <td>{{ coefficientText(row.l) }}</td>
                <td>
                  <span class="fit-status" :class="{ failed: !row.fitAvailable }">
                    {{ row.fitAvailable ? '已拟合' : '无法拟合' }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <p v-if="!baseResult && loading" class="loading-text">正在从数据库读取数据并计算回归曲线...</p>
      <p v-else-if="error && !baseResult" class="error-text top-error">{{ error }}</p>

      <template v-if="selectedGroupId && groupPumpItems.length">
        <section class="result-band group-result-band">
          <div class="result-header">
            <div>
              <h2>{{ selectedGroup?.name || selectedGroupId }} 组内水泵曲线</h2>
              <p>{{ rangeSummaryText }}</p>
            </div>
          </div>

          <div class="pump-card-stack">
            <article
              v-for="pump in groupPumpItems"
              :key="pump.id"
              class="result-card pump-result-card"
            >
              <header>
                <h3>{{ pump.name || pump.id }}</h3>
                <span>{{ pumpSummaryText(pump.id) }}</span>
              </header>

              <div class="metrics">
                <span v-if="resultFor(result, pump.id)">时间段 1：{{ periodStatusText(result, pump.id) }}</span>
                <span v-if="resultFor(secondResult, pump.id)">时间段 2：{{ periodStatusText(secondResult, pump.id) }}</span>
                <span v-if="bestResultFor(pump.id)">H-Q R2：{{ formatNumber(bestResultFor(pump.id).head_metrics?.r2) }}</span>
                <span v-if="bestResultFor(pump.id)">η-Q R2：{{ formatNumber(bestResultFor(pump.id).efficiency_metrics?.r2) }}</span>
              </div>

              <div class="chart-grid normalized-only-grid">
                <RegressionChart :asset-base="apiBase" :chart="combinedChartFor(pump.id, 'head')" />
                <RegressionChart :asset-base="apiBase" :chart="combinedChartFor(pump.id, 'efficiency')" />
              </div>

              <p v-if="hasUnfitPeriod(pump.id)" class="error-text pump-skip-text">
                当前时间段内存在散点数不足 10 个的情况，已保留散点图，未生成对应拟合曲线。
              </p>
            </article>
          </div>
        </section>
      </template>

      <p v-else-if="baseResult && !loading" class="error-text top-error">
        当前组内没有满足拟合条件的水泵。
      </p>
    </section>
  </main>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import RegressionChart from './components/RegressionChart.vue'

const apiBase = 'http://127.0.0.1:8010'

const apiOk = ref(false)
const options = ref(null)
const result = ref(null)
const secondResult = ref(null)
const loading = ref(false)
const error = ref('')
const selectedGroupId = ref('')
const hasConfirmedOnce = ref(false)

const form = reactive({
  dataset_name: 'sample_raw_points',
  start_time: '',
  end_time: '',
  second_start_time: '',
  second_end_time: '',
})

const hasSecondInput = computed(() => Boolean(form.second_start_time || form.second_end_time))
const hasCompleteSecondRange = computed(() => Boolean(form.second_start_time && form.second_end_time))
const hasPartialSecondRange = computed(() => hasSecondInput.value && !hasCompleteSecondRange.value)
const hasPrimaryRange = computed(() => Boolean(form.start_time && form.end_time))
const canRunRegression = computed(() => hasPrimaryRange.value && !hasPartialSecondRange.value && !loading.value)
const baseResult = computed(() => result.value || secondResult.value)
const confirmHintText = computed(() => {
  if (!hasPrimaryRange.value) return '请先完整选择时间段 1 的开始和结束时间。'
  if (hasPartialSecondRange.value) return '时间段 2 需要同时填写开始时间和结束时间。'
  if (hasConfirmedOnce.value && !baseResult.value) return '时间已变更，点击确认后重新生成图像。'
  return hasCompleteSecondRange.value ? '将同时生成两个时间段的对比图像。' : '将按时间段 1 生成回归图像。'
})

const visiblePayloads = computed(() => {
  const payloads = []
  if (result.value) {
    payloads.push({
      key: 'range-one',
      label: '时间段 1',
      data: result.value,
      timeText: `${form.start_time} 至 ${form.end_time}`,
      actualLineColor: '#2563eb',
      actualScatterColor: '#2563eb',
    })
  }
  if (secondResult.value) {
    payloads.push({
      key: 'range-two',
      label: '时间段 2',
      data: secondResult.value,
      timeText: `${form.second_start_time} 至 ${form.second_end_time}`,
      actualLineColor: '#0f766e',
      actualScatterColor: '#dc2626',
    })
  }
  return payloads
})

const groupOptions = computed(() => {
  const groups = new Map()
  for (const payload of visiblePayloads.value) {
    for (const group of payload.data?.groups || []) {
      if (!groups.has(group.id)) groups.set(group.id, group)
    }
  }
  return Array.from(groups.values()).sort((a, b) => `${a.source_type}-${a.id}`.localeCompare(`${b.source_type}-${b.id}`))
})

const selectedGroup = computed(() => {
  return groupOptions.value.find((group) => group.id === selectedGroupId.value) || null
})

const groupPumpItems = computed(() => {
  const pumps = new Map()
  for (const payload of visiblePayloads.value) {
    const group = payload.data?.groups?.find((item) => item.id === selectedGroupId.value)
    for (const pump of group?.pumps || []) {
      if (!pumps.has(pump.id)) pumps.set(pump.id, pump)
    }
  }
  return Array.from(pumps.values()).sort((a, b) => a.id.localeCompare(b.id))
})

const coefficientRows = computed(() => {
  const rows = []
  for (const pump of groupPumpItems.value) {
    for (const payload of visiblePayloads.value) {
      const item = resultFor(payload.data, pump.id)
      if (!item) continue
      rows.push({
        pumpId: pump.id,
        pumpName: pump.name || pump.id,
        periodKey: payload.key,
        periodLabel: payload.label,
        fitAvailable: Boolean(item.fit_available),
        a: item.head_coefficients?.a,
        b: item.head_coefficients?.b,
        c: item.head_coefficients?.c,
        j: item.efficiency_coefficients?.j,
        k: item.efficiency_coefficients?.k,
        l: item.efficiency_coefficients?.l,
      })
    }
  }
  return rows
})

const totalValidSamples = computed(() => {
  return visiblePayloads.value.reduce((sum, payload) => sum + Number(payload.data.valid_sample_count || 0), 0)
})

const totalRejects = computed(() => {
  return visiblePayloads.value.reduce((sum, payload) => sum + Number(payload.data.reject_count || 0), 0)
})

const totalSkipped = computed(() => {
  return visiblePayloads.value.reduce((sum, payload) => sum + Number(payload.data.skipped?.length || 0), 0)
})

const rangeSummaryText = computed(() => {
  return visiblePayloads.value.map((payload) => `${payload.label}: ${payload.timeText}`).join('；')
})

function resultFor(payload, pumpId) {
  return payload?.results?.find((item) => item.pump_id === pumpId && item.group_id === selectedGroupId.value)
    || payload?.results?.find((item) => item.pump_id === pumpId)
    || null
}

function bestResultFor(pumpId) {
  return [resultFor(result.value, pumpId), resultFor(secondResult.value, pumpId)].find((item) => item?.fit_available) || null
}

function hasAnyResult(pumpId) {
  return Boolean(resultFor(result.value, pumpId) || resultFor(secondResult.value, pumpId))
}

function periodStatusText(payload, pumpId) {
  const item = resultFor(payload, pumpId)
  if (!item) return '无数据'
  if (item.fit_available) return `n=${item.sample_count}`
  return `n=${item.sample_count}，不足 10 个点，无法生成拟合曲线`
}

function hasUnfitPeriod(pumpId) {
  return [resultFor(result.value, pumpId), resultFor(secondResult.value, pumpId)].some((item) => item && !item.fit_available)
}

function formatNumber(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '-'
  return number.toFixed(3)
}

function coefficientText(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '-'
  return number.toPrecision(6)
}

function formulaNumber(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return null
  return Number(number.toPrecision(6))
}

function formulaTerm(value, variable, isFirst = false) {
  const number = formulaNumber(value)
  if (number === null) return isFirst ? '-' : ' + -'
  const sign = number < 0 ? ' - ' : isFirst ? '' : ' + '
  return `${sign}${Math.abs(number)}${variable}`
}

function regressionFormulaFor(item, type, label) {
  if (!item?.fit_available) return `${label}: 无法生成拟合式`
  const coefficients = type === 'head' ? item.head_coefficients : item.efficiency_coefficients
  if (!coefficients) return `${label}: 无法生成拟合式`

  if (type === 'head') {
    return `${label}: H_eq = ${formulaTerm(coefficients.a, 'Q_eq²', true)}${formulaTerm(coefficients.b, 'Q_eq')}${formulaTerm(coefficients.c, '')}`
  }
  return `${label}: η = ${formulaTerm(coefficients.j, 'Q_eq²', true)}${formulaTerm(coefficients.k, 'Q_eq')}${formulaTerm(coefficients.l, '')}`
}

function formulaLinesFor(pumpId, type) {
  return visiblePayloads.value.map((payload) => {
    const item = resultFor(payload.data, pumpId)
    return regressionFormulaFor(item, type, payload.label)
  })
}

function pumpSummaryText(pumpId) {
  const parts = []
  const first = resultFor(result.value, pumpId)
  const second = resultFor(secondResult.value, pumpId)
  if (first) parts.push(`时间段 1 n=${first.sample_count}`)
  if (second) parts.push(`时间段 2 n=${second.sample_count}`)
  return parts.length ? parts.join(' / ') : '有效点不足'
}

function chartSourceFor(payload, pumpId, type) {
  return resultFor(payload.data, pumpId)?.charts?.[type === 'head' ? 'head_normalized_curve' : 'efficiency_normalized_curve']
}

function addActualPeriod(chartData, pumpId, type, payload) {
  const source = chartSourceFor(payload, pumpId, type)
  if (!source) return

  if (source.scatter?.length) {
    chartData.scatter_series.push({
      name: `${payload.label} 实际散点`,
      data: source.scatter,
      color: payload.actualScatterColor,
      symbolSize: 4.2,
      opacity: 0.34,
    })
  }

  for (const line of source.lines || []) {
    if (line.line_type === 'dashed') continue
    chartData.lines.push({
      ...line,
      name: `${payload.label} 实际拟合曲线`,
      color: payload.actualLineColor,
      line_type: 'solid',
    })
  }
}

function addCommonTheoryLine(chartData, pumpId, type) {
  for (const payload of visiblePayloads.value) {
    const source = chartSourceFor(payload, pumpId, type)
    const theoryLines = (source?.lines || []).filter((line) => line.line_type === 'dashed')
    if (!theoryLines.length) continue

    for (const line of theoryLines) {
      chartData.lines.push({
        ...line,
        name: '公共理论曲线',
        color: '#f97316',
        line_type: 'dashed',
      })
    }
    return
  }
}

function combinedChartFor(pumpId, type) {
  const isHead = type === 'head'
  const chartData = {
    title: `${pumpId} ${isHead ? '归一化 H-Q 曲线' : '归一化 η-Q 曲线'}`,
    formula_lines: formulaLinesFor(pumpId, type),
    x_name: 'Q_eq = Q / w (m3/h)',
    y_name: isHead ? 'H_eq = H / w^2 (m)' : 'η',
    scatter_series: [],
    lines: [],
  }

  for (const payload of visiblePayloads.value) {
    addActualPeriod(chartData, pumpId, type, payload)
  }
  addCommonTheoryLine(chartData, pumpId, type)
  return chartData
}

function chooseInitialGroup(payload) {
  const firstGroupWithResult = payload.groups?.find((group) => group.pumps?.some((pump) => pump.has_result))
  selectedGroupId.value = firstGroupWithResult?.id || payload.groups?.[0]?.id || ''
}

function showSkippedAlert(payload, label) {
  const skipped = payload.skipped || []
  if (!skipped.length) return
  const lines = skipped.slice(0, 20).map((item) => `${item.pump_id}: ${item.reason}`)
  const suffix = skipped.length > 20 ? `\n还有 ${skipped.length - 20} 台水泵未列出。` : ''
  window.alert(`${label} 中存在有效点数不足 10 个、未进行拟合的水泵：\n${lines.join('\n')}${suffix}`)
}

async function loadOptions() {
  error.value = ''
  const response = await fetch(`${apiBase}/api/options?dataset_name=${encodeURIComponent(form.dataset_name)}`)
  if (!response.ok) throw new Error('无法连接后端选项接口')
  options.value = await response.json()
  apiOk.value = true
  const range = options.value.time_range
  form.start_time = range.min_time || ''
  form.end_time = range.max_time || ''
  form.second_start_time = ''
  form.second_end_time = ''
}

async function reloadDataset() {
  result.value = null
  secondResult.value = null
  selectedGroupId.value = ''
  hasConfirmedOnce.value = false
  await loadOptions()
}

function handleTimeChange() {
  result.value = null
  secondResult.value = null
  selectedGroupId.value = ''
  error.value = hasPartialSecondRange.value ? '时间段 2 需要同时填写开始时间和结束时间。' : ''
}

async function runRegressionForRange(startTime, endTime) {
  const response = await fetch(`${apiBase}/api/regression`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      dataset_name: form.dataset_name,
      start_time: startTime,
      end_time: endTime,
      pump_ids: [],
    }),
  })
  const payload = await response.json()
  if (!response.ok) {
    throw new Error(payload.detail || '回归分析失败')
  }
  return payload
}

async function runAllRegression() {
  if (!form.start_time || !form.end_time) return
  if (hasPartialSecondRange.value) {
    error.value = '时间段 2 需要同时填写开始时间和结束时间。'
    return
  }

  loading.value = true
  error.value = ''
  result.value = null
  secondResult.value = null
  selectedGroupId.value = ''

  try {
    const firstPayload = await runRegressionForRange(form.start_time, form.end_time)
    result.value = firstPayload
    chooseInitialGroup(firstPayload)
    showSkippedAlert(firstPayload, '时间段 1')

    if (hasCompleteSecondRange.value) {
      const secondPayload = await runRegressionForRange(form.second_start_time, form.second_end_time)
      secondResult.value = secondPayload
      showSkippedAlert(secondPayload, '时间段 2')
    }
    hasConfirmedOnce.value = true
  } catch (err) {
    error.value = err.message || String(err)
  } finally {
    loading.value = false
  }
}

async function clearSecondRange() {
  form.second_start_time = ''
  form.second_end_time = ''
  secondResult.value = null
  handleTimeChange()
}

onMounted(async () => {
  try {
    await loadOptions()
  } catch (err) {
    apiOk.value = false
    error.value = err.message || String(err)
  }
})
</script>
