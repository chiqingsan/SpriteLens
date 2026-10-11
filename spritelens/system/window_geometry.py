"""初始窗口尺寸适配：工作区 + 系统 DPI 缩放（对标同类产品的 window_geometry）。

小屏笔记本若直接用固定 1440×900 开窗，会溢出工作区（任务栏遮挡/超出屏幕）。
规则：默认尺寸按 DPI 缩放后 clamp 到工作区 90% 以内，且不低于最小尺寸。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes

from spritelens.logs import get_logger

logger = get_logger("window_geometry")

# 上限写死 1440x810（蛋神同款：高分屏窗口物理尺寸随 DPI 自然放大，逻辑不超）
MAX_W, MAX_H = 1440, 810
_MIN_W, _MIN_H = 640, 360
_EDGE = 32  # 工作区边距
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
    """按 DPI 与工作区计算初始窗口尺寸（蛋神同款公式，纯函数便于测试）。

    work_* 为物理像素：先除以 DPI 缩放转逻辑像素（pywebview 的 width 参数
    即逻辑像素），再减去屏幕边距，上限 1440x810。此前把 DPI 当乘数放大
    尺寸是错误实现（150% 屏上窗口物理尺寸超屏，用户实测"过大"的根因）。
    """
    scale = max(1.0, dpi / 96.0)
    logical_w = work_width / scale
    logical_h = work_height / scale
    width = max(1, min(MAX_W, int(logical_w) - _EDGE))
    height = max(1, min(MAX_H, int(logical_h) - _EDGE))
    return width, height


def initial_window_size() -> tuple[int, int]:
    """开壳用的初始尺寸。"""
    work = work_area()
    dpi = system_dpi()
    width, height = fit_window(*work, dpi)
    logger.info("初始窗口尺寸: %dx%d（工作区 %s，DPI %d）", width, height, work, dpi)
    return width, height


__all__ = ["fit_window", "initial_window_size", "system_dpi", "work_area"]
