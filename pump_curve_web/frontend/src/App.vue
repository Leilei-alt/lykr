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
            <p>先选择时间段，再填写理论曲线系数；后台会读取运行数据回归“实际拟合曲线”，并按你输入的 a/b/c 与 j/k/l 生成“理论拟合曲线”。</p>
          </div>
        </div>

        <div class="time-ranges">
          <div class="time-card primary-range range-one" :class="{ complete: form.start_time && form.end_time }">
            <div class="time-card-top">
              <span>必选时间窗</span>
              <strong>{{ form.start_time && form.end_time ? '已就绪' : '待选择' }}</strong>
            </div>
            <div class="range-heading">
              <div class="range-title">
                <span class="range-index">1</span>
                <div>
                  <h2>时间段 1</h2>
                  <small>作为基准分析区间</small>
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
            <span>对比</span>
          </div>

          <div class="time-card optional-range range-two" :class="{ complete: hasCompleteSecondRange }">
            <div class="time-card-top">
              <span>可选时间窗</span>
              <strong>{{ hasCompleteSecondRange ? '已就绪' : '可留空' }}</strong>
            </div>
            <div class="range-heading">
              <div class="range-title">
                <span class="range-index">2</span>
                <div>
                  <h2>时间段 2</h2>
                  <small>用于同图对比分析</small>
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

        <div class="theory-coefficients" :class="{ complete: hasValidTheoryCoefficients }">
          <div class="theory-heading">
            <div class="theory-title">
              <span class="range-index theory-index">3</span>
              <div>
                <h2>理论曲线系数</h2>
                <small>按归一化公式填写设计曲线系数：虚线理论拟合曲线由这些系数生成，实测数据回归得到实线实际拟合曲线。</small>
              </div>
            </div>
            <span class="range-badge" :class="{ done: hasValidTheoryCoefficients }">
              {{ hasValidTheoryCoefficients ? '系数已就绪' : '待填写' }}
            </span>
          </div>

          <div class="theory-group-grid">
            <div class="theory-group head-group">
              <div class="theory-group-title">
                <strong>扬程 H 与流量 Q</strong>
                <span>H_eq = a·Q_eq² + b·Q_eq + c</span>
              </div>
              <div class="theory-input-grid">
                <label class="theory-field">
                  <span>系数 a</span>
                  <input v-model="form.theory.a" type="number" step="any" placeholder="二次项系数" @input="handleCoefficientChange" />
                </label>
                <label class="theory-field">
                  <span>系数 b</span>
                  <input v-model="form.theory.b" type="number" step="any" placeholder="一次项系数" @input="handleCoefficientChange" />
                </label>
                <label class="theory-field">
                  <span>系数 c</span>
                  <input v-model="form.theory.c" type="number" step="any" placeholder="常数项 (m)" @input="handleCoefficientChange" />
                </label>
              </div>
            </div>

            <div class="theory-group efficiency-group">
              <div class="theory-group-title">
                <strong>效率 η 与流量 Q</strong>
                <span>η = j·Q_eq² + k·Q_eq + l</span>
              </div>
              <div class="theory-input-grid">
                <label class="theory-field">
                  <span>系数 j</span>
                  <input v-model="form.theory.j" type="number" step="any" placeholder="二次项系数" @input="handleCoefficientChange" />
                </label>
                <label class="theory-field">
                  <span>系数 k</span>
                  <input v-model="form.theory.k" type="number" step="any" placeholder="一次项系数" @input="handleCoefficientChange" />
                </label>
                <label class="theory-field">
                  <span>系数 l</span>
                  <input v-model="form.theory.l" type="number" step="any" placeholder="常数项 (0-1)" @input="handleCoefficientChange" />
                </label>
              </div>
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

      <section v-if="baseResult" class="selection-layout group-pump-layout display-scope-layout">
        <div class="selection-panel display-scope-panel">
          <div class="panel-heading display-scope-heading">
            <div>
              <span class="panel-eyebrow">Display Scope</span>
              <h2>曲线展示范围</h2>
            </div>
            <span class="scope-badge">已生成回归结果</span>
          </div>
          <p class="display-scope-copy">选择一个设备组，页面会展示该组内全部水泵的归一化曲线与拟合结果。</p>
          <div class="selector-grid single-selector display-scope-select">
            <label class="select-field display-scope-field">
              <span class="field-label">当前设备组</span>
              <div class="select-shell">
                <select v-model="selectedGroupId">
                  <option v-for="group in groupOptions" :key="group.id" :value="group.id">
                    {{ group.name }} / {{ group.id }}
                  </option>
                </select>
              </div>
            </label>
          </div>
          <div v-if="selectedGroup" class="selected-group-card">
            <div class="selected-group-main">
              <span class="selected-group-icon">⌁</span>
              <strong>{{ selectedGroup.name }}</strong>
              <span>当前正在查看的回归曲线分组</span>
            </div>
            <div class="selected-group-stats">
              <span>
                <small>组号</small>
                <b>{{ selectedGroup.id }}</b>
              </span>
              <span>
                <small>来源</small>
                <b>{{ selectedGroup.source_label }}</b>
              </span>
              <span>
                <small>组内水泵</small>
                <b>{{ groupPumpItems.length }} 台</b>
              </span>
              <span>
                <small>时间段</small>
                <b>{{ selectedRangeCount }} 个</b>
              </span>
            </div>
          </div>
        </div>

        <aside class="summary-panel display-summary-panel">
          <div class="summary-heading">
            <div>
              <span class="panel-eyebrow">Overview</span>
              <h2>分析概况</h2>
            </div>
            <span class="summary-status"><i></i> 已就绪</span>
          </div>
          <dl>
            <div>
              <dt>时间段数量</dt>
              <dd>{{ selectedRangeCount }}</dd>
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
            <h2>实际拟合系数表</h2>
              <p>每行是选中组内某台水泵基于所选时间段数据回归得到的实际拟合系数；虚线理论曲线由上方输入的 a/b/c、j/k/l 生成。</p>
          </div>
          <span>{{ coefficientRows.length }} 条结果</span>
        </div>
        <div class="coefficient-table-wrap">
          <table class="coefficient-table">
            <thead>
              <tr>
                <th>水泵名称</th>
                <th>拟合范围</th>
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
                <span v-if="resultFor(result, pump.id)">合并数据：{{ periodStatusText(result, pump.id) }}</span>
                <span v-if="bestResultFor(pump.id)">H-Q R²：{{ formatNumber(bestResultFor(pump.id).head_metrics?.r2) }}</span>
                <span v-if="bestResultFor(pump.id)">η-Q R²：{{ formatNumber(bestResultFor(pump.id).efficiency_metrics?.r2) }}</span>
              </div>

              <div class="chart-grid normalized-only-grid">
                <RegressionChart :asset-base="apiBase" :chart="combinedChartFor(pump.id, 'head')" />
                <RegressionChart :asset-base="apiBase" :chart="combinedChartFor(pump.id, 'efficiency')" />
              </div>

              <p v-if="hasUnfitPeriod(pump.id)" class="error-text pump-skip-text">
                合并后的有效散点数不足 10 个，已保留散点图，未生成拟合曲线。
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

