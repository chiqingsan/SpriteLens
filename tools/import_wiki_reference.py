"""从 B 站 Wiki 的 Lua 数据模块导入本地补充资料；仅解析数据，不执行 Lua。

输入目录须包含 wiki-Catalog.txt、wiki-Skills.txt，wiki-Learnsets.txt、wiki-Evolutions.txt。
先输出到暂存目录核对，再将 wiki_reference.json 发布到 data/static。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


class LuaTableReader:
    """只接受 Wiki 导出的 return + 表/字符串/数值/布尔值字面量。"""
    def __init__(self, text: str) -> None:
        self.tokens = re.findall(r'"(?:\\.|[^"\\])*"|[A-Za-z_][A-Za-z_0-9]*|-?\d+(?:\.\d+)?|[{}=,]|\S', text)
        self.index = 0

    def take(self, expected: str | None = None) -> str:
        token = self.tokens[self.index]
        self.index += 1
        if expected is not None and token != expected:
            raise ValueError(f"Expected {expected}, got {token}")
        return token

    def value(self) -> dict | list | str | int | float | bool:
        token = self.take()
        if token == "{":
            values, fields = [], {}
            while self.tokens[self.index] != "}":
                if self.tokens[self.index + 1] == "=":
                    key = self.take()
                    self.take("=")
                    fields[key] = self.value()
                else:
                    values.append(self.value())
                if self.tokens[self.index] == ",":
                    self.take(",")
            self.take("}")
            if fields and values:
                raise ValueError("Mixed Lua table is unsupported")
            return fields if fields else values
        if token.startswith('"'):
            return json.loads(token)
        if token in ("true", "false"):
            return token == "true"
        if re.fullmatch(r"-?\d+(?:\.\d+)?", token):
            return float(token) if "." in token else int(token)
        raise ValueError(f"Unsupported Lua token: {token}")

    def read(self) -> dict:
        self.take("return")
        result = self.value()
        if self.index != len(self.tokens) or not isinstance(result, dict):
            raise ValueError("Expected one complete data table")
        return result


def convert(source: Path) -> dict:
    modules, sources = {}, []
    for name in ("Catalog", "Skills", "Learnsets", "Evolutions"):
        path = source / f"wiki-{name}.txt"
        raw = path.read_bytes()
        modules[name] = LuaTableReader(raw.decode("utf-8")).read()
        sources.append({"url": f"https://wiki.biligame.com/nrc/模块:Pets/data/{name}",
                        "sha256": hashlib.sha256(raw).hexdigest()})
    catalog = {}
    for pet in modules["Catalog"].values():
        key = str(pet["game_id"])
        if key in catalog:
            raise ValueError(f"Duplicate game id: {key}")
        catalog[key] = {field: pet.get(field) for field in (
            "title", "name", "class", "feature_skill_id", "learnset_id", "evolution_id",
            "ecology", "can_ride", "can_double_ride")}
        catalog[key]["source_url"] = "https://wiki.biligame.com/nrc/" + pet["title"]
    return {"retrieved_at": datetime.now(timezone.utc).isoformat(), "sources": sources,
            "catalog": catalog, "skills": {key: {field: skill[field] for field in (
                "name", "desc", "category", "damage_class", "element", "energy", "power") if field in skill}
                for key, skill in modules["Skills"].items()},
            "learnsets": modules["Learnsets"], "evolutions": modules["Evolutions"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = convert(args.source)
    args.output.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Imported {len(result['catalog'])} species, {len(result['skills'])} skills")


if __name__ == "__main__":
    main()
