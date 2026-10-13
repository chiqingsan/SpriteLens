"""从确认的好奇版头像 PNG 生成应用图标 resources/app.ico。

图标为多尺寸 .ico（16/24/32/48/64/128/256），供窗口标题栏、任务栏与
浏览器标签页复用。运行一次即可，产物入库；改设计后重跑覆盖。

用法: .venv\\Scripts\\python.exe tools/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "resources" / "app.ico"
SOURCE = ROOT / "resources" / "icon_source.png"
FAVICON = ROOT / "spritelens" / "web" / "static" / "favicon.png"

SIZES = (16, 24, 32, 48, 64, 128, 256)


def _load_canvas() -> Image.Image:
    """保留已确认方形 PNG 的背景与高光，不再按颜色抠除白色。"""
    with Image.open(SOURCE) as source:
        return source.convert("RGBA")


def main() -> int:
    canvas = _load_canvas()
    frames = [canvas.resize((size, size), Image.LANCZOS) for size in SIZES]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frames[-1].save(OUT, format="ICO", sizes=[(s, s) for s in SIZES], append_images=frames[:-1])
    print(f"已生成 {OUT}（{len(SIZES)} 个尺寸: {', '.join(map(str, SIZES))}）")

    # 同时导出 256px PNG 作为 favicon（浏览器标签页用）
    frames[-1].save(FAVICON, format="PNG")
    print(f"已生成 {FAVICON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
