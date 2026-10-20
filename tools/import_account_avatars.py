"""同步游戏名片头像 ID 映射；头像原图由运行时按需下载并缓存。"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from urllib.request import urlopen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with urlopen(args.config_url, timeout=20) as response:
        config = response.read()
    entries = json.loads(config)
    args.output.mkdir(parents=True, exist_ok=True)

    def mapping(entry: dict) -> dict:
        icon_id = int(entry["id"])
        url = f"https://wegame.shallow.ink/api/v1/resources/wiki/assets/profile/avatar/{icon_id}.png"
        return {"id": icon_id, "name": entry["icon_resource_name"],
                "resource": entry["icon_resource_path"], "source_url": url}

    assets = [mapping(entry) for entry in entries]
    manifest = {"config_url": args.config_url, "config_sha256": sha256(config).hexdigest(),
                "assets": assets}
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"mapped={len(assets)}")


if __name__ == "__main__":
    main()
