<template>
  <main class="app-shell">
    <section class="workspace">
      <header class="page-header">
        <div class="title-block">
          <p class="eyebrow">Pump Curve Regression</p>
          <h1>
            <span>水泵扬程及效率</span>
            <span>与水泵流量Q的回归曲线</span>
          </h1>
        </div>
        <div class="health" :class="{ ok: apiOk, bad: apiOk === false }">
          <span></span>
          {{ apiOk ? '后端已连接' : '等待后端' }}
        </div>
      </header>

      <section class="control-band">
        <div class="control-topline">
          <div>
            <h2>分析时间</h2>
            <p>选择一个或两个时间段生成对应拟合曲线</p>
          </div>
          <label class="dataset-field">
            <span>数据集</span>
            <input v-model="form.dataset_name" type="text" @change="reloadDataset" />
          </label>
        </div>

        <div class="time-ranges">
          <div class="time-card primary-range" :class="{ complete: form.start_time && form.end_time }">
            <div class="range-heading">
              <div class="range-title">
                <span class="range-index">1</span>
                <div>
                  <h2>基准时间段</h2>
                  <small>Range A</small>
                </div>
              </div>
              <span class="range-badge">默认拟合</span>
            </div>
            <div class="range-grid">
              <label class="time-field">
                <span>起始时间</span>
                <input v-model="form.start_time" type="datetime-local" @change="runAllRegression" />
              </label>
              <label class="time-field">
                <span>结束时间</span>
                <input v-model="form.end_time" type="datetime-local" @change="runAllRegression" />
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
                  <h2>对比时间段</h2>
                  <small>Range B</small>
                </div>
              </div>
              <button type="button" :disabled="!hasSecondInput" @click="clearSecondRange">清空</button>
            </div>
            <div class="range-grid">
              <label class="time-field">
                <span>起始时间</span>
                <input v-model="form.second_start_time" type="datetime-local" @change="runAllRegression" />
              </label>
              <label class="time-field">
                <span>结束时间</span>
                <input v-model="form.second_end_time" type="datetime-local" @change="runAllRegression" />
              </label>
            </div>
          </div>
        </div>
      </section>

      <section v-if="baseResult" class="selection-layout group-pump-layout">
        <div class="selection-panel">
          <div class="panel-heading">
            <h2>曲线选择</h2>
          </div>
          <div class="selector-grid">
            <label class="select-field">
              <span>组别</span>
              <select v-model="selectedGroupId" @change="chooseFirstPumpInGroup">
                <option v-for="group in baseResult.groups" :key="group.id" :value="group.id">
                  {{ group.name }} / {{ group.id }}
                </option>
              </select>
            </label>
            <label class="select-field">
              <span>水泵</span>
              <select v-model="selectedPumpId" :disabled="!availablePumps.length">
                <option v-for="pump in availablePumps" :key="pump.id" :value="pump.id">
                  {{ pump.name || pump.id }} / {{ pump.sample_count }} 个散点
                </option>
              </select>
            </label>
          </div>
          <div v-if="selectedGroup" class="selected-pump">
            <strong>{{ selectedGroup.name }}</strong>
            <span>组号 {{ selectedGroup.id }}</span>
            <span>来源 {{ selectedGroup.source_label }}</span>
            <span>可绘图水泵 {{ availablePumps.length }} 台</span>
          </div>
        </div>

        <aside class="summary-panel">
          <h2>当前结果</h2>
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
              <dt>异常样本</dt>
              <dd>{{ totalRejects }}</dd>
            </div>
            <div>
              <dt>未拟合水泵</dt>
              <dd>{{ totalSkipped }}</dd>
            </div>
          </dl>
          <p v-if="loading" class="hint-text">正在按所选时间段计算所有组...</p>
          <p v-if="error" class="error-text">{{ error }}</p>
        </aside>
      </section>

      <p v-if="!baseResult && loading" class="loading-text">正在计算当前时间段内所有组和水泵的拟合曲线...</p>
      <p v-else-if="error && !baseResult" class="error-text top-error">{{ error }}</p>

      <template v-if="selectedPumpId">
        <section
          v-for="payload in visiblePayloads"
          :key="payload.key"
          class="result-band"
        >
          <div class="result-header">
            <div>
              <h2>{{ payload.label }}回归结果</h2>
              <p>
                {{ payload.timeText }}，
                当前组：{{ selectedGroupName(payload.data) }}，
                当前水泵：{{ selectedPumpId }}
              </p>
            </div>
          </div>

          <div v-if="selectedResultFrom(payload.data)" class="result-grid">
            <article class="result-card">
              <header>
                <h3>{{ selectedResultFrom(payload.data).pump_id }}</h3>
                <span>{{ selectedResultFrom(payload.data).sample_count }} 个散点</span>
              </header>
              <div class="metrics">
                <span>H-Q R2: {{ formatNumber(selectedResultFrom(payload.data).head_metrics.r2) }}</span>
                <span>eta-Q R2: {{ formatNumber(selectedResultFrom(payload.data).efficiency_metrics.r2) }}</span>
                <span>Q: {{ formatNumber(selectedResultFrom(payload.data).q_min) }} - {{ formatNumber(selectedResultFrom(payload.data).q_max) }}</span>
                <span>w: {{ formatNumber(selectedResultFrom(payload.data).w_min) }} - {{ formatNumber(selectedResultFrom(payload.data).w_max) }}</span>
              </div>
              <div class="chart-grid">
                <RegressionChart :asset-base="apiBase" :chart="selectedResultFrom(payload.data).charts.head_curve" />
                <RegressionChart :asset-base="apiBase" :chart="selectedResultFrom(payload.data).charts.efficiency_curve" />
                <RegressionChart :asset-base="apiBase" :chart="selectedResultFrom(payload.data).charts.head_normalized_curve" />
                <RegressionChart :asset-base="apiBase" :chart="selectedResultFrom(payload.data).charts.efficiency_normalized_curve" />
              </div>
            </article>
          </div>

          <p v-else class="error-text top-error">
            {{ payload.label }}内当前水泵没有满足至少 10 个有效散点的拟合结果。
          </p>
        </section>
      </template>

      <p v-else-if="baseResult && !loading" class="error-text top-error">当前时间段内没有水泵满足至少 10 个有效散点的拟合条件。</p>
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
const selectedPumpId = ref('')

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
const baseResult = computed(() => result.value || secondResult.value)

