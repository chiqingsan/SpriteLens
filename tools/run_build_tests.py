"""工程门禁（G01/V01）：unittest + JS/资源 + Vue 类型、lint、测试与产物。

统一验证入口：`python -B tools/run_build_tests.py`
- unittest discover（全量 Python 测试）
- web/static 递归 JS 语法检查（node --check，含 pages/ 子目录）
- index.html 本地 script/link 引用存在性（新增页面漏登记即失败）
- smoke 固定资源清单（vue/entry.js 等随包文件必须存在）
- Vue 类型 / ESLint / Vitest 与源指纹、产物哈希检查

JS 语法/引用存在性是工程门禁，不替代浏览器交互验收（视觉/行为另跑）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
STATIC_DIR = PROJECT_ROOT / "spritelens" / "web" / "static"

# 随包必需的前端文件（与 spritelens/main.py 的 smoke 清单一致；两处同步维护）
REQUIRED_STATIC_FILES = (
    "index.html",
    "boot.js",
    "desktop-shell.js",
    "desktop-shell.css",
    "ui.js",
    "app.js",
    "app.css",
    "ui.css",
    "themes.css",
    "appearance.js",
    "pet-presentation.js",
    "account-requests.js",
    "icons.js",
    "icons/sprite.svg",
    "vue/entry.js",
    "favicon.png",
)


def check_js_syntax() -> list[str]:
    """node --check 递归检查全部静态 JS。

    缺 Node 时门禁失败，不能把未执行的必需检查报告为通过。
    """
    failures: list[str] = []
    js_files = sorted(STATIC_DIR.rglob("*.js"))
    if not js_files:
        return ["未找到任何 JS 文件（静态目录异常）"]
    import shutil

    node = shutil.which("node")
    if node is None:
        return ["未找到 node 可执行文件：请安装 Node.js 后重新执行完整门禁"]
    for path in js_files:
        proc = subprocess.run(
            [node, "--check", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            rel = path.relative_to(PROJECT_ROOT)
            failures.append(f"JS 语法错误: {rel}\n{proc.stderr.strip()}")
    return failures


def check_html_references() -> list[str]:
    """index.html 引用的本地 script/src/href 必须存在（远程/绝对 URL 跳过）。

    SVG sprite 的 `#fragment` 引用（sprite.svg#icon）指向同一文件内锚点，
    只校验文件本身存在，不校验 fragment。
    """
    failures: list[str] = []
    index = STATIC_DIR / "index.html"
    if not index.is_file():
        return ["index.html 缺失"]
    import re

    text = index.read_text(encoding="utf-8")
    # 服务端动态路由（非静态文件）：favicon 由 server._favicon 处理
    route_prefixes = ("/api/", "/ws")
    for match in re.finditer(r'(?:src|href)="([^"]+)"', text):
        target = match.group(1)
        if target.startswith(("http://", "https://", "//", "data:", "#")):
            continue
        rel = target.lstrip("/")
        if any(rel.startswith(prefix) for prefix in route_prefixes):
            continue
        if rel == "favicon.ico":
            continue  # 服务端路由，_favicon 回 204 或文件
        # /static/ 前缀映射到静态目录；相对路径按 index.html 所在目录解析
        if rel.startswith("static/"):
            path = STATIC_DIR / rel[len("static/"):]
        else:
            path = STATIC_DIR / rel
        # 同文件 fragment 引用（如 sprite.svg#xxx）：去掉 fragment 后校验
        path = Path(str(path).split("#", 1)[0])
        if not path.is_file():
            failures.append(f"index.html 引用缺失: {target}")
    return failures


def check_required_static_files() -> list[str]:
    failures: list[str] = []
    for name in REQUIRED_STATIC_FILES:
        if not (STATIC_DIR / name).is_file():
            failures.append(f"前端必需文件缺失: static/{name}")
    return failures


def check_dependencies() -> list[str]:
    """测试所需关键依赖可导入（新环境漏装时给出明确提示而非随机报错）。"""
    failures: list[str] = []
    for module, purpose in (("PIL", "资源/图片校验"), ("aiohttp", "Web 服务测试")):
        try:
            __import__(module)
        except ImportError as exc:
            failures.append(f"缺依赖 {module}（{purpose}）：请安装 requirements-dev.txt — {exc}")
    return failures


def main() -> int:
    failed = False

    print("[gate] unittest discover ...")
    import os

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    cmd = [
        sys.executable, "-B", "-m", "unittest", "discover",
        "-s", "tests", "-p", "test_*.py", "-q",
    ]
    proc = subprocess.run(
        cmd, cwd=PROJECT_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=env,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    print(output, end="" if output.endswith("\n") else "\n")
    if proc.returncode != 0:
        print("[gate] unittest 失败")
        failed = True
    else:
        import re

        matched = re.search(r"Ran (\d+) tests", output)
        print(f"[gate] unittest 通过: {matched.group(1) if matched else '?'} 项")

    print("[gate] JS 语法检查（递归）...")
    failures = check_js_syntax()
    if failures:
        failed = True
        for item in failures:
            print(f"  - {item}")
    else:
        js_count = len(list(STATIC_DIR.rglob("*.js")))
        print(f"[gate] JS 语法通过: {js_count} 个文件")

    print("[gate] HTML 引用检查 ...")
    failures = check_html_references()
    if failures:
        failed = True
        for item in failures:
            print(f"  - {item}")
    else:
        print("[gate] HTML 引用通过")

    print("[gate] 静态资源清单 ...")
    failures = check_required_static_files()
    if failures:
        failed = True
        for item in failures:
            print(f"  - {item}")
    else:
        print(f"[gate] 静态资源通过: {len(REQUIRED_STATIC_FILES)} 项")

    print("[gate] 依赖可用性 ...")
    failures = check_dependencies()
    if failures:
        failed = True
        for item in failures:
            print(f"  - {item}")
    else:
        print("[gate] 依赖通过")

    print("[gate] Vue 类型 / ESLint / 组件测试 / 产物 ...")
    import shutil
    from tools.frontend import check

    npm = shutil.which("npm")
    if npm is None:
        print("[gate] 缺 npm：请安装 Node.js 24 LTS / npm 11")
        failed = True
    else:
        for script in ("typecheck", "lint", "test"):
            result = subprocess.run([npm, "run", script], cwd=PROJECT_ROOT / "frontend")
            if result.returncode:
                failed = True
    for failure in check():
        print(f"[gate] {failure}")
        failed = True

    if failed:
        print("[gate] 失败")
        return 1
    print("[gate] 通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
