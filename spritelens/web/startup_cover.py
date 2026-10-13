"""桌面启动始终使用同一原生画面，直到首屏就绪；网页面板仅用于浏览器模式。"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from webview import Window


class StartupCover:
    def __init__(self, window: Window) -> None:
        self._window = window

    def install(self) -> None:
        """before_show 在 GUI 线程执行，图标不依赖尚未加载的网页。"""
        from System.Drawing import (
            ColorTranslator, ContentAlignment, Font, FontStyle, GraphicsUnit, Image,
        )
        from System.Windows.Forms import (
            Button, DockStyle, FlatStyle, Label, Panel, PictureBox, PictureBoxSizeMode, Timer,
        )

        self._cover = Panel()
        self._cover.Dock = DockStyle.Fill
        self._cover.BackColor = self._window.native.BackColor
        # WinForms 的 DeviceDpi 在这里仍可能为 96；与 WebView2 一样按真实窗口 DPI 缩放。
        get_dpi = ctypes.WinDLL("user32").GetDpiForWindow
        get_dpi.argtypes = [wintypes.HWND]
        get_dpi.restype = wintypes.UINT
        self._scale = get_dpi(self._window.native.Handle.ToInt64()) / 96
        self._title_font = Font("Microsoft YaHei UI", 20 * self._scale, FontStyle.Bold, GraphicsUnit.Pixel)
        self._text_font = Font("Microsoft YaHei UI", 13 * self._scale, FontStyle.Regular, GraphicsUnit.Pixel)
        self._image = Image.FromFile(str(Path(__file__).parent / "static" / "favicon.png"))
        self._logo = PictureBox()
        self._logo.Image = self._image
        self._logo.SizeMode = PictureBoxSizeMode.Zoom
        self._title = Label()
        self._title.Text = "小洛探探 SpriteLens"
        self._title.Font = self._title_font
        self._title.ForeColor = ColorTranslator.FromHtml("#344033")
        self._title.TextAlign = ContentAlignment.MiddleCenter
        self._message = Label()
        self._message.Font = self._text_font
        self._message.ForeColor = ColorTranslator.FromHtml("#64705f")
        self._message.TextAlign = ContentAlignment.TopCenter
        self._retry = Button()
        self._retry.Text = "重新加载"
        self._retry.Font = self._text_font
        self._retry.FlatStyle = FlatStyle.Flat
        self._retry.FlatAppearance.BorderSize = 0
        self._retry.BackColor = ColorTranslator.FromHtml("#5f7d48")
        self._retry.ForeColor = ColorTranslator.FromHtml("#ffffff")
        self._retry.Click += self._reload
        self._close = Button()
        self._close.Text = "×"
        self._close.AccessibleName = "关闭"
        self._close.Font = self._title_font
        self._close.FlatStyle = FlatStyle.Flat
        self._close.FlatAppearance.BorderSize = 0
        self._close.ForeColor = self._title.ForeColor
        self._close.Click += lambda _sender, _event: self._window.destroy()
        for control in (self._logo, self._title, self._message, self._retry, self._close):
            self._cover.Controls.Add(control)
        self._cover.Resize += self._layout
        self._timer = Timer()
        # 只在超时后回调一次，不再用高频 Python 回调驱动动画。
        self._timer.Interval = 20000
        self._timer.Tick += self._timeout
        self._reset()
        self._window.native.Controls.Add(self._cover)
        self._cover.BringToFront()
        self._layout()

    def _layout(self, _sender: object = None, _event: object = None) -> None:
        scale = self._scale
        width, height = self._cover.ClientSize.Width, self._cover.ClientSize.Height
        # 正常、失败、重试共用固定槽位；按钮出现也不推动图标和标题。
        top = (height - int(242 * scale)) // 2
        self._logo.SetBounds((width - int(80 * scale)) // 2, top, int(80 * scale), int(80 * scale))
        self._title.SetBounds(0, top + int(96 * scale), width, int(32 * scale))
        text_width = min(width - int(48 * scale), int(680 * scale))
        self._message.SetBounds((width - text_width) // 2, top + int(140 * scale), text_width, int(64 * scale))
        self._retry.SetBounds((width - int(112 * scale)) // 2, top + int(208 * scale), int(112 * scale), int(34 * scale))
        self._close.SetBounds(width - int(46 * scale), 0, int(46 * scale), int(40 * scale))

    def _timeout(self, _sender: object, _event: object) -> None:
        self._show_failure("启动超时：界面或本地数据未能就绪。请重新加载。")

    def _reset(self) -> None:
        self._timer.Stop()
        self._message.Text = "正在启动…"
        self._retry.Visible = False
        self._timer.Start()

    def _reload(self, _sender: object, _event: object) -> None:
        self._reset()
        # 登录 fragment 被网页清除后，仅恢复它会成为同页锚点导航，并不会重新加载。
        # 给已知的本地根 URL 加一次性查询值，强制完整导航，同时保留登录 fragment。
        base, _, token = self._window.original_url.partition("#")
        separator = "&" if "?" in base else "?"
        self._window.load_url(f"{base}{separator}startup_retry={time.monotonic_ns()}#{token}")

    def keep_on_top(self) -> None:
        """WebView2 创建客户区子窗口后仍由同一原生面板承接启动画面。"""
        from System import Action

        def show() -> None:
            if not self._cover.IsDisposed:
                self._cover.BringToFront()

        self._window.native.BeginInvoke(Action(show))

    def startup_failed(self, reason: str) -> None:
        """JS 桥接线程只提交状态，原生控件始终在 GUI 线程更新。"""
        from System import Action

        if not self._cover.IsDisposed:
            self._cover.BeginInvoke(Action(lambda: self._show_failure(reason)))

    def _show_failure(self, reason: str) -> None:
        if self._cover.IsDisposed:
            return
        self._timer.Stop()
        self._message.Text = reason
        self._retry.Visible = True

    def startup_ready(self) -> None:
        """网页首屏完成布局后才揭开，loaded 不再替换加载画面。"""
        self.remove()

    def remove(self) -> None:
        """首屏就绪、closing 都可能到达；释放本层拥有的 GDI 与计时资源。"""
        if self._cover.IsDisposed:
            return
        if self._cover.InvokeRequired:
            from System import Action

            self._cover.BeginInvoke(Action(self.remove))
            return
        self._timer.Stop()
        self._timer.Dispose()
        self._cover.Dispose()
        for resource in (self._image, self._title_font, self._text_font):
            resource.Dispose()
