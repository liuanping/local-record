"""日志：写入 %APPDATA%/LocalRecord/logs/app.log（滚动 5MB x 3）。"""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from .paths import logs_dir

_configured = False
_LOG_FILE: Path | None = None

_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def setup_logging(level: int = logging.INFO) -> Path:
    global _configured, _LOG_FILE
    if _configured:
        return _LOG_FILE  # type: ignore[return-value]
    logs = logs_dir()
    logs.mkdir(parents=True, exist_ok=True)
    _LOG_FILE = logs / "app.log"

    fmt = logging.Formatter(_FORMAT)
    fh = logging.handlers.RotatingFileHandler(
        _LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(fh)
    # 打包版是 --noconsole（sys.stderr 为 None），跳过 StreamHandler
    if sys.stderr is not None:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)
    _configured = True
    return _LOG_FILE


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
