"""智能配窝：纯规则、模拟几何和逐母本评估。无 IO、无真实游戏控制。"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from spritelens.domain.breeder_library import Candidate, can_pair
from spritelens.domain.breeding_nature import parent_nature_reference
from spritelens.domain.eggs import EggCatalog
from spritelens.domain.measurements import range_position
from spritelens.domain.pet_marks import pet_marks
from spritelens.domain.pets import Pet
from spritelens.domain.static_data import StaticData

RULE_VERSION = "planner-dual-mark-v1"
GEOMETRY_VERSION = "community-grid-v1"
# 20×20 草图内的窝中心坐标上限（2×2 占地、中心吸附半格），与页面画布一致。
# 手动编辑保留对称的负坐标边界，避免位于 (0, 0) 的旧布局无法继续向左上拖动。
BOARD_MIN = -18
BOARD_MAX = 18
UNKNOWN_GROUPS = {"未知", "未发现", "暂无蛋组", "暂无", ""}
INFERTILE_GROUPS = {"无", "无法孵蛋", "无蛋组"}


@dataclass(frozen=True)
class Goal:
    goal_id: str
    egg_key: str
    size_mark: str = ""
    voice_mark: str = ""
    nature_id: int = 0
    priority: int = 0

    @property
    def marks(self) -> set[str]:
        return {value for value in (self.size_mark, self.voice_mark) if value}


@dataclass(frozen=True)
class Placement:
    gid: str
    x: float
    y: float
    kind: str = "normal"
    lock: str = ""
    primary_goal_id: str = ""


@dataclass(frozen=True)
class Request:
    mode: str = "target"
    goals: tuple[Goal, ...] = ()
    selected: tuple[str, ...] = ()
    participation: str = "best"
    capacity: int = 10
    academy: bool = False
    placements: tuple[Placement, ...] = ()
    approved: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Pool:
    parents: dict[str, Candidate]
    eggs: dict[str, str]
    natures: dict[int, str]
    issues: tuple[str, ...] = ()
    egg_names: dict[str, str] = field(default_factory=dict)


def build_pool(pets: tuple[Pet, ...], static: StaticData, eggs: EggCatalog,
               overrides: dict[int, int]) -> Pool:
    accepted, issues = [], []
    # 保留已知有效蛋组；显式不可繁育与有效组共存属于资料冲突。
    for pet in pets:
        species = static.species(pet.base_conf_id)
        if pet.is_trial_pet or pet.is_mirror_pet or species is None or pet.gender not in (1, 2):
            continue
        groups = tuple(g for g in species.egg_groups if g not in UNKNOWN_GROUPS | INFERTILE_GROUPS)
        if any(g in INFERTILE_GROUPS for g in species.egg_groups):
            if groups:
                issues.append(f"个体 {pet.gid} 的蛋组资料冲突")
            continue
        if not groups:
            continue
        voice = overrides.get(pet.gid, pet.voice if pet.voice else None)
        nature = static.nature(pet.nature)
        accepted.append(Candidate(pet, species, nature.name if nature else "", groups,
                                  species.chain_members, tuple(pet_marks(replace(pet, voice=voice or 0), species.weight_range)),
                                  range_position(pet.height, species.height_range)["ratio"],
                                  range_position(pet.weight, species.weight_range)["ratio"], voice))
    parents = {str(p.pet.gid): p for p in accepted}
    egg_map = {gid: egg.egg_key for gid, p in parents.items()
               if (egg := eggs.egg_by_base_id(p.pet.base_conf_id)) is not None and egg.egg_type_name in ("普通", "普通蛋")}
    return Pool(parents, egg_map, {key: value.name for key, value in static.nature_items()}, tuple(issues),
                {egg.egg_key: egg.egg_name for egg in eggs.entries()})


def pair_key(goal: Goal, male: str, female: str) -> str:
    return f"{goal.goal_id}:{male}:{female}"


def pair_match(pool: Pool, male: str, female: str, goal: Goal) -> dict:
    m, f = pool.parents[male], pool.parents[female]
    shared = {v["name"] for v in m.marks} & {v["name"] for v in f.marks}
    result = {"kind": "none", "missing_marks": sorted(goal.marks - shared), "gap": None,
              "missing_parent": None, "candidate_voice": None, "candidate_weight_ratio": None,
              "candidate_weight": None, "candidate_species": None, "anchor_voice": None,
              "inheritance_status": "near_unverified", "voice_range": None,
              "offspring_size_range": None, "joint_support": None, "minimum_candidate_voice": None,
              "minimum_candidate_weight": None, "evidence": "遗传范围未核实，仅作培养方向参考"}
    if pool.eggs.get(female) != goal.egg_key or not can_pair(m, f, False):
        return result
    if not result["missing_marks"]:
        return {**result, "kind": "exact"}
    if len(result["missing_marks"]) != 1:
        return result
    mark = result["missing_marks"][0]
    tags = [{v["name"] for v in p.marks} for p in (m, f)]
    opposite = {"婉转声": "粗嗓门", "粗嗓门": "婉转声", "大块头": "小不点", "小不点": "大块头"}[mark]
    if opposite in tags[0] | tags[1] or (mark in tags[0]) == (mark in tags[1]):
        return result
    index = 0 if mark not in tags[0] else 1
    parent = (m, f)[index]
    result["missing_parent"] = (male, female)[index]
    result["candidate_species"] = parent.species.name
    result["candidate_weight"] = parent.pet.weight if parent.pet.weight > 0 else None
    result["anchor_voice"] = (f, m)[index].voice
    if mark in ("婉转声", "粗嗓门"):
        result["candidate_voice"] = parent.voice
        result["gap"] = max(0, 96 - parent.voice if mark == "婉转声" else parent.voice + 96) if parent.voice is not None else None
    else:
        ratio = parent.weight
        result["candidate_weight_ratio"] = ratio
        result["gap"] = max(0, .98 - ratio if mark == "大块头" else ratio - .02) if ratio is not None and 0 <= ratio <= 1 else None
    result["kind"] = "iterative" if result["gap"] is not None else "unknown"
    return result


def overlaps(a: Placement, b: Placement) -> bool:
    return abs(a.x - b.x) < 2 and abs(a.y - b.y) < 2


def nature_reference(m: Candidate, f: Candidate, male: Placement, female: Placement) -> dict:
    return parent_nature_reference(m.nature, f.nature, male_academy=male.kind == "academy", female_academy=female.kind == "academy")


def evaluate(pool: Pool, request: Request, placements: tuple[Placement, ...]) -> dict:
    issues = []
    target_chain_ids = {
        member
        for goal in request.goals
        for gid, candidate in pool.parents.items()
        if candidate.pet.gender == 2 and pool.eggs.get(gid) == goal.egg_key
        for member in candidate.chain
    }
    if request.mode == "selected" and request.participation == "all":
        if len(request.selected) > request.capacity + int(request.academy):
            issues.append("全部参与的精灵数量超过当前小窝容量")
        missing = set(request.selected) - pool.parents.keys()
        if missing:
            issues.append("当前记录未找到可繁育必选个体：" + "、".join(sorted(missing)))
    ids = [p.gid for p in placements]
    if len(ids) != len(set(ids)):
        issues.append("同一个体不能入住多个小窝")
    if len([p for p in placements if p.kind == "normal"]) > request.capacity or sum(p.kind == "academy" for p in placements) > int(request.academy):
        issues.append("布局超过当前普通窝或学院绿窝容量")
    if any(p.kind == "academy" and p.gid in pool.parents and pool.parents[p.gid].pet.gender != 2 for p in placements):
        issues.append("学院绿窝必须放置母本")
    for old in request.placements:
        current = next((p for p in placements if p.gid == old.gid), None)
        if old.lock and (current is None or old.lock == "position" and (current.x, current.y, current.kind) != (old.x, old.y, old.kind)):
            issues.append(f"个体 {old.gid} 的锁定约束未满足")
    for i, p in enumerate(placements):
        if p.gid not in pool.parents:
            issues.append(f"当前记录未找到可繁育个体 {p.gid}")
        if any(overlaps(p, q) for q in placements[:i]):
            issues.append("小窝占地发生重叠")
        if not (BOARD_MIN <= p.x <= BOARD_MAX and BOARD_MIN <= p.y <= BOARD_MAX):
            issues.append("草稿中有窝位超出 20×20 草图范围，请重新规划或调整位置")
    if issues:
        return {"status": "invalid", "issues": issues, "edges": [], "mothers": [], "goals": [], "score": (), "metrics": {}}
    edges, mothers = [], []
    for fpos in placements:
        f = pool.parents[fpos.gid]
        if f.pet.gender != 2:
            continue
        father_edges = []
        for mpos in placements:
            m = pool.parents[mpos.gid]
            if abs(mpos.x - fpos.x) + abs(mpos.y - fpos.y) > 5 or not can_pair(m, f, False):
                continue
            matches = {g.goal_id: pair_match(pool, mpos.gid, fpos.gid, g) for g in request.goals}
            edge = {"male": mpos.gid, "female": fpos.gid,
                    "groups": sorted(set(m.groups) & set(f.groups)),
                    "marks": sorted({v["name"] for v in m.marks} & {v["name"] for v in f.marks}),
                    "nature": nature_reference(m, f, mpos, fpos), "matches": matches}
            edges.append(edge)
            father_edges.append(edge)
        count = len(father_edges)
        references = []
        for goal in request.goals:
            if pool.eggs.get(fpos.gid) != goal.egg_key:
                continue
            exact = [e for e in father_edges if e["matches"][goal.goal_id]["kind"] == "exact"]
            iterative = [e for e in father_edges if e["matches"][goal.goal_id]["kind"] == "iterative" and pair_key(goal, e["male"], fpos.gid) in request.approved]
            nature = pool.natures.get(goal.nature_id, "")
            best_nature = max((e["nature"]["known"].get(nature, 0) for e in exact), default=0)
            references.append({"goal_id": goal.goal_id, "kind": "exact" if exact else "iterative" if iterative else "unknown",
                               "matching_fathers": len(exact), "iterative_fathers": len(iterative), "father_count": count,
                               "father_fraction": len(exact) / count if count else None,
                               "nature_contribution": sum(e["nature"]["known"].get(nature, 0) for e in exact) / count if count and goal.nature_id else None,
                               "interference": [e["male"] for e in father_edges if e not in exact or goal.nature_id and e["nature"]["known"].get(nature, 0) < best_nature],
                               "all_father_nature_contribution": sum(e["nature"]["known"].get(nature, 0) for e in father_edges) / count if count and goal.nature_id else None})
        distribution: dict[str, float] = {}
        for e in father_edges:
            for name, share in e["nature"]["known"].items():
                distribution[name] = distribution.get(name, 0) + share / count
        mothers.append({"gid": fpos.gid, "egg_key": pool.eggs.get(fpos.gid), "fathers": [e["male"] for e in father_edges],
                        "references": references, "primary_goal_id": fpos.primary_goal_id,
                        "nature": {"known": distribution, "random": sum(e["nature"]["random"] for e in father_edges) / count if count else None,
                                   "unknown": sum(e["nature"]["unknown"] for e in father_edges) / count if count else None}})
    # 每只母本只占一个主目标名额，先覆盖、再集中到库存优势目标。
    strength = {g.goal_id: sum(pool.eggs.get(gid) == g.egg_key and g.marks <= {v["name"] for v in p.marks} for gid, p in pool.parents.items() if p.pet.gender == 2) for g in request.goals}
    assigned: dict[str, list[dict]] = {g.goal_id: [] for g in request.goals}
    unassigned = list(mothers)
    ordered = sorted(request.goals, key=lambda g: (-g.priority, -strength[g.goal_id], g.goal_id))
    for goal in ordered:
        manual = [m for m in unassigned if m["primary_goal_id"] == goal.goal_id]
        for mother in manual:
            assigned[goal.goal_id].append(mother)
            unassigned.remove(mother)
    for goal in ordered:
        if assigned[goal.goal_id]:
            continue
        choices = [m for m in unassigned if any(r["goal_id"] == goal.goal_id and r["kind"] != "unknown" for r in m["references"])]
        if choices:
            mother = min(choices, key=lambda m: (sum(r["kind"] != "unknown" for r in m["references"]), m["gid"]))
            mother["primary_goal_id"] = goal.goal_id
            assigned[goal.goal_id].append(mother)
            unassigned.remove(mother)
    for mother in unassigned:
        goal = next((g for g in ordered if any(r["goal_id"] == g.goal_id and r["kind"] != "unknown" for r in mother["references"])), None)
        if goal:
            mother["primary_goal_id"] = goal.goal_id
            assigned[goal.goal_id].append(mother)
    results = []
    for goal in ordered:
        refs = [r for m in assigned[goal.goal_id] for r in m["references"] if r["goal_id"] == goal.goal_id]
        good = [r for r in refs if r["kind"] != "unknown"]
        all_refs = [r for m in mothers for r in m["references"] if r["goal_id"] == goal.goal_id]
        supported = [r for r in all_refs if r["kind"] != "unknown"]
        results.append({"goal_id": goal.goal_id, "covered": bool(supported), "mother_count": len(good),
                        "shared_mothers": len(supported) - len(good),
                        "exact_mothers": sum(r["kind"] == "exact" for r in good),
                        "ready": any(r["kind"] == "exact" and r["father_fraction"] == 1 and not r["interference"] and (not goal.nature_id or (r["nature_contribution"] or 0) > 0) for r in supported),
                        "reason": "" if supported else "当前布局未覆盖；可检查库存、容量、锁定或重新规划"})
    score = []
    for priority in (1, 0):
        subset = [r for r in results if next(g for g in ordered if g.goal_id == r["goal_id"]).priority == priority]
        score.extend((sum(r["covered"] for r in subset), sum(r["mother_count"] for r in subset)))
    score.extend(r["mother_count"] for r in results)
    refs = [r for m in mothers for r in m["references"] if r["goal_id"] == m["primary_goal_id"]]
    connected = {e[key] for e in edges for key in ("male", "female")}
    score.extend((sum(r["exact_mothers"] for r in results), sum(r["father_fraction"] == 1 for r in refs),
                  sum(r["nature_contribution"] or 0 for r in refs), sum(r["father_fraction"] or 0 for r in refs),
                  -sum(len(r["interference"]) for r in refs)))
    iterative_edges = [(g, e["matches"][g.goal_id]) for g in request.goals for e in edges
                       if e["matches"][g.goal_id]["kind"] == "iterative" and pair_key(g, e["male"], e["female"]) in request.approved]
    score.extend((-sum(match["gap"] for g, match in iterative_edges if match["missing_marks"][0] == g.voice_mark),
                  -sum(match["gap"] for g, match in iterative_edges if match["missing_marks"][0] == g.size_mark)))
    if request.mode == "selected":
        score = [sum(bool(m["fathers"]) for m in mothers), len(connected), sum(len(e["marks"]) for e in edges)]
    males = sum(pool.parents[p.gid].pet.gender == 1 for p in placements)
    females = sum(pool.parents[p.gid].pet.gender == 2 for p in placements)
    same_chain = sum(bool(set(pool.parents[p.gid].chain) & target_chain_ids) for p in placements)
    # 先保证所有入住精灵都在有效连线中，再尽量填满容量；同等方案下平衡公母并偏好目标蛋进化链。
    score.extend((-sum(p.gid not in connected for p in placements), len(placements), -abs(males - females), same_chain))
    academy_nature_matches = sum(
        any(pool.parents[p.gid].pet.nature == goal.nature_id and goal.nature_id and pool.eggs.get(p.gid) == goal.egg_key
            for goal in request.goals)
        for p in placements
        if p.kind == "academy" and p.gid in pool.parents and pool.parents[p.gid].pet.gender == 2
    )
    score.append(academy_nature_matches)
    required = set(request.selected) if request.mode == "selected" and request.participation == "all" else {p.gid for p in request.placements if p.lock}
    ready = required <= connected and (all(r["ready"] for r in results) and all(r["kind"] == "exact" and r["father_fraction"] == 1 and not r["interference"] for r in refs) if request.mode == "target" else True)
    if required - connected:
        names = [pool.parents[gid].pet.name or str(gid) for gid in sorted(required - connected) if gid in pool.parents]
        issues.append("必须参与但尚未形成兼容连线：" + "、".join(names))
    return {"status": "no_plan" if not edges else "ready" if ready else "partial", "issues": issues,
            "edges": edges, "mothers": mothers, "goals": results, "score": tuple(score),
            "metrics": {"males": males,
                        "females": females, "effective_mothers": sum(bool(m["fathers"]) for m in mothers),
                        "gender_gap": abs(males - females), "same_chain": same_chain,
                        "academy_nature_matches": academy_nature_matches,
                        "unused_slots": request.capacity + int(request.academy) - len(placements)}}
