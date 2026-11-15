"""按 B 站 Wiki 进化表补全 data/static 的进化链。

进化链以 Wiki 的 `evolutions` 模块为准：`wiki_reference.json` 的 catalog 用游戏 ID 记录
`evolution_id`，此处按「名称必须唯一命中，且命中项的 evolution_id 与链一致」解析成员，
不按相似名称借用其它形态。分支线取 `chain` 与 `lord_branches`（首领形态）两段，
解析不出的链整条跳过并计数，不做猜测。

写入口径：缺链补全；本地已有值是 Wiki 链的子集时按 Wiki 扩充（只增不减）；
本地链含 Wiki 之外的成员时保留原值并列为冲突，不删除本机资料。

用法:
    .venv\\Scripts\\python.exe tools/sync_wiki_chains.py           # 写入缺失字段
    .venv\\Scripts\\python.exe tools/sync_wiki_chains.py --check   # 只检查，有可补链时退出非 0
"""
from __future__ import annotations

import argparse
import json
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "data" / "static"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: dict) -> None:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def norm_name(name: object) -> str:
    return unicodedata.normalize("NFKC", str(name or "")).strip()


class ChainIndex:
    """把 Wiki 进化表解析成「物种 ID → 分支线 / 下一阶」索引。"""

    def __init__(self, species: dict, wiki: dict) -> None:
        self.species = species
        self.catalog = wiki.get("catalog") or {}
        self.evolutions = wiki.get("evolutions") or {}
        self.byname: dict[str, set[str]] = {}
        for key, row in species.items():
            for name in {norm_name(row.get("name")), norm_name(row.get("display_name"))} - {""}:
                self.byname.setdefault(name, set()).add(str(key))
        self.chains: dict[str, list[tuple[list[str], list[str]]]] = {}
        self.unresolved: dict[str, int] = {}
        self.skipped: list[str] = []
        self._build()

    def _resolve(self, name: object, evolution_id: object) -> str | None:
        candidates = self.byname.get(norm_name(name), set())
        if len(candidates) > 1:
            candidates = {key for key in candidates
                          if self.catalog.get(key, {}).get("evolution_id") == evolution_id}
        return next(iter(candidates)) if len(candidates) == 1 else None

    def _miss(self, name: object) -> None:
        key = norm_name(name)
        self.unresolved[key] = self.unresolved.get(key, 0) + 1

    def _build(self) -> None:
        for base_id, entry in self.catalog.items():
            if base_id not in self.species:
                continue
            evolution_id = entry.get("evolution_id")
            lines: list[tuple[list[str], list[str]]] = []
            for branch in self.evolutions.get(evolution_id) or []:
                chain = [self._resolve(member.get("name"), evolution_id) for member in branch.get("chain") or []]
                if not chain or not all(chain) or len(set(chain)) != len(chain):
                    for member, key in zip(branch.get("chain") or [], chain):
                        if key is None:
                            self._miss(member.get("name"))
                    continue
                lords: list[str] = []
                for member in branch.get("lord_branches") or []:
                    key = self._resolve(member.get("name"), evolution_id)
                    if key is None:
                        self._miss(member.get("name"))
                    elif key not in lords:
                        lords.append(key)
                lines.append((chain, lords))
            if lines:
                self.chains[base_id] = lines
            else:
                self.skipped.append(base_id)

    def chain_of(self, base_id: str) -> tuple[list[int], list[int]] | None:
        """返回 (chain_members, evolutions)；base 不在任何已解析分支时返回 None。"""
        lines = [line for line in self.chains.get(base_id, []) if base_id in line[0] or base_id in line[1]]
        if not lines:
            return None
        members: list[int] = []
        for chain, lords in lines:
            for key in chain + lords:
                if int(key) not in members:
                    members.append(int(key))
        evolutions: list[int] = []
        for chain, lords in lines:
            if base_id not in chain:
                continue
            position = chain.index(base_id)
            children = chain[position + 1: position + 2] or lords
            for key in children:
                if int(key) not in evolutions:
                    evolutions.append(int(key))
        return members, evolutions


def sync(static: Path, check: bool) -> int:
    species = load(static / "species.json")
    eggs = load(static / "eggs.json")
    wiki = load(static / "wiki_reference.json")
    index = ChainIndex(species, wiki)

    filled: list[tuple[str, str]] = []
    enriched: list[tuple[str, str]] = []
    conflicts: list[dict] = []
    for base_id, chains in index.chains.items():
        row = species[base_id]
        expected = index.chain_of(base_id)
        if expected is None:
            continue
        members, evolutions = expected
        current = row.get("chain_members")
        if not current:
            row["chain_members"] = members
            row["evolutions"] = evolutions
            filled.append((base_id, row.get("name") or ""))
            continue
        if list(current) != members:
            if set(current) <= set(members):
                row["chain_members"] = members
                row["evolutions"] = evolutions
                enriched.append((base_id, row.get("name") or ""))
            else:
                conflicts.append({"id": base_id, "field": "chain_members", "name": row.get("name"),
                                  "kept": current, "wiki": members})
            continue
        if (row.get("evolutions") or []) != evolutions:
            if set(row.get("evolutions") or []) <= set(evolutions):
                row["evolutions"] = evolutions
                enriched.append((base_id, row.get("name") or ""))
            else:
                conflicts.append({"id": base_id, "field": "evolutions", "name": row.get("name"),
                                  "kept": row.get("evolutions"), "wiki": evolutions})

    egg_filled: list[str] = []
    egg_enriched: list[str] = []
    for egg in eggs["eggs"]:
        base_id = egg.get("base_id")
        row = species.get(str(base_id))
        if not row or not row.get("chain_members"):
            continue
        expected = [int(key) for key in row["chain_members"]]
        current = egg.get("chain_members")
        if not current:
            egg["chain_members"] = expected
            egg_filled.append(egg.get("egg_key") or "")
        elif list(current) != expected:
            if set(current) <= set(expected):
                egg["chain_members"] = expected
                egg_enriched.append(egg.get("egg_key") or "")
            else:
                conflicts.append({"id": egg.get("egg_key"), "field": "egg.chain_members",
                                  "name": egg.get("egg_name"), "kept": current, "wiki": expected})

    print(f"Wiki 可解析物种 {len(index.chains)}，跳过 {len(index.skipped)} 个（成员未唯一命中）")
    print(f"补全物种链 {len(filled)}: {[name for _, name in filled]}")
    print(f"按 Wiki 超集扩充 {len(enriched)} 条（只增不减）")
    print(f"补全蛋链 {len(egg_filled)}: {egg_filled}")
    print(f"扩充蛋链 {len(egg_enriched)} 条（只增不减）")
    print(f"冲突（本地含 Wiki 之外的成员，保留已有值）{len(conflicts)}: {conflicts[:5]}")
    if index.unresolved:
        print(f"未命中成员名 {len(index.unresolved)} 个（如 {list(index.unresolved)[:5]}）")

    if check:
        return 1 if (filled or enriched or egg_filled or egg_enriched) else 0
    if filled or enriched:
        write(static / "species.json", species)
    if egg_filled or egg_enriched:
        write(static / "eggs.json", eggs)
    if not (filled or enriched or egg_filled or egg_enriched):
        print("无需写入：链数据已与 Wiki 一致")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--static", type=Path, default=STATIC, help="静态数据目录（默认 data/static）")
    parser.add_argument("--check", action="store_true", help="只检查不写入；存在可补/可扩充字段时退出码 1")
    args = parser.parse_args()
    raise SystemExit(sync(args.static, args.check))


if __name__ == "__main__":
    main()
