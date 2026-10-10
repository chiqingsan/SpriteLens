"""数据目录解析：配置、日志、录制帧、密钥的落盘位置。

测试与便携场景用环境变量 SPRITELENS_DATA_ROOT 覆盖，默认写用户目录
（%LOCALAPPDATA%\\SpriteLens），与 meow toolkit 的存储策略保持一致。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import spritelens

_DATA_ROOT_ENV = "SPRITELENS_DATA_ROOT"


def data_root() -> Path:
    """返回数据根目录，保证存在；创建失败时降级到系统临时目录。"""
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
    except OSError:
        # 只读环境（如部分企业策略）下退到临时目录，保证工具仍可运行
        fallback = Path(tempfile.gettempdir()) / spritelens.APP_NAME.lower()
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


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


def logs_dir() -> Path:
    path = data_root() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def project_root() -> Path:
    """仓库根目录（源码态），用于定位 docs / data 等随仓库分发的资源。"""
    return Path(__file__).resolve().parent.parent


def schema_dir() -> Path:
    return project_root() / "data" / "schemas"


def static_dir() -> Path:
    """静态映射数据（物种/性格/技能/系别），随仓库分发。"""
    return project_root() / "data" / "static"
