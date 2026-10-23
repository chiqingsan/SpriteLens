"""Web 界面入口：pywebview 窗口（系统 WebView2）+ 本地服务。

与竞品（蛋神助手）同型：单进程、原生窗口壳、内容为本地 Web 页面。
窗口只负责开壳——数据、命令与推送全部走 `LocalServer`。

失败降级：系统缺 WebView2 时 `webview.start()` 抛错，这里提示用户安装
（Win10/11 一般预装；缺失时可从微软官网装 Evergreen Runtime）。
"""

from __future__ import annotations

import os
import threading
import webbrowser
from types import SimpleNamespace

import spritelens
from spritelens.app_context import build_app_context
from spritelens.logs import get_logger, setup_logger
from spritelens.paths import logs_dir, project_root
from spritelens.paths import config_path
from spritelens.repositories.settings import SettingsRepository
from spritelens.system.runtime_session import read_runtime
from spritelens.system.single_instance import (
    UI_ACTIVATION_EVENT_NAME,
    UI_MUTEX_NAME,
    SingleInstanceGuard,
)

logger = get_logger("web_run")

WINDOW_TITLE = f"{spritelens.APP_DISPLAY_NAME} {spritelens.APP_NAME}"
WEBVIEW2_HINT = (
    "无法创建 WebView2 窗口：系统可能缺少 WebView2 运行时。\n"
    "请安装 Microsoft Edge WebView2 Runtime 后重试：\n"
    "https://developer.microsoft.com/microsoft-edge/webview2/"
)
# 与 index.html 内联启动遮罩的默认 --bg 保持一致。
SPLASH_BG = "#f6f6ed"


def run_web(*, open_browser: bool = False, ui_only: bool = False) -> int:
    """启动 Web 界面；返回进程退出码。

    资源保护（D07）：guard 获取后所有步骤（WebView2 预检、装配、
    server 构造与启动、等待/窗口）都在统一 finally 覆盖内；任一步失败
    时，已创建的部分资源（context/server）随 finally 清理，guard 一定
    释放。支持只创建部分资源的退出。唯一例外是用户明确放弃保存：
    直接终止进程，由 OS 回收句柄，避免解释器等待阻塞的请求线程。
    """
    try:
        log_directory = logs_dir()
        setup_logger(log_directory)
    except OSError as exc:
        _fatal("用户数据目录初始化失败", str(exc))
        return 1
    _enable_dpi_awareness()
    _set_app_user_model_id()

    if ui_only:
        return _run_remote_ui()

    guard = SingleInstanceGuard()
    if not guard.acquire():
        if read_runtime() is not None:
            notified = guard.notify_existing()
            logger.info("检测到后台采集实例，已请求打开主界面=%s", notified)
            return 0
        notified = guard.notify_existing()
        logger.info("检测到已有实例在运行（唤醒已有窗口=%s），本次启动退出", notified)
        return 0

    context = None
    server = None
    exit_code = 0
    abandoned = False
    try:
        # 开壳前预检测 WebView2：缺失时弹原生对话框引导安装，避免白屏式失败
        from spritelens.system.webview_guard import ensure_webview2

        if not ensure_webview2(log_directory):
            logger.warning("WebView2 不可用，已按用户选择退出")
            exit_code = 1
        else:
            try:
                context = build_app_context()
            except Exception as exc:  # noqa: BLE001 - 装配失败给出可读提示
                logger.exception("应用初始化失败")
                _fatal("应用初始化失败", f"{exc}\n\n日志目录：{log_directory}")
                exit_code = 1

            if exit_code == 0:
                server = LocalServer(context)
                try:
                    server.start()
                except Exception as exc:  # noqa: BLE001 - 端口/绑定失败直接给出可读提示
                    logger.exception("本地服务启动失败")
                    _fatal("本地服务启动失败", f"{exc}\n\n日志目录：{log_directory}")
                    exit_code = 1

            if exit_code == 0:
                logger.info("Web 界面入口: %s", f"http://{server.host}:{server.port}/")
                if open_browser:
                    # 调试模式：用系统浏览器打开，便于 DevTools（pywebview 也可开，但外置更省事）
                    webbrowser.open(server.url)
                    _wait_until_interrupted(server)
                else:
                    try:
                        if _run_window(server, guard) is False:
                            abandoned = True
                            exit_code = 1
                    except Exception as exc:  # noqa: BLE001 - WebView2 缺失等环境问题
                        logger.error("窗口创建失败: %s", exc)
                        _fatal("窗口创建失败", f"{WEBVIEW2_HINT}\n\n原始错误：{exc}\n日志目录：{log_directory}")
                        exit_code = 1
    finally:
        if abandoned:
            # 仅用于用户明确放弃。解释器退出还会 join to_thread 的线程池，
            # 即使跳过 context.close 也可能卡住；由 OS 回收窗口、锁与句柄。
            os._exit(1)
        elif not _shutdown(server, context, guard):
            exit_code = 1
    return exit_code


