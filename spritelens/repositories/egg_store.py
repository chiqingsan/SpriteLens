"""蛋仓持久化网关：写透 + 读取（与 PetStore 同型的简化版）。

蛋仓每次登录由服务器全量重推（先清后写即可保证一致），条目量级小
（几百行），直接同步写，无需 PetStore 的 write-behind 批量刷盘。
"""

from __future__ import annotations

import json
import time

from spritelens.domain.egg_box import EggBoxEntry
from spritelens.logs import get_logger
from spritelens.repositories.database import Database

logger = get_logger("egg_store")


class EggStore:
    """eggs 表的读写网关；单连接由 Database 的锁串行化。"""

    def __init__(self, database: Database) -> None:
        self._db = database

    def put(self, uid: int, eggs: list[EggBoxEntry]) -> int:
        """覆盖式写入一批蛋（同 instance_id 覆盖）。"""
        if uid <= 0 or not eggs:
            return 0
        now = time.time()
        rows = [
            (
                uid,
                egg.instance_id,
                egg.egg_conf_id,
                egg.pet_conf_id,
                egg.quantity,
                egg.obtained_at,
                1 if egg.hatching else 0,
                json.dumps(
                    {
                        "height_cm": egg.height_cm,
                        "weight_g": egg.weight_g,
                        "hatch_seconds": egg.hatch_seconds,
                        "hatched_seconds": egg.hatched_seconds,
                        "hatch_updated_at": egg.hatch_updated_at,
                        "start_hatch_time": egg.start_hatch_time,
                        "category": egg.category,
                        "special_egg_conf_id": egg.special_egg_conf_id,
                        "appearance_type": egg.appearance_type,
                        "extension_type": egg.extension_type,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                now,
            )
            for egg in eggs
        ]
        try:
            self._db.execute_many(
                """
                INSERT INTO eggs (uid, instance_id, egg_conf_id, pet_conf_id, quantity,
                                  obtained_at, hatching, detail_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (uid, instance_id) DO UPDATE SET
                    egg_conf_id = excluded.egg_conf_id,
                    pet_conf_id = excluded.pet_conf_id,
                    quantity    = excluded.quantity,
                    obtained_at = excluded.obtained_at,
                    hatching    = excluded.hatching,
                    detail_json = excluded.detail_json,
                    updated_at  = excluded.updated_at
                """,
                rows,
            )
        except Exception as exc:  # noqa: BLE001 - 持久化失败不阻断采集
            logger.warning("蛋仓写入失败: %s", exc)
            return 0
        return len(rows)

    def load(self, uid: int) -> tuple[EggBoxEntry, ...]:
        try:
            rows = self._db.query(
                "SELECT instance_id, egg_conf_id, pet_conf_id, quantity, obtained_at,"
                " hatching, detail_json FROM eggs WHERE uid = ? ORDER BY obtained_at, instance_id",
                (uid,),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("蛋仓读取失败: %s", exc)
            return ()
        out: list[EggBoxEntry] = []
        for row in rows:
            try:
                detail = json.loads(row["detail_json"] or "{}")
            except json.JSONDecodeError:
                detail = {}
            out.append(
                EggBoxEntry(
                    instance_id=int(row["instance_id"]),
                    egg_conf_id=int(row["egg_conf_id"]),
                    pet_conf_id=int(row["pet_conf_id"]),
                    quantity=int(row["quantity"]),
                    obtained_at=int(row["obtained_at"]),
                    bag_type=8,
                    height_cm=int(detail.get("height_cm") or 0),
                    weight_g=int(detail.get("weight_g") or 0),
                    hatch_seconds=int(detail.get("hatch_seconds") or 0),
                    hatched_seconds=int(detail.get("hatched_seconds") or 0),
                    hatch_updated_at=int(detail.get("hatch_updated_at") or 0),
                    start_hatch_time=int(detail.get("start_hatch_time") or 0),
                    category=int(detail.get("category") or 0),
                    special_egg_conf_id=int(detail.get("special_egg_conf_id") or 0),
                    appearance_type=int(detail.get("appearance_type") or 0),
                    extension_type=int(detail.get("extension_type") or 0),
                )
            )
        return tuple(out)

    def load_latest(self) -> tuple[int, tuple[EggBoxEntry, ...]]:
        """最近活跃账号的蛋仓快照（离线展示用）。"""
        try:
            rows = self._db.query(
                "SELECT uid, MAX(updated_at) AS recent FROM eggs GROUP BY uid ORDER BY recent DESC LIMIT 1"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("蛋仓账号查询失败: %s", exc)
            return 0, ()
        if not rows:
            return 0, ()
        uid = int(rows[0]["uid"])
        return uid, self.load(uid)


__all__ = ["EggStore"]
