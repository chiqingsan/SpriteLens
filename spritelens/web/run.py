"""Web 界面入口：pywebview 窗口（系统 WebView2）+ 本地服务。

与竞品（蛋神助手）同型：单进程、原生窗口壳、内容为本地 Web 页面。
窗口只负责开壳——数据、命令与推送全部走 `LocalServer`。

失败降级：系统缺 WebView2 时 `webview.start()` 抛错，这里提示用户安装
（Win10/11 一般预装；缺失时可从微软官网装 Evergreen Runtime）。
"""

from __future__ import annotations

import threading
import webbrowser

import spritelens
from spritelens.app_context import build_app_context
from spritelens.logs import get_logger, setup_logger
from spritelens.paths import logs_dir, project_root
from spritelens.system.single_instance import SingleInstanceGuard

logger = get_logger("web_run")

WINDOW_TITLE = f"{spritelens.APP_DISPLAY_NAME} {spritelens.APP_NAME}"
WEBVIEW2_HINT = (
    "无法创建 WebView2 窗口：系统可能缺少 WebView2 运行时。\n"
    "请安装 Microsoft Edge WebView2 Runtime 后重试：\n"
    "https://developer.microsoft.com/microsoft-edge/webview2/"
)
# 与前端 index.html 启动遮罩同款配色（.startup 渐变起始色）
SPLASH_BG = "#074f5d"


def run_web(*, open_browser: bool = False) -> int:
    """启动 Web 界面；返回进程退出码。"""
    setup_logger(logs_dir())
    _enable_dpi_awareness()
    _set_app_user_model_id()

    guard = SingleInstanceGuard()
    if not guard.acquire():
        notified = guard.notify_existing()
        logger.info("检测到已有实例在运行（唤醒已有窗口=%s），本次启动退出", notified)
        return 0

    # 开壳前预检测 WebView2：缺失时弹原生对话框引导安装，避免白屏式失败
    from spritelens.system.webview_guard import ensure_webview2

    if not ensure_webview2(logs_dir()):
        logger.warning("WebView2 不可用，已按用户选择退出")
        guard.close()
        return 1

    context = build_app_context()
    server = LocalServer(context)
    try:
        server.start()
    except Exception as exc:  # noqa: BLE001 - 端口/绑定失败直接给出可读提示
        logger.exception("本地服务启动失败")
        _fatal("本地服务启动失败", f"{exc}\n\n日志目录：{logs_dir()}")
        context.close()
        guard.close()
        return 1

    logger.info("Web 界面入口: %s", f"http://{server.host}:{server.port}/")

    if open_browser:
        # 调试模式：用系统浏览器打开，便于 DevTools（pywebview 也可开，但外置更省事）
        webbrowser.open(server.url)
        try:
            _wait_until_interrupted(server)
        finally:
            _shutdown(server, context, guard)
        return 0

    try:
        _run_window(server, guard)
    except Exception as exc:  # noqa: BLE001 - WebView2 缺失等环境问题
        logger.error("窗口创建失败: %s", exc)
        _fatal("窗口创建失败", f"{WEBVIEW2_HINT}\n\n原始错误：{exc}\n日志目录：{logs_dir()}")
        _shutdown(server, context, guard)
        return 1
    _shutdown(server, context, guard)
    return 0


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
    IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
    for flag, size in ((0x80, 32), (0x81, 16)):  # WM_SETICON: ICON_BIG / ICON_SMALL
        handle = user32.LoadImageW(None, icon_path, IMAGE_ICON, size, size, LR_LOADFROMFILE)
        if handle:
            user32.SendMessageW(wintypes.HWND(hwnd), wintypes.UINT(flag), wintypes.WPARAM(0), wintypes.LPARAM(handle))


def _run_window(server: "LocalServer", guard: SingleInstanceGuard) -> None:
    """开 pywebview 窗口并阻塞到用户关闭它。"""
    import webview

    from spritelens.system.window_geometry import initial_window_size

    settings = server._context.settings
    saved = settings.window_geometry()
    if saved:
        width, height = saved["width"], saved["height"]
    else:
        width, height = initial_window_size()

    # 唤醒句柄交给 WebView2 的窗口做前台置顶（重复启动时）
    activation_handle = guard.create_activation_event()

    window = webview.create_window(
        WINDOW_TITLE,
        server.url,
        width=width,
        height=height,
        min_size=(1024, 640),
        text_select=True,
        # WebView2 渲染前的空窗默认白色；用启动页同款深青色，消除白屏观感
        background_color=SPLASH_BG,
    )

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
            args=(window, _icon_path(), settings),  # GUI 就绪后在后台线程执行
            debug=False,
            icon=str(_icon_path()),
        )  # 阻塞至窗口关闭
    finally:
        if stop_flag is not None:
            stop_flag.set()


def _late_init(window, icon_path: str, settings) -> None:
    """GUI 就绪后的收尾：窗口图标 + 关闭时保存窗口几何。"""
    import time

    time.sleep(0.8)  # 等 WebView2 窗口真实创建（EnumWindows 找句柄）
    try:
        _apply_window_icons(_window_handle(), icon_path)
    except Exception as exc:  # noqa: BLE001 - 图标失败不影响功能
        logger.debug("窗口图标设置失败: %s", exc)

    def _save_geometry() -> None:
        try:
            if window.is_maximized:
                return  # 最大化尺寸不是用户期望的还原尺寸，保留上次窗口化几何
            settings.set_window_geometry(
                width=int(window.width),
                height=int(window.height),
                maximized=False,
            )
        except Exception as exc:  # noqa: BLE001 - 几何保存失败不阻断退出
            logger.debug("窗口几何保存失败: %s", exc)

    try:
        window.events.closed += _save_geometry
    except Exception as exc:  # noqa: BLE001
        logger.debug("closed 事件注册失败: %s", exc)


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


def _shutdown(server: "LocalServer", context, guard: SingleInstanceGuard) -> None:
    server.stop()
    context.close()
    guard.close()
    logger.info("Web 界面已退出")


from spritelens.web.server import LocalServer  # noqa: E402 - 放尾部避免循环导入困扰

__all__ = ["LocalServer", "WEBVIEW2_HINT", "WINDOW_TITLE", "run_web"]