const apiBase = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8010'

const DEFAULT_DATASET_NAME = 'sample_raw_points'

const apiOk = ref(false)
const options = ref(null)
const result = ref(null)
const loading = ref(false)
const error = ref('')
const selectedGroupId = ref('')
const hasConfirmedOnce = ref(false)

const form = reactive({
  start_time: '',
  end_time: '',
  second_start_time: '',
  second_end_time: '',
  theory: {
    a: '',
    b: '',
    c: '',
    j: '',
    k: '',
    l: '',
  },
})

const hasSecondInput = computed(() => Boolean(form.second_start_time || form.second_end_time))
const hasCompleteSecondRange = computed(() => Boolean(form.second_start_time && form.second_end_time))
const hasPartialSecondRange = computed(() => hasSecondInput.value && !hasCompleteSecondRange.value)
function parseTheoryNumber(value) {
  const text = value == null ? '' : String(value).trim()
  if (text === '') return NaN
  return Number(text)
}

const theoryValues = computed(() => ({
  a: parseTheoryNumber(form.theory.a),
  b: parseTheoryNumber(form.theory.b),
  c: parseTheoryNumber(form.theory.c),
  j: parseTheoryNumber(form.theory.j),
  k: parseTheoryNumber(form.theory.k),
  l: parseTheoryNumber(form.theory.l),
}))

const hasValidTheoryCoefficients = computed(() => {
  return ['a', 'b', 'c', 'j', 'k', 'l'].every((key) => Number.isFinite(theoryValues.value[key]))
})
const hasPrimaryRange = computed(() => Boolean(form.start_time && form.end_time))
const canRunRegression = computed(() => hasPrimaryRange.value && !hasPartialSecondRange.value && hasValidTheoryCoefficients.value && !loading.value)
const baseResult = computed(() => result.value)
const selectedRangeCount = computed(() => hasCompleteSecondRange.value ? 2 : 1)
const confirmHintText = computed(() => {
  if (!hasPrimaryRange.value) return '请先完整选择时间段 1 的开始和结束时间。'
  if (!hasValidTheoryCoefficients.value) return '请先完整填写理论曲线系数：H-Q 的 a/b/c 与 η-Q 的 j/k/l。'
  if (hasPartialSecondRange.value) return '时间段 2 需要同时填写开始时间和结束时间。'
  if (hasConfirmedOnce.value && !baseResult.value) return '时间段或系数已变更，点击确认后重新生成图像。'
  return hasCompleteSecondRange.value ? '两个时间段的数据将合并后统一拟合。' : '将按时间段 1 生成回归图像。'
})

