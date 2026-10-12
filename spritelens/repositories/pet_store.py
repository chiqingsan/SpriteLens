"""宠物持久化网关：写回缓存 + 后台批量落盘 + 读取。

为什么异步（实测教训）：抓包回调运行在 MonitorService 锁内，任何同步 IO
都会阻塞 UI 的 drain_events 与后续帧处理——事件日志每条 flush 在登录突发
下净增约 14ms，UI 轮询最长等待 57ms。因此 put() 只并入内存待写表，
落盘由独立 worker 线程按 flush_interval 批量执行。

模式：
- 适配器/Repository：domain 对象（Pet）进出，调用方不接触 SQL。
- Write-behind：同一 (uid, gid) 的重复更新在待写表天然合并，
  登录突发（百只级）最终只产生一次批量 upsert。
- 失败重试：写库异常整批回滚回待写表（新值优先），下轮重试，不丢数据。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Iterable

from spritelens.domain.pets import Pet, PetAttribute, PetSkill
from spritelens.domain.pet_locations import Backpack, PetLocation
from spritelens.logs import get_logger
from spritelens.repositories.database import Database

logger = get_logger("pet_store")

DEFAULT_FLUSH_INTERVAL = 0.5
_ATTR_SLOTS = ("hp", "atk", "spa", "def", "spd", "spe")

# 名称/等级为空或 0 时不覆盖既有值（身份包可能缺字段，不能让好数据退化）
_UPSERT_ACCOUNT = """
INSERT INTO accounts (uid, name, level, first_seen, last_seen)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT(uid) DO UPDATE SET
    name      = CASE WHEN excluded.name <> '' THEN excluded.name ELSE accounts.name END,
    level     = CASE WHEN excluded.level > 0 THEN excluded.level ELSE accounts.level END,
    last_seen = excluded.last_seen
