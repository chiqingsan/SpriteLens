"""启动带合成数据的 Web 版 SpriteLens（供浏览器/截图工具做视觉验收）。

合成数据 + 真实本地服务：起服务后用系统
浏览器打开，便于人工核对布局或由 browser-use 类工具截图。
数据为合成，不依赖游戏在线。

用法：
    python tools/run_web_demo.py [--pets 12]
按 Ctrl+C 退出。
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spritelens.app_context import AppContext
from spritelens.capture.key_store import KeyStore
from spritelens.domain.egg_box import EggBoxEntry
from spritelens.domain.flowers import FlowerRecord, FlowerSnapshot
from spritelens.domain.eggs import EggCatalog
from spritelens.domain.identity import PlayerIdentity
from spritelens.domain.pets import Pet, PetAttribute, PetSkill
from spritelens.domain.static_data import load_static_data
from spritelens.logs import setup_logger
from spritelens.paths import logs_dir, schema_dir, static_dir
from spritelens.protocol.opcodes import OpcodeCatalog
from spritelens.protocol.schema import load_library
from spritelens.repositories.settings import SettingsRepository
from spritelens.domain.home import HomeFurniture, HomeResident, HomeSnapshot
from spritelens.services.egg_repository import EggBoxRepository
from spritelens.services.flower_repository import FlowerRepository
from spritelens.services.home_repository import HomeRepository
from spritelens.services.monitor_service import MonitorService
from spritelens.services.pet_repository import PetRepository
from spritelens.view_models import CaptureViewModel, EventsViewModel, PetViewModel
from spritelens.web.server import LocalServer

_SAMPLE = (
    ("迪莫", 3004, 60), ("火神", 3006, 60), ("水灵", 3005, 55), ("彩蝶鲨", 3117, 48),
    ("燃薪虫", 3437, 42), ("小独角兽", 3062, 35), ("菊花梨", 3227, 28), ("恶魔叮", 3010, 22),
    ("皇家狮鹫", 3469, 58), ("治愈兔", 3081, 44), ("机械方方", 3200, 39), ("乖乖鹄", 3344, 31),
)


def _demo_flowers() -> FlowerRepository:
    repo = FlowerRepository()
    repo._snapshot = FlowerSnapshot(
        own=tuple(
            FlowerRecord(slot_id=20128 + i, slot_index=i, pet_conf_id=conf,
                         planted_at=1791748800, height=0, weight=0, voice=0, owner="self")
            for i, conf in enumerate((130308, 130311, 140149, 5400470, 130156, 130169))
        ),
        friends=tuple(
            FlowerRecord(slot_id=65516 + i, slot_index=i, pet_conf_id=conf,
                         planted_at=1791748800, height=403695 + i, weight=675368, voice=64,
                         owner="friend")
            for i, conf in enumerate((130310, 130312, 1200492, 5400469))
        ),
    )
    repo._version += 1
    return repo


def _demo_home() -> HomeRepository:
    repo = HomeRepository()
    repo._snapshot = HomeSnapshot(
        room_level=10,
        residents=(
            HomeResident(actor_id=0x84182c0b68a0000a, name="护主犬", gender=1, level=41,
                         position=(-882, 1284, 61)),
            HomeResident(actor_id=0x84182c0b68a0000b, name="喵喵", gender=2, level=35,
                         position=(100, 200, 1)),
        ),
        furniture=(
            HomeFurniture(config_id=710069, guid="70182c0b68100000", kind="ordinary",
                          name="普通小窝", position=(100, 200, 1)),
            HomeFurniture(config_id=150011, guid="65d37b61f2690", kind="furniture",
                          name="家具 #150011", position=(300, 400, 1)),
        ),
    )
    repo._version += 1
    return repo


def build_demo_context(tmp: Path, count: int) -> AppContext:
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
            nature=rng.randint(1, 25), gender=rng.randint(1, 2), blood_id=(i % 5) + 1,
            talent_rank=rng.randint(1, 5), is_first_catch=rng.random() < 0.35,
            base_conf_id=base_conf,
            attributes=tuple(
                PetAttribute(total_race=rng.randint(70, 130), talent=rng.choice([0, 24, 48]),
                             base_value=rng.randint(120, 220), effort_add=rng.randint(0, 30))
                for _ in _ATTR_SLOTS
            ),
            height=rng.randint(70, 200), weight=rng.randint(20000, 100000),
            voice=rng.randint(-100, 100), mutation_type=1 if i % 4 == 0 else 0,
            classis=i % 18, breakthrough_lv=level // 10, speciality_id=100 + i,
            ball_id=(i % 5) + 1,
            skills=tuple(
                PetSkill(skill_id=sid, conf_idx=10 + k, is_learned=True, is_equipped=k < 2, pos=k)
                for k, sid in enumerate((7050210 + i * 10, 7050190, 7050270, 200107))
            ),
        )
    repository._version += 1
    repository._identity = PlayerIdentity(uid=101384922, name="话绵雨", level=60)

    # 合成蛋仓（联查蛋目录：confId 取 eggs.json 的真实条目）
    egg_box = EggBoxRepository()
    catalog = EggCatalog(static_dir())
    conf_ids = [info.egg_conf_id for info in catalog.entries()][:8]
    import time as _time
    for i, conf_id in enumerate(conf_ids):
        hatching = i % 3 == 0
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
        events_vm=EventsViewModel(monitor=monitor),
        pet_vm=PetViewModel(repository, static_data=static),
        egg_catalog=catalog,
        egg_box=egg_box,
        home_repo=_demo_home(),
        flower_repo=_demo_flowers(),
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pets", type=int, default=12)
    parser.add_argument("--no-open", action="store_true", help="不开浏览器，只打印 URL")
    args = parser.parse_args(argv)

    setup_logger(logs_dir())
    tmp = Path(tempfile.mkdtemp())
    context = build_demo_context(tmp, args.pets)
    server = LocalServer(context, port=0)
    server.start()

    info = {"url": server.url, "port": server.port, "pets": args.pets}
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
