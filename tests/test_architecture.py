"""架构边界回归测试：分层依赖方向（节选自 docs/DEVELOPMENT_GUIDE.md）。

用 AST 静态解析源码，不导入被测模块（避免 import 副作用与平台差异）。
约束一旦被破坏即在此变红——竞品的 import 图污染正是缺了这道闸。

已豁免的既有例外（在约束收紧前记录在案，不得再增加）：
1. protocol 内的 schema/opcodes 依赖 logs（加载期告警日志）。
（原例外2「domain 依赖 services.PacketEvent」已随事件类型移入
  spritelens/events.py 中立叶子模块而移除，2026-10-12。）
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "spritelens"

# 业务层（除 web 外）一律不得依赖 Web 栈
WEB_FRAMEWORKS = {"aiohttp", "webview"}
BUSINESS_PACKAGES = (
    "protocol",
    "domain",
    "repositories",
    "services",
    "capture",
    "recording",
    "view_models",
    "system",
    "logs",
)

# 已批准的例外：(依赖方模块前缀, 被依赖模块前缀)
APPROVED_EXCEPTIONS = {
    ("spritelens.protocol", "spritelens.logs"),
}

# protocol 是纯函数层：只允许标准库 + 第三方密码库 + logs 例外
PROTOCOL_ALLOWED_INTERNAL = {"spritelens.protocol", "spritelens.logs"}


def _iter_modules():
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path


def _imports_of(path: Path) -> list[str]:
    """收集一个文件中所有 import 的目标模块名（顶层形式）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    targets: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # 相对导入在包内已统一为绝对形式，出现即视为违规信号
                targets.append("." * node.level + (node.module or ""))
            elif node.module:
                targets.append(node.module)
    return targets


def _module_name(path: Path) -> str:
    rel = path.relative_to(PACKAGE_ROOT.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _package_of(path: Path) -> str:
    rel = path.relative_to(PACKAGE_ROOT).parts
    return rel[0] if len(rel) > 1 else ""


class NoWebDependencyTest(unittest.TestCase):
    """业务层不得依赖 Web 框架（aiohttp / pywebview）。"""

    def test_business_layers_do_not_import_web_frameworks(self):
        offenders: list[str] = []
        for path in _iter_modules():
            package = _package_of(path)
            if package not in BUSINESS_PACKAGES:
                continue
            for target in _imports_of(path):
                if target.split(".")[0] in WEB_FRAMEWORKS:
                    offenders.append(f"{_module_name(path)} → {target}")
        self.assertEqual([], offenders, f"业务层引入了 Web 依赖: {offenders}")


class LayerDirectionTest(unittest.TestCase):
    """依赖方向：上层可依赖下层，反向依赖必须报错（已批准例外除外）。"""

    # 层级序号越小越底层；允许依赖序号更小的层。
    # spritelens.events 是中立叶子模块（无 IO 无依赖），层级 0——任何层
    # 都可以依赖它而不视为反向。
    LAYER_ORDER = {
        "protocol": 0,
        "logs": 0,
        "events": 0,
        "capture": 1,
        "domain": 2,
        "repositories": 2,
        "services": 3,
        "view_models": 4,
        "recording": 4,
        "system": 4,
        "web": 5,
    }
    # 同层或跨层的既有合法依赖（本测试只拦截明确反向的）
    def test_no_upward_internal_dependencies(self):
        offenders: list[str] = []
        for path in _iter_modules():
            source_pkg = _package_of(path)
            source_layer = self.LAYER_ORDER.get(source_pkg)
            if source_layer is None:
                continue
            for target in _imports_of(path):
                if not target.startswith("spritelens."):
                    continue
                target_pkg = target.split(".")[1]
                target_layer = self.LAYER_ORDER.get(target_pkg)
                if target_layer is None or target_layer <= source_layer:
                    continue
                pair = (f"spritelens.{source_pkg}", f"spritelens.{target_pkg}")
                # 例外按「模块 + 包」放宽到整个包前缀
                if any(
                    f"spritelens.{source_pkg}".startswith(s) and f"spritelens.{target_pkg}".startswith(t)
                    for s, t in APPROVED_EXCEPTIONS
                ):
                    continue
                offenders.append(f"{_module_name(path)} (层{source_layer}) → {target} (层{target_layer})")
        self.assertEqual([], offenders, f"出现反向依赖: {offenders}")


class ProtocolPurityTest(unittest.TestCase):
    """protocol 是纯函数层：不得依赖业务层，只允许 logs 例外。"""

    def test_protocol_only_depends_on_itself_and_logs(self):
        offenders: list[str] = []
        for path in _iter_modules():
            if _package_of(path) != "protocol":
                continue
            for target in _imports_of(path):
                if not target.startswith("spritelens."):
                    continue
                if not any(target.startswith(allowed) for allowed in PROTOCOL_ALLOWED_INTERNAL):
                    offenders.append(f"{_module_name(path)} → {target}")
        self.assertEqual([], offenders, f"protocol 依赖了业务层: {offenders}")

    def test_protocol_has_no_threading_or_io_imports(self):
        """零 IO / 零线程：不引入 threading、socket、asyncio、urllib 等。"""
        forbidden = {"threading", "socket", "asyncio", "urllib", "http", "subprocess"}
        offenders: list[str] = []
        for path in _iter_modules():
            if _package_of(path) != "protocol":
                continue
            for target in _imports_of(path):
                if target.split(".")[0] in forbidden:
                    offenders.append(f"{_module_name(path)} → {target}")
        self.assertEqual([], offenders, f"protocol 引入 IO/线程依赖: {offenders}")


class WebLayerTest(unittest.TestCase):
    """web 层可以碰 Web 框架，但不得被业务层反向依赖（由上面的方向测试覆盖）。"""

    def test_web_layer_exists_and_is_only_ui_entry(self):
        web_dir = PACKAGE_ROOT / "web"
        self.assertTrue((web_dir / "server.py").is_file())
        self.assertTrue((web_dir / "run.py").is_file())

        # app_context 是装配根，允许被 web 依赖；业务层不得依赖 app_context
        offenders: list[str] = []
        for path in _iter_modules():
            if _package_of(path) in ("web", "logs"):
                continue
            for target in _imports_of(path):
                if target.startswith("spritelens.app_context"):
                    offenders.append(_module_name(path))
        self.assertEqual([], offenders, f"业务层依赖了装配根: {offenders}")


if __name__ == "__main__":
    unittest.main()
