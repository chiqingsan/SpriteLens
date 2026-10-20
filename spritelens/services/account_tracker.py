"""账号切换检测：把「身份事件 → 当前账号」的判定收敛到一处。

历史教训（审查复现）：切号只更新 uid、不清快照，B 登录后界面里 A/B
数据混合，孵化槽帧还会把 A 的蛋写进 B 的库记录。各聚合器统一的处理是：
observe() 报告「真切换」时清空自己持有的账号数据。

两个不能误清的衔接场景：
- 同账号重发身份帧（进出场景会反复收到 ZoneEnterSceneRsp）；
- 启动时离线载入的数据与首个身份同账号（note_loaded 记录归属）。

线程安全由调用方在自己的锁内使用。
"""

from __future__ import annotations

from spritelens.domain.identity import PlayerIdentity


class AccountTracker:
    """当前账号与切换判定。"""

    def __init__(self) -> None:
        self._identity: PlayerIdentity | None = None
        self._loaded_uid: int | None = None

    @property
    def identity(self) -> PlayerIdentity | None:
        return self._identity

    @property
    def uid(self) -> int:
        """当前账号 uid；尚未识别身份时为 0。"""
        return self._identity.uid if self._identity is not None else 0

    @property
    def display_uid(self) -> int:
        """内存数据归属；离线加载不代表实时身份，写路径仍使用 uid。"""
        return self.uid or self._loaded_uid or 0

    def note_loaded(self, uid: int) -> None:
        """记录离线载入的内存数据属于哪个账号（该账号登录不算切换）。"""
        if uid > 0:
            self._loaded_uid = uid

    def select_loaded(self, uid: int) -> None:
        """切换到指定历史账号，等待后续身份包恢复实时状态。"""
        if uid <= 0:
            raise ValueError("账号 uid 无效")
        self._identity = None
        self._loaded_uid = uid

    def observe(self, identity: PlayerIdentity) -> bool:
        """观察一条身份信息；返回 True 表示账号发生切换（须清空旧快照）。"""
        previous = self._identity
        self._identity = identity
        if previous is not None:
            return previous.uid != identity.uid
        # 首次身份到达：与离线载入数据同账号（或没有离线数据）时不算切换
        return self._loaded_uid is not None and self._loaded_uid != identity.uid


__all__ = ["AccountTracker"]
