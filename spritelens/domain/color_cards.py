"""炫彩色卡目录：44 张色卡（底色×混色）+ glass → 卡号判定。

数据文件 data/static/color_cards.json（tools 侧从游戏客户端配置整理，
字段：card_id / base_name / mix_name / base_color / mix_color；另含 4 种粒子）。

卡号判定（与蛋神 color_cards.card_id_from_glass 同逻辑）：
    glass_type == 2 且 value & 0xFFFFF ∈ {1..4} → "s1".."s4"（赛季卡）
    否则 card_id = str(glass_value & 0xFFFFF)（值高位为标志位）
    查不到目录 → 未收录（前端按编号显示）
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from spritelens.logs import get_logger

logger = get_logger("color_cards")

FILE = "color_cards.json"
_GLASS_SEASON_TYPE = 2
_VALUE_MASK = 0xFFFFF
_SEASON_IDS = ("1", "2", "3", "4")


@dataclass(frozen=True)
class ColorCard:
    """一张炫彩色卡：底色 × 混色组合。"""

    card_id: str
    base_name: str
    mix_name: str
    base_color: str
    mix_color: str


class ColorCatalog:
    """色卡只读索引；加载失败整体降级空表。"""

    def __init__(self, directory: Path | None) -> None:
        self._cards: dict[str, ColorCard] = {}
        if directory is None:
            return
        path = directory / FILE
        if not path.is_file():
            logger.info("色卡目录缺失: %s（色卡页将降级为编号显示）", path)
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("色卡目录加载失败 %s: %s", path, exc)
            return
        for row in data.get("cards") or []:
            if not isinstance(row, dict) or not row.get("card_id"):
                continue
            card = ColorCard(
                card_id=str(row["card_id"]),
                base_name=str(row.get("base_name") or ""),
                mix_name=str(row.get("mix_name") or ""),
                base_color=str(row.get("base_color") or ""),
                mix_color=str(row.get("mix_color") or ""),
            )
            self._cards[card.card_id] = card

    def card(self, card_id: str) -> ColorCard | None:
        return self._cards.get(card_id)

    def cards(self) -> tuple[ColorCard, ...]:
        return tuple(self._cards.values())

    def card_id_for(self, glass_type: int, glass_value: int) -> str:
        """glass 参数 → 卡号；未收录返回空串。"""
        if glass_type == _GLASS_SEASON_TYPE:
            seasonal = glass_value & _VALUE_MASK
            if seasonal and str(seasonal) in _SEASON_IDS:
                return f"s{seasonal}"
            if seasonal == 1000:
                return "1000"
            return ""
        packed = str(glass_value & _VALUE_MASK)
        return packed if packed in self._cards else ""

    @property
    def available(self) -> bool:
        return bool(self._cards)

    @staticmethod
    def is_seasonal(card_id: str) -> bool:
        """赛季卡（s1-s4）不属于普通底色×混色网格，栏目单独成组。"""
        return card_id.startswith("s") and card_id[1:] in _SEASON_IDS

    def effect_for(self, glass_type: int, glass_value: int) -> dict | None:
        """低 20 位为卡号，高位 1..4 为粒子；未知粒子不猜测。"""
        card_id = self.card_id_for(glass_type, glass_value)
        card = self.card(card_id)
        if card is None:
            return None
        particle = glass_value >> 20
        names = {1: "四角星", 2: "爱心", 3: "方块", 4: "镂空五角星"}
        return {"card_id": card_id, "base_color": card.base_color, "mix_color": card.mix_color,
                "name": f"{card.mix_name} · {card.base_name}",
                "particle_id": particle if particle in names else 0,
                "particle_name": names.get(particle, "暂无粒子数据")}


__all__ = ["ColorCard", "ColorCatalog"]
