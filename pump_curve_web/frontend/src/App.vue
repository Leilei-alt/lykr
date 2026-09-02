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
        <div class="field-grid">
          <label>
            <span>起始时间</span>
            <input v-model="form.start_time" type="datetime-local" />
          </label>
          <label>
            <span>结束时间</span>
            <input v-model="form.end_time" type="datetime-local" />
          </label>
          <label>
            <span>数据集</span>
            <input v-model="form.dataset_name" type="text" />
          </label>
        </div>

        <div class="side-row">
          <button
            v-for="side in sides"
            :key="side.value"
            type="button"
            :class="{ active: form.side === side.value }"
            @click="chooseSide(side.value)"
          >
            {{ side.label }}
          </button>
        </div>
      </section>

      <section v-if="activeGroup" class="selection-layout">
        <div class="selection-panel">
          <div class="panel-heading">
            <h2>冷机/冷却设备</h2>
            <button type="button" @click="selectAllFacilities">全选</button>
          </div>
          <label v-for="facility in activeGroup.facilities" :key="facility.id" class="check-row">
            <input v-model="form.facility_ids" type="checkbox" :value="facility.id" />
            <span>
              <strong>{{ facility.name || facility.id }}</strong>
              <small>{{ facility.status_point }}</small>
            </span>
          </label>
        </div>

        <div class="selection-panel">
          <div class="panel-heading">
            <h2>水泵</h2>
            <button type="button" @click="selectAllPumps">全选</button>
          </div>
          <label v-for="pump in activeGroup.pumps" :key="pump.id" class="check-row">
            <input v-model="form.pump_ids" type="checkbox" :value="pump.id" />
            <span>
              <strong>{{ pump.name || pump.id }}</strong>
              <small>{{ pump.frequency_point }} / {{ pump.head_point }}</small>
            </span>
          </label>
        </div>

        <aside class="summary-panel">
          <h2>当前条件</h2>
          <dl>
            <div>
              <dt>侧别</dt>
              <dd>{{ sideLabel(form.side) }}</dd>
            </div>
            <div>
              <dt>冷机/设备数量</dt>
              <dd>{{ form.facility_ids.length }}</dd>
            </div>
            <div>
              <dt>水泵数量</dt>
              <dd>{{ form.pump_ids.length }}</dd>
            </div>
            <div>
              <dt>数据库时间点</dt>
              <dd>{{ options?.time_range?.time_count || 0 }}</dd>
            </div>
          </dl>
          <button class="primary-action" type="button" :disabled="loading" @click="runRegression">
            {{ loading ? '分析中...' : '确认并生成曲线' }}
          </button>
          <p v-if="error" class="error-text">{{ error }}</p>
        </aside>
      </section>
      <p v-else-if="error" class="error-text top-error">{{ error }}</p>

      <section v-if="result" class="result-band">
        <div class="result-header">
          <div>
            <h2>回归结果</h2>
            <p>
              有效样本 {{ result.valid_sample_count }} 条，
              原始时间点 {{ result.raw_time_count }} 个，
              异常样本 {{ result.reject_count }} 条
            </p>
          </div>
        </div>

        <div class="result-grid">
          <article v-for="item in result.results" :key="item.pump_id" class="result-card">
            <header>
              <h3>{{ item.pump_id }}</h3>
              <span>{{ item.sample_count }} 个散点</span>
            </header>
            <div class="metrics">
              <span>H-Q R2: {{ formatNumber(item.head_metrics.r2) }}</span>
              <span>eta-Q R2: {{ formatNumber(item.efficiency_metrics.r2) }}</span>
              <span>Q: {{ formatNumber(item.q_min) }} - {{ formatNumber(item.q_max) }}</span>
              <span>w: {{ formatNumber(item.w_min) }} - {{ formatNumber(item.w_max) }}</span>
            </div>
            <div class="chart-grid">
              <RegressionChart :asset-base="apiBase" :chart="item.charts.head_curve" />
              <RegressionChart :asset-base="apiBase" :chart="item.charts.efficiency_curve" />
              <RegressionChart :asset-base="apiBase" :chart="item.charts.head_normalized_curve" />
              <RegressionChart :asset-base="apiBase" :chart="item.charts.efficiency_normalized_curve" />
            </div>
          </article>
        </div>
      </section>
    </section>
  </main>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import RegressionChart from './components/RegressionChart.vue'

const apiBase = 'http://127.0.0.1:8010'
const sides = [
  { value: 'chilled_water', label: '冷冻侧' },
  { value: 'cooling_water', label: '冷却侧' },
]

const apiOk = ref(false)
const options = ref(null)
const result = ref(null)
const loading = ref(false)
const error = ref('')

const form = reactive({
  dataset_name: 'sample_raw_points',
  start_time: '',
  end_time: '',
  side: 'chilled_water',
  facility_ids: [],
  pump_ids: [],
})

const activeGroup = computed(() => {
  return options.value?.groups?.find((group) => group.side === form.side)
})

function sideLabel(value) {
  return sides.find((side) => side.value === value)?.label || value
}

function formatNumber(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '-'
  return number.toFixed(3)
}

function chooseSide(side) {
  form.side = side
  result.value = null
  void nextTick(resetSelections)
}

function resetSelections() {
  const group = activeGroup.value
  form.facility_ids = group?.facilities?.map((item) => item.id) || []
  form.pump_ids = group?.pumps?.map((item) => item.id) || []
}

function selectAllFacilities() {
  form.facility_ids = activeGroup.value?.facilities?.map((item) => item.id) || []
}

function selectAllPumps() {
  form.pump_ids = activeGroup.value?.pumps?.map((item) => item.id) || []
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
  resetSelections()
}

async function runRegression() {
  loading.value = true
  error.value = ''
  result.value = null
  try {
    const response = await fetch(`${apiBase}/api/regression`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form),
    })
    const payload = await response.json()
    if (!response.ok) {
      throw new Error(payload.detail || '回归分析失败')
    }
    result.value = payload
  } catch (err) {
    error.value = err.message || String(err)
  } finally {
    loading.value = false
  }
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