const visiblePayloads = computed(() => {
  if (!result.value) return []
  return [{
    key: 'merged-ranges',
    label: hasCompleteSecondRange.value ? '合并时间段' : '时间段 1',
    data: result.value,
    timeText: hasCompleteSecondRange.value
      ? `${form.start_time} 至 ${form.end_time}；${form.second_start_time} 至 ${form.second_end_time}`
      : `${form.start_time} 至 ${form.end_time}`,
    actualLineColor: '#2563eb',
    actualScatterColor: '#2563eb',
  }]
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
  const payload = visiblePayloads.value[0]
  if (!payload) return rows
  for (const pump of groupPumpItems.value) {
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
  return rows
})

const totalValidSamples = computed(() => {
  return Number(result.value?.valid_sample_count || 0)
})

const totalRejects = computed(() => {
  return Number(result.value?.reject_count || 0)
})

const totalSkipped = computed(() => {
  return Number(result.value?.skipped?.length || 0)
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
  return resultFor(result.value, pumpId)?.fit_available ? resultFor(result.value, pumpId) : null
}

function hasAnyResult(pumpId) {
  return Boolean(resultFor(result.value, pumpId))
}

function periodStatusText(payload, pumpId) {
  const item = resultFor(payload, pumpId)
  if (!item) return '无数据'
  if (item.fit_available) return `n=${item.sample_count}`
  return `n=${item.sample_count}，不足 10 个点，无法生成拟合曲线`
}

function hasUnfitPeriod(pumpId) {
  const item = resultFor(result.value, pumpId)
  return Boolean(item && !item.fit_available)
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

function theoryFormulaLine(type) {
  if (!hasValidTheoryCoefficients.value) return null
  const v = theoryValues.value
  if (type === 'head') {
    return `理论曲线: H_eq = ${formulaTerm(v.a, 'Q_eq²', true)}${formulaTerm(v.b, 'Q_eq')}${formulaTerm(v.c, '')}`
  }
  return `理论曲线: η = ${formulaTerm(v.j, 'Q_eq²', true)}${formulaTerm(v.k, 'Q_eq')}${formulaTerm(v.l, '')}`
}

function formulaLinesFor(pumpId, type) {
  const lines = visiblePayloads.value.map((payload) => {
    const item = resultFor(payload.data, pumpId)
    return regressionFormulaFor(item, type, payload.label)
  })
  const theoryLine = theoryFormulaLine(type)
  if (theoryLine) lines.push(theoryLine)
  return lines
}

function pumpSummaryText(pumpId) {
  const parts = []
  const first = resultFor(result.value, pumpId)
  if (first) parts.push(`${hasCompleteSecondRange.value ? '合并数据' : '时间段 1'} n=${first.sample_count}`)
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
  const payload = visiblePayloads.value[0]
  if (!payload) return
  const source = chartSourceFor(payload, pumpId, type)
  const theoryLines = (source?.lines || []).filter((line) => line.line_type === 'dashed')
  for (const line of theoryLines) {
    chartData.lines.push({
      ...line,
      name: '理论拟合曲线',
      color: '#f97316',
      line_type: 'dashed',
    })
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

  const payload = visiblePayloads.value[0]
  if (payload) addActualPeriod(chartData, pumpId, type, payload)
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
  const response = await fetch(`${apiBase}/api/options?dataset_name=${encodeURIComponent(DEFAULT_DATASET_NAME)}`)
  if (!response.ok) throw new Error('无法连接后端选项接口')
  options.value = await response.json()
  apiOk.value = true
  const range = options.value.time_range
  form.start_time = range.min_time || ''
  form.end_time = range.max_time || ''
  form.second_start_time = ''
  form.second_end_time = ''
}

function handleTimeChange() {
  result.value = null
  selectedGroupId.value = ''
  error.value = hasPartialSecondRange.value ? '时间段 2 需要同时填写开始时间和结束时间。' : ''
}

function handleCoefficientChange() {
  result.value = null
  selectedGroupId.value = ''
  error.value = ''
}

async function runRegressionForRanges() {
  const response = await fetch(`${apiBase}/api/regression`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      dataset_name: DEFAULT_DATASET_NAME,
      start_time: form.start_time,
      end_time: form.end_time,
      second_start_time: hasCompleteSecondRange.value ? form.second_start_time : null,
      second_end_time: hasCompleteSecondRange.value ? form.second_end_time : null,
      pump_ids: [],
      theory_a: theoryValues.value.a,
      theory_b: theoryValues.value.b,
      theory_c: theoryValues.value.c,
      theory_j: theoryValues.value.j,
      theory_k: theoryValues.value.k,
      theory_l: theoryValues.value.l,
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
  selectedGroupId.value = ''

  try {
    result.value = await runRegressionForRanges()
    chooseInitialGroup(result.value)
    showSkippedAlert(result.value, hasCompleteSecondRange.value ? '合并时间段' : '时间段 1')
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
