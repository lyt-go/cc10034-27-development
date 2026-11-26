<template>
  <section class="page" data-module="pseudonym_delivery">
    <header class="page-head">
      <div>
        <h2>假名交付确认</h2>
        <p class="page-desc">
          按已核验样本批次与当前有效映射核发假名交付单；确认即冻结映射版本，轮换后在途任务仍按先前确认版本完成，水印页可追溯交付批次。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" data-testid="refresh-orders" type="button" @click="reload">刷新任务</button>
      </div>
    </header>

    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">交付请求总数</span>
        <strong class="stat-value">{{ orders.length }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">在途（已确认待生成/生成中）</span>
        <strong class="stat-value">{{ inFlightCount }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">版本冲突</span>
        <strong class="stat-value">{{ conflictCount }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">已交付文件</span>
        <strong class="stat-value">{{ deliveredCount }}</strong>
      </article>
    </div>

    <form class="analysis-form" data-testid="delivery-form" @submit.prevent="submitConfirm">
      <label>
        样本批次（仅已核验可选）
        <select v-model="form.batchId" data-testid="select-batch" required>
          <option v-for="batch in verifiedBatches" :key="batch.id" :value="batch.id">
            {{ batch.批次编号 }}｜{{ batch.批次名称 }}（{{ batch.样本数量 }}条）
          </option>
        </select>
      </label>
      <label>
        假名映射（仅当前有效可选）
        <select v-model="form.mappingId" data-testid="select-mapping" required>
          <option v-for="mapping in activeMappings" :key="mapping.id" :value="mapping.id">
            第{{ mapping.映射代次 }}版 {{ mapping.映射编号 }}｜{{ mapping.盐值哈希 }}
          </option>
        </select>
      </label>
      <button class="btn primary" data-testid="open-prepare" type="button" @click="submitPrepare">
        打开确认页（草稿）
      </button>
      <button class="btn primary" data-testid="submit-confirm" type="submit">
        交付确认并核发
      </button>
    </form>
    <p v-if="formHint" class="page-desc" data-testid="form-hint">{{ formHint }}</p>

    <h3>交付请求与在途任务</h3>
    <table class="data-table" data-testid="orders-table">
      <thead>
        <tr>
          <th>交付单编号</th>
          <th>样本批次</th>
          <th>确认映射版本</th>
          <th>当前链版本</th>
          <th>交付状态</th>
          <th>文件任务</th>
          <th>版本冲突 / 下一步</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="order in orders"
          :key="order.id"
          :data-testid="`order-row-${order.id}`"
          :data-conflict="String(order.版本冲突)"
        >
          <td>{{ order.交付单编号 }}</td>
          <td>{{ order.样本批次编号 }}<br /><small>{{ order.样本批次名称 }}</small></td>
          <td>第{{ order.映射快照.映射代次 }}版 {{ order.映射快照.映射编号 }}</td>
          <td>第{{ order.当前映射代次 }}版</td>
          <td>{{ order.交付状态 }}</td>
          <td>
            <span :data-testid="`file-status-${order.id}`">{{ order.文件状态 }}</span>
            <br /><small v-if="order.文件名">{{ order.文件名 }}</small>
          </td>
          <td>
            <span v-if="order.版本冲突" class="conflict-badge">版本冲突</span>
            <span v-else class="ok-badge">版本一致</span>
            <br /><small>{{ order.冲突处置 }}</small>
          </td>
          <td class="row-actions">
            <template v-if="order.交付状态 === '待确认'">
              <button
                v-if="!order.版本冲突"
                class="link"
                type="button"
                :data-testid="`confirm-draft-${order.id}`"
                @click="onConfirmDraft(order.id)"
              >
                确认请求
              </button>
              <button
                class="link"
                type="button"
                :data-testid="`resubmit-${order.id}`"
                @click="onResubmit(order.id)"
              >
                重新提交
              </button>
            </template>
            <template v-else-if="order.文件状态 === '待生成'">
              <button
                class="link"
                type="button"
                :data-testid="`generate-${order.id}`"
                @click="onGenerate(order.id)"
              >
                启动后台生成
              </button>
            </template>
            <template v-else-if="order.文件状态 === '生成中'">
              <span class="muted-text">后台生成中…</span>
            </template>
            <template v-else-if="order.文件状态 === '已生成' && order.文件名">
              <button
                class="link"
                type="button"
                :data-testid="`download-${order.id}`"
                @click="onDownload(order)"
              >
                下载交付文件
              </button>
            </template>
          </td>
        </tr>
        <tr v-if="!orders.length">
          <td colspan="8" class="empty-state">暂无交付请求，先选择已核验批次与有效映射核发交付单</td>
        </tr>
      </tbody>
    </table>

    <h3>水印溯源（已交付文件）</h3>
    <table class="data-table" data-testid="trace-table">
      <thead>
        <tr>
          <th>水印编号</th>
          <th>水印指纹</th>
          <th>关联交付单</th>
          <th>关联样本批次</th>
          <th>冻结映射版本</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="trace in traces" :key="trace.id" :data-testid="`trace-row-${trace.id}`">
          <td>{{ trace.水印编号 }}</td>
          <td><code>{{ trace.水印指纹 }}</code></td>
          <td>{{ trace.交付单编号 }}</td>
          <td>{{ trace.样本批次编号 }}</td>
          <td>第{{ trace.映射代次 }}版 {{ trace.映射编号 }}</td>
          <td class="row-actions">
            <button
              class="link"
              type="button"
              :data-testid="`trace-detail-${trace.id}`"
              @click="openTrace(trace.id)"
            >
              水印详情
            </button>
          </td>
        </tr>
        <tr v-if="!traces.length">
          <td colspan="6" class="empty-state">尚无已交付文件，文件生成后会自动写入水印溯源记录</td>
        </tr>
      </tbody>
    </table>

    <div v-if="traceDetail" class="modal-backdrop" data-testid="trace-modal" @click.self="traceDetail = null">
      <div class="modal">
        <h3>水印详情 · {{ traceDetail.水印编号 }}</h3>
        <dl class="dag-detail">
          <template v-for="(value, key) in traceFields" :key="key">
            <dt>{{ key }}</dt>
            <dd :data-testid="`trace-field-${key}`">{{ value }}</dd>
          </template>
        </dl>
        <div class="page-actions">
          <button class="btn primary" type="button" @click="traceDetail = null">关闭</button>
        </div>
      </div>
    </div>

    <footer class="page-foot">
      <span>刷新后以服务端实时版本冲突标注为准；已交付老文件长期保留可下载、可追溯。</span>
      <span v-if="errorMessage" class="error-text" data-testid="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

import {
  confirmDelivery,
  confirmDraft,
  downloadFile,
  fetchBatches,
  fetchOrders,
  fetchTrace,
  fetchTraces,
  generateFile,
  prepareDelivery,
  resubmitOrder,
} from '@/api/delivery-service'
import { listEntries } from '@/api/backend-service'
import type { DeliveryOrder, SampleBatch, WatermarkTrace } from '@/data/delivery'
import type { EntryRow } from '@/data/types'

const batches = ref<SampleBatch[]>([])
const mappings = ref<EntryRow[]>([])
const orders = ref<DeliveryOrder[]>([])
const traces = ref<WatermarkTrace[]>([])
const traceDetail = ref<WatermarkTrace | null>(null)
const errorMessage = ref('')
const formHint = ref('')
const form = ref({ batchId: 0, mappingId: 0 })
let timer: number | undefined

const verifiedBatches = computed(() => batches.value.filter((item) => item.核验状态 === '已核验'))
const activeMappings = computed(() => mappings.value.filter((item) => item.status === '有效'))
const inFlightCount = computed(
  () => orders.value.filter((item) => item.交付状态 === '已确认').length,
)
const conflictCount = computed(() => orders.value.filter((item) => item.版本冲突).length)
const deliveredCount = computed(
  () => orders.value.filter((item) => item.交付状态 === '已交付').length,
)

const traceFields = computed(() => {
  const trace = traceDetail.value
  if (!trace) return {}
  const detail = trace.交付单详情
  return {
    水印指纹: trace.水印指纹,
    目标数据集: trace.目标数据集,
    水印算法: trace.水印算法,
    交付单编号: trace.交付单编号,
    样本批次: `${trace.样本批次编号}${detail ? `｜${detail.样本批次名称}` : ''}`,
    冻结映射: `第${trace.映射代次}版 ${trace.映射编号}`,
    交付文件: detail?.文件名 ?? '—',
    交付时间: detail?.交付时间 ?? '—',
    文件状态: detail?.文件状态 ?? '—',
  }
})

async function reload() {
  if (timer) {
    window.clearTimeout(timer)
    timer = undefined
  }
  try {
    const [orderList, traceList] = await Promise.all([fetchOrders(), fetchTraces()])
    orders.value = orderList
    traces.value = traceList
    if (orders.value.some((item) => item.文件状态 === '生成中' || item.文件状态 === '待生成')) {
      timer = window.setTimeout(reload, 2500)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '交付数据读取失败'
  }
}

async function loadBaseData() {
  const [batchList, mappingPage] = await Promise.all([
    fetchBatches(),
    listEntries('pseudonym', { status: '有效' }),
  ])
  batches.value = batchList
  mappings.value = mappingPage.items
  if (!form.value.batchId && verifiedBatches.value.length) {
    form.value.batchId = verifiedBatches.value[0].id
  }
  if (!form.value.mappingId && activeMappings.value.length) {
    form.value.mappingId = Number(activeMappings.value[0].id)
  }
}

async function guard(result: { ok: boolean; message: string }) {
  if (!result.ok) {
    errorMessage.value = result.message
    return false
  }
  errorMessage.value = ''
  formHint.value = result.message
  await reload()
  return true
}

async function submitPrepare() {
  formHint.value = ''
  const result = await prepareDelivery(form.value.batchId, form.value.mappingId)
  await guard(result)
}

async function submitConfirm() {
  formHint.value = ''
  const result = await confirmDelivery(form.value.batchId, form.value.mappingId)
  await guard(result)
}

async function onConfirmDraft(orderId: number) {
  await guard(await confirmDraft(orderId))
}

async function onResubmit(orderId: number) {
  await guard(await resubmitOrder(orderId))
}

async function onGenerate(orderId: number) {
  await guard(await generateFile(orderId))
  await reload()
}

async function onDownload(order: DeliveryOrder) {
  if (!order.文件名) return
  try {
    await downloadFile(order.id, order.文件名)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '下载失败'
  }
}

async function openTrace(watermarkId: number) {
  try {
    traceDetail.value = await fetchTrace(watermarkId)
    errorMessage.value = ''
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '水印详情读取失败'
  }
}

onMounted(async () => {
  try {
    await loadBaseData()
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '交付工作台初始化失败'
  }
})

onUnmounted(() => {
  if (timer) window.clearTimeout(timer)
})
</script>

<style scoped>
.conflict-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  background: #fef3c7;
  color: #b45309;
  font-size: 12px;
}
.ok-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  background: #dcfce7;
  color: #15803d;
  font-size: 12px;
}
.muted-text {
  color: var(--muted);
  font-size: 12px;
}
small {
  color: var(--muted);
}
</style>
