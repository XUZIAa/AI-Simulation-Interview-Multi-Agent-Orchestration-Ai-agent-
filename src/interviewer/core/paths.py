from __future__ import annotations

import os
import sys
from functools import cache
from pathlib import Path

APP_DIR_NAME = "Interviewer"


@cache
def data_root() -> Path:
    """用户数据根目录，随平台落到标准位置。"""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    root = base / APP_DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def _sub(name: str) -> Path:
    path = data_root() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


@cache
def database_file() -> Path:
    return data_root() / "interviewer.db"


@cache
def log_dir() -> Path:
    return _sub("logs")


@cache
def audio_dir() -> Path:
    return _sub("audio")


@cache
def export_dir() -> Path:
    return _sub("exports")


@cache
def resume_dir() -> Path:
    return _sub("resumes")


@cache
def assets_root() -> Path:
    """打包后资源随 _MEIPASS 走，开发期指向源码目录。"""
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle) / "assets"
    return Path(__file__).resolve().parents[1] / "assets"
