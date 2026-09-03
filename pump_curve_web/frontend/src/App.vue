<template>
  <main class="app-shell">
    <section class="workspace">
      <header class="page-header">
        <div class="title-block">
          <p class="eyebrow">Pump Curve Regression</p>
          <h1>
            <span>水泵扬程及效率</span>
            <span>与水泵流量Q的拟合曲线</span>
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
            <input v-model="form.dataset_name" type="text" @change="loadOptions" />
          </label>
        </div>

        <div v-if="options?.sources?.length" class="side-row">
          <button
            v-for="source in options.sources"
            :key="source.value"
            type="button"
            :class="{ active: form.source_types.includes(source.value) }"
            @click="toggleSource(source.value)"
          >
            {{ source.label }}
          </button>
        </div>
      </section>

      <section v-if="options" class="selection-layout">
        <div class="selection-panel">
          <div class="panel-heading">
            <h2>流量来源设备</h2>
            <button type="button" @click="selectAllFlowDevices">全选</button>
          </div>
          <template v-for="source in selectedSources" :key="source.value">
            <h3 class="source-title">{{ source.label }}</h3>
            <label v-for="device in source.devices" :key="`${source.value}-${device.id}`" class="check-row">
              <input v-model="form.flow_device_ids" type="checkbox" :value="device.id" />
              <span>
                <strong>{{ device.name || device.id }}</strong>
                <small>组号 {{ device.group_id }} / {{ device.row_count }} 条</small>
              </span>
            </label>
          </template>
        </div>

        <div class="selection-panel">
          <div class="panel-heading">
            <h2>组号</h2>
            <button type="button" @click="selectAllGroups">全选</button>
          </div>
          <label v-for="group in options.groups" :key="group.id" class="check-row">
            <input v-model="form.group_ids" type="checkbox" :value="group.id" />
            <span>
              <strong>{{ group.name || group.id }}</strong>
              <small>同组流量来源与水泵会被匹配计算</small>
            </span>
          </label>
        </div>

        <div class="selection-panel">
          <div class="panel-heading">
            <h2>水泵</h2>
            <button type="button" @click="selectAllPumps">全选</button>
          </div>
          <label v-for="pump in filteredPumps" :key="pump.id" class="check-row">
            <input v-model="form.pump_ids" type="checkbox" :value="pump.id" />
            <span>
              <strong>{{ pump.name || pump.id }}</strong>
              <small>组号 {{ pump.group_id }} / {{ pump.row_count }} 条</small>
            </span>
          </label>
        </div>

        <aside class="summary-panel">
          <h2>当前条件</h2>
          <dl>
            <div>
              <dt>流量来源</dt>
              <dd>{{ sourceSummary }}</dd>
            </div>
            <div>
              <dt>组号数量</dt>
              <dd>{{ form.group_ids.length }}</dd>
            </div>
            <div>
              <dt>来源设备</dt>
              <dd>{{ form.flow_device_ids.length }}</dd>
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
import { computed, onMounted, reactive, ref } from 'vue'
import RegressionChart from './components/RegressionChart.vue'

const apiBase = 'http://127.0.0.1:8010'

const apiOk = ref(false)
const options = ref(null)
const result = ref(null)
const loading = ref(false)
const error = ref('')

const form = reactive({
  dataset_name: 'sample_raw_points',
  start_time: '',
  end_time: '',
  side: '',
  source_types: [],
  group_ids: [],
  flow_device_ids: [],
  facility_ids: [],
  pump_ids: [],
})

const selectedSources = computed(() => {
  return options.value?.sources?.filter((source) => form.source_types.includes(source.value)) || []
})

const filteredPumps = computed(() => {
  const groups = new Set(form.group_ids)
  const pumps = options.value?.pumps || []
  if (!groups.size) return pumps
  return pumps.filter((pump) => groups.has(pump.group_id))
})

const sourceSummary = computed(() => {
  const labels = selectedSources.value.map((source) => source.label)
  return labels.length ? labels.join('、') : '-'
})

function formatNumber(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '-'
  return number.toFixed(3)
}

function toggleSource(sourceType) {
  result.value = null
  if (form.source_types.includes(sourceType)) {
    form.source_types = form.source_types.filter((item) => item !== sourceType)
  } else {
    form.source_types = [...form.source_types, sourceType]
  }
  const visibleDeviceIds = new Set(selectedSources.value.flatMap((source) => source.devices.map((item) => item.id)))
  form.flow_device_ids = form.flow_device_ids.filter((id) => visibleDeviceIds.has(id))
}

function resetSelections() {
  form.source_types = options.value?.sources?.map((item) => item.value) || []
  form.group_ids = options.value?.groups?.map((item) => item.id) || []
  selectAllFlowDevices()
  selectAllPumps()
}

function selectAllFlowDevices() {
  form.flow_device_ids = selectedSources.value.flatMap((source) => source.devices.map((item) => item.id))
  form.facility_ids = [...form.flow_device_ids]
}

function selectAllGroups() {
  form.group_ids = options.value?.groups?.map((item) => item.id) || []
  selectAllPumps()
}

function selectAllPumps() {
  form.pump_ids = filteredPumps.value.map((item) => item.id)
}

async function loadOptions() {
  error.value = ''
  result.value = null
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
  form.facility_ids = [...form.flow_device_ids]
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
