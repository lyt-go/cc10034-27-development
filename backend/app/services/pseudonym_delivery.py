"""假名交付领域服务。

核心约束（与业务验收口径一一对应）：
1. 交付确认时按用户选择的「样本批次 + 当前映射」核发假名交付单，并把映射
   快照（版本/代次/盐值/假名规则）冻结在单据上；文件与交付单永远指向同一次
   生成，映射轮换后后台任务仍以冻结的先前确认版本完成，绝不混用两版。
2. 已失效、已轮换且未经确认的映射不得再生成新的交付文件——核发阶段直接拦截。
3. 映射轮换与在途交付发生版本冲突时，已确认的在途任务继续以先前确认版本完成，
   操作者可在单据上看到「继续沿用已确认版本」；未确认（草稿/打开未确认）的请求
   标记为「需重新提交」。
4. 已交付的老文件长期保留、随时可下载，并在水印详情中可追溯到交付批次。
"""
from __future__ import annotations

import csv
import hashlib
import io
import threading
from datetime import datetime
from typing import Any

from app.store import store
from app.services.pseudonym import PseudonymService

# 交付单生命周期
ORDER_DRAFT = "待确认"
ORDER_CONFIRMED = "已确认"
ORDER_DELIVERED = "已交付"

# 文件任务生命周期
FILE_PENDING = "待生成"
FILE_GENERATING = "生成中"
FILE_READY = "已生成"

GENERATION_DELAY_SECONDS = 2.0


