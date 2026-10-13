"""Nuitka 打包脚本（SpriteLens）。

配置驱动：常用选项改 build_config.toml，不在这里写死。
用法：
    .venv\\Scripts\\python.exe build.py             # 正式打包
    .venv\\Scripts\\python.exe build.py --dry-run   # 只打印命令，不编译
    build.bat                                        # 同上（自动找 venv）
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = PROJECT_ROOT / "build_config.toml"
VERSION_INIT_FILE = PROJECT_ROOT / "spritelens" / "__init__.py"


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
    """从 spritelens/__init__.py 读 __version__（不 import，避免副作用）。"""
    text = init_file.read_text(encoding="utf-8")
    matched = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.M)
    if not matched:
        raise SystemExit(f"未在 {init_file} 找到 __version__")
    return matched.group(1)


def windows_version_string(version: str) -> str:
    """Windows 资源版本要求 a.b.c.d；不足位补零。"""
    parts = re.findall(r"\d+", version)[:4]
    while len(parts) < 4:
        parts.append("0")
    return ".".join(parts)


def build_output_name(config: dict[str, Any], version: str) -> str:
    template = str(config.get("output_name_template") or "{app_name}_{version}")
    return template.format(
        app_name=config.get("app_name", "app"),
        version=version,
        timestamp="0",
    )


def build_command(config: dict[str, Any], *, version: str) -> list[str]:
    app_name = str(config.get("app_name") or "app")
    output_name = build_output_name(config, version)
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


def main(argv: list[str] | None = None) -> int:
    configure_stdio_encoding()
    parser = argparse.ArgumentParser(description="Nuitka 打包 SpriteLens")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="配置文件路径")
    parser.add_argument("--dry-run", action="store_true", help="只打印命令，不编译")
    args = parser.parse_args(argv)

    from tools.frontend import check
    failures = check()
    if failures:
        raise SystemExit("\n".join(failures))

    config = load_config(Path(args.config))
    version = str(config.get("version") or load_project_version())
    check_environment(config)
    print_summary(config, version)

    command = build_command(config, version=version)
    env = build_environment(config)

    printable = " ".join(f'"{part}"' if " " in part else part for part in command)
    print(f"[build] 命令:\n{printable}\n")

    if args.dry_run:
        print("[build] --dry-run：未执行编译")
        return 0

    print("[build] 开始编译（首次运行需下载 MinGW 编译器，耗时较长）...")
    proc = subprocess.run(command, cwd=PROJECT_ROOT, env=env)
    if proc.returncode != 0:
        print(f"[build] 失败，退出码 {proc.returncode}")
        return proc.returncode

    output_dir = resolve_project_path(str(config.get("output_dir", "build")), "output_dir", must_exist=False)
    suffix = ".exe" if os.name == "nt" else ""
    exe = output_dir / f"{build_output_name(config, version)}{suffix}"
    if exe.is_file():
        size_mb = exe.stat().st_size / 1024 / 1024
        print(f"[build] 完成: {exe} ({size_mb:.1f} MB)")
    else:
        print(f"[build] 完成，但未在 {output_dir} 找到预期产物（请检查 Nuitka 输出）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
