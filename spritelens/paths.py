"""数据目录解析：配置、日志、录制帧、密钥的落盘位置。

测试与便携场景用环境变量 SPRITELENS_DATA_ROOT 覆盖，默认写用户目录
（%LOCALAPPDATA%\\SpriteLens），与 meow toolkit 的存储策略保持一致。

同时提供打包后的只读资源定位（frozen/_MEIPASS 分支），见 `project_root()`。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import spritelens

_DATA_ROOT_ENV = "SPRITELENS_DATA_ROOT"


def data_root() -> Path:
    """返回指定用户数据目录；不可用时明确失败，不切换存储位置。"""
    raw = os.environ.get(_DATA_ROOT_ENV)
    if raw:
        root = Path(raw)
    elif os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        root = Path(base) / spritelens.APP_NAME if base else Path.home() / f".{spritelens.APP_NAME.lower()}"
    else:
        root = Path.home() / f".{spritelens.APP_NAME.lower()}"
    try:
        root.mkdir(parents=True, exist_ok=True)
        return root
    except OSError as exc:
        raise OSError(f"用户数据目录不可用：{root}；请检查路径和权限") from exc


def config_path() -> Path:
    return data_root() / "config.json"


def database_path() -> Path:
    """SQLite 持久化库（宠物/账号等业务数据）；跨会话累积，与日志分开存放。"""
    return data_root() / "spritelens.sqlite"


def keys_dir() -> Path:
    path = data_root() / "keys"
    path.mkdir(parents=True, exist_ok=True)
    return path


def recordings_dir() -> Path:
    path = data_root() / "recordings"
    path.mkdir(parents=True, exist_ok=True)
    return path


def scene_checkpoint_path() -> Path:
    """附近精灵可丢弃场景基线；与业务 SQLite 分开保存。"""
    return data_root() / "scene_checkpoints.json"


def logs_dir() -> Path:
    path = data_root() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _bundle_root() -> Path:
    """随程序分发的只读资源（data/）所在根目录。

    源码态是仓库根；打包后（PyInstaller 的 `sys._MEIPASS`、Nuitka 的
    `__compiled__`）资源被释放到临时目录，必须走这个分支，否则
    `project_root()` 指到 exe 所在位置，静态数据全部找不到。
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    if "__compiled__" in globals() or getattr(sys, "frozen", False):
        # Nuitka standalone：资源随 exe 同目录；onefile 亦解包到 exe 旁
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def project_root() -> Path:
    """资源根目录：源码态为仓库根，打包态为资源释放目录。"""
    return _bundle_root()


def schema_dir() -> Path:
    return project_root() / "data" / "schemas"


def static_dir() -> Path:
    """静态映射数据（物种/性格/技能/系别），随仓库分发。"""
    return project_root() / "data" / "static"