class PseudonymDeliveryService:
    """假名交付单与后台文件任务的全部领域逻辑集中在本服务。"""

    MODULE = "pseudonym_delivery"
    BATCH_MODULE = "sample_batch"
    WATERMARK_MODULE = "watermark"

    def __init__(self) -> None:
        # 内存仓库下用进程锁串行化核发/确认/生成，避免交错请求写花状态。
        self._lock = threading.RLock()
        self._files: dict[int, bytes] = {}

    # ------------------------------------------------------------------
    # 样本批次
    # ------------------------------------------------------------------
    def list_batches(self) -> list[dict[str, Any]]:
        return list(store.rows(self.BATCH_MODULE))

    def _verified_batch(self, batch_id: int) -> dict[str, Any] | None:
        batch = store.find(self.BATCH_MODULE, batch_id)
        if batch is not None and batch.get("核验状态") == "已核验":
            return batch
        return None

    # ------------------------------------------------------------------
    # 映射快照
    # ------------------------------------------------------------------
    @staticmethod
    def _snapshot(mapping: dict[str, Any]) -> dict[str, Any]:
        return {
            "映射ID": mapping["id"],
            "映射编号": mapping["映射编号"],
            "映射版本": mapping.get("映射版本", 1),
            "映射代次": mapping.get("映射代次", 1),
            "版本链ID": mapping.get("版本链ID", mapping["id"]),
            "映射算法": mapping["映射算法"],
            "盐值哈希": mapping["盐值哈希"],
            "可逆标记": mapping["可逆标记"],
            "原始标识": mapping["原始标识"],
            "假名标识": mapping["假名标识"],
        }

    def _current_chain_generation(self, chain_id: int) -> int:
        pseudo = PseudonymService()
        chain = pseudo.chain_snapshot(chain_id)
        return max((int(row.get("映射代次", 1)) for row in chain), default=1)

    # ------------------------------------------------------------------
    # 冲突装饰：每次读取实时计算，保证刷新后看到的就是最新轮换结果
    # ------------------------------------------------------------------
    def _decorate(self, order: dict[str, Any]) -> dict[str, Any]:
        view = dict(order)
        snapshot = order.get("映射快照") or {}
        chain_id = int(snapshot.get("版本链ID") or 0)
        current_gen = self._current_chain_generation(chain_id) if chain_id else int(
            snapshot.get("映射代次", 1))
        pinned_gen = int(snapshot.get("映射代次", 1))
        behind = current_gen > pinned_gen
        view["当前映射代次"] = current_gen
        view["版本冲突"] = behind

        if order["交付状态"] == ORDER_DELIVERED:
            view["冲突处置"] = "历史交付，按确认版本留档可追溯"
        elif behind and order["交付状态"] == ORDER_CONFIRMED:
            view["冲突处置"] = "在途任务继续沿用已确认的第 %d 版，无需重新提交" % pinned_gen
        elif behind and order["交付状态"] == ORDER_DRAFT:
            view["冲突处置"] = "映射已轮换到第 %d 版，需重新提交后再确认" % current_gen
        else:
            view["冲突处置"] = "与当前映射版本一致"
        return view

    def list_orders(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = [self._decorate(row) for row in store.rows(self.MODULE)]
        return sorted(rows, key=lambda row: int(row["id"]), reverse=True)

    def get_order(self, order_id: int) -> dict[str, Any] | None:
        with self._lock:
            order = store.find(self.MODULE, order_id)
            return self._decorate(order) if order else None

    # ------------------------------------------------------------------
    # 核发 / 确认 / 重新提交
    # ------------------------------------------------------------------
    def prepare_order(self, batch_id: int, mapping_id: int) -> tuple[dict[str, Any] | None, str]:
        """打开交付确认页：生成草稿请求，不产生任何交付文件。"""
        with self._lock:
            order, message = self._build_order(batch_id, mapping_id, confirmed=False)
            return order, message

    def confirm_order(self, batch_id: int, mapping_id: int) -> tuple[dict[str, Any] | None, str]:
        """交付确认：校验通过后核发已确认交付单，并排队后台文件任务。"""
        with self._lock:
            order, message = self._build_order(batch_id, mapping_id, confirmed=True)
            if order is None:
                return None, message
            return self._decorate(order), message

    def confirm_draft(self, order_id: int) -> tuple[dict[str, Any] | None, str]:
        """确认此前仅打开（草稿）的请求；若映射已轮换则要求重新提交。"""
        with self._lock:
            order = store.find(self.MODULE, order_id)
            if order is None:
                return None, f"交付单 {order_id} 不存在或已归档"
            if order["交付状态"] != ORDER_DRAFT:
                return None, "仅待确认请求可以执行确认"
            mapping = store.find("pseudonym", int(order["映射快照"]["映射ID"]))
            if mapping is None or mapping.get("status") != "有效":
                return None, "该映射已失效或已轮换，请重新提交并选择当前有效映射"
            if self._current_chain_generation(int(order["映射快照"]["版本链ID"])) > int(
                    order["映射快照"]["映射代次"]):
                return None, "映射已轮换，草稿绑定的是旧版本，请重新提交后再确认"
            order["交付状态"] = ORDER_CONFIRMED
            order["确认时间"] = _now()
            order["文件状态"] = FILE_PENDING
            return self._decorate(order), "交付单已确认，文件任务已排队"

    def resubmit_order(self, order_id: int) -> tuple[dict[str, Any] | None, str]:
        """未确认请求按当前有效映射重新提交，刷新冻结快照。"""
        with self._lock:
            order = store.find(self.MODULE, order_id)
            if order is None:
                return None, f"交付单 {order_id} 不存在或已归档"
            if order["交付状态"] != ORDER_DRAFT:
                return None, "仅待确认请求允许重新提交；已确认任务按既有版本继续生成"
            mapping = PseudonymService().active_mapping(int(order["映射快照"]["映射ID"]))
            chain_id = int(order["映射快照"].get("版本链ID") or order["映射快照"]["映射ID"])
            if mapping is None:
                latest = self._latest_active_in_chain(chain_id)
                if latest is None:
                    return None, "该版本链当前没有有效映射，无法重新提交"
                mapping = latest
            order["映射快照"] = self._snapshot(mapping)
            order["提交时间"] = _now()
            return self._decorate(order), "已按当前第 %d 版映射重新提交，等待确认" % mapping.get("映射代次", 1)

    def _latest_active_in_chain(self, chain_id: int) -> dict[str, Any] | None:
        chain = PseudonymService().chain_snapshot(chain_id)
        active = [row for row in chain if row.get("status") == "有效"]
        return active[-1] if active else None

    def _build_order(
        self, batch_id: int, mapping_id: int, *, confirmed: bool
    ) -> tuple[dict[str, Any] | None, str]:
        batch = self._verified_batch(batch_id)
        if batch is None:
            return None, "样本批次不存在或尚未核验，不能核发假名交付单"

        mapping = store.find("pseudonym", mapping_id)
        if mapping is None:
            return None, f"假名映射 {mapping_id} 不存在"
        # 已失效且未经确认的映射不得继续生成新的交付文件；已轮换映射同样拦截。
        if mapping.get("status") == "已失效":
            return None, "该映射已失效，禁止基于失效映射核发新交付，请改用当前有效映射"
        if mapping.get("status") == "已轮换":
            latest = self._latest_active_in_chain(int(mapping.get("版本链ID") or mapping_id))
            hint = f"，请改用最新有效映射 {latest['映射编号']}" if latest else ""
            return None, f"该映射已轮换并冻结{hint}，历史交付仍可追溯但不能混用旧版"
        if mapping.get("status") != "有效":
            return None, f"映射当前状态为「{mapping.get('status')}」，不满足交付条件"

        rows = store.rows(self.MODULE)
        order: dict[str, Any] = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "交付单编号": f"DELI-{_today_compact()}-{max((int(row.get('id', 0)) for row in rows), default=0) + 1:04d}",
            "样本批次ID": batch["id"],
            "样本批次编号": batch["批次编号"],
            "样本批次名称": batch["批次名称"],
            "映射快照": self._snapshot(mapping),
            "交付状态": ORDER_CONFIRMED if confirmed else ORDER_DRAFT,
            "文件状态": FILE_PENDING if confirmed else "未排队",
            "文件名": None,
            "水印编号": None,
            "提交时间": _now(),
            "确认时间": _now() if confirmed else None,
            "交付时间": None,
        }
        rows.append(order)
        if confirmed:
            return order, "交付单已按第 %d 版映射确认，文件任务排队待生成" % mapping.get("映射代次", 1)
        return order, "已打开交付确认页（草稿），尚未核发交付文件"

    # ------------------------------------------------------------------
    # 后台文件任务
    # ------------------------------------------------------------------
    def enqueue_generation(self, order_id: int) -> tuple[dict[str, Any] | None, str]:
        with self._lock:
            order = store.find(self.MODULE, order_id)
            if order is None:
                return None, f"交付单 {order_id} 不存在或已归档"
            if order["交付状态"] != ORDER_CONFIRMED:
                return None, "只有已确认交付单可以启动文件生成"
            if order["文件状态"] in (FILE_GENERATING, FILE_READY):
                return self._decorate(order), "文件任务已在处理流程中"
            order["文件状态"] = FILE_GENERATING
            order["排队时间"] = _now()

        thread = threading.Thread(
            target=self._generate_in_background, args=(order_id,), daemon=True)
        thread.start()
        with self._lock:
            return self._decorate(store.find(self.MODULE, order_id)), "后台文件任务已启动"

    def _generate_in_background(self, order_id: int) -> None:
        # 模拟后台生成耗时；期间映射即使轮换，也只读取确认时冻结的快照。
        timer = threading.Event()
        timer.wait(timeout=GENERATION_DELAY_SECONDS)
        with self._lock:
            order = store.find(self.MODULE, order_id)
            if order is None or order["文件状态"] != FILE_GENERATING:
                return
            payload = self._render_file(order)
            filename = f"{order['交付单编号']}_pseudonym.csv"
            self._files[order_id] = payload

            watermark = self._write_watermark(order, payload)
            order["文件名"] = filename
            order["水印编号"] = watermark["水印编号"]
            order["水印ID"] = watermark["id"]
            order["文件状态"] = FILE_READY
            order["交付状态"] = ORDER_DELIVERED
            order["交付时间"] = _now()

    def _render_file(self, order: dict[str, Any]) -> bytes:
        snapshot = order["映射快照"]
        batch = store.find(self.BATCH_MODULE, int(order["样本批次ID"]))
        sample_count = int(batch.get("样本数量", 0) if batch else 0)
        fingerprint = hashlib.sha256(
            f"{order['交付单编号']}|{snapshot['映射编号']}|{snapshot['盐值哈希']}".encode("utf-8")
        ).hexdigest()[:16]

        output = io.StringIO()
        output.write("﻿")
        writer = csv.writer(output, lineterminator="\n")
        # 水印头：检测端据此找到准确的交付版本。
        writer.writerow([
            f"# 水印指纹={fingerprint}",
            f"交付单={order['交付单编号']}",
            f"样本批次={order['样本批次编号']}",
            f"映射版本=第{snapshot['映射代次']}版({snapshot['映射编号']})",
            f"盐值={snapshot['盐值哈希']}",
        ])
        writer.writerow(["序号", "原始标识", "假名标识", "映射算法", "来源批次", "水印指纹"])
        preview_rows = min(sample_count, 20)
        for index in range(1, preview_rows + 1):
            raw = f"{snapshot['原始标识']}_row{index:04d}"
            pseudo = hashlib.sha256(
                f"{raw}|{snapshot['盐值哈希']}".encode("utf-8")).hexdigest()[:16]
            writer.writerow([
                index, raw, f"{snapshot['假名标识'].split(':')[0]}:{pseudo}",
                snapshot["映射算法"], order["样本批次编号"], fingerprint,
            ])
        return output.getvalue().encode("utf-8")

    def _write_watermark(self, order: dict[str, Any], payload: bytes) -> dict[str, Any]:
        rows = store.rows(self.WATERMARK_MODULE)
        snapshot = order["映射快照"]
        fingerprint = hashlib.sha256(
            f"{order['交付单编号']}|{snapshot['映射编号']}|{snapshot['盐值哈希']}".encode("utf-8")
        ).hexdigest()[:16]
        watermark: dict[str, Any] = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "status": "已嵌入",
            "pending": True,
            "abnormal": False,
            "水印编号": f"WATE-DEL-{order['id']:04d}",
            "目标数据集": f"假名交付文件 {order['文件名']}",
            "水印算法": "交付指纹水印(SHA256)",
            "嵌入强度": "中",
            "可检测性": "0.99",
            "鲁棒性评分": "0.90",
            "嵌入时间": _now(),
            "检测结果": "待检测",
            # 溯源锚点：水印详情据此找到交付版本与批次。
            "交付单ID": order["id"],
            "交付单编号": order["交付单编号"],
            "样本批次ID": order["样本批次ID"],
            "样本批次编号": order["样本批次编号"],
            "映射版本": snapshot["映射版本"],
            "映射代次": snapshot["映射代次"],
            "映射编号": snapshot["映射编号"],
            "版本链ID": snapshot["版本链ID"],
            "水印指纹": fingerprint,
            "文件字节数": len(payload),
        }
        rows.append(watermark)
        return watermark

    def download_file(self, order_id: int) -> tuple[bytes, str] | None:
        with self._lock:
            order = store.find(self.MODULE, order_id)
            if order is None:
                return None
            if order["文件状态"] != FILE_READY or order_id not in self._files:
                return None
            return self._files[order_id], order["文件名"]

    # ------------------------------------------------------------------
    # 水印溯源
    # ------------------------------------------------------------------
    def list_traces(self) -> list[dict[str, Any]]:
        rows = store.rows(self.WATERMARK_MODULE)
        return [dict(row) for row in rows if row.get("交付单ID")]

    def get_trace(self, watermark_id: int) -> dict[str, Any] | None:
        row = store.find(self.WATERMARK_MODULE, watermark_id)
        if row is None or not row.get("交付单ID"):
            return None
        trace = dict(row)
        order = store.find(self.MODULE, int(row["交付单ID"]))
        if order is not None:
            trace["交付单详情"] = {
                "交付单编号": order["交付单编号"],
                "样本批次编号": order["样本批次编号"],
                "样本批次名称": order["样本批次名称"],
                "文件名": order["文件名"],
                "交付时间": order["交付时间"],
                "文件状态": order["文件状态"],
                "映射快照": order["映射快照"],
            }
        return trace


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today_compact() -> str:
    return datetime.now().strftime("%Y%m%d")
