"""opcode → 名称/分类目录。

数据来自外挂 data/schemas/opcodes.json（格式见该文件头注释）；
未收录的 opcode 不影响解码，显示为 op_0xXXXX，由 schema 层兜底。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from spritelens.logs import get_logger

logger = get_logger("opcodes")


@dataclass(frozen=True)
class OpcodeInfo:
    name: str
    category: str
    message: str | None


class OpcodeCatalog:
    """线程安全的 opcode 只读目录；加载失败时降级为空目录（全部走占位名）。"""

    def __init__(self, mapping: dict[int, OpcodeInfo]) -> None:
        self._mapping = mapping

    def lookup(self, opcode: int) -> OpcodeInfo | None:
        return self._mapping.get(opcode)

    def display_name(self, opcode: int) -> str:
        info = self._mapping.get(opcode)
        return info.name if info else f"op_0x{opcode:04X}"

    @property
    def size(self) -> int:
        return len(self._mapping)

    @classmethod
    def load(cls, path: Path) -> "OpcodeCatalog":
        try:
            if not path.is_file():
                logger.warning("opcode 目录缺失: %s", path)
                return cls({})
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("opcode 目录加载失败，使用占位名: %s", exc)
            return cls({})
        mapping: dict[int, OpcodeInfo] = {}
        for key, item in raw.get("opcodes", {}).items():
            if not isinstance(item, dict):
                continue
            try:
                opcode = int(key, 16) if key.startswith("0x") else int(key)
            except ValueError:
                continue
            message = item.get("message")
            mapping[opcode] = OpcodeInfo(
                name=str(item.get("name", f"op_0x{opcode:04X}")),
                category=str(item.get("category", "misc")),
                message=str(message) if message else None,
            )
        return cls(mapping)
