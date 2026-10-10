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


def run_web(*, open_browser: bool = False) -> int:
    """启动 Web 界面；返回进程退出码。"""
    setup_logger(logs_dir())

    guard = SingleInstanceGuard()
    if not guard.acquire():
        notified = guard.notify_existing()
        logger.info("检测到已有实例在运行（唤醒已有窗口=%s），本次启动退出", notified)
        return 0

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
    print(f"[web] {title}：{message}")
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, f"{WINDOW_TITLE} — {title}", 0x10)
    except Exception:  # noqa: BLE001 - 对话框失败不影响退出码
        pass


def _run_window(server: "LocalServer", guard: SingleInstanceGuard) -> None:
    """开 pywebview 窗口并阻塞到用户关闭它。"""
    import webview

    # 唤醒句柄交给 WebView2 的窗口做前台置顶（重复启动时）
    activation_handle = guard.create_activation_event()

    window = webview.create_window(
        WINDOW_TITLE,
        server.url,
        width=1440,
        height=900,
        min_size=(1024, 640),
        text_select=True,
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
        webview.start(debug=False, icon=str(_icon_path()))  # 阻塞至窗口关闭
    finally:
        if stop_flag is not None:
            stop_flag.set()


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