const selectedGroup = computed(() => {
  return baseResult.value?.groups?.find((group) => group.id === selectedGroupId.value) || null
})

const availablePumps = computed(() => {
  return selectedGroup.value?.pumps?.filter((pump) => pump.has_result) || []
})

const visiblePayloads = computed(() => {
  const payloads = []
  if (result.value) {
    payloads.push({
      key: 'range-one',
      label: '时间段一',
      data: result.value,
      timeText: `${form.start_time} 至 ${form.end_time}`,
    })
  }
  if (secondResult.value) {
    payloads.push({
      key: 'range-two',
      label: '时间段二',
      data: secondResult.value,
      timeText: `${form.second_start_time} 至 ${form.second_end_time}`,
    })
  }
  return payloads
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

function selectedResultFrom(payload) {
  return payload?.results?.find((item) => item.pump_id === selectedPumpId.value && item.group_id === selectedGroupId.value)
    || payload?.results?.find((item) => item.pump_id === selectedPumpId.value)
    || null
}

function selectedGroupName(payload) {
  const group = payload?.groups?.find((item) => item.id === selectedGroupId.value)
  return group?.name || selectedGroup.value?.name || '-'
}

function formatNumber(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '-'
  return number.toFixed(3)
}

function chooseFirstPumpInGroup() {
  selectedPumpId.value = availablePumps.value[0]?.id || ''
}

function chooseInitialResult(payload) {
  const firstGroupWithResult = payload.groups?.find((group) => group.pumps?.some((pump) => pump.has_result))
  selectedGroupId.value = firstGroupWithResult?.id || payload.groups?.[0]?.id || ''
  chooseFirstPumpInGroup()
}

function showSkippedAlert(payload, label) {
  const skipped = payload.skipped || []
  if (!skipped.length) return
  const lines = skipped.slice(0, 20).map((item) => `${item.pump_id}: ${item.reason}`)
  const suffix = skipped.length > 20 ? `\n其余 ${skipped.length - 20} 台水泵未显示。` : ''
  window.alert(`${label}中以下水泵有效散点不足 10 个，未进行拟合：\n${lines.join('\n')}${suffix}`)
}

async function loadOptions() {
  error.value = ''
  const response = await fetch(`${apiBase}/api/options?dataset_name=${encodeURIComponent(form.dataset_name)}`)
  if (!response.ok) throw new Error('无法读取后端选项')
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
  selectedPumpId.value = ''
  await loadOptions()
  await runAllRegression()
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
    error.value = '时间段二需要同时填写起始时间和结束时间。'
    return
  }

  loading.value = true
  error.value = ''
  result.value = null
  secondResult.value = null
  selectedGroupId.value = ''
  selectedPumpId.value = ''

  try {
    const firstPayload = await runRegressionForRange(form.start_time, form.end_time)
    result.value = firstPayload
    chooseInitialResult(firstPayload)
    showSkippedAlert(firstPayload, '时间段一')

    if (hasCompleteSecondRange.value) {
      const secondPayload = await runRegressionForRange(form.second_start_time, form.second_end_time)
      secondResult.value = secondPayload
      showSkippedAlert(secondPayload, '时间段二')
    }
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
  await runAllRegression()
}

onMounted(async () => {
  try {
    await loadOptions()
    await runAllRegression()
  } catch (err) {
    apiOk.value = false
    error.value = err.message || String(err)
  }
})
</script>