def _run_remote_ui() -> int:
    """不抢采集互斥锁，只连接后台实例提供的本地服务。"""
    runtime = read_runtime()
    if runtime is None:
        _fatal("后台监听未运行", "当前没有可连接的后台采集实例。")
        return 1
    try:
        from spritelens.system.webview_guard import ensure_webview2

        if not ensure_webview2(logs_dir()):
            return 1
        guard = SingleInstanceGuard(
            mutex_name=UI_MUTEX_NAME,
            activation_name=UI_ACTIVATION_EVENT_NAME,
        )
        if not guard.acquire():
            guard.notify_existing()
            return 0
        settings = SettingsRepository(config_path())
        context = SimpleNamespace(
            settings=settings,
            capture_vm=SimpleNamespace(stop=lambda: None),
            pet_store=None,
            egg_store=None,
            home_store=None,
            event_log=None,
        )
        server = SimpleNamespace(url=runtime.url, _context=context)
        try:
            return 0 if _run_window(server, guard) else 1
        finally:
            guard.close()
    except Exception as exc:  # noqa: BLE001 - UI 进程失败给出可读错误
        logger.exception("连接后台采集实例失败")
        _fatal("主界面启动失败", f"{exc}\n\n请先确认后台监听仍在运行。")
        return 1


def _fatal(title: str, message: str) -> None:
    """弹出系统错误框：pythonw 启动时控制台不可见，必须让用户看到失败原因。"""
    try:
        print(f"[web] {title}：{message}")  # pythonw 下 stdout 为 None，静默跳过
    except Exception:  # noqa: BLE001
        pass
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, f"{WINDOW_TITLE} — {title}", 0x10)
    except Exception:  # noqa: BLE001 - 对话框失败不影响退出码
        pass


def _enable_dpi_awareness() -> None:
    """声明 DPI 感知，高分屏按真实分辨率渲染（三级降级，Win8.1 起全覆盖）。"""
    import ctypes

    try:
        user32 = ctypes.windll.user32
        if hasattr(user32, "SetProcessDpiAwarenessContext"):
            # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
                return
        shcore = ctypes.windll.shcore
        shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
        return
    except Exception:  # noqa: BLE001 - 旧系统无此 API
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception as exc:  # noqa: BLE001 - 全部失败则保持系统默认
        logger.debug("DPI 感知声明失败: %s", exc)


def _set_app_user_model_id() -> None:
    """声明独立 AppUserModelID：源码运行时任务栏不归到 pythonw.exe 默认图标。"""
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SpriteLens.App")
    except Exception as exc:  # noqa: BLE001 - 失败只影响任务栏图标归属
        logger.debug("AppUserModelID 设置失败: %s", exc)


def _apply_window_icons(hwnd: int, icon_path: str) -> None:
    """给窗口发大小两档图标：标题栏 + 任务栏 + Alt-Tab（源码运行场景）。"""
    import ctypes
    from ctypes import wintypes

    if not icon_path or not hwnd:
        return
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    # Win32 默认返回 int，会截断 64 位句柄；显式声明指针宽度。
    user32.LoadImageW.argtypes = [
        wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
        ctypes.c_int, ctypes.c_int, wintypes.UINT,
    ]
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.SendMessageW.argtypes = [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    ]
    user32.SendMessageW.restype = ctypes.c_ssize_t
    IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
    WM_SETICON = 0x80
    for icon_type, size in ((1, 32), (0, 16)):  # ICON_BIG / ICON_SMALL
        handle = user32.LoadImageW(None, icon_path, IMAGE_ICON, size, size, LR_LOADFROMFILE)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        user32.SendMessageW(hwnd, WM_SETICON, icon_type, handle)


