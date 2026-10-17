"""规划输入快照、并发搜索取消及按账号草稿保存。"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json
from threading import Event, Lock

from spritelens.domain.breeding_planner import GEOMETRY_VERSION, RULE_VERSION, Request, build_pool, evaluate
from spritelens.domain.breeding_solver import solve


class StalePlannerInput(ValueError):
    pass


class BreedingPlannerService:
    def __init__(self, repository, static, eggs, settings):
        self.repository, self.static, self.eggs, self.settings = repository, static, eggs, settings
        catalog = {"species": [(key, asdict(value)) for key, value in static.species_items()] if static else [],
                   "natures": [(key, asdict(value)) for key, value in static.nature_items()] if static else [],
                   "eggs": [asdict(value) for value in eggs.entries()] if eggs else [],
                   "mapping": [(key, egg.egg_key) for key, _ in static.species_items()
                               if (egg := eggs.egg_by_base_id(int(key)))] if static and eggs else []}
        self.catalog_version = sha256(json.dumps(catalog, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
        self._lock = Lock()
        self._active: Event | None = None

    def snapshot(self):
        inventory, overrides = self.repository.breeding_snapshot()
        pool = build_pool(inventory.pets, self.static, self.eggs, overrides) if self.static and self.static.available and self.eggs and self.eggs.available else None
        return inventory, pool

    def check(self, uid: int, version: int) -> None:
        inventory = self.repository.consistent_snapshot()
        if inventory.uid != uid or inventory.version != version:
            raise StalePlannerInput("背包或账号已变化，请刷新规划资料后重试；原布局仍保留")

    def calculate(self, uid: int, version: int, request: Request, action: str) -> dict:
        inventory, pool = self.snapshot()
        if inventory.uid != uid or inventory.version != version:
            raise StalePlannerInput("背包或账号已变化，请刷新规划资料后重试")
        if pool is None:
            raise ValueError("静态目录不可用")
        if action == "solve":
            with self._lock:
                if self._active is not None:
                    self._active.set()
                cancel = Event()
                self._active = cancel
            try:
                result = solve(pool, request, cancel)
                if cancel.is_set():
                    raise StalePlannerInput("本次规划已被新请求取消")
            finally:
                with self._lock:
                    if self._active is cancel:
                        self._active = None
        else:
            self.cancel()
            result = evaluate(pool, request, request.placements)
            result = {"plans": [{**result, "plan_id": "adjusted", "placements": [asdict(p) for p in request.placements], "unused_candidates": []}],
                      "status": result["status"], "iterations": [], "issues": [], "search_status": "not_run"}
        self.check(uid, version)
        return {"uid": uid, "version": version, "rule_version": RULE_VERSION,
                "geometry_version": GEOMETRY_VERSION, "catalog_version": self.catalog_version, **result}

    def cancel(self) -> None:
        with self._lock:
            if self._active is not None:
                self._active.set()

    def load_draft(self, uid: int, mode: str):
        return deepcopy(self.settings.get_value(f"breeding-planner.{uid}.{mode}"))

    def save_draft(self, uid: int, version: int, mode: str, draft: dict) -> None:
        if uid <= 0:
            raise ValueError("请先读取账号背包记录")
        self.check(uid, version)
        self.settings.set_checked(f"breeding-planner.{uid}.{mode}", deepcopy(draft))