"""

# first_seen 不参与更新：保留首次落库时间，updated_at 记录最近一次变化
_UPSERT_PET = """
INSERT INTO pets (
    uid, gid, conf_id, name, level, exp, nature, gender,
    blood_id, talent_rank, is_first_catch, first_seen, updated_at,
    attr_hp, attr_atk, attr_spa, attr_def, attr_spd, attr_spe,
    height, weight, voice, mutation_type, classis, breakthrough_lv,
    speciality_id, ball_id, attributes_json, skills_json, base_conf_id,
    colorful_conf_id, glass_type, glass_value, worn_medal_id, is_trial_pet, is_mirror_pet
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(uid, gid) DO UPDATE SET
    conf_id        = excluded.conf_id,
    name           = excluded.name,
    level          = excluded.level,
    exp            = excluded.exp,
    nature         = excluded.nature,
    gender         = excluded.gender,
    blood_id       = excluded.blood_id,
    talent_rank    = excluded.talent_rank,
    is_first_catch = excluded.is_first_catch,
    attr_hp        = excluded.attr_hp,
    attr_atk       = excluded.attr_atk,
    attr_spa       = excluded.attr_spa,
    attr_def       = excluded.attr_def,
    attr_spd       = excluded.attr_spd,
    attr_spe       = excluded.attr_spe,
    height         = excluded.height,
    weight         = excluded.weight,
    voice          = excluded.voice,
    mutation_type  = excluded.mutation_type,
    classis        = excluded.classis,
    breakthrough_lv = excluded.breakthrough_lv,
    speciality_id  = excluded.speciality_id,
    ball_id        = excluded.ball_id,
    attributes_json = excluded.attributes_json,
    skills_json    = excluded.skills_json,
    base_conf_id   = excluded.base_conf_id,
    colorful_conf_id = excluded.colorful_conf_id,
    glass_type     = excluded.glass_type,
    glass_value    = excluded.glass_value,
    worn_medal_id  = excluded.worn_medal_id,
    is_trial_pet   = excluded.is_trial_pet,
    is_mirror_pet  = excluded.is_mirror_pet,
    updated_at     = excluded.updated_at
"""

_SELECT_PETS = """
SELECT gid, conf_id, name, level, exp, nature, gender, blood_id, talent_rank, is_first_catch,
       attr_hp, attr_atk, attr_spa, attr_def, attr_spd, attr_spe,
       height, weight, voice, mutation_type, classis, breakthrough_lv,
       speciality_id, ball_id, attributes_json, skills_json, base_conf_id,
       colorful_conf_id, glass_type, glass_value, worn_medal_id, is_trial_pet, is_mirror_pet
FROM pets WHERE uid = ? ORDER BY gid
"""

_SELECT_ACCOUNTS = "SELECT uid, name FROM accounts ORDER BY last_seen DESC"


def _attr_final(pet: Pet, slot: str) -> int:
    return pet.attribute(slot).final_value


def _attributes_to_json(pet: Pet) -> str:
    """六维明细 JSON（种族值/天赋/努力等），空值也序列化以保持列语义一致。"""
    return json.dumps(
        [
            {
                "total_race": a.total_race,
                "talent": a.talent,
                "base_value": a.base_value,
                "effort_add": a.effort_add,
                "talent_add": a.talent_add,
            }
            for a in pet.attributes
        ],
        separators=(",", ":"),
    )


def _skills_to_json(pet: Pet) -> str:
    return json.dumps(
        [
            {
                "skill_id": s.skill_id,
                "conf_idx": s.conf_idx,
                "is_learned": s.is_learned,
                "is_equipped": s.is_equipped,
                "pos": s.pos,
                "unlock_need_lv": s.unlock_need_lv,
                "use_times": s.use_times,
            }
            for s in pet.skills
        ],
        separators=(",", ":"),
    )


def _attributes_from_json(text: str) -> tuple[PetAttribute, ...]:
    if not text:
        return ()
    try:
        items = json.loads(text)
    except (TypeError, ValueError):
        return ()
    if not isinstance(items, list):
        return ()
    return tuple(
        PetAttribute(
            total_race=int(item.get("total_race", 0) or 0),
            talent=int(item.get("talent", 0) or 0),
            base_value=int(item.get("base_value", 0) or 0),
            effort_add=int(item.get("effort_add", 0) or 0),
            talent_add=int(item.get("talent_add", 0) or 0),
        )
        for item in items
        if isinstance(item, dict)
    )


def _skills_from_json(text: str) -> tuple[PetSkill, ...]:
    if not text:
        return ()
    try:
        items = json.loads(text)
    except (TypeError, ValueError):
        return ()
    if not isinstance(items, list):
        return ()
    return tuple(
        PetSkill(
            skill_id=int(item.get("skill_id", 0) or 0),
            conf_idx=int(item.get("conf_idx", 0) or 0),
            is_learned=bool(item.get("is_learned")),
            is_equipped=bool(item.get("is_equipped")),
            pos=int(item.get("pos", 0) or 0),
            unlock_need_lv=int(item.get("unlock_need_lv", 0) or 0),
            use_times=int(item.get("use_times", 0) or 0),
        )
        for item in items
        if isinstance(item, dict)
    )


class PetStore:
    """宠物写回缓存与批量落盘；写入方（抓包线程）永不等待磁盘。"""

    def __init__(self, database: Database, *, flush_interval: float = DEFAULT_FLUSH_INTERVAL) -> None:
        self._db = database
        self._flush_interval = max(0.05, float(flush_interval))
        self._lock = threading.Lock()
        # 批次串行化：保护「换出批次 → 写库/失败回填」整段顺序。待写表锁
        # 保持短促（put 不等磁盘）；落盘锁保证并发 flush 按取出顺序提交，
        # 旧批次不会在新批次之后落库把值拉回去（R02）。
        self._flush_lock = threading.Lock()
        self._pending: dict[tuple[int, int], Pet] = {}
        self._pending_accounts: dict[int, tuple[str, int]] = {}
        self._pending_locations: dict[int, Backpack] = {}
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._closed = False
        self._written = 0

    # -- 写入（任意线程，无 IO）----------------------------------------
    def put(self, uid: int, pets: Iterable[Pet]) -> None:
        """并入待写表（重复 (uid, gid) 以最新为准）；不落盘、不阻塞。"""
        if uid <= 0:
            return
        accepted = [pet for pet in pets if pet.gid > 0]
        if not accepted:
            return
        with self._lock:
            if self._closed:
                logger.warning("PetStore 已关闭，忽略 %d 只宠物的写入", len(accepted))
                return
            for pet in accepted:
                self._pending[(uid, pet.gid)] = pet
            self._ensure_worker_locked()

    def put_account(self, uid: int, name: str, level: int) -> None:
        if uid <= 0:
            return
        with self._lock:
            if self._closed:
                return
            self._pending_accounts[uid] = (name or "", int(level or 0))
            self._ensure_worker_locked()

    # -- 落盘 ----------------------------------------------------------
    def put_locations(self, uid: int, locations: dict[int, PetLocation]) -> None:
        self.put_backpack(uid, Backpack.from_locations(locations))

    def put_backpack(self, uid: int, backpack: Backpack) -> None:
        if uid <= 0:
            return
        with self._lock:
            if not self._closed:
                self._pending_locations[uid] = Backpack(dict(backpack.boxes), backpack.teams, backpack.active_team)
                self._ensure_worker_locked()

    def load_locations(self, uid: int) -> dict[int, PetLocation]:
        return self.load_backpack(uid).locations()

    def load_backpack(self, uid: int) -> Backpack:
        rows = self._db.query("SELECT snapshot_json FROM pet_locations WHERE uid = ?", (uid,))
        try:
            raw = json.loads(rows[0]["snapshot_json"]) if rows else []
            return Backpack.restore(raw)
        except (ValueError, TypeError, KeyError, AttributeError):
            return Backpack()

    def flush(self) -> int:
        """把待写表批量写入 SQLite；返回本次写入的宠物条数。

        线程安全：待写表在校验锁内整体换出；整次提交由落盘锁串行化，
        并发调用按取得批次的先后顺序写库，旧批次不可能后到覆盖新值。
        """
        with self._lock:
            pets = self._pending
            accounts = self._pending_accounts
            locations = self._pending_locations
            self._pending = {}
            self._pending_accounts = {}
            self._pending_locations = {}
        if not pets and not accounts and not locations:
            return 0
        with self._flush_lock:
            return self._commit_batch(pets, accounts, locations)

    def _commit_batch(
        self,
        pets: dict[tuple[int, int], Pet],
        accounts: dict[int, tuple[str, int]],
        locations: dict[int, Backpack],
    ) -> int:
        now = time.time()
        try:
            if accounts:
                self._db.execute_many(
                    _UPSERT_ACCOUNT,
                    [(uid, name, level, now, now) for uid, (name, level) in accounts.items()],
                )
            if pets:
                self._db.execute_many(
                    _UPSERT_PET,
                    [
                        (
                            uid, pet.gid, pet.conf_id, pet.name, pet.level, pet.exp,
                            pet.nature, pet.gender, pet.blood_id, pet.talent_rank,
                            int(pet.is_first_catch), now, now,
                            _attr_final(pet, "hp"), _attr_final(pet, "atk"),
                            _attr_final(pet, "spa"), _attr_final(pet, "def"),
                            _attr_final(pet, "spd"), _attr_final(pet, "spe"),
                            pet.height, pet.weight, pet.voice, pet.mutation_type,
                            pet.classis, pet.breakthrough_lv, pet.speciality_id, pet.ball_id,
                            _attributes_to_json(pet), _skills_to_json(pet), pet.base_conf_id,
                            pet.colorful_conf_id, pet.glass_type, pet.glass_value, pet.worn_medal_id,
                            int(pet.is_trial_pet),
                            int(pet.is_mirror_pet),
                        )
                        for (uid, _gid), pet in pets.items()
                    ],
                )
            if locations:
                self._db.execute_many(
                    "INSERT INTO pet_locations (uid, snapshot_json) VALUES (?, ?) ON CONFLICT(uid) DO UPDATE SET snapshot_json = excluded.snapshot_json",
                    [(uid, json.dumps(snapshot.record(), ensure_ascii=False)) for uid, snapshot in locations.items()],
                )
        except sqlite3.Error as exc:
            logger.warning("宠物写库失败，留待下轮重试: %s", exc)
            with self._lock:
                for key, pet in pets.items():  # 新值优先：不覆盖期间已合并的新数据
                    self._pending.setdefault(key, pet)
                for uid, info in accounts.items():
                    self._pending_accounts.setdefault(uid, info)
                for uid, snapshot in locations.items():
                    self._pending_locations.setdefault(uid, snapshot)
            return 0
        with self._lock:
            self._written += len(pets)
        return len(pets)

    # -- 读取 ----------------------------------------------------------
    def load(self, uid: int) -> tuple[Pet, ...]:
        """读取某账号全部宠物（按 gid 排序）；无记录返回空元组。"""
        if uid <= 0:
            return ()
        rows = self._db.query(_SELECT_PETS, (uid,))
        return tuple(
            Pet(
                gid=int(row["gid"]),
                conf_id=int(row["conf_id"]),
                name=str(row["name"]),
                level=int(row["level"]),
                exp=int(row["exp"]),
                nature=int(row["nature"]),
                gender=int(row["gender"]),
                blood_id=int(row["blood_id"]),
                talent_rank=int(row["talent_rank"]),
                is_first_catch=bool(row["is_first_catch"]),
                base_conf_id=int(row["base_conf_id"]),
                attributes=_attributes_from_json(str(row["attributes_json"] or "")),
                height=int(row["height"]),
                weight=int(row["weight"]),
                voice=int(row["voice"]),
                mutation_type=int(row["mutation_type"]),
                classis=int(row["classis"]),
                breakthrough_lv=int(row["breakthrough_lv"]),
                speciality_id=int(row["speciality_id"]),
                ball_id=int(row["ball_id"]),
                colorful_conf_id=int(row["colorful_conf_id"]),
                glass_type=int(row["glass_type"]),
                glass_value=int(row["glass_value"]),
                worn_medal_id=int(row["worn_medal_id"]),
                is_trial_pet=bool(row["is_trial_pet"]),
                is_mirror_pet=bool(row["is_mirror_pet"]),
                skills=_skills_from_json(str(row["skills_json"] or "")),
            )
            for row in rows
        )

    def list_accounts(self) -> tuple[tuple[int, str], ...]:
        """本地库中有历史的账号（uid, 名字），按最近活跃优先。"""
        rows = self._db.query(_SELECT_ACCOUNTS)
        return tuple((int(row["uid"]), str(row["name"])) for row in rows)

    def load_account(self, uid: int) -> tuple[int, str, int] | None:
        rows = self._db.query("SELECT uid, name, level FROM accounts WHERE uid = ?", (uid,))
        return (int(rows[0]["uid"]), str(rows[0]["name"]), int(rows[0]["level"])) if rows else None

    # -- 生命周期 ------------------------------------------------------
    def close(self) -> None:
        """停止 worker 并做最后一次落盘（退出不丢数据）。"""
        with self._lock:
            self._closed = True
        self._stop.set()
        worker = self._worker
        if worker is not None:
            worker.join(timeout=5)
        self.flush()

    def _ensure_worker_locked(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._run, name="spritelens-pet-store", daemon=True)
        self._worker.start()

    def _run(self) -> None:
        while not self._stop.wait(self._flush_interval):
            self.flush()

    # -- 观测 ----------------------------------------------------------
    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    @property
    def written_count(self) -> int:
        with self._lock:
            return self._written


__all__ = ["DEFAULT_FLUSH_INTERVAL", "PetStore"]
