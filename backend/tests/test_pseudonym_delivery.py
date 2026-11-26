"""假名交付确认领域测试：版本冻结、在途冲突、拦截规则与水印溯源。

运行：cd backend && python3 -m pytest tests/test_pseudonym_delivery.py -v
"""
from __future__ import annotations

import time

import pytest

from app.services import pseudonym_delivery as delivery_module
from app.services.pseudonym import PseudonymService
from app.services.pseudonym_delivery import (
    FILE_GENERATING,
    FILE_PENDING,
    FILE_READY,
    ORDER_CONFIRMED,
    ORDER_DELIVERED,
    ORDER_DRAFT,
    PseudonymDeliveryService,
)
from app.store import store


@pytest.fixture(autouse=True)
def fast_generation(monkeypatch):
    """把后台文件生成等待压到测试可接受范围。"""
    monkeypatch.setattr(delivery_module, "GENERATION_DELAY_SECONDS", 0.05)


@pytest.fixture
def services():
    return PseudonymDeliveryService(), PseudonymService()


def _active_mapping(pseudo: PseudonymService) -> dict:
    rows = [r for r in store.rows("pseudonym") if r.get("status") == "有效"]
    assert rows, "种子数据应至少有一条有效映射"
    return rows[0]


def _wait_ready(svc: PseudonymDeliveryService, order_id: int, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        order = svc.get_order(order_id)
        if order["文件状态"] == FILE_READY:
            return order
        time.sleep(0.05)
    raise AssertionError(f"交付单 {order_id} 文件任务未在 {timeout}s 内完成")


class TestDeliveryGuardrails:
    def test_unverified_batch_rejected(self, services):
        svc, _ = services
        mapping = _active_mapping(PseudonymService())
        order, message = svc.confirm_order(3, mapping["id"])  # PSEU-B03 待核验
        assert order is None
        assert "尚未核验" in message

    def test_expired_mapping_rejected(self, services):
        svc, _ = services
        order, message = svc.confirm_order(1, 2)  # PSEU-0002 已失效
        assert order is None
        assert "已失效" in message

    def test_rotated_mapping_rejected(self, services):
        svc, _ = services
        order, message = svc.confirm_order(1, 4)  # PSEU-0001-v2 已轮换
        assert order is None
        assert "已轮换" in message
        assert "历史交付仍可追溯" in message

    def test_prepare_creates_draft_without_file(self, services):
        svc, pseudo = services
        mapping = _active_mapping(pseudo)
        order, message = svc.prepare_order(1, mapping["id"])
        assert order is not None
        assert order["交付状态"] == ORDER_DRAFT
        assert order["文件状态"] == "未排队"
        assert svc.download_file(order["id"]) is None
        assert "草稿" in message


class TestVersionFreezing:
    def test_confirm_freezes_snapshot(self, services):
        svc, pseudo = services
        mapping = _active_mapping(pseudo)
        order, _ = svc.confirm_order(1, mapping["id"])
        assert order["交付状态"] == ORDER_CONFIRMED
        assert order["文件状态"] == FILE_PENDING
        snapshot = order["映射快照"]
        assert snapshot["映射ID"] == mapping["id"]
        assert snapshot["映射代次"] == mapping["映射代次"]
        assert snapshot["盐值哈希"] == mapping["盐值哈希"]

    def test_inflight_order_keeps_confirmed_version_after_rotation(self, services):
        svc, pseudo = services
        mapping = _active_mapping(pseudo)
        confirmed_gen = mapping["映射代次"]
        order, _ = svc.confirm_order(2, mapping["id"])
        order_id = order["id"]

        queued, _ = svc.enqueue_generation(order_id)
        assert queued["文件状态"] == FILE_GENERATING

        # 在途期间轮换映射；旧映射冻结、新版本生效。
        new_mapping, rotate_msg = pseudo.run_action(mapping["id"], "轮换映射")
        assert new_mapping["映射编号"].endswith(f"-v{confirmed_gen + 1}")
        assert "-v" not in new_mapping["映射编号"].rsplit("-v", 1)[0]
        assert "已轮换" in rotate_msg

        view = svc.get_order(order_id)
        assert view["版本冲突"] is True
        assert view["当前映射代次"] == confirmed_gen + 1
        assert "继续沿用已确认的第 %d 版" % confirmed_gen in view["冲突处置"]
        # 在途任务不能被重新提交或再次排队
        again, _ = svc.resubmit_order(order_id)
        assert again is None

        finished = _wait_ready(svc, order_id)
        assert finished["交付状态"] == ORDER_DELIVERED
        assert finished["映射快照"]["映射代次"] == confirmed_gen  # 文件仍是确认时的版本
        assert finished["当前映射代次"] == confirmed_gen + 1

        download = svc.download_file(order_id)
        assert download is not None
        payload, filename = download
        text = payload.decode("utf-8")
        assert f"映射版本=第{confirmed_gen}版" in text
        assert f"交付单={finished['交付单编号']}" in text
        assert filename == finished["文件名"]

    def test_delivered_file_remains_traceable_after_further_rotation(self, services):
        svc, pseudo = services
        mapping = _active_mapping(pseudo)
        order, _ = svc.confirm_order(1, mapping["id"])
        order_id = order["id"]
        svc.enqueue_generation(order_id)
        finished = _wait_ready(svc, order_id)

        # 再次轮换后，老交付仍可下载、冲突处置转为历史留档。
        active = _active_mapping(pseudo)
        pseudo.run_action(active["id"], "轮换映射")
        view = svc.get_order(order_id)
        assert view["交付状态"] == ORDER_DELIVERED
        assert svc.download_file(order_id) is not None
        assert "历史交付" in view["冲突处置"]
        assert finished["水印ID"] is not None


class TestDraftControlRequest:
    def test_draft_confirm_blocked_after_rotation_then_resubmit(self, services):
        svc, pseudo = services
        mapping = _active_mapping(pseudo)
        draft, _ = svc.prepare_order(1, mapping["id"])
        draft_id = draft["id"]

        # 仅打开未确认；随后映射轮换。
        pseudo.run_action(mapping["id"], "轮换映射")
        blocked, message = svc.confirm_draft(draft_id)
        assert blocked is None
        assert "重新提交" in message

        view = svc.get_order(draft_id)
        assert view["版本冲突"] is True
        assert "需重新提交" in view["冲突处置"]

        resubmitted, msg = svc.resubmit_order(draft_id)
        assert resubmitted is not None
        active = _active_mapping(pseudo)
        assert resubmitted["映射快照"]["映射ID"] == active["id"]
        assert resubmitted["版本冲突"] is False

        confirmed, _ = svc.confirm_draft(draft_id)
        assert confirmed["交付状态"] == ORDER_CONFIRMED
        svc.enqueue_generation(draft_id)
        finished = _wait_ready(svc, draft_id)
        assert finished["文件状态"] == FILE_READY
        assert svc.download_file(draft_id) is not None


class TestWatermarkTrace:
    def test_trace_links_batch_and_pinned_version(self, services):
        svc, pseudo = services
        mapping = _active_mapping(pseudo)
        order, _ = svc.confirm_order(2, mapping["id"])  # PSEU-B02
        order_id = order["id"]
        svc.enqueue_generation(order_id)
        finished = _wait_ready(svc, order_id)

        traces = svc.list_traces()
        assert any(t["交付单ID"] == order_id for t in traces)

        trace = svc.get_trace(finished["水印ID"])
        assert trace["样本批次编号"] == "PSEU-B02"
        assert trace["映射代次"] == mapping["映射代次"]
        assert trace["映射编号"] == mapping["映射编号"]
        assert trace["交付单详情"]["文件名"] == finished["文件名"]
        assert trace["交付单详情"]["样本批次名称"] == "风控建模样本-2026Q4"
        assert trace["水印指纹"]

    def test_trace_unknown_watermark_returns_none(self, services):
        svc, _ = services
        assert svc.get_trace(999999) is None
        # 种子水印（非交付产生）也没有溯源信息
        assert svc.get_trace(1) is None
