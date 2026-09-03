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
      </section>

      <section v-if="options" class="selection-layout pump-picker-layout">
        <div class="selection-panel">
          <div class="panel-heading">
            <h2>用户选择水泵</h2>
            <button type="button" @click="selectVisiblePumps">选择当前列表</button>
          </div>
          <label class="select-field">
            <span>搜索水泵</span>
            <input v-model.trim="pumpKeyword" type="text" placeholder="输入水泵编号或组号" />
          </label>
          <div class="pump-list">
            <label v-for="pump in filteredPumps" :key="pump.id" class="check-row">
              <input v-model="form.selected_pump_ids" type="checkbox" :value="pump.id" />
              <span>
                <strong>{{ pump.name || pump.id }}</strong>
                <small>组号 {{ pump.group_id }} / {{ pump.source_label || '未识别来源' }} / {{ pump.row_count }} 条</small>
              </span>
            </label>
          </div>
        </div>

        <div class="selection-panel">
          <div class="panel-heading">
            <h2>绘图水泵</h2>
          </div>
          <label class="select-field">
            <span>从已选水泵中选择</span>
            <select v-model="form.display_pump_id">
              <option v-for="pump in selectedCandidatePumps" :key="pump.id" :value="pump.id">
                {{ pump.name || pump.id }} / {{ pump.group_id }} / {{ pump.source_label || '未识别来源' }}
              </option>
            </select>
          </label>
          <div v-if="selectedPump" class="selected-pump">
            <strong>{{ selectedPump.name || selectedPump.id }}</strong>
            <span>组号 {{ selectedPump.group_id }}</span>
            <span>流量来源 {{ selectedPump.source_label || '未识别来源' }}</span>
            <span>数据 {{ selectedPump.row_count }} 条</span>
          </div>
        </div>

        <aside class="summary-panel">
          <h2>当前条件</h2>
          <dl>
            <div>
              <dt>当前水泵</dt>
              <dd>{{ selectedPump?.id || '-' }}</dd>
            </div>
            <div>
              <dt>已选水泵</dt>
              <dd>{{ form.selected_pump_ids.length }}</dd>
            </div>
            <div>
              <dt>所属组号</dt>
              <dd>{{ selectedPump?.group_id || '-' }}</dd>
            </div>
            <div>
              <dt>流量来源</dt>
              <dd>{{ selectedSourceSummary }}</dd>
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
            <p>
              自动识别组号：{{ result.inferred_group_ids?.join('、') || '-' }}；
              自动识别来源：{{ formatSourceTypes(result.inferred_source_types) }}
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
import { computed, onMounted, reactive, ref, watch } from 'vue'
import RegressionChart from './components/RegressionChart.vue'

const apiBase = 'http://127.0.0.1:8010'
const sourceLabels = {
  header_controller: '干管协调控制器',
  chiller: '冷机',
}

const apiOk = ref(false)
const options = ref(null)
const result = ref(null)
const loading = ref(false)
const error = ref('')

const form = reactive({
  dataset_name: 'sample_raw_points',
  start_time: '',
  end_time: '',
  selected_pump_ids: [],
  display_pump_id: '',
})
const pumpKeyword = ref('')

const filteredPumps = computed(() => {
  const pumps = options.value?.pumps || []
  const keyword = pumpKeyword.value.toLowerCase()
  if (!keyword) return pumps
  return pumps.filter((pump) => {
    return [pump.id, pump.name, pump.group_id, pump.source_label]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(keyword))
  })
})

const selectedCandidatePumps = computed(() => {
  const selected = new Set(form.selected_pump_ids)
  return options.value?.pumps?.filter((pump) => selected.has(pump.id)) || []
})

const selectedPump = computed(() => {
  return selectedCandidatePumps.value.find((pump) => pump.id === form.display_pump_id) || null
})

const selectedSourceSummary = computed(() => {
  const sources = (selectedPump.value?.source_types || []).map((source) => sourceLabels[source] || source)
  return sources.length ? sources.join('、') : '-'
})

function formatSourceTypes(values) {
  if (!values?.length) return '-'
  return values.map((value) => sourceLabels[value] || value).join('、')
}

function formatNumber(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '-'
  return number.toFixed(3)
}

function resetSelections() {
  form.selected_pump_ids = options.value?.pumps?.map((item) => item.id) || []
  form.display_pump_id = form.selected_pump_ids[0] || ''
}

function selectVisiblePumps() {
  form.selected_pump_ids = filteredPumps.value.map((item) => item.id)
  form.display_pump_id = form.selected_pump_ids[0] || ''
}

watch(
  () => form.selected_pump_ids.slice(),
  () => {
    if (!form.selected_pump_ids.includes(form.display_pump_id)) {
      form.display_pump_id = form.selected_pump_ids[0] || ''
    }
  },
)

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
  if (!form.display_pump_id) {
    error.value = '请先选择候选水泵，并在下拉框中选择一个绘图水泵'
    loading.value = false
    return
  }
  try {
    const response = await fetch(`${apiBase}/api/regression`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dataset_name: form.dataset_name,
        start_time: form.start_time,
        end_time: form.end_time,
        pump_ids: [form.display_pump_id],
      }),
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
