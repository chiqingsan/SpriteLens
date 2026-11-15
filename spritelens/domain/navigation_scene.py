"""供外部客户端晚连接时同步的交互 NPC 快照；仅保留本次连接观察到的事实。"""
from __future__ import annotations

from spritelens.domain.scene import children, integer, nodes, position, removed_ids
from spritelens.events import PacketEvent


NAVIGATION_OPCODES = frozenset({0x0102, 0x0133, 0x0137, 0x014A, 0x0152, 0x015C,
                               0x0413, 0x0414, 0x1316, 0x132C})


class NavigationScene:
    def __init__(self) -> None:
        self.scene_id: int | None = None
        self.scene_generation = 0
        self.player_position: tuple[int | None, int | None, int | None] | None = None
        # 主控朝向，单位 0.1°，0° 指向 +x、顺时针为正（0x0133 的 to_rot.z）。
        # 外部客户端用它画自己的箭头；站立不动时保持最后一次移动方向。
        self.player_heading: int | None = None
        self.position_seq = 0
        self.actors: dict[int, dict] = {}
        # 场景里可见的其他玩家 avatar（ActorInfo.no=12）：奇遇的 create_avatar_id 就是
        # 创建者的 avatar actor_id，所以这个集合能在自身身份未知时判断奇遇归属。
        self.players: dict[int, bool] = {}
        self.battle_id: int | None = None
        self.interacted: int | None = None
        self.interacted_at = 0.0
        # 自身 avatar 的 actor_id：0x0152 进场响应与 0x015C 传送通知都带 self_info，
        # 外部据此比对奇遇的 creator_id（create_avatar_id）判断归属。取不到时保持 None。
        self.self_actor_id: int | None = None

    def submit(self, event: PacketEvent, seq: int) -> None:
        fields, opcode = event.decoded, event.opcode
        if event.direction == "c2s":
            if opcode == 0x0137:
                self.interacted = integer(fields, 1)
                self.interacted_at = event.ts
            elif opcode == 0x0133 and self.battle_id is None:
                scene_id = integer(fields, 17)
                if scene_id is None:
                    return
                if scene_id != self.scene_id:
                    self.scene_generation = seq
                if self.scene_id is not None and scene_id != self.scene_id:
                    self.actors.clear()
                    self.interacted = None
                self.scene_id = scene_id
                point = children(fields, 2)
                request_time = integer(fields, 1)
                samples = [node.get("children") or [] for node in nodes(fields, 12)]
                samples = [sample for sample in samples if request_time is not None
                           and (integer(sample, 2) or 0) <= request_time]
                if samples and integer(fields, 8) != 1:
                    point = children(max(samples, key=lambda s: integer(s, 2) or 0), 1)
                self.player_position = position(point)
                # ctrl_rot 与 to_rot 的 z 实测一致，to_rot 缺失时用它兜底。
                heading = integer(children(fields, 3), 3, signed=True)
                if heading is None:
                    heading = integer(children(fields, 15), 3, signed=True)
                if heading is not None:
                    self.player_heading = heading
                self.position_seq = seq
            return
        if event.direction != "s2c":
            return
        if opcode in (0x0102, 0x0152, 0x015C):
            self.__init__()
            self.scene_generation = seq
            if opcode == 0x0152:
                self.scene_id = integer(fields, 2)
                base = children(children(children(fields, 11), 12), 1)
                self.self_actor_id = integer(base, 2)
                self.player_position = position(children(children(base, 8), 1))
            elif opcode == 0x015C:
                self.scene_id = integer(fields, 11)
                self.player_position = position(children(children(fields, 14), 1))
                # 传送通知同样携带自身 avatar，进场响应还没到时也能拿到身份。
                base = children(children(children(fields, 21), 12), 1)
                self.self_actor_id = integer(base, 2) or self.self_actor_id
            self.position_seq = seq
            return
        if opcode == 0x1316:
            battle_id = integer(children(fields, 6), 1)
            if battle_id is not None:
                self.battle_id = battle_id
                if 0 <= event.ts - self.interacted_at <= 10:
                    self.actors.pop(self.interacted, None)
                self.interacted = None
            return
        if opcode == 0x132C:
            if integer(children(fields, 1), 19) == self.battle_id:
                self.battle_id = None
            return
        if self.battle_id is not None:
            return
        if opcode == 0x014A:
            for node in nodes(fields, 7):
                self._add(node)
        elif opcode in (0x0413, 0x0414):
            wrappers = nodes(fields, 1)
            if opcode == 0x0413:
                wrappers = [item for wrapper in wrappers
                            for item in nodes(wrapper.get("children") or [], 1)]
            for wrapper in wrappers:
                for action in wrapper.get("children") or []:
                    content = action.get("children") or []
                    if action["no"] == 1:
                        for node in nodes(content, 1):
                            self._add(node)
                    elif action["no"] == 2:
                        actor_ids, invalid = removed_ids(content)
                        if invalid:
                            self.actors.clear()
                            self.scene_generation = seq
                        for actor_id in actor_ids:
                            self.actors.pop(actor_id, None)
                            self.players.pop(actor_id, None)
                    elif action["no"] in (12, 13, 222):
                        # 移动实体不再作为固定坐标使用，等待下一次完整下发。
                        self.actors.pop(integer(content, 1), None)

    def _add(self, node: dict) -> None:
        node_children = node.get("children") or []
        npc = children(node_children, 11)
        if not npc:
            player_id = integer(children(children(node_children, 12), 1), 2)
            if player_id:
                self.players[player_id] = True
            return
        base = children(npc, 1)
        actor_id = integer(base, 2)
        options = [option.get("children") or [] for option in nodes(children(npc, 5), 1)]
        if actor_id is None:
            return
        if not options:
            self.actors.pop(actor_id, None)
            return
        # 只提供交互选项、定位与归属字段，避免保存整棵 NPC 解码树。
        # creator_id 即 npc_base.create_avatar_id；界面上的「拥有者 XXX」是同一节点的
        # create_avatar_name，所以它是奇遇归属的判据（base.owner_id 只是位面归属，不代表创建者）。
        creator_id = integer(children(npc, 3), 19)
        self.actors[actor_id] = {
            "actor_id": str(actor_id), "config_id": integer(children(npc, 3), 1),
            "creator_id": str(creator_id) if creator_id else None,
            "position": position(children(children(base, 8), 1)),
            "options": [{"id": integer(option, 1), "enabled": integer(option, 2)} for option in options],
        }

    def snapshot(self) -> dict:
        return {"scene_id": self.scene_id, "scene_generation": self.scene_generation,
                "position": self.player_position, "heading": self.player_heading,
                "position_seq": self.position_seq,
                "self_actor_id": str(self.self_actor_id) if self.self_actor_id else None,
                "player_actor_ids": [str(player_id) for player_id in self.players],
                "in_battle": self.battle_id is not None, "actors": list(self.actors.values())}
