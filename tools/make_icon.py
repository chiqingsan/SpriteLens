"""生成应用图标 resources/app.ico（品牌 teal + 放大镜语义，对应 SpriteLens）。

图标为多尺寸 .ico（16/24/32/48/64/128/256），供窗口标题栏、任务栏与
浏览器标签页复用。运行一次即可，产物入库；改设计后重跑覆盖。

用法: .venv\\Scripts\\python.exe tools/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "resources" / "app.ico"

# 品牌色（与 web/static/app.css 的 teal 体系一致）
TEAL = (7, 151, 143)
TEAL_DEEP = (6, 70, 83)
WHITE = (255, 255, 255)

SIZES = (16, 24, 32, 48, 64, 128, 256)


def _draw(size: int) -> Image.Image:
    """在 size×size 画布上画：深色圆角底 + 白色镜筒 + 三个像素点。"""
    scale = 8  # 先大画布绘制再缩放，得到抗锯齿边缘
    canvas = size * scale
    img = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    radius = int(canvas * 0.22)
    draw.rounded_rectangle([0, 0, canvas - 1, canvas - 1], radius=radius, fill=TEAL_DEEP)

    # 放大镜：圆环 + 手柄
    ring_r = int(canvas * 0.26)
    cx, cy = int(canvas * 0.44), int(canvas * 0.42)
    stroke = max(scale, int(canvas * 0.085))
    draw.ellipse(
        [cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r],
        outline=WHITE,
        width=stroke,
    )
    handle_w = stroke
    draw.line(
        [cx + int(ring_r * 0.72), cy + int(ring_r * 0.72), int(canvas * 0.80), int(canvas * 0.80)],
        fill=WHITE,
        width=handle_w,
    )

    # 镜内三个像素点，暗示「精灵（点阵）」
    dot = max(1, int(canvas * 0.045))
    for dx, dy in ((-0.10, -0.10), (0.12, -0.04), (0.0, 0.14)):
        px, py = cx + int(canvas * dx), cy + int(canvas * dy)
        draw.rectangle([px - dot, py - dot, px + dot, py + dot], fill=TEAL)

    return img.resize((size, size), Image.LANCZOS)


def main() -> int:
    frames = [_draw(size) for size in SIZES]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frames[-1].save(OUT, format="ICO", sizes=[(s, s) for s in SIZES], append_images=frames[:-1])
    print(f"已生成 {OUT}（{len(SIZES)} 个尺寸: {', '.join(map(str, SIZES))}）")

    # 同时导出 256px PNG 作为 favicon（浏览器标签页用）
    png = ROOT / "spritelens" / "web" / "static" / "favicon.png"
    frames[-1].save(png, format="PNG")
    print(f"已生成 {png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
