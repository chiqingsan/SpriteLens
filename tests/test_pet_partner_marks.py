"""伙伴标记实时更新：0x0403 增量解析与仓库应用。

样本结构来自 2026-10-29 真实对局（docs/PROTOCOL_NOTES.md「伙伴标记实时更新」）：
游戏内改标记只回 0x0403，goods_change 里是 type=39 + gid + num（新标记值），
没有完整 PetData，因此必须单独解析才能让界面跟随。
"""

import unittest
from unittest.mock import Mock

from spritelens.domain.pet_partner_marks import extract_partner_marks
from spritelens.events import PacketEvent
from spritelens.services.pet_repository import PetRepository

OPCODE_UPDATE_COLLECT_TAG_RSP = 0x0403
OPCODE_PET_PAGE_RSP = 0x1346
OPCODE_ENTER_SCENE_RSP = 0x0152
PARTNER_MARK_GOODS_TYPE = 39
UID = 101384922


def _field(no: int, name: str, raw: object, children: list[dict] | None = None) -> dict:
    node = {"no": no, "name": name, "type": "", "value": "", "raw": raw}
    if children is not None:
        node["children"] = children
    return node


def _tag_rsp(gid: int, mark: int, *, ret_code: int = 0, goods_type: int = PARTNER_MARK_GOODS_TYPE) -> list[dict]:
    """ZoneUpdatePetCollectTagRsp: RetInfo{1: ret_code, 4: GoodsChange{1: changes}}。

    解码器把 repeated 的 GoodsChangeItem 展平：changes 的 children 直接是
    该条的字段（真实抓包即此形状），嵌套容器的兼容见 compatibility 测试。
    """
    changes = _field(1, "changes", None, [
        _field(1, "type", goods_type),
        _field(2, "op", 2),
        _field(3, "num", mark),
        _field(5, "id", 0),
        _field(14, "gid", gid),
        _field(15, "coro_id", 130689260),
    ])
    return [_field(1, "ret_info", None, [
        _field(1, "ret_code", ret_code),
        _field(4, "goods_change_info", None, [
            changes,
            _field(2, "pet_data_vesion", 731220),
            _field(3, "bag_data_vesion", 4487063),
        ]),
    ])]


def _event(direction: str, opcode: int, decoded: list[dict], opcode_name: str = "") -> PacketEvent:
    return PacketEvent(ts=0.0, session_id="s", direction=direction, opcode=opcode,
                       opcode_name=opcode_name, payload_len=0, decoded=decoded)


def _pet_event(gid: int, conf_id: int = 20508, name: bytes = b"Cat", level: int = 5) -> PacketEvent:
    """一条命中形状搜索的完整宠物（与 0x1346 分页包同形状）。"""
    node = _field(1, "pet_data", None, [
        _field(1, "gid", gid),
        _field(2, "conf_id", conf_id),
        _field(3, "name", name),
        _field(10, "level", level),
    ])
    return _event("s2c", OPCODE_PET_PAGE_RSP, [node])


def _identity_event(uid: int = UID) -> PacketEvent:
    node = _field(0, "self_info", None, [_field(0, "avatar", None, [_field(0, "base", None, [
        _field(0, "logic_id", uid),
        _field(0, "name", b"Tester"),
        _field(0, "lv", 70),
    ])])])
    return _event("s2c", OPCODE_ENTER_SCENE_RSP, [node])


