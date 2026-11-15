"""Nuitka 打包脚本（SpriteLens）。

配置驱动：常用选项改 build_config.toml，不在这里写死。
用法：
    .venv\\Scripts\\python.exe build.py             # 正式打包
    .venv\\Scripts\\python.exe build.py --dry-run   # 只打印命令，不编译
    build.bat                                        # 同上（自动找 venv）
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = PROJECT_ROOT / "build_config.toml"
VERSION_INIT_FILE = PROJECT_ROOT / "spritelens" / "__init__.py"
VERSION_FORMAT_PATTERN = re.compile(r"^\d+\.\d+(?:\.\d+)?(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?$")
BACKEND_FLAG_ENV_KEYS = {
    "backend_cpp_flags": "CPPFLAGS",
    "backend_c_flags": "CFLAGS",
    "backend_cc_flags": "CCFLAGS",
    "backend_cxx_flags": "CXXFLAGS",
    "backend_ld_flags": "LDFLAGS",
}


def configure_stdio_encoding() -> None:
    """让 Windows 命令行稳定输出 UTF-8 中文。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def load_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"找不到配置文件: {path}")
    with path.open("rb") as handle:
        return tomllib.load(handle)


def as_list(config: dict[str, Any], key: str) -> list[str]:
    value = config.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"配置项 {key} 必须是数组")
    return [str(item) for item in value]


def as_bool(config: dict[str, Any], key: str, default: bool = False) -> bool:
    value = config.get(key, default)
    return bool(value)


def resolve_project_path(value: str, field_name: str, *, must_exist: bool = True) -> Path:
    path = (PROJECT_ROOT / value).resolve()
    if must_exist and not path.exists():
        raise SystemExit(f"{field_name} 指向的路径不存在: {path}")
    return path


def load_project_version(init_file: Path = VERSION_INIT_FILE) -> str:
    """从 spritelens/__init__.py 解析 __version__，不 import 应用代码。"""
    try:
        source = init_file.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError) as exc:
        raise RuntimeError(f"无法读取版本号: {init_file}") from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__version__":
                    value = ast.literal_eval(node.value)
                    if isinstance(value, str):
                        return value
    raise RuntimeError(f"未在 {init_file} 找到字符串 __version__")


def normalize_version_input(raw: str) -> str:
    """规范化版本号；允许 v 前缀，拒绝不能用于产物命名的字符。"""
    value = str(raw).strip()
    if value[:1] in {"v", "V"}:
        value = value[1:].strip()
    if not value:
        return ""
    if not VERSION_FORMAT_PATTERN.match(value):
        raise ValueError(f"版本号格式无效: {raw!r}；示例: 0.2 / 0.2.0 / 0.2.0-rc.1")
    return value


def set_project_version(new_version: str, *, init_file: Path = VERSION_INIT_FILE) -> str:
    """更新 spritelens/__init__.py 中的 __version__，返回旧版本号。"""
    old_version = load_project_version(init_file)
    text = init_file.read_bytes().decode("utf-8")
    pattern = re.compile(r"(?m)^(__version__\s*=\s*)(['\"])[^'\"]*\2")
    new_text, replaced = pattern.subn(
        lambda match: f"{match.group(1)}{match.group(2)}{new_version}{match.group(2)}",
        text,
        count=1,
    )
    if replaced != 1:
        raise RuntimeError(f"无法定位 __version__ 赋值行: {init_file}")
    if new_text != text:
        init_file.write_bytes(new_text.encode("utf-8"))
    return old_version


def prompt_project_version(current_version: str) -> str | None:
    """交互式读取新版本号；空输入取消。"""
    print(f"当前版本号: {current_version}")
    print("示例: 0.2 / 0.2.0 / 0.2.0-rc.1（直接回车取消）")
    while True:
        print("新的版本号: ", end="", flush=True)
        try:
            raw = input()
        except EOFError:
            return None
        try:
            value = normalize_version_input(raw)
        except ValueError as exc:
            print(exc)
            continue
        return value or None


