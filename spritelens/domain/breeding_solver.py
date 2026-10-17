"""有预算的确定性联合选配与有限网格摆位搜索。"""
from __future__ import annotations

from dataclasses import asdict, replace
from itertools import zip_longest
from threading import Event
from time import monotonic

from spritelens.domain.breeder_library import can_pair
from spritelens.domain.breeding_planner import (
    Placement, Pool, Request, evaluate, overlaps, pair_key, pair_match,
)


def opportunities(pool: Pool, request: Request, cancel: Event) -> tuple[list[dict], set[str], dict[str, bool | None], list[tuple[str, str]], bool]:
    iterations, useful, exact_goals = [], set(), {}
    buckets: dict[tuple, list[str]] = {}
    for gid, parent in pool.parents.items():
        if parent.pet.gender == 1:
            key = (tuple(sorted(parent.groups)), tuple(sorted(m["name"] for m in parent.marks)))
            buckets.setdefault(key, []).append(gid)
    females = sorted(gid for gid, p in pool.parents.items() if p.pet.gender == 2)
    pairs = []
    exact_goals = {g.goal_id: None for g in request.goals}
    checked, stopped = 0, False
    deadline = monotonic() + 1
    for goal in request.goals:
        candidates = []
        exact_goals[goal.goal_id] = False
        ranked_buckets = [sorted(ids, key=lambda gid: (pool.parents[gid].pet.nature != goal.nature_id,
                            -(pool.parents[gid].voice or 0) if goal.voice_mark == "婉转声" else pool.parents[gid].voice or 0,
                            -(pool.parents[gid].weight or 0) if goal.size_mark == "大块头" else pool.parents[gid].weight or 0, gid)) for ids in buckets.values()]
        for female in females:
            if cancel.is_set() or checked >= 60000 or monotonic() > deadline:
                stopped = True
                break
            if pool.eggs.get(female) != goal.egg_key:
                continue
            for ids in ranked_buckets:
                checked += 1
                representative = pair_match(pool, ids[0], female, goal)
                if representative["kind"] == "exact":
                    useful.update((*ids, female))
                    exact_goals[goal.goal_id] = True
                    pairs.append((ids[0], female))
                    continue
                allowed = [gid for gid in ids if pair_key(goal, gid, female) in request.approved]
                for male in dict.fromkeys(ids[:3] + allowed):
                    match = pair_match(pool, male, female, goal)
                    if match["kind"] not in ("iterative", "unknown"):
                        continue
                    key = pair_key(goal, male, female)
                    candidates.append({**match, "key": key, "goal_id": goal.goal_id, "male": male, "female": female,
                                       "approved": key in request.approved})
                    if match["kind"] == "iterative" and key in request.approved:
                        useful.update((male, female))
                        pairs.append((male, female))
        # 先按原始数值缺口排序，未知不冒充数值很差。列表有界，准许项始终保留。
        candidates.sort(key=lambda row: (not row["approved"], row["gap"] is None,
                                        row["missing_marks"][0] not in ("婉转声", "粗嗓门"), row["gap"] or 0, row["key"]))
        if stopped and not exact_goals[goal.goal_id]:
            exact_goals[goal.goal_id] = None
        retained = [row for i, row in enumerate(candidates) if i < 24 or row["approved"]]
        iterations.extend([{**row, "has_exact": exact_goals[goal.goal_id]} for row in retained])
        if stopped:
            break
    return iterations, useful, exact_goals, list(dict.fromkeys(pairs)), stopped


def signature(placements: tuple[Placement, ...], result: dict) -> tuple:
    # 平移/镜像但父本关系和绿窝入住相同，不冒充不同方案。
    return (tuple(sorted(p.gid for p in placements)), tuple(sorted((e["male"], e["female"]) for e in result["edges"])),
            tuple(p.gid for p in placements if p.kind == "academy"))


