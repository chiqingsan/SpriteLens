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
    "flag": ["planner-target", "goal"],
    "arrows-shuffle": ["generate", "plan", "regenerate"],
    "alert-circle": ["error", "failure"],
    "info-circle": ["notice", "info"],
}
STROKE_WIDTH_OVERRIDES = {"arrow-up": "2.5", "arrow-down": "2.5"}

# 项目内手工保留的图标（非 Tabler 官方资源，沿用原图形，来源见 docs/FRONTEND_DEVELOPMENT.md）。
EXTRAS = {
    "star": ('viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"', '<path d="m12 3 2.8 5.7 6.2 .9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2-4.5-4.4 6.2-.9z" />'),
    "star-filled": ('viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"', '<path d="m12 3 2.8 5.7 6.2 .9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2-4.5-4.4 6.2-.9z" />'),
    "graduation-cap": ('viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"', '<path d="M2 8.5 12 4l10 4.5-10 4.5-10-4.5Z" />\n  <path d="M6 10.9V16c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5v-5.1" />\n  <path d="M21 9.6V14" />'),
    "sprout": ('viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"', '<path d="M12 21v-8" />\n  <path d="M12 13c0-3.3 2.7-6 6-6 0 3.3-2.7 6-6 6Z" />\n  <path d="M12 15c0-2.8-2.2-5-5-5 0 2.8 2.2 5 5 5Z" />'),
}


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
        (dest / f"{name}.svg").write_text(text, encoding="utf-8")
        body = text[text.index(">", text.index("<svg")) + 1:text.rindex("</svg>")]
        symbols.append(f'<symbol id="{name}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="{stroke_width}" stroke-linecap="round" stroke-linejoin="round">{body}</symbol>')
        metadata.append({"name": name, "source": "Tabler Icons", "url": f"https://tabler.io/icons/icon/{name}",
                         "svg_url": url, "license": "MIT", "search_tags": tags, "sha256": hashlib.sha256(data).hexdigest()})
    for name, (attrs, body) in EXTRAS.items():
        (dest / f"{name}.svg").write_text(f'<svg xmlns="http://www.w3.org/2000/svg" {attrs}>{body}</svg>\n', encoding="utf-8")
        symbols.append(f'<symbol id="{name}" {attrs}>{body}</symbol>')
        metadata.append({"name": name, "source": "项目保留图形（原资源）", "url": "", "svg_url": "",
                         "license": "ISC", "search_tags": ["legacy"], "sha256": ""})
    (dest / "sprite.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg">' + "\n".join(symbols) + '</svg>\n', encoding="utf-8")
    (dest / "sources.json").write_text(json.dumps({"commit": commit, "icons": metadata}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (dest / "LICENSE.txt").write_bytes(fetch(f"{base}/LICENSE"))
    print(f"Imported {len(metadata)} Tabler icons at {commit}")


if __name__ == "__main__":
    main()