def run_version_update(raw_version: str) -> int:
    """执行 --set-version；不带值时进入交互输入。"""
    current_version = load_project_version()
    if raw_version:
        try:
            new_version = normalize_version_input(raw_version)
        except ValueError as exc:
            print(exc)
            return 1
    else:
        new_version = prompt_project_version(current_version)
        if new_version is None:
            print("已取消修改版本号。")
            return 0
    if new_version == current_version:
        print(f"版本号未变化: {current_version}")
        return 0
    old_version = set_project_version(new_version)
    print(f"版本号已修改: {old_version} -> {new_version}")
    print(f"文件: {VERSION_INIT_FILE}")
    return 0


def windows_version_string(version: str) -> str:
    """Windows 资源版本要求 a.b.c.d；不足位补零。"""
    parts = re.findall(r"\d+", version)[:4]
    while len(parts) < 4:
        parts.append("0")
    return ".".join(parts)


def build_timestamp(*, now_seconds: int | None = None) -> str:
    """本地日期 MMDD + Unix 时间戳秒数后四位，固定八位。"""
    seconds = int(time.time()) if now_seconds is None else int(now_seconds)
    return f"{time.strftime('%m%d', time.localtime(seconds))}{seconds % 10000:04d}"


def build_output_name(
    config: dict[str, Any], version: str, *, timestamp: str | None = None
) -> str:
    app_name = str(config.get("app_name") or "app")
    template = str(
        config.get("output_name_template")
        or "{app_display_name}_{app_name}_{version}_{timestamp}"
    )
    return template.format(
        app_display_name=str(config.get("app_display_name") or app_name),
        app_name=app_name,
        version=version,
        timestamp=timestamp if timestamp is not None else build_timestamp(),
    )


def available_output_name(
    config: dict[str, Any],
    version: str,
    *,
    timestamp: str,
    output_dir: Path,
    suffix: str,
) -> str:
    """文件名优先使用时间戳；已存在时追加序号，避免覆盖旧产物。"""
    base_name = build_output_name(config, version, timestamp=timestamp)
    candidate = base_name
    index = 2
    while (output_dir / f"{candidate}{suffix}").exists():
        candidate = f"{base_name}-{index}"
        index += 1
    return candidate


def build_command(
    config: dict[str, Any], *, version: str, timestamp: str | None = None
) -> list[str]:
    app_name = str(config.get("app_name") or "app")
    output_name = build_output_name(config, version, timestamp=timestamp)
    entry = resolve_project_path(str(config.get("entry") or "main.py"), "entry")

    command: list[str] = [sys.executable, "-m", "nuitka"]

    if as_bool(config, "standalone", True):
        command.append("--standalone")
    if as_bool(config, "onefile", True):
        command.append("--onefile")
    if as_bool(config, "windowed", True):
        command.append("--windows-console-mode=disable")
    if as_bool(config, "uac_admin", False):
        command.append("--windows-uac-admin")
    if as_bool(config, "remove_output", True):
        command.append("--remove-output")
    if as_bool(config, "assume_yes_for_downloads", True):
        command.append("--assume-yes-for-downloads")
    if as_bool(config, "mingw64", False):
        command.append("--mingw64")
    if as_bool(config, "show_progress", False):
        command.append("--show-progress")
    if as_bool(config, "show_memory", False):
        command.append("--show-memory")

    command.append(f"--output-filename={output_name}")
    command.append(f"--output-dir={resolve_project_path(str(config.get('output_dir', 'build')), 'output_dir', must_exist=False)}")

    product_name = str(config.get("product_name") or app_name)
    file_description = str(config.get("file_description") or product_name)
    company_name = str(config.get("company_name") or app_name)
    command.extend(
        [
            f"--product-name={product_name}",
            f"--file-description={file_description}",
            f"--file-version={windows_version_string(version)}",
            f"--product-version={windows_version_string(version)}",
            f"--company-name={company_name}",
        ]
    )

    icon_value = config.get("icon")
    if icon_value:
        icon = resolve_project_path(str(icon_value), "icon")
        command.append(f"--windows-icon-from-ico={icon}")

    for plugin_name in as_list(config, "plugins"):
        command.append(f"--enable-plugin={plugin_name}")
    for package_name in as_list(config, "include_packages"):
        command.append(f"--include-package={package_name}")
    for module_name in as_list(config, "include_modules"):
        command.append(f"--include-module={module_name}")
    for item in as_list(config, "include_data_dirs"):
        if "=" not in item:
            raise SystemExit(f"include_data_dirs 项须为 source=dest 格式: {item}")
        source_value, dest = item.split("=", 1)
        source = resolve_project_path(source_value.strip(), "include_data_dirs")
        if not source.is_dir():
            raise SystemExit(f"include_data_dirs 源必须是目录: {source}")
        command.append(f"--include-data-dir={source}={dest.strip()}")
    for item in as_list(config, "include_data_files"):
        if "=" not in item:
            raise SystemExit(f"include_data_files 项须为 source=dest 格式: {item}")
        source_value, dest = item.split("=", 1)
        source = resolve_project_path(source_value.strip(), "include_data_files")
        if not source.is_file():
            raise SystemExit(f"include_data_files 源必须是文件: {source}")
        command.append(f"--include-data-file={source}={dest.strip()}")
    for item in as_list(config, "nofollow_imports"):
        command.append(f"--nofollow-import-to={item}")

    command.extend(as_list(config, "additional_args"))
    command.append(str(entry))
    return command


