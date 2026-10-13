"""F02：跨域状态只发布与宠物展示账号相符的统计，失配保持未知。"""
from __future__ import annotations

from spritelens.services.egg_repository import EggBoxRepository
from spritelens.services.home_repository import HomeRepository
from spritelens.services.flower_repository import FlowerRepository


def account_domains_payload(uid: int, egg_repo: EggBoxRepository | None,
                            home_repo: HomeRepository | None, flower_repo: FlowerRepository | None) -> dict:
    egg = egg_repo.consistent_snapshot() if egg_repo is not None else None
    home = home_repo.consistent_snapshot() if home_repo is not None else None
    flower = flower_repo.consistent_snapshot() if flower_repo is not None else None

    def status(owner: int, version: int, source: str) -> dict:
        return {"uid": owner, "version": version, "consistent": owner == uid,
                "source": source if owner == uid else "unknown", "complete": None}

    domains = {
        "egg_box": status(egg.uid, egg.version, egg.source) if egg else status(0, 0, "unknown"),
        "home": status(home.uid, home.version, "stale" if home.pending_deltas and home.data else "observed" if home.data else "unknown") if home else status(0, 0, "unknown"),
        "flowers": status(flower.uid, flower.version, "observed" if flower.data else "unknown") if flower else status(0, 0, "unknown"),
    }
    return {
        "domains": domains,
        "egg_box_version": domains["egg_box"]["version"],
        "egg_box_total": len(egg.entries) if egg and domains["egg_box"]["consistent"] and egg.source != "unknown" else None,
        "home_version": domains["home"]["version"],
        "flower_version": domains["flowers"]["version"],
    }
