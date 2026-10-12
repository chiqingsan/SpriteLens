"""蛋目录：精灵蛋静态数据（蛋组 / 孵化时长 / 公母比 / 身高体重 / 进化链）。

数据文件 data/static/eggs.json（tools/import_egg_data.py 转制自游戏客户端配置）。
为孵蛋工具链（蛋图鉴 / 蛋蛋仓库 / 配窝推断）提供静态联查：
  - egg_conf_id（协议蛋条目 itemConfId）→ 蛋记录
  - base_id（物种 base_conf_id）→ 蛋记录（该物种产什么蛋）

设计约束同 static_data：零 IO 副作用、加载失败整体降级空表。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from spritelens.logs import get_logger

logger = get_logger("static_data_eggs")

EGGS_FILE = "eggs.json"


@dataclass(frozen=True)
class EggInfo:
    """一种精灵蛋的静态属性（按 egg_conf_id 索引）。"""

    egg_key: str
    name_key: str
    egg_conf_id: int
    pet_egg_pet_id: int
    egg_name: str
    name: str
    owner_base_id: int
    base_id: int
    dex_no: int
    handbook_no: str
    egg_item_id: int
    egg_item_name: str
    egg_type_id: int
    egg_type_name: str
    hatch_label: str
    hatch_seconds: int
    egg_group_ids: tuple[int, ...]
    egg_group_names: tuple[str, ...]
    height_low: int
    height_high: int
    weight_low: int
    weight_high: int
    chain_key: str
    chain_members: tuple[int, ...]
    gender_male: int
    gender_female: int


class EggCatalog:
    """蛋目录只读索引；全量加载一次，进程内共享。"""

    def __init__(self, directory: Path | None) -> None:
        self._eggs: dict[int, EggInfo] = {}
        self._by_base_id: dict[int, EggInfo] = {}
        self._entries: tuple[EggInfo, ...] = ()
        self._groups: dict[str, str] = {}
        if directory is None:
            return
        self._load(directory / EGGS_FILE)

    def _load(self, path: Path) -> None:
        if not path.is_file():
            logger.info("蛋目录缺失: %s（蛋相关页面将不可用）", path)
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("蛋目录加载失败 %s: %s", path, exc)
            return
        if not isinstance(data, dict):
            return
        self._groups = {str(k): str(v) for k, v in (data.get("groups") or {}).items()}
        entries: list[EggInfo] = []
        for entry in data.get("eggs") or []:
            if not isinstance(entry, dict) or not entry.get("egg_conf_id"):
                continue
            info = EggInfo(
                egg_key=str(entry.get("egg_key") or ""),
                name_key=str(entry.get("name_key") or ""),
                egg_conf_id=int(entry.get("egg_conf_id") or 0),
                pet_egg_pet_id=int(entry.get("pet_egg_pet_id") or 0),
                egg_name=str(entry.get("egg_name") or ""),
                name=str(entry.get("name") or ""),
                owner_base_id=int(entry.get("owner_base_id") or 0),
                base_id=int(entry.get("base_id") or 0),
                dex_no=int(entry.get("dex_no") or 0),
                handbook_no=str(entry.get("handbook_no") or ""),
                egg_item_id=int(entry.get("egg_item_id") or 0),
                egg_item_name=str(entry.get("egg_item_name") or ""),
                egg_type_id=int(entry.get("egg_type_id") or 0),
                egg_type_name=str(entry.get("egg_type_name") or ""),
                hatch_label=str(entry.get("hatch_label") or ""),
                hatch_seconds=int(entry.get("hatch_seconds") or 0),
                egg_group_ids=tuple(int(g) for g in (entry.get("egg_group_ids") or [])),
                egg_group_names=tuple(str(g) for g in (entry.get("egg_group_names") or [])),
                height_low=int(entry.get("height_low") or 0),
                height_high=int(entry.get("height_high") or 0),
                weight_low=int(entry.get("weight_low") or 0),
                weight_high=int(entry.get("weight_high") or 0),
                chain_key=str(entry.get("chain_key") or ""),
                chain_members=tuple(
                    int(m) for m in (entry.get("chain_members") or []) if isinstance(m, int)
                ),
                gender_male=int(entry.get("gender_male") or 0),
                gender_female=int(entry.get("gender_female") or 0),
            )
            self._eggs[info.egg_conf_id] = info
            if info.base_id and info.base_id not in self._by_base_id:
                self._by_base_id[info.base_id] = info
            entries.append(info)
        entries.sort(key=lambda e: (e.dex_no, e.egg_conf_id))
        self._entries = tuple(entries)
        by_key = {info.egg_key: info for info in entries}
        for conf_id, egg_key in (data.get("egg_conf_index") or {}).items():
            if str(conf_id).isdigit() and egg_key in by_key:
                self._eggs.setdefault(int(conf_id), by_key[egg_key])
        for base_id, egg_key in (data.get("egg_base_index") or {}).items():
            if str(base_id).isdigit() and egg_key in by_key:
                self._by_base_id[int(base_id)] = by_key[egg_key]

    # -- 查询 ----------------------------------------------------------
    def egg(self, egg_conf_id: int) -> EggInfo | None:
        return self._eggs.get(egg_conf_id)

    def egg_by_base_id(self, base_id: int) -> EggInfo | None:
        return self._by_base_id.get(base_id)

    def entries(self) -> tuple[EggInfo, ...]:
        return self._entries

    def groups(self) -> dict[str, str]:
        return dict(self._groups)

    def group_names(self) -> tuple[str, ...]:
        """实际出现的蛋组名（按 id 排序，供筛选器）。"""
        seen: dict[str, None] = {}
        for info in self._entries:
            for name in info.egg_group_names:
                seen.setdefault(name, None)
        return tuple(seen)

    def type_names(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for info in self._entries:
            if info.egg_type_name:
                seen.setdefault(info.egg_type_name, None)
        return tuple(seen)

    def stats(self) -> dict[str, int]:
        return {
            "eggs": len(self._entries),
            "conf_index": len(self._eggs),
            "by_base_id": len(self._by_base_id),
            "groups": len(self._groups),
        }

    @property
    def available(self) -> bool:
        return bool(self._entries)


__all__ = ["EggCatalog", "EggInfo"]
