"""资源路径解析：冻结版（PyInstaller）与开发版共用。

冻结版布局（onedir，Windows）::

    dist/Local Record/
    ├── LocalRecord.exe
    ├── config.yaml
    ├── _internal/          # PyInstaller 6 收集的代码与依赖（等价 macOS 的 Contents/Frameworks）
    └── storage/            # 资源：模型、llama-server、ASR、OCR（打包脚本复制到 exe 同级）

开发版布局：项目根目录下的 ``storage/``。

可用环境变量 ``LOCAL_RECORD_DIR`` 强制指定资源根目录
（例如模型放在 D 盘时，指向包含 storage/ 的目录）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """返回包含 storage/ 的应用根目录。"""
    env = os.environ.get("LOCAL_RECORD_DIR")
    if env:
        return Path(env)
    if is_frozen():
        exe_dir = Path(sys.executable).resolve().parent
        # 优先 exe 同级（打包脚本复制 storage 的位置），其次 _internal（兜底）
        for cand in (exe_dir, exe_dir / "_internal"):
            if (cand / "storage").is_dir():
                return cand
        return exe_dir
    # 开发版：项目根目录（app/ 的父目录）
    return Path(__file__).resolve().parent.parent


def storage_dir() -> Path:
    """资源根目录：storage/"""
    return app_root() / "storage"


def config_path() -> Path:
    """配置文件路径：优先 exe/项目根目录下的 config.yaml。"""
    root = app_root()
    for cand in (root / "config.yaml", root / "storage" / "config.yaml"):
        if cand.is_file():
            return cand
    return root / "config.yaml"


def appdata_dir() -> Path:
    """用户数据目录（日志、录音）。Windows: %APPDATA%/LocalRecord"""
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData/Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "LocalRecord"


def logs_dir() -> Path:
    return appdata_dir() / "logs"


def recordings_dir() -> Path:
    return appdata_dir() / "recordings"