def _run_window(server: "LocalServer", guard: SingleInstanceGuard) -> bool:
    """开 pywebview 窗口并阻塞到用户关闭它。"""
    import webview

    from spritelens.system.window_geometry import initial_window_size
    from spritelens.web.desktop_shell import WindowControls
    from spritelens.web.startup_cover import StartupCover
    from spritelens.web.close_coordinator import CloseCoordinator

    settings = server._context.settings
    saved = settings.window_geometry()
    width, height = initial_window_size((saved["width"], saved["height"]) if saved else None)

    # 唤醒句柄交给 WebView2 的窗口做前台置顶（重复启动时）
    activation_handle = guard.create_activation_event()

    window = webview.create_window(
        WINDOW_TITLE,
        server.url.replace('/#', '/?desktop=1#'),
        width=width,
        height=height,
        x=0 if saved and saved["x"] is not None else None,
        y=0 if saved and saved["y"] is not None else None,
        min_size=(640, 360),
        text_select=True,
        frameless=True,
        easy_drag=False,
        shadow=True,
        # 与原生遮罩、网页启动面板同底色，交接时不闪白。
        background_color=SPLASH_BG,
    )
    position = (saved["x"], saved["y"]) if saved and saved["x"] is not None else None
    controls = WindowControls(window, position)
    close_coordinator = CloseCoordinator(window, server._context, get_geometry=controls.get_window_geometry)
    window.events.closing += close_coordinator.request_close
    window.expose(controls.minimize, controls.toggle_maximize, controls.close,
                  controls.get_window_state, controls.resize_window)
    window.events.before_show += controls.install_native_frame
    window.events.before_show += controls.enable_native_drag
    startup_cover = StartupCover(window)
    window.expose(startup_cover.startup_ready, startup_cover.startup_failed)
    window.events.before_show += startup_cover.install
    window.events.closing += startup_cover.remove
    window.events.shown += startup_cover.reveal
    window.events.loaded += startup_cover.keep_on_top
    window.events.loaded += controls.sync_state
    window.events.maximized += controls.sync_state
    window.events.restored += controls.sync_state

    if activation_handle:
        stop_flag = threading.Event()

        def poll_activation() -> None:
            while not stop_flag.wait(0.25):
                if guard.consume_activation(activation_handle):
                    try:
                        window.restore()
                        window.show()
                        hwnd = _window_handle()
                        SingleInstanceGuard.force_foreground(hwnd) if hwnd else None
                    except Exception as exc:  # noqa: BLE001 - 置顶失败不强求
                        logger.debug("唤醒已有窗口失败: %s", exc)

        threading.Thread(target=poll_activation, name="spritelens-activate", daemon=True).start()
    else:
        stop_flag = None

    try:
        webview.start(
            _late_init,
            args=(window, _icon_path()),  # GUI 就绪后在后台线程执行
            debug=False,
            icon=str(_icon_path()),
        )  # 阻塞至窗口关闭
    finally:
        if stop_flag is not None:
            stop_flag.set()
    return not close_coordinator.abandoned


def _late_init(window, icon_path: str) -> None:
    """GUI 就绪后的收尾：窗口图标。"""
    import time

    time.sleep(0.8)  # 等 WebView2 窗口真实创建（EnumWindows 找句柄）
    try:
        _apply_window_icons(_window_handle(), icon_path)
    except Exception as exc:  # noqa: BLE001 - 图标失败不影响功能
        logger.debug("窗口图标设置失败: %s", exc)

def _icon_path() -> str:
    """窗口/任务栏图标（resources/app.ico，随包分发；缺失时回落空串）。"""
    icon = project_root() / "resources" / "app.ico"
    return str(icon) if icon.is_file() else ""


def _window_handle() -> int:
    """取本进程第一个可见顶层窗口句柄（用于强制置顶）。

    不能用 GetForegroundWindow：那返回的是系统当前前台窗口，可能是其他
    程序的窗口；这里按进程 ID 枚举过滤。
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    pid = kernel32.GetCurrentProcessId()

    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _visit(hwnd, _lparam):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(wintypes.HWND(hwnd)):
            found.append(int(hwnd))
            return False
        return True

    user32.EnumWindows(_visit, 0)
    return found[0] if found else 0


def _wait_until_interrupted(server: "LocalServer") -> None:
    """浏览器模式：等服务结束（Ctrl+C 退出）。"""
    try:
        while server.running:
            threading.Event().wait(0.5)
    except KeyboardInterrupt:
        pass


def _shutdown(server: "LocalServer | None", context, guard: SingleInstanceGuard) -> bool:
    """退出清理（S02/D07）：逐项尝试、单项失败不跳过其余，守卫最后释放。

    支持只创建了部分资源（server/context 为 None）的退出；
    复核 C02/D07：原实现任一项抛异常会跳过后续清理。
    """
    failures: list[tuple[str, Exception]] = []
    steps: list[tuple[str, object]] = []
    if server is not None:
        steps.append(("server", server.stop))
    if context is not None:
        steps.append(("context", context.close))
    for label, action in steps:
        try:
            action()
        except TimeoutError as exc:
            failures.append((label, exc))
            logger.warning("关闭 %s 超时，保留尚在使用的下游资源: %s", label, exc)
            break
        except Exception as exc:  # noqa: BLE001 - 退出路径尽量多释放
            failures.append((label, exc))
            logger.warning("关闭 %s 失败: %s", label, exc)
    try:
        guard.close()
    except Exception as exc:  # noqa: BLE001
        failures.append(("guard", exc))
        logger.warning("关闭 guard 失败: %s", exc)
    if failures:
        label, exc = failures[0]
        logger.error("退出清理存在失败项（首项 %s）: %s", label, exc)
    logger.info("Web 界面已退出")
    return not failures


from spritelens.web.server import LocalServer  # noqa: E402 - 放尾部避免循环导入困扰

__all__ = ["LocalServer", "WEBVIEW2_HINT", "WINDOW_TITLE", "run_web"]
