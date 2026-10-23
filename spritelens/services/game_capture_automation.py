"""游戏进程触发的后台采集设置与任务计划程序编排。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from spritelens.repositories.settings import SettingsRepository
from spritelens.logs import get_logger
from spritelens.system.game_process import (
    GAME_PROCESS_AUDIT_GUIDANCE,
    GAME_TASK_NAME,
    DEFAULT_GAME_PROCESS_NAME,
    install_game_trigger,
    remove_game_trigger,
)

GAME_AUTOMATION_SETTING_KEY = "capture.game_automation"
logger = get_logger("game_capture_automation")


def _normalize(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    return {"enabled": raw.get("enabled") is True, "process_name": DEFAULT_GAME_PROCESS_NAME}


class GameCaptureAutomation:
    """配置与系统任务的唯一写入者。"""

    def __init__(
        self,
        settings: SettingsRepository,
        *,
        install: Callable[[str], None] = install_game_trigger,
        remove: Callable[[], None] = remove_game_trigger,
    ) -> None:
        self._settings = settings
        self._install = install
        self._remove = remove

    def snapshot(self) -> dict[str, Any]:
        value = _normalize(self._settings.get_value(GAME_AUTOMATION_SETTING_KEY, {}))
        return {
            **value,
            "task_name": GAME_TASK_NAME,
            "audit_guidance": GAME_PROCESS_AUDIT_GUIDANCE,
        }

    def configure(self, *, enabled: bool) -> dict[str, Any]:
        if type(enabled) is not bool:
            raise ValueError("字段 enabled 必须是布尔值")
        previous = _normalize(self._settings.get_value(GAME_AUTOMATION_SETTING_KEY, {}))
        next_value = {"enabled": enabled}

        if enabled:
            self._install(DEFAULT_GAME_PROCESS_NAME)
        else:
            self._remove()
        try:
            self._settings.set_checked(GAME_AUTOMATION_SETTING_KEY, next_value)
        except Exception:
            # 配置写失败时尽量恢复任务与原配置的对应关系；原始异常继续上抛。
            try:
                if previous["enabled"]:
                    self._install(DEFAULT_GAME_PROCESS_NAME)
                else:
                    self._remove()
            except Exception as rollback_error:  # 回滚失败不能覆盖原始保存错误，但必须留痕
                logger.warning("自动监听任务回滚失败：%s", rollback_error)
            raise
        return self.snapshot()


__all__ = ["GAME_AUTOMATION_SETTING_KEY", "GameCaptureAutomation"]
