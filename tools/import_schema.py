"""导入外部 schema 数据到 data/schemas/（应用层语义化的数据前置）。

两个来源：
- proto_schema.json（innovationb1ue/rocom-helper，3458 条消息字段定义）
- opcodes.json（yuzeis/RocoMITMServer，1626 条 opcode → 消息名映射）

用法：
    python tools/import_schema.py [SRC_DIR]
SRC_DIR 缺省时从 GitHub raw 下载；也可以指向包含上述两文件的本地目录
（或 git clone 的工作副本，脚本会按已知相对路径查找）。

合并策略：data/schemas/opcodes.json 中已手工确认的条目优先，导入条目只补缺。
产出：messages/all.json（消息字段定义全集）+ 更新后的 opcodes.json。
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = PROJECT_ROOT / "data" / "schemas"

URL_PROTO = "https://raw.githubusercontent.com/innovationb1ue/rocom-helper/main/data/game/proto_schema.json"
URL_OPCODES = "https://raw.githubusercontent.com/yuzeis/Roco-Kingdom-MITM-Server/main/config/opcodes.json"

# 本地工作副本的候选相对路径（支持 git clone 的目录直接作为 SRC_DIR）
_LOCAL_PROTO_CANDIDATES = ("data/game/proto_schema.json", "proto_schema.json")
_LOCAL_OPCODES_CANDIDATES = ("config/opcodes.json", "opcodes.json")


def _fetch(name: str, url: str, candidates: tuple[str, ...], src_dir: Path | None) -> bytes:
    """本地目录优先，否则从 GitHub raw 下载。"""
    if src_dir is not None:
        for rel in candidates:
            path = src_dir / rel
            if path.is_file():
                print(f"[import] {name}: 本地 {path}")
                return path.read_bytes()
        raise FileNotFoundError(f"{src_dir} 下找不到 {' 或 '.join(candidates)}")
    print(f"[import] {name}: 下载 {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "SpriteLens/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def _normalize_proto(raw: dict) -> dict:
    """proto_schema.json → 我们的 messages/all.json 格式（结构一致，直接精简）。"""
    out: dict[str, dict] = {}
    for name, item in raw.get("messages", {}).items():
        fields = {}
        for no_key, field in (item.get("fields") or {}).items():
            try:
                fields[str(int(no_key))] = {
                    "name": str(field.get("name", f"field_{no_key}")),
                    "type": str(field.get("type", "")),
                }
            except (TypeError, ValueError):
                continue
        out[name] = {"fields": fields}
    return {"messages": out}


def _merge_opcodes(existing: dict, imported: dict) -> tuple[dict, int]:
    """手写/既有条目优先；导入条目仅补缺。message 名去掉 .Next. 前缀。"""
    opcodes = dict(existing.get("opcodes", {}))
    added = 0
    for key, item in imported.get("opcodes", {}).items():
        if key in opcodes:
            continue
        message = str(item.get("proto_name") or item.get("decode_as") or "").lstrip(".").removeprefix("Next.")
        opcodes[key] = {
            "name": item.get("name", f"op_{key}"),
            "category": str(item.get("category", "imported")),
            "message": message or None,
        }
        added += 1
    return {"opcodes": opcodes}, added


def main(argv: list[str]) -> int:
    src_dir = Path(argv[1]).resolve() if len(argv) > 1 else None
    proto_bytes = _fetch("proto_schema", URL_PROTO, _LOCAL_PROTO_CANDIDATES, src_dir)
    opcodes_bytes = _fetch("opcodes", URL_OPCODES, _LOCAL_OPCODES_CANDIDATES, src_dir)

    proto = json.loads(proto_bytes.decode("utf-8-sig"))
    imported_opcodes = json.loads(opcodes_bytes.decode("utf-8-sig"))

    messages_path = SCHEMA_DIR / "messages" / "all.json"
    messages_path.parent.mkdir(parents=True, exist_ok=True)
    normalized = _normalize_proto(proto)
    messages_path.write_text(
        json.dumps(normalized, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    print(f"[import] messages/all.json: {len(normalized['messages'])} 条消息定义")

    opcodes_path = SCHEMA_DIR / "opcodes.json"
    existing = json.loads(opcodes_path.read_text(encoding="utf-8")) if opcodes_path.is_file() else {}
    merged, added = _merge_opcodes(existing, imported_opcodes)
    opcodes_path.write_text(
        json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"[import] opcodes.json: 新增 {added} 条（保留既有 {len(existing.get('opcodes', {}))} 条）")
    print("[import] 完成。重启 SpriteLens 生效。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
