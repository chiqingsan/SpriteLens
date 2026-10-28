"""按道具 ID 补齐缺失的精灵蛋图标（wiki 资源站 → webp）。

蛋图标默认来自官方资源镜像（tools/sync_catalog_resources.py 按 manifest 导入）。
当目录里有蛋、但镜像里没有这张图时（如活动蛋 150006 的目录图 107249），
用 wiki 资源站的 items/bag 图补缺，并把来源 URL 与哈希写进
data/static/resource_sync_report.json，保证可复查、可重复导入。

用法:
    python tools/import_egg_icons.py 107249 150006
    python tools/import_egg_icons.py --dry-run 107249

失败分支:
    - HTTP 失败 / 内容不是可解码图片：记录 status=missing 与 reason，不写文件，退出码 1
    - 目标已存在且内容哈希一致：status=unchanged，跳过下载写入
    - 本地 report 缺失或损坏：只补图并新建最小报告，不覆盖其它字段
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICON_DIR = ROOT / "spritelens" / "web" / "static" / "egg-icons"
REPORT = ROOT / "data" / "static" / "resource_sync_report.json"
SOURCE_URL = "https://wegame.shallow.ink/api/v1/resources/wiki/assets/items/bag/{item_id}.png"


def fetch_icon(item_id: int) -> tuple[bytes, str]:
    """下载单张图标；返回 (png 字节, 源 URL)。网络错误由调用方记入报告。"""
    url = SOURCE_URL.format(item_id=item_id)
    with urllib.request.urlopen(url, timeout=20) as response:
        return response.read(), response.geturl() or url


def write_icon(item_id: int, data: bytes) -> str:
    """把 PNG 转成无损 webp；返回目标文件路径。"""
    from PIL import Image

    image = Image.open(io.BytesIO(data)).convert("RGBA")
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    dest = ICON_DIR / f"{item_id}.webp"
    image.save(dest, "WEBP", lossless=True, method=4)
    return str(dest.relative_to(ROOT))


def load_report() -> dict:
    if REPORT.is_file():
        try:
            value = json.loads(REPORT.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass
    return {"source": "wiki 资源站补充蛋图标", "resource_imports": [], "coverage": {}}


def import_icons(item_ids: list[int], dry_run: bool) -> list[dict]:
    report = load_report()
    imports = {f"{row.get('kind')}/{row.get('id')}": row
               for row in report.get("resource_imports") or [] if isinstance(row, dict)}
    outcomes: list[dict] = []
    for item_id in item_ids:
        record = {"kind": "egg", "id": str(item_id)}
        try:
            data, url = fetch_icon(item_id)
        except (urllib.error.URLError, OSError) as exc:
            outcomes.append({**record, "status": "missing", "reason": str(exc)})
            continue
        digest = hashlib.sha256(data).hexdigest()
        dest = ICON_DIR / f"{item_id}.webp"
        previous = imports.get(f"egg/{item_id}") or {}
        if dest.is_file() and previous.get("sha256_source") == digest:
            # 源哈希与上次导入一致：图已是最新，不重复解码转换
            outcomes.append({**record, "status": "unchanged", "source_url": url, "sha256_source": digest})
            continue
        record.update(source_url=url, sha256_source=digest)
        if dry_run:
            outcomes.append({**record, "status": "planned"})
            continue
        try:
            record["path"] = write_icon(item_id, data)
        except (OSError, ValueError) as exc:
            outcomes.append({**record, "status": "missing", "reason": f"图片转换失败: {exc}"})
            continue
        outcomes.append({**record, "status": "imported"})
    if not dry_run:
        for outcome in outcomes:
            if outcome["status"] in ("imported", "unchanged"):
                imports[f"egg/{outcome['id']}"] = outcome
        report["resource_imports"] = list(imports.values())
        coverage = report.setdefault("coverage", {})
        coverage["egg_images"] = len(list(ICON_DIR.glob("*.webp")))
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(report, ensure_ascii=False, separators=(",", ":")) + "\n",
                          encoding="utf-8")
    return outcomes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("item_ids", type=int, nargs="+", help="蛋道具 ID（egg_item_id）")
    parser.add_argument("--dry-run", action="store_true", help="只校验来源，不落盘")
    args = parser.parse_args(argv)
    outcomes = import_icons(args.item_ids, args.dry_run)
    print(json.dumps(outcomes, ensure_ascii=False))
    return 0 if all(row["status"] in ("imported", "unchanged", "planned") for row in outcomes) else 1


if __name__ == "__main__":
    sys.exit(main())
