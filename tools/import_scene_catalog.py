"""从解包 desktop-data.json 裁剪 NPC 配置到物种的精确映射。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    raw = args.source.read_bytes()
    mapping = json.loads(raw)["npc_pets"]
    if not isinstance(mapping, dict) or not all(
        key.isdecimal() and isinstance(value, int) and not isinstance(value, bool) and value > 0
        for key, value in mapping.items()
    ):
        raise ValueError("npc_pets 映射格式无效")
    output = Path(__file__).resolve().parent.parent / "data/static/scene_npc_pets.json"
    output.write_text(json.dumps({
        "source": "小洛克精灵工具箱 1.0.0 runtime_assets/desktop-data.json:npc_pets",
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "npc_pets": dict(sorted(mapping.items(), key=lambda pair: int(pair[0]))),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"导入 {len(mapping)} 条 NPC 配置映射")


if __name__ == "__main__":
    main()
