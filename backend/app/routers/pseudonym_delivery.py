"""假名交付确认 API。

路由固定前缀 /api/pseudonym-delivery，必须先于通用资源路由注册，
避免 /api/{module} 动态路径抢先匹配。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services.pseudonym_delivery import PseudonymDeliveryService

router = APIRouter(prefix="/api/pseudonym-delivery", tags=["假名交付确认"])

service = PseudonymDeliveryService()


class DeliveryPayload(BaseModel):
    batch_id: int
    mapping_id: int
    remark: str | None = None


class OrderPayload(BaseModel):
    order_id: int
    remark: str | None = None


def _result(order: dict[str, Any] | None, message: str) -> dict[str, Any]:
    return {"ok": order is not None, "message": message, "entry": order}


@router.get("/batches")
def list_batches() -> dict[str, Any]:
    """样本批次列表，前端只允许选择已核验批次。"""
    return {"items": service.list_batches(), "total": len(service.list_batches())}


@router.get("/orders")
def list_orders() -> dict[str, Any]:
    """全部交付请求（含仅打开未确认的草稿），带实时版本冲突标注。"""
    items = service.list_orders()
    return {"items": items, "total": len(items)}


@router.get("/orders/{order_id}")
def get_order(order_id: int) -> dict[str, Any]:
    order = service.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail=f"交付单 {order_id} 不存在或已归档")
    return order


@router.post("/prepare")
def prepare_order(payload: DeliveryPayload) -> dict[str, Any]:
    """打开交付确认页：仅生成待确认草稿，不核发任何文件。"""
    order, message = service.prepare_order(payload.batch_id, payload.mapping_id)
    return _result(order, message)


@router.post("/confirm")
def confirm_order(payload: DeliveryPayload) -> dict[str, Any]:
    """按用户选择的样本批次和映射核发假名交付单（已确认，文件排队）。"""
    order, message = service.confirm_order(payload.batch_id, payload.mapping_id)
    return _result(order, message)


@router.post("/orders/{order_id}/confirm")
def confirm_draft(order_id: int, payload: OrderPayload) -> dict[str, Any]:
    """确认一笔此前仅打开的草稿请求。"""
    order, message = service.confirm_draft(order_id)
    return _result(order, message)


@router.post("/orders/{order_id}/resubmit")
def resubmit_order(order_id: int, payload: OrderPayload) -> dict[str, Any]:
    """草稿请求按当前有效映射重新提交。"""
    order, message = service.resubmit_order(order_id)
    return _result(order, message)


@router.post("/orders/{order_id}/generate")
def generate_file(order_id: int, payload: OrderPayload) -> dict[str, Any]:
    """启动后台文件生成；已确认版本被冻结，轮换不影响在途任务。"""
    order, message = service.enqueue_generation(order_id)
    return _result(order, message)


@router.get("/orders/{order_id}/download")
def download_file(order_id: int) -> StreamingResponse:
    result = service.download_file(order_id)
    if result is None:
        raise HTTPException(status_code=404, detail="交付文件尚未生成或交付单不存在")
    payload, filename = result
    return StreamingResponse(
        iter([payload]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/watermark-traces")
def list_traces() -> dict[str, Any]:
    """水印溯源列表：仅返回由假名交付生成的水印记录。"""
    items = service.list_traces()
    return {"items": items, "total": len(items)}


@router.get("/watermark-traces/{watermark_id}")
def get_trace(watermark_id: int) -> dict[str, Any]:
    """水印详情页核对已交付文件关联的批次与冻结映射版本。"""
    trace = service.get_trace(watermark_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="该水印记录暂无假名交付溯源信息")
    return trace
