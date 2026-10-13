"""Vue 运行产物契约；源码指纹检查由构建工具负责，冻结包只检查产物。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def check_frontend_assets(directory: Path) -> list[str]:
    """检查入口、Vite chunk/媒体引用及发布哈希，缺失或损坏必须阻断发布。"""
    try:
        receipt = json.loads((directory / "build.json").read_text(encoding="utf-8"))
        manifest = json.loads((directory / ".vite/manifest.json").read_text(encoding="utf-8"))
        outputs = receipt["outputs"]
        entry = manifest["src/main.ts"]
        if not entry["isEntry"] or "entry.js" not in outputs:
            return ["Vue 入口清单无效"]
        failures: list[str] = []
        for name, digest in outputs.items():
            path = (directory / name).resolve()
            if not path.is_relative_to(directory.resolve()):
                failures.append(f"Vue 清单路径越界: {name}")
            elif not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                failures.append(f"Vue 产物缺失或已改变: {name}")
        for chunk in manifest.values():
            for name in [chunk["file"], *chunk.get("css", []), *chunk.get("assets", [])]:
                if name not in outputs:
                    failures.append(f"Vue 引用未登记: {name}")
            for name in [*chunk.get("imports", []), *chunk.get("dynamicImports", [])]:
                if name not in manifest:
                    failures.append(f"Vue chunk 引用缺失: {name}")
        return failures
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [f"Vue 产物清单不可用，请运行 tools/frontend.py build: {exc}"]
