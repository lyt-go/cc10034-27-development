/** 假名交付确认 API：核发、确认、重新提交、后台生成、下载与水印溯源。 */
import { request } from './client'
import type {
  DeliveryOrder,
  DeliveryResult,
  SampleBatch,
  WatermarkTrace,
} from '@/data/delivery'

async function readJson<T>(response: Response): Promise<T> {
  return (await response.json()) as T
}

export async function fetchBatches(): Promise<SampleBatch[]> {
  const response = await request('/api/pseudonym-delivery/batches')
  if (!response.ok) throw new Error('样本批次读取失败')
  const payload = await readJson<{ items: SampleBatch[] }>(response)
  return payload.items
}

export async function fetchOrders(): Promise<DeliveryOrder[]> {
  const response = await request('/api/pseudonym-delivery/orders')
  if (!response.ok) throw new Error('交付单读取失败')
  const payload = await readJson<{ items: DeliveryOrder[] }>(response)
  return payload.items
}

export async function prepareDelivery(batchId: number, mappingId: number): Promise<DeliveryResult> {
  const response = await request('/api/pseudonym-delivery/prepare', {
    method: 'POST',
    body: JSON.stringify({ batch_id: batchId, mapping_id: mappingId }),
  })
  return readJson<DeliveryResult>(response)
}

export async function confirmDelivery(batchId: number, mappingId: number): Promise<DeliveryResult> {
  const response = await request('/api/pseudonym-delivery/confirm', {
    method: 'POST',
    body: JSON.stringify({ batch_id: batchId, mapping_id: mappingId }),
  })
  return readJson<DeliveryResult>(response)
}

export async function confirmDraft(orderId: number): Promise<DeliveryResult> {
  const response = await request(`/api/pseudonym-delivery/orders/${orderId}/confirm`, {
    method: 'POST',
    body: JSON.stringify({ order_id: orderId }),
  })
  return readJson<DeliveryResult>(response)
}

export async function resubmitOrder(orderId: number): Promise<DeliveryResult> {
  const response = await request(`/api/pseudonym-delivery/orders/${orderId}/resubmit`, {
    method: 'POST',
    body: JSON.stringify({ order_id: orderId }),
  })
  return readJson<DeliveryResult>(response)
}

export async function generateFile(orderId: number): Promise<DeliveryResult> {
  const response = await request(`/api/pseudonym-delivery/orders/${orderId}/generate`, {
    method: 'POST',
    body: JSON.stringify({ order_id: orderId }),
  })
  return readJson<DeliveryResult>(response)
}

export async function downloadFile(orderId: number, fileName: string): Promise<void> {
  const response = await request(`/api/pseudonym-delivery/orders/${orderId}/download`)
  if (!response.ok) throw new Error('交付文件尚未生成，暂时无法下载')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function fetchTraces(): Promise<WatermarkTrace[]> {
  const response = await request('/api/pseudonym-delivery/watermark-traces')
  if (!response.ok) throw new Error('水印溯源记录读取失败')
  const payload = await readJson<{ items: WatermarkTrace[] }>(response)
  return payload.items
}

export async function fetchTrace(watermarkId: number): Promise<WatermarkTrace> {
  const response = await request(`/api/pseudonym-delivery/watermark-traces/${watermarkId}`)
  if (!response.ok) {
    throw new Error('该水印记录暂无假名交付溯源信息')
  }
  return readJson<WatermarkTrace>(response)
}
