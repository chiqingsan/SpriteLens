"""view_models 包内共享工具：解码树的文本渲染等。"""

from __future__ import annotations


def render_decoded(decoded: list[dict], indent: int = 0) -> str:
    """把 schema/wire 解码树渲染为缩进文本（UI 详情面板用）。"""
    lines: list[str] = []
    _render_fields(decoded, indent, lines)
    return "\n".join(lines)


def _render_fields(fields: list[dict], indent: int, lines: list[str]) -> None:
    pad = "  " * indent
    for field in fields:
        name = field.get("name", "?")
        ftype = field.get("type", "?")
        value = field.get("value", "")
        lines.append(f"{pad}{name} [{ftype}] = {value}")
        children = field.get("children")
        if children:
            _render_fields(children, indent + 1, lines)
        if field.get("text"):
            lines.append(f"{pad}  └ 文本: {field['text']}")
