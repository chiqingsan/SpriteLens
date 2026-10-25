"""schema 双路解码：schema 精确字段名优先，缺失时降级 wire 字段号树。

schema 数据外挂在 data/schemas/：
- opcodes.json            opcode → 名称/分类/消息名
- messages/<Name>.json    消息字段定义 {"fields": {"<字段号>": {"name","type"}}}

解码输出统一为 list[dict]（JSON 友好，UI 与测试共用）：
    {"no", "name", "type", "value", "children"?/"text"?}
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from spritelens.logs import get_logger
from spritelens.protocol import wire

logger = get_logger("schema")

Messages = dict[str, dict[int, dict[str, str]]]

_library: "SchemaLibrary | None" = None


@dataclass(frozen=True)
class SchemaLibrary:
    """只读 schema 集合；加载失败整体降级为空库（wire 兜底仍可用）。"""

    messages: Messages
    source_dir: Path | None

    def field_defs(self, message_name: str) -> dict[int, dict[str, str]] | None:
        fields = self.messages.get(message_name)
        if fields is None:
            # 兼容带命名空间前缀的消息名（如 Next.XxxRsp）
            short = message_name.rsplit(".", 1)[-1]
            fields = self.messages.get(short)
        return fields

    def decode(self, payload: bytes, message_name: str | None) -> list[dict]:
        """解码 payload：schema 命中 → 字段名；否则 field_N 占位。"""
        tree = wire.decode_wire(payload)
        fields = self.field_defs(message_name) if message_name else None
        return [_field_to_dict(f, fields, self) for f in tree]


def _field_to_dict(
    field: wire.WireField,
    defs: dict[int, dict[str, str]] | None,
    library: "SchemaLibrary | None" = None,
) -> dict:
    meta = (defs or {}).get(field.no, {})
    raw = field.value if field.children is None else None
    # schema 命中时不必先算兜底名称/类型：dict.get 的默认实参会立即求值，
    # 大包每节点会白算两次（2026-10-26 实测单个 0x0102 包 5.3 万节点）。
    name = meta["name"] if "name" in meta else field.display_name()
    type_name = meta["type"] if "type" in meta else _wire_type_name(field.wire_type)
    out: dict = {
        "no": field.no,
        "name": name,
        "type": type_name,
        "value": field.display_value(),
        # raw 为强类型原值（int / bytes），供语义层提取；嵌套节点无 raw
        "raw": raw,
    }
    if field.children is not None:
        child_defs = None
        child_type = meta.get("type", "")
        # 嵌套消息的字段定义约定存放在 messages/<ChildType>.json；
        # 递归显式使用发起解码的实例（R07）：不读全局库，多个实例库
        # 或按游戏版本选库时互不污染，也不依赖全局加载顺序
        if child_type and library is not None:
            child_defs = library.field_defs(child_type)
        out["children"] = [_field_to_dict(c, child_defs, library) for c in field.children]
    elif field.text is not None:
        out["text"] = field.text
    return out


def _wire_type_name(wire_type: int) -> str:
    return {
        wire.WIRE_VARINT: "varint",
        wire.WIRE_FIXED64: "fixed64",
        wire.WIRE_LEN: "len",
        wire.WIRE_FIXED32: "fixed32",
    }.get(wire_type, f"wt{wire_type}")


def load_library(schema_dir: Path) -> SchemaLibrary:
    """加载 messages/*.json（进程级缓存；重复调用覆盖）。失败降级空库。

    合并策略是**字段级**而非消息级：all.json 提供全量定义，后加载的手写
    文件只覆盖它显式列出的字段，其余字段保留。手写文件若整体替换同名消息
    （历史行为）会把 all.json 里未列出的字段一起丢掉——实测中 PetBriefInfo
    因此从 38 字段缩到 11 字段，六维/身高体重等字段名全部退化成 field_N。
    """
    global _library
    messages: Messages = {}
    try:
        for path in sorted(schema_dir.glob("messages/*.json")):
            if path.name.startswith("_"):
                continue
            raw = json.loads(path.read_text(encoding="utf-8"))
            for name, item in raw.get("messages", {}).items():
                fields = messages.setdefault(name, {})
                for no_key, field in (item.get("fields") or {}).items():
                    try:
                        fields[int(no_key)] = {
                            "name": str(field.get("name", f"field_{no_key}")),
                            "type": str(field.get("type", "")),
                        }
                    except (TypeError, ValueError):
                        continue
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("schema 加载失败，wire 级兜底: %s", exc)
    _library = SchemaLibrary(messages=messages, source_dir=schema_dir if messages else None)
    return _library


def get_library() -> SchemaLibrary:
    """未显式加载时返回空库，保证任何调用路径都有 wire 级兜底。"""
    return _library if _library is not None else SchemaLibrary(messages={}, source_dir=None)
