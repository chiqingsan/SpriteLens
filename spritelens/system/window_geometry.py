"""初始窗口尺寸适配：工作区 + 系统 DPI 缩放（对标同类产品的 window_geometry）。

小屏笔记本若直接用固定 1440×900 开窗，会溢出工作区（任务栏遮挡/超出屏幕）。
规则：默认尺寸按 DPI 缩放后 clamp 到工作区 90% 以内，且不低于最小尺寸。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes

from spritelens.logs import get_logger

logger = get_logger("window_geometry")

DEFAULT_W, DEFAULT_H = 1280, 720
MIN_W, MIN_H = 640, 360
_WORKAREA_RATIO = 0.9
_SPI_GETWORKAREA = 0x0030
_FALLBACK_WORK = (1920, 1040)  # 取不到工作区时的合理兜底（1080p 常见值）
_FALLBACK_DPI = 96


def work_area() -> tuple[int, int]:
    """主显示器工作区（去掉任务栏），宽高像素。"""
    try:
        rect = wintypes.RECT()
        if ctypes.windll.user32.SystemParametersInfoW(_SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
            return max(1, rect.right - rect.left), max(1, rect.bottom - rect.top)
    except Exception as exc:  # noqa: BLE001 - 非 Windows/异常时用兜底
        logger.debug("取工作区失败: %s", exc)
    return _FALLBACK_WORK


def system_dpi() -> int:
    """系统 DPI（96 = 100% 缩放）。"""
    try:
        if hasattr(ctypes.windll.user32, "GetDpiForSystem"):
            return int(ctypes.windll.user32.GetDpiForSystem()) or _FALLBACK_DPI
    except Exception as exc:  # noqa: BLE001
        logger.debug("取系统 DPI 失败: %s", exc)
    return _FALLBACK_DPI


def fit_window(work_width: int, work_height: int, dpi: int) -> tuple[int, int]:
    """按 DPI 与工作区计算初始窗口尺寸（纯函数，便于测试）。"""
    scale = dpi / 96.0
    width = min(DEFAULT_W * scale, work_width * _WORKAREA_RATIO)
    height = min(DEFAULT_H * scale, work_height * _WORKAREA_RATIO)
    width = max(width, min(MIN_W * scale, work_width))
    height = max(height, min(MIN_H * scale, work_height))
    return int(width), int(height)


def initial_window_size() -> tuple[int, int]:
    """开壳用的初始尺寸。"""
    width, height = fit_window(*work_area(), system_dpi())
    logger.info("初始窗口尺寸: %dx%d（工作区 %s，DPI %d）", width, height, work_area(), system_dpi())
    return width, height


__all__ = ["fit_window", "initial_window_size", "system_dpi", "work_area"]
