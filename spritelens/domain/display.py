"""展示常量：系别配色、六维标签、天赋阶配色。

从旧版桌面主题模块下沉而来——这些是"游戏语义 → 展示"的映射，
与任何 UI 框架无关，Web 载荷与未来的任何前端都直接复用。
"""

from __future__ import annotations

# 系别 → 颜色（与游戏 type_chart 色一致；缺失时用中性蓝）
TYPE_COLORS: dict[str, str] = {
    "普通": "#a8a878",
    "火": "#f08030",
    "水": "#6890f0",
    "草": "#78c850",
    "光": "#f8d030",
    "地": "#b8a038",
    "冰": "#98d8d8",
    "龙": "#7038f8",
    "电": "#f8d030",
    "毒": "#a040a0",
    "虫": "#a8b820",
    "武": "#c03028",
    "翼": "#a890f0",
    "萌": "#ee99ac",
    "幽": "#705898",
    "恶": "#6f5848",
    "机械": "#b8b8d0",
    "幻": "#e8a0d8",
}

# 六维字段名 → 中文标签（与 domain/pets.py 的 _ATTR_SLOTS 顺序一致）
STAT_LABELS: tuple[tuple[str, str], ...] = (
    ("hp", "生命"),
    ("atk", "物攻"),
    ("spa", "魔攻"),
    ("def", "物防"),
    ("spd", "魔防"),
    ("spe", "速度"),
)

# 天赋阶 → 展示色（越高越亮）
TALENT_RANK_COLORS: tuple[str, ...] = (
    "#8695b8",  # 0/1 无评级
    "#8695b8",
    "#7fd1a8",
    "#59c3f0",
    "#b48ff5",
    "#f5b64c",
)

__all__ = ["STAT_LABELS", "TALENT_RANK_COLORS", "TYPE_COLORS"]
