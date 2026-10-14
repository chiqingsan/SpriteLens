"""精灵奖牌归属：登录集合按获得精灵关联，不用佩戴者或体型推算。"""
from __future__ import annotations

from dataclasses import dataclass
from spritelens.events import PacketEvent


@dataclass(frozen=True)
class MedalUpdate:
    collection: dict[int, tuple[int, ...]] | None
    invalidated: frozenset[int]


def _number(fields: list[dict], no: int) -> int:
    return next((item['raw'] for item in fields if item.get('no') == no and isinstance(item.get('raw'), int)), 0)


def extract_medals(event: PacketEvent) -> MedalUpdate | None:
    """完整登录集合有明确语义；未核验的奖牌变更使相关集合失效待重采。"""
    if event.direction != 's2c':
        return None
    collection = None
    invalidated: set[int] = set()

    def walk(fields: list[dict]) -> None:
        nonlocal collection
        for item in fields:
            children = item.get('children', [])
            if item.get('type') == 'CliPetMedalInfo' and event.opcode_name == 'ZoneLoginRsp':
                owned: dict[int, set[int]] = {}
                for record in children:
                    if record.get('no') != 1:
                        continue
                    data = record.get('children', [])
                    medal_id = _number(data, 1)
                    for bucket in (value for value in data if value.get('no') == 3):
                        for detail in bucket.get('children', []):
                            if detail.get('no') != 2:
                                continue
                            gid = _number(detail.get('children', []), 6)
                            if gid > 0 and medal_id > 0:
                                owned.setdefault(gid, set()).add(medal_id)
                collection = {gid: tuple(sorted(ids)) for gid, ids in owned.items()}
            elif item.get('type') == 'PetMedal':
                # 当前录制没有奖牌增量，不能猜 op 枚举和删除语义。
                detail = next((value.get('children', []) for value in children if value.get('no') == 3), [])
                gid = _number(detail, 6) or _number(children, 4)
                invalidated.add(gid)
            walk(children)

    walk(event.decoded)
    return MedalUpdate(collection, frozenset(invalidated)) if collection is not None or invalidated else None