def build_environment(config: dict[str, Any]) -> dict[str, str]:
    env = os.environ.copy()
    output_dir = resolve_project_path(str(config.get("output_dir", "build")), "output_dir", must_exist=False)
    cache_root = output_dir / "nuitka-cache"
    for key in ("NUITKA_CACHE_DIR", "NUITKA_CACHE_DIR_ZIG", "ZIG_LOCAL_CACHE_DIR", "ZIG_GLOBAL_CACHE_DIR"):
        env.setdefault(key, str(cache_root))
    # Windows onefile：Zig 的 C23 #embed 可能复用过期对象，改用 COFF 嵌入
    if os.name == "nt" and as_bool(config, "onefile", True):
        env.setdefault("NUITKA_RESOURCE_MODE", "coff_obj")
    for config_key, env_key in BACKEND_FLAG_ENV_KEYS.items():
        flags = as_list(config, config_key)
        if flags:
            additions = " ".join(flag.strip() for flag in flags if flag.strip())
            if additions:
                existing = env.get(env_key, "").strip()
                env[env_key] = f"{existing} {additions}".strip()
    return env


def check_environment(config: dict[str, Any]) -> None:
    """打包前检查：Nuitka 可用、编译器就绪与否给出提示。"""
    try:
        import nuitka  # noqa: F401
    except ImportError:
        raise SystemExit(
            "Nuitka 未安装。先执行：\n"
            "    .venv\\Scripts\\pip install -r requirements-build.txt"
        )

    icon = config.get("icon")
    if icon and not resolve_project_path(str(icon), "icon").is_file():
        raise SystemExit(f"图标不存在，先跑 tools/make_icon.py 生成: {icon}")


def print_summary(config: dict[str, Any], version: str) -> None:
    mode = "onefile" if as_bool(config, "onefile", True) else "standalone 目录"
    print(f"[build] 应用: {config.get('product_name')} {version}")
    print(f"[build] 形态: {mode} / {'windowed' if as_bool(config, 'windowed', True) else 'console'}")
    for item in as_list(config, "include_data_dirs"):
        print(f"[build] 附带资源: {item}")


MENU_BUILD_ARGS = {
    "1": "--config build_config.toml",
    "2": "--config build_config.toml --dry-run",
}