class ExtractPartnerMarksTest(unittest.TestCase):
    def test_success_response_yields_mark(self):
        event = _event("s2c", OPCODE_UPDATE_COLLECT_TAG_RSP, _tag_rsp(100781, 4),
                       opcode_name="ZoneUpdatePetCollectTagRsp")
        self.assertEqual(extract_partner_marks(event), {100781: 4})

    def test_failed_ret_code_ignored(self):
        event = _event("s2c", OPCODE_UPDATE_COLLECT_TAG_RSP, _tag_rsp(100781, 4, ret_code=1))
        self.assertIsNone(extract_partner_marks(event))

    def test_other_goods_type_ignored(self):
        event = _event("s2c", OPCODE_UPDATE_COLLECT_TAG_RSP, _tag_rsp(100781, 4, goods_type=1))
        self.assertIsNone(extract_partner_marks(event))

    def test_other_opcode_ignored(self):
        event = _event("s2c", OPCODE_PET_PAGE_RSP, _tag_rsp(100781, 4))
        self.assertIsNone(extract_partner_marks(event))

    def test_c2s_ignored(self):
        event = _event("c2s", OPCODE_UPDATE_COLLECT_TAG_RSP, _tag_rsp(100781, 4))
        self.assertIsNone(extract_partner_marks(event))

    def test_missing_num_means_cleared(self):
        """摘除标记的样本未采集：num 缺失按 0（已摘除）解释。"""
        decoded = _tag_rsp(100781, 4)
        changes = decoded[0]["children"][1]["children"][0]
        changes["children"] = [item for item in changes["children"] if item["no"] != 3]
        self.assertEqual(extract_partner_marks(_event("s2c", OPCODE_UPDATE_COLLECT_TAG_RSP, decoded)),
                         {100781: 0})

    def test_nested_container_shape_compatible(self):
        """若解码器改为保留 repeated 容器（children 里再套 children）也能解析。"""
        decoded = _tag_rsp(100781, 4)
        changes = decoded[0]["children"][1]["children"][0]
        changes["children"] = [_field(0, "", None, changes["children"])]
        self.assertEqual(extract_partner_marks(_event("s2c", OPCODE_UPDATE_COLLECT_TAG_RSP, decoded)),
                         {100781: 4})


class PetRepositoryPartnerMarkTest(unittest.TestCase):
    def _repo_with_pet(self, gid: int = 100781, mark: int = 0) -> PetRepository:
        repo = PetRepository()
        repo.handle_packet(_pet_event(gid))
        if mark:
            repo.handle_packet(_event("s2c", OPCODE_UPDATE_COLLECT_TAG_RSP, _tag_rsp(gid, mark)))
        return repo

    def _mark_of(self, repo: PetRepository, gid: int) -> int:
        return next(pet.partner_mark for pet in repo.snapshot() if pet.gid == gid)

    def test_mark_update_applies_and_bumps_version(self):
        repo = self._repo_with_pet(100781)
        before = repo.version
        repo.handle_packet(_event("s2c", OPCODE_UPDATE_COLLECT_TAG_RSP, _tag_rsp(100781, 4)))
        self.assertEqual(self._mark_of(repo, 100781), 4)
        self.assertGreater(repo.version, before)

    def test_same_mark_does_not_bump_version(self):
        repo = self._repo_with_pet(100781, mark=4)
        before = repo.version
        repo.handle_packet(_event("s2c", OPCODE_UPDATE_COLLECT_TAG_RSP, _tag_rsp(100781, 4)))
        self.assertEqual(repo.version, before)

    def test_clearing_mark_sets_zero(self):
        repo = self._repo_with_pet(100781, mark=4)
        repo.handle_packet(_event("s2c", OPCODE_UPDATE_COLLECT_TAG_RSP, _tag_rsp(100781, 0)))
        self.assertEqual(self._mark_of(repo, 100781), 0)

    def test_unknown_gid_not_inserted(self):
        repo = PetRepository()
        repo.handle_packet(_event("s2c", OPCODE_UPDATE_COLLECT_TAG_RSP, _tag_rsp(999999, 4)))
        self.assertEqual(repo.snapshot(), ())

    def test_change_is_handed_to_store(self):
        store = Mock()
        repo = PetRepository(store=store)
        repo.handle_packet(_identity_event())
        repo.handle_packet(_pet_event(100781))
        repo.handle_packet(_event("s2c", OPCODE_UPDATE_COLLECT_TAG_RSP, _tag_rsp(100781, 4)))
        written = [pet for call in store.put.call_args_list for pet in call.args[1]]
        self.assertTrue(any(pet.gid == 100781 and pet.partner_mark == 4 for pet in written))


if __name__ == "__main__":
    unittest.main()
