"""获取少量 Tabler 官方 outline SVG，生成本地 sprite 和来源清单。"""
from __future__ import annotations

import hashlib
import json
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICONS = {
    "layout-dashboard": ["overview", "dashboard"], "backpack": ["pet", "bag"],
    "book-2": ["handbook", "catalog"], "egg": ["egg", "hatch"],
    "box": ["warehouse", "storage"], "table": ["matrix", "coverage"],
    "users": ["breeder", "parents"], "sitemap": ["planner", "nest"],
    "checklist": ["collection", "progress"], "home": ["home", "house"],
    "palette": ["color", "palette"],
    "activity": ["protocol", "stream"], "settings": ["settings", "capture"],
    "filter": ["filter", "condition"], "filter-off": ["reset", "clear"],
    "refresh": ["reload", "refresh"], "search": ["search", "empty"],
    "chevron-left": ["previous", "back"], "chevron-right": ["next", "forward"],
    "x": ["close", "remove"], "download": ["download", "install"],
    "player-play": ["start", "capture"], "player-stop": ["stop", "capture"],
    "trash": ["clear", "delete"], "circle-check": ["selected", "success"],
    "layout-grid": ["grid", "card"], "adjustments": ["appearance", "display"],
    "clock": ["hatch", "time"],
    "ruler-2": ["egg", "height", "size"], "weight": ["egg", "weight", "mass"],
    "eye": ["uid", "show"], "eye-off": ["uid", "hide"],
    "square": ["stop", "capture"], "chevron-down": ["account", "expand"],
    "gender-male": ["male", "gender"], "gender-female": ["female", "gender"],
    "arrow-up": ["nature-positive", "increase", "up"],
    "arrow-down": ["nature-negative", "decrease", "down"],
    "bell": ["reminder", "sound"], "bell-off": ["reminder", "mute"],
}
STROKE_WIDTH_OVERRIDES = {"arrow-up": "2.5", "arrow-down": "2.5"}

# 注意：sprite.svg 里另有 4 个手工追加的本地 symbol（star / star-filled / graduation-cap / sprout），
# 它们不在 ICONS 里，直接重跑本脚本会把 sprite.svg 覆盖成纯 Tabler 版本而丢掉这 4 个图标。
# 加图标时需要先合并手工 symbol（做法见 docs/CODEBASE_MAP.md 的图标小节）。


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "SpriteLens-resource-sync"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def main() -> None:
    dest = ROOT / "spritelens/web/static/icons"
    dest.mkdir(parents=True, exist_ok=True)
    commit = "a4ce1404bc6d24d3c365afe7b258d6bf6f48d62d"
    base = f"https://raw.githubusercontent.com/tabler/tabler-icons/{commit}"
    metadata, symbols = [], []
    for name, tags in ICONS.items():
        url = f"{base}/icons/outline/{name}.svg"
        data = fetch(url)
        svg = ET.fromstring(data)
        assert svg.get("viewBox") == "0 0 24 24" and svg.get("stroke-width") == "2"
        stroke_width = STROKE_WIDTH_OVERRIDES.get(name, "2")
        text = data.decode("utf-8").replace('stroke-width="2"', f'stroke-width="{stroke_width}"', 1)
        (dest / f"{name}.svg").write_text(text, encoding="utf-8", newline="\n")
        body = text[text.index(">", text.index("<svg")) + 1:text.rindex("</svg>")]
        symbols.append(f'<symbol id="{name}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="{stroke_width}" stroke-linecap="round" stroke-linejoin="round">{body}</symbol>')
        metadata.append({"name": name, "source": "Tabler Icons", "url": f"https://tabler.io/icons/icon/{name}",
                         "svg_url": url, "license": "MIT", "search_tags": tags, "sha256": hashlib.sha256(data).hexdigest()})
    (dest / "sprite.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg">' + "\n".join(symbols) + '</svg>\n', encoding="utf-8", newline="\n")
    (dest / "sources.json").write_text(json.dumps({"commit": commit, "icons": metadata}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    (dest / "LICENSE.txt").write_bytes(fetch(f"{base}/LICENSE"))
    print(f"Imported {len(metadata)} Tabler icons at {commit}")


if __name__ == "__main__":
    main()