def run_interactive_menu() -> int:
    """显示打包菜单；文案走 stderr，最后只向 stdout 输出构建参数。"""
    while True:
        print("Build target / 构建目标:", file=sys.stderr)
        print(f"  Current version / 当前版本: {load_project_version()}", file=sys.stderr)
        print("  1. Normal build / 普通构建", file=sys.stderr)
        print("  2. Normal build dry-run / 普通构建预演", file=sys.stderr)
        print("  3. Change project version / 修改项目版本号", file=sys.stderr)
        print("  0. Cancel / 取消", file=sys.stderr)
        print(file=sys.stderr)
        print("Enter choice number / 输入选项编号: ", file=sys.stderr, end="", flush=True)
        try:
            raw = input().strip()
        except EOFError:
            return 1
        if raw == "0":
            return 1
        if raw == "3":
            from contextlib import redirect_stdout

            with redirect_stdout(sys.stderr):
                run_version_update("")
            print(file=sys.stderr)
            continue
        build_args = MENU_BUILD_ARGS.get(raw)
        if build_args is None:
            print("Invalid choice / 无效选项.", file=sys.stderr)
            print(file=sys.stderr)
            continue
        print(build_args)
        return 0


def main(argv: list[str] | None = None) -> int:
    configure_stdio_encoding()
    parser = argparse.ArgumentParser(description="Nuitka 打包 SpriteLens")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="配置文件路径")
    parser.add_argument("--dry-run", action="store_true", help="只打印命令，不编译")
    parser.add_argument("--get-version", action="store_true", help="打印当前项目版本号后退出")
    parser.add_argument("--menu", action="store_true", help="显示交互式打包菜单")
    parser.add_argument(
        "--set-version",
        nargs="?",
        const="",
        default=None,
        metavar="VERSION",
        help="修改 spritelens/__init__.py 中的版本号；不带值时进入交互输入",
    )
    args = parser.parse_args(argv)

    if args.get_version:
        print(load_project_version())
        return 0
    if args.menu:
        return run_interactive_menu()
    if args.set_version is not None:
        return run_version_update(args.set_version)

    from tools.frontend import check
    failures = check()
    if failures:
        raise SystemExit("\n".join(failures))

    config = load_config(Path(args.config))
    version = str(config.get("version") or load_project_version())
    check_environment(config)
    print_summary(config, version)

    output_dir = resolve_project_path(str(config.get("output_dir", "build")), "output_dir", must_exist=False)
    suffix = ".exe" if os.name == "nt" else ""
    timestamp = build_timestamp()
    output_name = available_output_name(
        config, version, timestamp=timestamp, output_dir=output_dir, suffix=suffix
    )
    command = build_command(config, version=version, timestamp=timestamp)
    env = build_environment(config)

    printable = " ".join(f'"{part}"' if " " in part else part for part in command)
    print(f"[build] 命令:\n{printable}\n")
    for env_key in BACKEND_FLAG_ENV_KEYS.values():
        original = os.environ.get(env_key, "")
        if env.get(env_key, "") != original:
            print(f"[build] {env_key}={env[env_key]}")

    if args.dry_run:
        print("[build] --dry-run：未执行编译")
        return 0

    print(f"[build] 编译缓存: {env['NUITKA_CACHE_DIR']}")
    print("[build] 开始编译（首次运行需下载 MinGW 编译器，耗时较长）...", flush=True)
    started = time.perf_counter()
    proc = subprocess.run(command, cwd=PROJECT_ROOT, env=env)
    print(f"[build] 编译耗时: {time.perf_counter() - started:.1f} 秒")
    if proc.returncode != 0:
        print(f"[build] 失败，退出码 {proc.returncode}")
        return proc.returncode

    exe = output_dir / f"{output_name}{suffix}"
    if exe.is_file():
        size_mb = exe.stat().st_size / 1024 / 1024
        print(f"[build] 完成: {exe} ({size_mb:.1f} MB)")
    else:
        print(f"[build] 完成，但未在 {output_dir} 找到预期产物（请检查 Nuitka 输出）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