def solve(pool: Pool, request: Request, cancel: Event, budget: int = 4500) -> dict:
    start = monotonic()
    iterations, useful, exact_goals, pairs, screened_partially = opportunities(pool, request, cancel)
    capacity = request.capacity + int(request.academy)
    base = tuple(replace(p, primary_goal_id="") for p in request.placements if p.lock)
    fixed = [p for p in base if p.lock == "position"]
    anchors = fixed or [Placement("", 2, 2)]
    start_slots = [(p.x + dx, p.y + dy) for p in anchors for dy in (0, -2, 2, 4) for dx in (0, -2, 2, 4)]
    relocated = list(fixed)
    for parent in base:
        if parent.lock == "position":
            continue
        slot = next(((x, y) for x, y in start_slots if not any(overlaps(Placement("", x, y), p) for p in relocated)), None)
        if slot is not None:
            kind = "normal" if sum(p.kind == "normal" for p in relocated) < request.capacity else "academy"
            relocated.append(replace(parent, x=slot[0], y=slot[1], kind=kind))
    base = tuple(relocated)
    selected = set(request.selected)
    issues = list(pool.issues)
    if capacity < 2:
        issues.append("至少需要两个小窝才能形成配对")
    if screened_partially:
        issues.append("候选筛查达到预算；未完整扫描的目标不能据此判断库存缺少合格亲本")
    if request.mode == "selected":
        useful = selected & pool.parents.keys()
        missing = selected - pool.parents.keys()
        if missing:
            issues.append("当前记录未找到可繁育个体：" + "、".join(sorted(missing)))
    else:
        missing = set()
    useful.update(p.gid for p in base)
    invalid = evaluate(pool, request, base)
    if invalid["status"] == "invalid" or request.participation == "all" and request.mode == "selected" and (len(selected) > capacity or missing):
        return {"plans": [], "iterations": iterations, "issues": issues + invalid["issues"] + ["请解除锁定、补齐个体资料或调整容量"], "status": "invalid", "search_status": "not_run", "evaluations": 0}
    # 公母及各目标的候选保留一定宽度；大仓库只作有界推荐，不宣称全局最优。
    def rank(gid: str) -> tuple:
        p = pool.parents[gid]
        return (-sum(g.priority + 1 for g in request.goals if p.pet.nature == g.nature_id), -len(p.marks), gid)
    ordered = sorted(useful, key=rank)
    if len(ordered) > 64 and not (request.mode == "selected" and request.participation == "all"):
        keep = list(dict.fromkeys(p.gid for p in base))
        # 分组仅用于保留搜索候选，不作为产出配额。
        groups = [[gid for gid in ordered if pool.parents[gid].pet.gender == sex and (not egg or pool.eggs.get(gid) == egg)]
                  for sex, egg in [(1, ""), *[(2, egg) for egg in dict.fromkeys(pool.eggs.get(gid, "") for gid in ordered if pool.parents[gid].pet.gender == 2)]]]
        for row in zip_longest(*groups):
            for gid in row:
                if gid is not None and gid not in keep and len(keep) < 64:
                    keep.append(gid)
        ordered = keep
        issues.append("候选较多，本次在有界候选池内搜索")
    pairs = ([(m, f) for m in ordered if pool.parents[m].pet.gender == 1 for f in ordered if can_pair(pool.parents[m], pool.parents[f], False)]
             if request.mode == "selected" else [(m, f) for m, f in pairs if m in ordered and f in ordered])
    # 2×2贴边的紧凑网格与分离簇；固定位置锁周围补充半格候选。
    grids = [((2, 2),) + tuple((x, y) for y in (0, 2, 4) for x in (0, 2, 4, 6) if (x, y) != (2, 2)),
             tuple((x, y) for y in (0, 2) for x in (0, 2, 4, 9, 11, 13))]
    if base:
        grids = [tuple(dict.fromkeys((p.x + dx, p.y + dy) for p in base for dx, dy in ((0, 0), (2, 0), (-2, 0), (0, 2), (0, -2), (2, 2), (-2, -2), (2, -2), (-2, 2), (4, 0), (0, 4), (2.5, 0), (0, 2.5))))]
    seen, best = set(), {}
    previous = tuple(replace(p, primary_goal_id="") for p in request.placements)
    if previous and (request.mode == "target" or {p.gid for p in previous} <= selected):
        assessed = evaluate(pool, request, previous)
        if assessed["status"] != "invalid" and (request.mode == "selected" or any(g["covered"] for g in assessed["goals"])):
            if request.mode != "selected" or request.participation != "all" or {p.gid for p in previous} == selected:
                best[signature(previous, assessed)] = previous, assessed
    evaluations = 0
    halted = False
    for grid in grids:
        beam = [base]
        for _ in range(capacity - len(base) + 1):
            next_states = []
            for placements in beam:
                result = evaluate(pool, request, placements)
                evaluations += 1
                if result["status"] != "invalid":
                    sig = signature(placements, result)
                    if sig not in best or result["score"] > best[sig][1]["score"]:
                        if request.mode != "selected" or request.participation != "all" or set(p.gid for p in placements) == selected:
                            best[sig] = (placements, result)
                if len(placements) >= capacity:
                    continue
                remaining = [gid for gid in ordered if gid not in {p.gid for p in placements}]
                slots = [(x, y) for x, y in grid if not any(overlaps(Placement("", x, y), p) for p in placements)]
                # 多个候选点保留不同配对关系，避免固定公母交替顺序。
                additions = [(gid,) for gid in remaining]
                if len(placements) + 2 <= capacity:
                    additions += [(m, f) for m, f in pairs if m in remaining and f in remaining][:64]
                for residents in additions:
                    for first in slots[:2]:
                        coordinates = [first]
                        if len(residents) == 2:
                            neighbor = next((slot for slot in slots if slot != first and abs(slot[0] - first[0]) + abs(slot[1] - first[1]) <= 5), None)
                            if neighbor is None:
                                continue
                            coordinates.append(neighbor)
                        normal_count = sum(p.kind == "normal" for p in placements)
                        school_free = request.academy and not any(p.kind == "academy" for p in placements)
                        kinds = [tuple("normal" for _ in residents)] if normal_count + len(residents) <= request.capacity else []
                        if school_free and normal_count + len(residents) - 1 <= request.capacity:
                            kinds += [tuple("academy" if i == index else "normal" for i in range(len(residents))) for index in range(len(residents))]
                        for nest_types in kinds:
                            state = placements + tuple(Placement(gid, x, y, kind) for gid, (x, y), kind in zip(residents, coordinates, nest_types))
                            key = tuple(sorted((p.gid, p.x, p.y, p.kind) for p in state))
                            if key in seen:
                                continue
                            seen.add(key)
                            assessed = evaluate(pool, request, state)
                            evaluations += 1
                            if assessed["status"] != "invalid":
                                next_states.append((assessed["score"], key, state))
                            if evaluations >= budget or cancel.is_set() or monotonic() - start > 3:
                                halted = True
                                break
                        if halted:
                            break
                    if halted:
                        break
                if halted:
                    break
            # 收录最后一批已评估结果（预算可能在扩展中耗尽）。
            next_states.sort(key=lambda row: (row[0], row[1]), reverse=True)
            beam = [row[2] for row in next_states[:2]]
            for state in beam:
                result = evaluate(pool, request, state)
                if request.mode != "selected" or request.participation != "all" or {p.gid for p in state} == selected:
                    sig = signature(state, result)
                    if sig not in best or result["score"] > best[sig][1]["score"]:
                        best[sig] = state, result
            if halted or not beam:
                break
        if halted:
            break
    ranked = sorted(best.values(), key=lambda row: (row[1]["score"], tuple(p.gid for p in row[0])), reverse=True)
    connected_plans = [row for row in ranked if row[1]["edges"]]
    winners = connected_plans[:3] if connected_plans else ranked[:1]
    opposite_groups = {gender: {group for gid in request.selected if gid in pool.parents and pool.parents[gid].pet.gender != gender
                               for group in pool.parents[gid].groups} for gender in (1, 2)}
    unused_reasons = {gid: "当前记录未找到可繁育个体" if gid not in pool.parents else
                      "自选池中没有异性且共享蛋组的亲本" if not opposite_groups[pool.parents[gid].pet.gender].intersection(pool.parents[gid].groups)
                      else "容量、摆位或本方案未增加目标收益" for gid in request.selected}
    plans = [{**result, "plan_id": f"plan-{i + 1}", "placements": [asdict(p) for p in positions],
              "unused_candidates": [{"gid": gid, "reason": unused_reasons[gid]} for gid in request.selected if gid not in {p.gid for p in positions}]} for i, (positions, result) in enumerate(winners)]
    for goal in request.goals:
        if exact_goals[goal.goal_id] is False:
            mothers = [p for gid, p in pool.parents.items() if p.pet.gender == 2 and pool.eggs.get(gid) == goal.egg_key]
            male_groups = {group for p in pool.parents.values() if p.pet.gender == 1 for group in p.groups}
            if not mothers:
                reason = "当前记录未找到可产此蛋的母本"
            elif not any(male_groups.intersection(f.groups) for f in mothers):
                reason = "当前记录未找到与目标母本共享蛋组的父本"
            else:
                reason = "未找到双方共有目标奖牌的组合，可查看迭代候选"
            issues.append(f"{pool.egg_names.get(goal.egg_key, '目标蛋')}：{reason}")
    return {"plans": plans, "iterations": iterations, "issues": issues,
            "status": plans[0]["status"] if plans else "no_plan", "search_status": "bounded",
            "evaluations": evaluations, "elapsed_ms": round((monotonic() - start) * 1000)}
