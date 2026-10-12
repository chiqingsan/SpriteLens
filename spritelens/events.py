"""中立事件与值对象：协议层产出的统一事件类型（无 IO、无依赖）。

PacketEvent 原定义在 services.monitor_service 中，domain 的五个事件
提取模块运行时反向导入它，形成 domain→services 依赖环（审查 R 边界
偏差）。移到本叶子模块后：protocol/domain/services 任何层都可以依赖
它，而不产生层间反向引用。

过渡期 services.monitor_service 从此处重导出（兼容旧调用方），全部
调用方迁移完成后移除重导出——删除条件见 ROADMAP 阶段1。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PacketEvent:
    """协议层产出的统一事件：功能层与 UI 的唯一消费类型。"""

    ts: float
    session_id: str
    direction: str
    opcode: int
    opcode_name: str
    payload_len: int
    decoded: list[dict]
    resumed_identity: tuple[int, str, int] | None = None


__all__ = ["PacketEvent"]
