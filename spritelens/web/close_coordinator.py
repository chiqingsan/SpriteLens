"""桌面退出握手：窗口保持存活，直到页面保存和业务缓存落盘完成。"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from spritelens.logs import get_logger

logger = get_logger("close_coordinator")


class CloseCoordinator:
    def __init__(self, window, context, *, save_timeout: float = 15.0,
                 get_geometry: Callable[[], dict[str, int]] | None = None) -> None:
        self._window = window
        self._context = context
        self._lock = threading.Lock()
        self._saving = False
        self._approved = False
        self._abandoned = False
        self._save_timeout = save_timeout
        self._get_geometry = get_geometry
        self._page_thread: threading.Thread | None = None
        self._recovery_thread: threading.Thread | None = None
        self._recovery_error: Exception | None = None
        self._storage_done = threading.Event()
        self._storage_thread: threading.Thread | None = None
        self._storage_error: Exception | None = None

    @property
    def abandoned(self) -> bool:
        return self._abandoned

    def _flush_storage(self) -> None:
        try:
            self._context.capture_vm.stop()
            for store in (self._context.pet_store, self._context.egg_store, self._context.home_store):
                if store is not None:
                    store.flush()
            if self._context.event_log is not None:
                self._context.event_log.flush()
            if self._get_geometry is not None:
                self._context.settings.set_window_geometry(**self._get_geometry(), maximized=False)
        except Exception as exc:
            self._storage_error = exc
        finally:
            self._storage_done.set()

    def _wait_for_storage(self) -> None:
        # 超时不取消正在使用数据库的线程；重试先等它完成，禁止创建并发保存者。
        deadline = time.monotonic() + self._save_timeout
        if self._storage_thread is not None and not self._storage_done.wait(self._save_timeout):
            raise TimeoutError("上次退出保存仍在等待存储，请稍后重试")
        self._storage_done.clear()
        self._storage_error = None
        self._storage_thread = threading.Thread(
            target=self._flush_storage, name="spritelens-exit-storage", daemon=True,
        )
        self._storage_thread.start()
        if not self._storage_done.wait(max(0.0, deadline - time.monotonic())):
            raise TimeoutError("退出保存等待存储超时；未保存内容仍保留在内存中")
        if self._storage_error is not None:
            raise self._storage_error

    def _wait_for_page(self) -> None:
        deadline = time.monotonic() + self._save_timeout
        # 恢复命令必须先结束，避免上次取消在本次保存期间解除 inert。
        for thread in (self._recovery_thread, self._page_thread):
            if thread is not None:
                thread.join(max(0.0, deadline - time.monotonic()))
                if thread.is_alive():
                    raise TimeoutError("上次页面调用尚未完成，请稍后重试")
        if self._recovery_error is not None:
            raise self._recovery_error
        done = threading.Event()
        result = {}
        errors: list[Exception] = []

        def received(value) -> None:
            result.update(value)
            done.set()

        def dispatch() -> None:
            try:
                self._window.evaluate_js(
                    "window.SpriteLensPrepareClose ? window.SpriteLensPrepareClose() : Promise.resolve({ok:true})",
                    callback=received,
                )
            except Exception as exc:
                errors.append(exc)
                done.set()

        # WebView2 evaluate_js 自身也可能阻塞；必须和异步确认共用等待预算。
        self._page_thread = threading.Thread(target=dispatch, name="spritelens-exit-page", daemon=True)
        self._page_thread.start()
        self._page_thread.join(max(0.0, deadline - time.monotonic()))
        if self._page_thread.is_alive() or not done.wait(max(0.0, deadline - time.monotonic())):
            raise TimeoutError("页面保存超时；请重试")
        if errors:
            raise errors[0]
        if not result.get("ok"):
            raise OSError(result.get("error", "页面草稿保存失败"))

    def _restore_page(self) -> None:
        if self._recovery_thread is not None and self._recovery_thread.is_alive():
            return
        page_thread = self._page_thread
        self._recovery_error = None

        def restore() -> None:
            # 不能取消 WebView2 的同步调用；等它返回后再恢复，禁止并发派发。
            if page_thread is not None:
                page_thread.join()
            try:
                self._window.evaluate_js("window.SpriteLensCancelClose && window.SpriteLensCancelClose()")
            except Exception as exc:
                self._recovery_error = exc
                logger.warning("取消退出后恢复页面失败: %s", exc)

        self._recovery_thread = threading.Thread(target=restore, name="spritelens-exit-restore", daemon=True)
        self._recovery_thread.start()

    def request_close(self) -> bool:
        """closing 在 GUI 线程调用；立即取消本次关闭，由后台握手后重新关闭。"""
        with self._lock:
            if self._approved:
                return True
            if not self._saving:
                self._saving = True
                threading.Thread(target=self._prepare, name="spritelens-save-before-close").start()
        return False

    def _prepare(self) -> None:
        try:
            if self._window.events.loaded.is_set():
                self._wait_for_page()
            # 页面仍在、HTTP 服务仍在；先确认所有持久化写入再销毁窗口。
            self._wait_for_storage()
        except Exception as exc:
            logger.warning("退出前保存失败，窗口保留: %s", exc)
            abandon = self._window.create_confirmation_dialog(
                "退出前保存失败",
                f"{exc}\n\n确定：放弃未保存内容并退出。\n取消：保留窗口，处理问题后重新关闭以重试。",
            )
            if not abandon:
                self._restore_page()
                with self._lock:
                    self._saving = False
                return
            self._abandoned = True
        with self._lock:
            self._approved = True
        self._window.destroy()


__all__ = ["CloseCoordinator"]
