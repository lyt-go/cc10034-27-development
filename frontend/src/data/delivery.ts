/** 假名交付确认领域类型，与后端 pseudonym_delivery 服务契约保持一致。 */

export type MappingSnapshot = {
  映射ID: number
  映射编号: string
  映射版本: number
  映射代次: number
  版本链ID: number
  映射算法: string
  盐值哈希: string
  可逆标记: string
  原始标识: string
  假名标识: string
}

export type DeliveryOrder = {
  id: number
  交付单编号: string
  样本批次ID: number
  样本批次编号: string
  样本批次名称: string
  映射快照: MappingSnapshot
  交付状态: '待确认' | '已确认' | '已交付'
  文件状态: '未排队' | '待生成' | '生成中' | '已生成'
  文件名: string | null
  水印编号: string | null
  水印ID?: number
  提交时间: string
  确认时间: string | null
  交付时间: string | null
  当前映射代次: number
  版本冲突: boolean
  冲突处置: string
}

export type SampleBatch = {
  id: number
  批次编号: string
  批次名称: string
  样本数量: string
  核验状态: '已核验' | '待核验'
  核验时间: string
  数据范围: string
}

export type WatermarkTrace = {
  id: number
  水印编号: string
  目标数据集: string
  水印算法: string
  水印指纹: string
  交付单ID: number
  交付单编号: string
  样本批次ID: number
  样本批次编号: string
  映射版本: number
  映射代次: number
  映射编号: string
  版本链ID: number
  文件字节数: number
  交付单详情?: {
    交付单编号: string
    样本批次编号: string
    样本批次名称: string
    文件名: string
    交付时间: string
    文件状态: string
    映射快照: MappingSnapshot
  }
}

export type DeliveryResult = {
  ok: boolean
  message: string
  entry: DeliveryOrder | null
}
