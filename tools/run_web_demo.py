"""启动带合成数据的 Web 版 SpriteLens（供浏览器/截图工具做视觉验收）。

合成数据 + 真实本地服务：起服务后用系统
浏览器打开，便于人工核对布局或由 browser-use 类工具截图。
数据为合成，不依赖游戏在线。

用法：
    python tools/run_web_demo.py [--pets 12] [--scenario normal|extreme]
    --scenario extreme 使用极限布局数据集（最长名称、全部已映射伙伴标记、
    稀有+色卡+最多奖牌+体型/声音组合、四种箱位空态），仅用于视觉验收。
按 Ctrl+C 退出。
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spritelens.app_context import AppContext
from spritelens.capture.key_store import KeyStore
from spritelens.domain.color_cards import ColorCatalog
from spritelens.domain.egg_box import EggBoxEntry
from spritelens.domain.eggs import EggCatalog
from spritelens.domain.identity import PlayerIdentity
from spritelens.domain.pets import Pet, PetAttribute, PetSkill
from spritelens.domain.pet_locations import Backpack, PetBox
from spritelens.domain.static_data import load_static_data
from spritelens.logs import setup_logger
from spritelens.paths import logs_dir, schema_dir, static_dir
from spritelens.protocol.opcodes import OpcodeCatalog
from spritelens.protocol.schema import load_library
from spritelens.repositories.settings import SettingsRepository
from spritelens.domain.home import HomeCouple, HomeFurniture, HomeResident, HomeSceneEgg, HomeSnapshot
from spritelens.services.egg_repository import EggBoxRepository
from spritelens.services.home_repository import HomeRepository
from spritelens.services.monitor_service import MonitorService
from spritelens.services.pet_repository import PetRepository
from spritelens.view_models import CaptureViewModel, PetViewModel
from spritelens.web.server import LocalServer

_SAMPLE = (
    ("迪莫", 3004, 60), ("火神", 3006, 60), ("水灵", 3005, 55), ("彩蝶鲨", 3117, 48),
    ("燃薪虫", 3437, 42), ("小独角兽", 3062, 35), ("菊花梨", 3227, 28), ("恶魔叮", 3010, 22),
    ("皇家狮鹫", 3469, 58), ("治愈兔", 3081, 44), ("机械方方", 3200, 39), ("乖乖鹄", 3344, 31),
    ("护主犬", 3070, 1),
)

# 极限布局数据集（--scenario extreme）：用真实静态数据中的最长名称、全部已映射伙伴标记、
# 稀有+色卡+最多奖牌+体型/声音组合，以及四种箱位空态，验证真实 6 列点阵而不是单张合成卡片。
_PARTNER_MARK_IDS = (1, 3, 4, 5, 6, 7, 8, 14, 15)
_UNKNOWN_PARTNER_MARK_ID = 2  # 素材映射表没有 2：未知 ID 必须完全不渲染
_LONGEST_SPECIES = (16000002, "厉毒修萝-B1小游戏变形用")  # 静态数据内最长名称（含测试用条目）
_LONGEST_NORMAL = (5062, "暮风隐者（枯叶的样子）")  # 有真实体型区间的长名称
_ALL_MEDALS = (1001, 1002, 1004, 1005, 1006, 1010, 1025, 1026, 1028, 1030)
_UNKNOWN_SLOT_GIDS = tuple(5555 + index for index in range(10))  # 箱内存在但未采集的精灵 → 待补


def _extreme_pet(static, gid: int, name: str, base_conf: int, *, gender: int, mark: int = 0,
                 nature: int = 1, level: int = 60, mutation: int = 0, glass: tuple[int, int] = (0, 0),
                 worn_medal_id: int = 0, awarded: tuple[int, ...] | None = None,
                 height: int | None = None, weight: int | None = None, voice: int = 0) -> Pet:
    from spritelens.domain.pets import _ATTR_SLOTS  # noqa: PLC0415 - demo 专用

    species = static.species(base_conf)
    height_range = species.height_range if species is not None else (0, 0)
    weight_range = species.weight_range if species is not None else (0, 0)
    if height is None:
        height = (height_range[0] + height_range[1]) // 2 if height_range[1] > height_range[0] > 0 else 100
    if weight is None:
        weight = (weight_range[0] + weight_range[1]) // 2 if weight_range[1] > weight_range[0] > 0 else 10000
    rng = random.Random(gid)
    return Pet(
        gid=gid, conf_id=900000 + gid, name=name, level=level, exp=0,
        nature=nature, gender=gender, blood_id=gid % 5 + 1, talent_rank=rng.randint(1, 5),
        is_first_catch=False, base_conf_id=base_conf,
        attributes=tuple(PetAttribute(total_race=rng.randint(70, 130), talent=rng.choice([0, 24, 48]),
                                      base_value=rng.randint(120, 220), effort_add=rng.randint(0, 30))
                         for _ in _ATTR_SLOTS),
        height=height, weight=weight, voice=voice, mutation_type=mutation,
        glass_type=glass[0], glass_value=glass[1], worn_medal_id=worn_medal_id,
        awarded_medal_ids=awarded, classis=gid % 18, breakthrough_lv=level // 10,
        speciality_id=401 + gid % 3, ball_id=1,
        skills=tuple(PetSkill(skill_id=7050210 + k, conf_idx=10 + k, is_learned=True, is_equipped=k < 2, pos=k)
                     for k in range(4)),
        partner_mark=mark, catch_way=gid % 6 + 1, add_time=int(time.time()) - gid * 3600,
    )


def _apply_extreme_dataset(static, repository: PetRepository) -> None:
    """把合成仓库替换成极限布局数据集；只影响当前进程，不落库。"""
    rows = [
        # 1) 最长名称 + 异色/炫彩 + 色卡 + 10 枚奖牌 + 佩戴"大" + 粗嗓门（同卡最多标记）
        dict(gid=5001, name=_LONGEST_SPECIES[1], base_conf=_LONGEST_SPECIES[0], gender=1, mark=1, nature=12,
             mutation=9, glass=(2, 1), worn_medal_id=1001, awarded=_ALL_MEDALS, voice=-100),
        dict(gid=5002, name="迪莫", base_conf=3004, gender=2, mark=0, nature=1),  # 无标记
        dict(gid=5003, name="火神", base_conf=3006, gender=2, mark=_UNKNOWN_PARTNER_MARK_ID, nature=2),  # 未知标记
        dict(gid=5004, name="水灵", base_conf=3005, gender=0, mark=4, nature=14),  # 性别未知 + 标记
        dict(gid=5005, name="彩蝶鲨", base_conf=3117, gender=1, mark=3, nature=4),
        dict(gid=5006, name="燃薪虫", base_conf=3437, gender=2, mark=5, nature=10),
        dict(gid=5007, name="小独角兽", base_conf=3062, gender=1, mark=6, nature=7),
        dict(gid=5008, name="菊花梨", base_conf=3227, gender=2, mark=7, nature=13),
        dict(gid=5009, name="恶魔叮", base_conf=3010, gender=1, mark=8, nature=12),
        dict(gid=5010, name="皇家狮鹫", base_conf=3469, gender=2, mark=14, nature=4),
        dict(gid=5011, name="治愈兔", base_conf=3081, gender=1, mark=15, nature=1),
        # 12) 体型下限 + 满声音 → 参考规则得到"小 + 婉"；名称是真实最长可用名
        dict(gid=5012, name=_LONGEST_NORMAL[1], base_conf=_LONGEST_NORMAL[0], gender=2, mark=0, nature=13,
             weight=5000, voice=100),
        dict(gid=5013, name="机械方方", base_conf=3200, gender=1, mark=6, nature=10),
        # 14) 未知性格 ID：性格胶囊显示原始编号（3 字符），验证胶囊不被撑破
        dict(gid=5014, name="护主犬", base_conf=3070, gender=2, mark=0, nature=999, level=1),
        dict(gid=5015, name="乖乖鹄", base_conf=3344, gender=1, mark=3, nature=7),
        # 16) 体型上限 → "大"；长名称 + 两个参考标记
        dict(gid=5016, name=_LONGEST_NORMAL[1], base_conf=_LONGEST_NORMAL[0], gender=2, mark=0, nature=2,
             weight=9000),
        dict(gid=5017, name="迪莫", base_conf=3004, gender=1, mark=1, nature=14, worn_medal_id=1002),
        dict(gid=5018, name="火神", base_conf=3006, gender=2, mark=4, nature=1, worn_medal_id=1025),
        dict(gid=5019, name="水灵", base_conf=3005, gender=1, mark=8, nature=12, worn_medal_id=1026),
        dict(gid=5020, name="燃薪虫", base_conf=3437, gender=2, mark=0, nature=4),
        dict(gid=5021, name="小独角兽", base_conf=3062, gender=1, mark=15, nature=10),
        dict(gid=5022, name="菊花梨", base_conf=3227, gender=2, mark=5, nature=13),
        dict(gid=5023, name="恶魔叮", base_conf=3010, gender=1, mark=0, nature=7),
        dict(gid=5024, name="皇家狮鹫", base_conf=3469, gender=2, mark=14, nature=12),
    ]
    box_pets = [_extreme_pet(static, **row) for row in rows]
    team_pets = []
    for index in range(12):
        name, base_conf, _level = _SAMPLE[index % len(_SAMPLE)]
        team_pets.append(_extreme_pet(
            static, 5101 + index, name, base_conf, gender=1 + index % 2,
            mark=(_PARTNER_MARK_IDS + (0, _UNKNOWN_PARTNER_MARK_ID, 1))[index], nature=1 + index % 15,
        ))
    repository._pets = {pet.gid: pet for pet in box_pets + team_pets}
    repository._backpack = Backpack(
        {
            # 6 列 5 排：前 24 格是极限卡片，后 6 格留空格
            1: PetBox(1, tuple(row["gid"] for row in rows) + (0,) * 6, "极限数据箱"),
            # 四种空态：未采集（None）/ 空格（0）/ 待补（箱内 gid 未采集到）
            2: PetBox(2, (None,) * 10 + (0,) * 10 + _UNKNOWN_SLOT_GIDS, "四种空态"),
            3: PetBox(3, (0,) * 30, ""),
        },
        (
            PetBox(1, tuple(pet.gid for pet in team_pets[:6]), "极限队伍一"),
            PetBox(2, tuple(pet.gid for pet in team_pets[6:]), "极限队伍二"),
            PetBox(3, (0,) * 6, ""),
        ),
        1,
    )
    repository._locations = repository._backpack.locations()
    repository._version += 1



def _demo_home() -> HomeRepository:
    repo = HomeRepository()
    repo._account.observe(PlayerIdentity(101384922, "话绵雨", 60))
    ordinary_nest = "70182c0b68100000"
    academy_nest = "65d37b61f2690"
    father_a = 0x84182c0b68a0000a
    mother = 0x84182c0b68a0000b
    father_b = 0x84182c0b68a0000c
    repo._snapshot = HomeSnapshot(
        room_level=10,
        residents=(
            HomeResident(actor_id=father_a, name="护主犬", gender=1, level=41,
                         position=(-882, 1284, 61), instance_id=1000, nest_guid=ordinary_nest),
            HomeResident(actor_id=mother, name="喵喵", gender=2, level=35,
                         position=(100, 200, 1), instance_id=1001, nest_guid=ordinary_nest),
            HomeResident(actor_id=father_b, name="火花", gender=1, level=22,
                         position=(300, 400, 1), instance_id=1002, nest_guid=academy_nest),
        ),
        nests=(
            HomeFurniture(config_id=710069, guid=ordinary_nest, kind="ordinary",
                          name="普通小窝", position=(100, 200, 1),
                          resident_ids=(father_a, mother)),
            HomeFurniture(config_id=1001072, guid=academy_nest, kind="academy",
                          name="学院小窝", position=(300, 400, 1),
                          resident_ids=(father_b,)),
        ),
        couples=(HomeCouple(female_actor_id=mother, male_actor_ids=(father_a, father_b)),),
        scene_eggs=(HomeSceneEgg(actor_id=0x84182c0b68a00010, furniture_guid=academy_nest,
                                 npc_config_id=3001001),),
    )
    repo._version += 1
    return repo


def build_demo_context(tmp: Path, count: int, scenario: str = "normal") -> AppContext:
    """合成 AppContext：内存快照 + 临时配置，不落库、不抓包。"""
    load_library(schema_dir())
    static = load_static_data(static_dir())
    monitor = MonitorService(
        catalog=OpcodeCatalog.load(Path(__file__).resolve().parent.parent / "data" / "schemas" / "opcodes.json"),
        key_store=KeyStore(tmp / "keys"),
    )
    repository = PetRepository(store=None)
    rng = random.Random(11)
    names = _SAMPLE * ((count // len(_SAMPLE)) + 1)
    from spritelens.domain.pets import _ATTR_SLOTS  # noqa: PLC0415 - demo 专用

    for i in range(count):
        name, base_conf, level = names[i]
        repository._pets[1000 + i] = Pet(
            gid=1000 + i, conf_id=2000000 + i, name=name, level=level, exp=1000 * i,
            nature=next(key for key, info in static.nature_items() if info.name == '胆小') if i == 12 else rng.randint(1, 25),
            gender=1 if i == 12 else rng.randint(1, 2), blood_id=(i % 5) + 1,
            talent_rank=rng.randint(1, 5), is_first_catch=rng.random() < 0.35,
            base_conf_id=base_conf,
            attributes=tuple(PetAttribute(total_race=static.species(3070).stats[key], base_value=value - bonus, talent_add=bonus)
                             for (_, key), value, bonus in zip(_ATTR_SLOTS, (49, 57, 26, 53, 44, 61), (9, 0, 0, 7, 0, 8))) if i == 12 else tuple(
                PetAttribute(total_race=rng.randint(70, 130), talent=rng.choice([0, 24, 48]),
                             base_value=rng.randint(120, 220), effort_add=rng.randint(0, 30))
                for _ in _ATTR_SLOTS
            ),
            catch_way=(i % 6) + 1, add_time=int(time.time()) - i * 86400,
            awarded_medal_ids=(1001, 1002, 1004, 1005, 1006, 1010, 1025, 1026, 1028, 1030) if i == 0 else (1001, 1010) if i == 12 else () if i == 2 else None,
            height=88 if i == 12 else round(sum(static.species(base_conf).height_range) / 2) if i == 0 else rng.randint(70, 200),
            weight=16931 if i == 12 else round(sum(static.species(base_conf).weight_range) / 2) if i == 0 else rng.randint(20000, 100000),
            voice=-96 if i == 12 else rng.randint(-100, 100), mutation_type=8 if i == 12 else 9 if i % 4 == 0 else (8 if i % 4 == 1 else 0),
            glass_type=2 if i % 7 == 0 else 1,
            glass_value=(1 if i % 7 == 0 else rng.choice((7, 29, 1048605, 1048597, 2097156))),
            classis=i % 18, breakthrough_lv=level // 10, speciality_id=401 if i == 12 else 100 + i,
            ball_id=(i % 5) + 1,
            skills=tuple(
                PetSkill(skill_id=sid, conf_idx=10 + k, is_learned=True, is_equipped=k < 2, pos=k)
                for k, sid in enumerate((7050210 + i * 10, 7050190, 7050270, 200107))
            ),
        )
    # 留出空箱、筛选空格与一组位置未知个体，验证真实箱模式。
    gids = list(repository._pets)
    boxes = {}
    for index in range(0, max(0, len(gids) - 3), 24):
        slots = [0] * 30
        for slot, gid in enumerate(gids[index:min(index + 24, len(gids) - 3)]):
            slots[slot] = gid
        box_id = index // 24 + 1
        boxes[box_id] = PetBox(box_id, tuple(slots), "常用精灵" if box_id == 1 else "")
    boxes[len(boxes) + 1] = PetBox(len(boxes) + 1, (0,) * 30)
    teams = (PetBox(1, tuple(gids[:6])), PetBox(2, tuple(gids[6:12])), PetBox(3, tuple([0] * 6))) if count >= 12 else ()
    if teams:
        team_gids = set(gids[:12])
        boxes = {key: PetBox(key, tuple(0 if gid in team_gids else gid for gid in box.slots), box.name) for key, box in boxes.items()}
    repository._backpack = Backpack(boxes, teams, 1 if teams else None)
    repository._locations = repository._backpack.locations()
    repository._version += 1
    if scenario == "extreme":
        _apply_extreme_dataset(static, repository)
    repository._account.observe(PlayerIdentity(uid=101384922, name="话绵雨", level=60))

    # 合成蛋仓（联查蛋目录：confId 取 eggs.json 的真实条目）
    egg_box = EggBoxRepository()
    egg_box._account.observe(PlayerIdentity(101384922, "话绵雨", 60))
    catalog = EggCatalog(static_dir())
    conf_ids = [info.egg_conf_id for info in catalog.entries()][:8]
    import time as _time
    for i, conf_id in enumerate(conf_ids):
        hatching = i % 3 == 0
        if hatching:
            egg_box._hatch_slots.add(9000 + i)
        hatch_total = 43200 if i % 2 else 28800
        egg_box._eggs[9000 + i] = EggBoxEntry(
            instance_id=9000 + i, egg_conf_id=conf_id, pet_conf_id=0, quantity=(i % 3) + 1,
            obtained_at=int(_time.time()) - i * 3600, bag_type=8,
            height_cm=25 + i, weight_g=1300 + i * 10,
            hatch_seconds=hatch_total,
            hatched_seconds=hatch_total // 3 * (i % 3 + 1) if hatching else 0,
            hatch_updated_at=0, start_hatch_time=int(_time.time()) - 3600 if hatching else 0,
            category=6, special_egg_conf_id=0, appearance_type=0, extension_type=0,
        )
    egg_box._version += 1
    egg_box._source = "observed"
    egg_box._slots_source = "observed"

    settings = SettingsRepository(tmp / "config.json")
    capture_vm = CaptureViewModel(
        monitor=monitor,
        settings=settings,
        keys_dir=tmp / "keys",
        recordings_dir=tmp / "recordings",
        port=8195,
    )
    return AppContext(
        settings=settings,
        static_data=static,
        monitor=monitor,
        pet_repository=repository,
        capture_vm=capture_vm,
        pet_vm=PetViewModel(repository, static_data=static),
        egg_catalog=catalog,
        color_catalog=ColorCatalog(static_dir()),
        egg_box=egg_box,
        home_repo=_demo_home(),
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pets", type=int, default=None, help="普通数据集精灵数量（默认 12）")
    parser.add_argument("--scenario", choices=("normal", "extreme"), default="normal",
                        help="normal=日常演示数据；extreme=极限布局验收数据集")
    parser.add_argument("--no-open", action="store_true", help="不开浏览器，只打印 URL")
    args = parser.parse_args(argv)

    setup_logger(logs_dir())
    tmp = Path(tempfile.mkdtemp())
    count = args.pets if args.pets is not None else 12
    context = build_demo_context(tmp, count, scenario=args.scenario)
    server = LocalServer(context, port=0)
    server.start()

    info = {"url": server.url, "port": server.port, "scenario": args.scenario,
            "pets": len(context.pet_repository.snapshot())}
    print("[web-demo] " + json.dumps(info, ensure_ascii=False), flush=True)

    if not args.no_open:
        webbrowser.open(server.url)
    try:
        while server.running:
            try:
                __import__("time").sleep(0.5)
            except KeyboardInterrupt:
                break
    finally:
        server.stop()
        context.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
