"""生成应用图标 resources/app.ico（品牌 teal + 放大镜语义，对应 SpriteLens）。

图标为多尺寸 .ico（16/24/32/48/64/128/256），供窗口标题栏、任务栏与
浏览器标签页复用。运行一次即可，产物入库；改设计后重跑覆盖。

用法: .venv\\Scripts\\python.exe tools/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "resources" / "app.ico"
SOURCE = ROOT / "resources" / "icon_source.jpg"
FAVICON = ROOT / "spritelens" / "web" / "static" / "favicon.png"

SIZES = (16, 24, 32, 48, 64, 128, 256)


def _load_canvas() -> Image.Image:
    """加载源图：白底转透明（容差渐变保边缘平滑）、裁剪内容区、方形化居中。"""
    src = Image.open(SOURCE).convert("RGBA")
    px = src.load()
    w, h = src.size
    for y in range(h):
        for x in range(w):
            r, g, b, _ = px[x, y]
            whiteness = min(r, g, b)
            if whiteness >= 245 and max(r, g, b) - whiteness <= 12:
                px[x, y] = (r, g, b, 0)
    src = src.crop(src.getbbox())
    side = max(src.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(src, ((side - src.width) // 2, (side - src.height) // 2), src)
    return canvas


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
