"""V01：暂存构建、校验后发布；仅拥有 static/vue，不触碰媒体与原生页面。"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from spritelens.web.frontend_assets import check_frontend_assets

FRONTEND = ROOT / "frontend"
STATIC = ROOT / "spritelens/web/static"

# 稳定加载器：入口源 → 发布文件名与对外导出。主窗口壳与独立雷达窗各取所需，
# 雷达窗不再下载主窗口的业务页代码（PERF04）。
ENTRY_LOADERS = {
    "src/main.ts": "entry.js",
    "src/radar.ts": "radar-entry.js",
}
RADAR_EXPORTS = ("mountFloatingRadar",)


def _entry_css(manifest: dict, source: str) -> list[str]:
    """入口可达的 CSS（跟随静态与动态 import 的 manifest 引用）。"""
    seen: set[str] = set()
    styles: list[str] = []
    stack = [source]
    while stack:
        key = stack.pop()
        if key in seen:
            continue
        seen.add(key)
        chunk = manifest.get(key)
        if not isinstance(chunk, dict):
            continue
        for name in chunk.get("css", []):
            if name not in styles:
                styles.append(name)
        stack.extend(chunk.get("imports", []))
        stack.extend(chunk.get("dynamicImports", []))
    return sorted(styles)


def _style_links(styles: list[str]) -> str:
    return "".join(
        f"const link{i} = document.createElement('link'); link{i}.rel = 'stylesheet'; "
        f"link{i}.href = '/static/vue/{name}'; document.head.appendChild(link{i});\n"
        for i, name in enumerate(styles))


def source_hash() -> str:
    # 测试和合成数据不进入运行产物，修改它们不应强迫重建页面。
    files = sorted(path for path in (FRONTEND / "src").rglob("*")
                   if not path.name.endswith(".test.ts") and path.name not in {"testData.ts", "petTestData.ts"}) + [FRONTEND / name for name in
        ("package.json", "package-lock.json", "tsconfig.json", "vite.config.ts",
         ".node-version", ".npmrc")] + [ROOT / "tools/frontend.py"]
    digest = hashlib.sha256()
    for path in files:
        if path.is_file():
            digest.update(path.relative_to(ROOT).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def check() -> list[str]:
    directory = STATIC / "vue"
    failures = check_frontend_assets(directory)
    for name in ("vue-pending", "vue-previous"):
        if (STATIC / name).exists():
            failures.append(f"前端发布残留: {name}，请检查上次发布失败的产物")
    if not failures:
        receipt = json.loads((directory / "build.json").read_text(encoding="utf-8"))
        if receipt["source_hash"] != source_hash():
            failures.append("Vue 产物过期，请运行 .venv/Scripts/python.exe tools/frontend.py build")
    return failures


def build() -> int:
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit("请安装 Node.js 24 LTS 与 npm 11，并在 frontend 执行 npm ci")
    proc = subprocess.run([npm, "run", "build"], cwd=FRONTEND)
    if proc.returncode:
        return proc.returncode
    stage = FRONTEND / "dist"
    manifest = json.loads((stage / ".vite/manifest.json").read_text(encoding="utf-8"))
    # 稳定入口由旧壳动态 import，媒体继续使用现有 /static 路径。
    # 新增页面桥必须同步登记在这里：漏登记时壳只会在浏览器里报「xxx is not a function」。
    mounts = ("mountFloatingRadar", "mountNearby", "mountCaptureDiagnostics", "mount", "mountEggBox", "mountHome", "mountCollectionLines",
              "mountBreederLibrary", "mountBreedingPlanner", "mountPetFilters",
              "mountPetInventory", "mountHandbook", "mountColors")
    for source, loader_name in ENTRY_LOADERS.items():
        entry = manifest[source]
        if not entry.get("isEntry"):
            raise SystemExit(f"Vue 入口不是独立入口: {source}")
        exports = RADAR_EXPORTS if source == "src/radar.ts" else mounts
        # entry.js 导入后才注入样式链接：两个窗口各自只等自己入口可达的 CSS。
        loader = _style_links(_entry_css(manifest, source))
        loader += f"export {{ {', '.join(exports)} }} from './{entry['file']}';\n"
        (stage / loader_name).write_text(loader, encoding="utf-8", newline="\n")
    outputs = {path.relative_to(stage).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
               for path in sorted(stage.rglob("*")) if path.is_file()}
    receipt = {"source_hash": source_hash(), "outputs": outputs}
    (stage / "build.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
    failures = check_frontend_assets(stage)
    if failures:
        raise SystemExit("\n".join(failures))
    target = (STATIC / "vue").resolve()
    if target.parent != STATIC.resolve() or target.name != "vue":
        raise SystemExit("发布目录越界")
    # 所有验证完成后才替换专用生成目录；复制失败保留旧产物。
    pending = STATIC / "vue-pending"
    if pending.exists():
        raise SystemExit("vue-pending 已存在，请检查上次发布失败的产物")
    backup = STATIC / "vue-previous"
    if backup.exists():
        raise SystemExit("vue-previous 已存在，请检查上次发布失败的产物")
    shutil.copytree(stage, pending)
    if target.exists():
        target.rename(backup)
    try:
        pending.rename(target)
    except OSError:
        if backup.exists():
            backup.rename(target)
        raise
    if backup.exists():
        if backup.resolve().parent != STATIC.resolve():
            raise SystemExit("清理目录越界")
        shutil.rmtree(backup)
    print(f"[frontend] 发布通过: {len(outputs)} 个文件")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "check"))
    args = parser.parse_args()
    if args.action == "build":
        return build()
    failures = check()
    for failure in failures:
        print(failure)
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
