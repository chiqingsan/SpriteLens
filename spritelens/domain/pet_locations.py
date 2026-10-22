"""真实箱表：零为空格，None 为尚未采集；只消费服务端快照与移动。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PetLocation:
    box_id: int
    slot: int

    def payload(self) -> dict:
        return {"box_id": self.box_id, "slot": self.slot,
                "row": (self.slot - 1) // 6 + 1, "column": (self.slot - 1) % 6 + 1}


@dataclass(frozen=True)
class PetBox:
    box_id: int
    slots: tuple[int | None, ...]
    name: str = ""
    historical: bool = False


@dataclass(frozen=True)
class Backpack:
    boxes: dict[int, PetBox] = field(default_factory=dict)
    teams: tuple[PetBox, ...] = ()
    active_team: int | None = None

    def locations(self) -> dict[int, PetLocation]:
        return {gid: PetLocation(box.box_id, slot)
                for box in self.boxes.values() for slot, gid in enumerate(box.slots, 1) if gid}

    @classmethod
    def from_locations(cls, locations: dict[int, PetLocation]) -> Backpack:
        slots = {}
        for gid, location in locations.items():
            slots.setdefault(location.box_id, [None] * 30)[location.slot - 1] = gid
        return cls({box: PetBox(box, tuple(values), historical=True) for box, values in slots.items()})

    def record(self) -> dict:
        return {"version": 2, "boxes": [{"box_id": b.box_id, "slots": list(b.slots), "name": b.name}
                                        for b in self.boxes.values()],
                "teams": [{"team_id": b.box_id, "slots": list(b.slots), "name": b.name} for b in self.teams],
                "active_team": self.active_team}

    @classmethod
    def restore(cls, raw) -> Backpack:
        if not isinstance(raw, dict) or raw.get("version") != 2:
            raise ValueError("箱位快照不是当前 version 2 格式")
        boxes = {}
        if isinstance(raw, dict) and raw.get("version") == 2:
            for entry in raw.get("boxes", []):
                box, slots = entry.get("box_id"), entry.get("slots")
                if (type(box) is int and box > 0 and isinstance(slots, list) and len(slots) == 30
                        and all(gid is None or type(gid) is int and gid >= 0 for gid in slots)):
                    boxes[box] = PetBox(box, tuple(slots), str(entry.get("name") or ""), True)
        teams = []
        if isinstance(raw, dict):
            for entry in raw.get("teams", []):
                team, slots = entry.get("team_id"), entry.get("slots")
                if (type(team) is int and 1 <= team <= 3 and isinstance(slots, list) and len(slots) == 6
                        and all(gid is None or type(gid) is int and gid >= 0 for gid in slots)):
                    teams.append(PetBox(team, tuple(slots), str(entry.get("name") or ""), True))
        active = raw.get("active_team") if isinstance(raw, dict) else None
        return cls(boxes, tuple(teams), active if type(active) is int and 1 <= active <= 3 else None)


def update_backpack(event, previous: Backpack) -> Backpack | None:
    if event.direction != "s2c":
        return None
    boxes = dict(previous.boxes)
    teams = previous.teams
    active_team = previous.active_team
    changed = False
    if getattr(event, "opcode", None) == 0x0102 and any(f.get("name") == "player_info" for f in event.decoded):
        boxes = {}
        teams = ()
        active_team = None
        changed = True

    def remove(gid):
        for box_id, box in list(boxes.items()):
            if gid in box.slots:
                boxes[box_id] = PetBox(box_id, tuple(0 if value == gid else value for value in box.slots), box.name, box.historical)

    def remove_from_team(gid):
        nonlocal teams
        teams = tuple(PetBox(team.box_id, tuple(0 if value == gid else value for value in team.slots), team.name, team.historical) for team in teams)

    def walk(fields, path=()):
        nonlocal changed, teams, active_team
        for node in fields:
            children = node.get("children") or []
            values = {item.get("no"): item.get("raw") for item in children}
            if node.get("type") == "PetBox":
                box_id = values.get(1)
                slots = [item.get("raw") for item in children if item.get("no") == 3]
                if (type(box_id) is int and box_id > 0 and len(slots) == 30
                        and all(type(gid) is int and gid >= 0 for gid in slots)
                        and len([gid for gid in slots if gid]) == len(set(gid for gid in slots if gid))):
                    for gid in slots:
                        if gid:
                            remove(gid)
                            remove_from_team(gid)
                    name = values.get(5, "")
                    if isinstance(name, bytes):
                        name = name.decode("utf-8", errors="replace")
                    boxes[box_id] = PetBox(box_id, tuple(slots), name if isinstance(name, str) else "")
                    changed = True
            elif node.get("type") == "PetBoxPetChange":
                gid, team, box_id, slot = (values.get(no) for no in (1, 2, 3, 4))
                if team == 1 and type(gid) is int and gid > 0:
                    remove(gid)
                    changed = True
                elif (team == 0 and type(gid) is int and gid >= 0 and type(box_id) is int and box_id > 0
                      and type(slot) is int and 1 <= slot <= 30):
                    if gid:
                        remove(gid)
                        remove_from_team(gid)
                    old = boxes.get(box_id, PetBox(box_id, (None,) * 30))
                    slots = list(old.slots)
                    slots[slot - 1] = gid
                    boxes[box_id] = PetBox(box_id, tuple(slots), old.name, old.historical)
                    changed = True
            elif (node.get("type") == "PetTeamInfo" and values.get(4) == 1
                  and (path == ("player_info", "pet_info")
                       or path[-3:] == ("ret_info", "goods_change_info", "changes"))):
                # 用户星星眼的 1队1格 / 2队4格 / 3队2格实测证实列表顺序。
                entries = [item for item in children if item.get("no") == 2]
                if len(entries) == 3:
                    parsed = []
                    for team_id, entry in enumerate(entries, 1):
                        fields_by_no = {item.get("no"): item.get("raw") for item in entry.get("children") or []}
                        members = [item for item in entry.get("children") or [] if item.get("no") == 2]
                        if len(members) > 6 or fields_by_no.get(6) == 1:
                            break
                        slots = []
                        for member in members:
                            raw = {item.get("no"): item.get("raw") for item in member.get("children") or []}
                            gid = raw.get(1, 0)
                            slots.append(gid if type(gid) is int and gid >= 0 and raw.get(3) != 1 else None)
                        name = fields_by_no.get(3, "")
                        parsed.append(PetBox(team_id, tuple(slots + [0] * (6 - len(slots))), name if isinstance(name, str) else ""))
                    if len(parsed) == 3:
                        teams = tuple(parsed)
                        main = values.get(1, 0)
                        active_team = main + 1 if type(main) is int and 0 <= main <= 2 else None
                        for team in teams:
                            for gid in team.slots:
                                if gid:
                                    remove(gid)
                        changed = True
            walk(children, path + (node.get("name"),))

    walk(event.decoded)
    return Backpack(boxes, teams, active_team) if changed else None


def update_locations(event, previous: dict[int, PetLocation]) -> dict[int, PetLocation] | None:
    updated = update_backpack(event, Backpack.from_locations(previous))
    return updated.locations() if updated is not None else None
