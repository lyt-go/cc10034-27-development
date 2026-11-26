"""假名化领域服务：字段、状态和动作来自业务配置，并扩展映射轮换版本链。

轮换语义：
- 同一「版本链ID」上的映射共享原始标识，轮换一次产生一条新映射，
  映射版本/代次递增，旧映射置为「已轮换」并冻结其假名与盐值。
- 交付确认只允许使用当前「有效」的最新映射；已失效/已轮换的映射
  不得再核发新交付，但历史交付单仍按确认时冻结的快照保留可追溯性。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class PseudonymService(BaseModuleService):
    MODULE = "pseudonym"
    ENTITY = "假名映射"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["映射编号", "原始标识", "假名标识", "映射算法", "可逆标记", "盐值哈希", "创建时间", "失效时间"]
    REQUIRED_FIELDS = ["映射编号", "原始标识", "假名标识"]
    STATUS_ORDER = ["有效", "已失效", "已轮换"]
    ACTION_RULES = {"标记失效": "已失效", "轮换映射": "已轮换"}
    NEGATIVE_ACTIONS = []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None, f"{self.ENTITY} {entry_id} 不存在或已归档"
        if action not in self.ACTION_RULES:
            return None, f"动作「{action}」不属于{self.MODULE}可执行范围"

        if action == "标记失效":
            entry["status"] = "已失效"
            entry["pending"] = True
            entry["abnormal"] = True
            return entry, f"{self.ENTITY}已标记失效，未确认的新交付将被拦截"

        if action == "轮换映射":
            return self._rotate(entry)

        return None, f"动作「{action}」不属于{self.MODULE}可执行范围"

    def _rotate(self, entry: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """在同一版本链上生成下一代映射，旧映射置为已轮换。"""
        rows = store.rows(self.MODULE)
        chain_id = int(entry.get("版本链ID") or entry["id"])
        chain = [row for row in rows if int(row.get("版本链ID") or row["id"]) == chain_id]
        if entry.get("status") == "已轮换":
            return None, "该映射已经轮换，请使用版本链上的最新有效映射"
        if entry.get("status") == "已失效":
            return None, "已失效映射不能直接轮换，请先恢复或新建映射"

        next_gen = max(int(row.get("映射代次", 1)) for row in chain) + 1
        today = date.today().isoformat()
        base_code = entry["映射编号"].rsplit("-v", 1)[0] if "-v" in entry["映射编号"] else entry["映射编号"]
        new_entry: dict[str, Any] = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "status": "有效",
            "pending": True,
            "abnormal": False,
            "映射编号": f"{base_code}-v{next_gen}",
            "原始标识": entry["原始标识"],
            "假名标识": f"hash:rot{next_gen}:{abs(hash((chain_id, next_gen))) % 10**12:012x}",
            "映射算法": entry["映射算法"],
            "可逆标记": entry["可逆标记"],
            "盐值哈希": f"salt_v{next_gen}_{today[:4]}Q{(int(today[5:7]) - 1) // 3 + 1}",
            "创建时间": today,
            "失效时间": f"{int(today[:4]) + 1}-{today[5:]}",
            "映射版本": next_gen,
            "映射代次": next_gen,
            "版本链ID": chain_id,
            "上一版映射ID": entry["id"],
        }
        rows.append(new_entry)

        entry["status"] = "已轮换"
        entry["pending"] = False
        entry["abnormal"] = False
        return new_entry, f"已轮换生成第 {next_gen} 版映射 {new_entry['映射编号']}，旧版冻结保留"

    def active_mapping(self, mapping_id: int) -> dict[str, Any] | None:
        """返回映射当前可用记录；仅「有效」状态允许核发新交付。"""
        entry = store.find(self.MODULE, mapping_id)
        if entry is None or entry.get("status") != "有效":
            return None
        return entry

    def chain_snapshot(self, chain_id: int) -> list[dict[str, Any]]:
        rows = store.rows(self.MODULE)
        chain = [row for row in rows if int(row.get("版本链ID") or row["id"]) == chain_id]
        return sorted(chain, key=lambda row: int(row.get("映射代次", 1)))
