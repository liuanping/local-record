"""通用小工具：时间/体积/文件名格式化与文件扫描。"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

AUDIO_SUFFIXES = (".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac", ".wma")


def fmt_time(seconds: float) -> str:
    """秒 → HH:MM:SS（转写时间戳用）。"""
    s = int(max(0, seconds))
    return f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}"


def fmt_mmss(seconds: float) -> str:
    """秒 → MM:SS（超过 1 小时自动变 H:MM:SS）。"""
    s = int(max(0, seconds))
    if s >= 3600:
        return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}"
    return f"{s // 60:02d}:{s % 60:02d}"


def fmt_timer(seconds: float) -> str:
    """秒 → MM:SS.d（录音中的大计时器，带 0.1 秒）。"""
    seconds = max(0.0, seconds)
    m = int(seconds) // 60
    s = seconds - m * 60
    return f"{m:02d}:{s:04.1f}"


def fmt_size(num_bytes: float) -> str:
    """字节 → 人类可读体积。"""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def fmt_datetime(ts: float) -> str:
    """时间戳 → 本地时间描述（今天 / 昨天 / 日期）。"""
    dt = datetime.fromtimestamp(ts)
    now = datetime.now()
    if dt.date() == now.date():
        return f"今天 {dt:%H:%M}"
    if (now.date() - dt.date()).days == 1:
        return f"昨天 {dt:%H:%M}"
    if dt.year == now.year:
        return f"{dt:%m-%d %H:%M}"
    return f"{dt:%Y-%m-%d %H:%M}"


def wav_duration(path: Path) -> Optional[float]:
    """只读 wav 头估算时长（避免把整个文件读进内存）。"""
    try:
        import wave
        with wave.open(str(path), "rb") as w:
            rate = w.getframerate() or 1
            return w.getnframes() / float(rate)
    except Exception:
        return None


def scan_audio_files(directory: Path) -> List[Path]:
    """扫描目录下的音频文件，按修改时间倒序（最新在前）。"""
    if not directory.is_dir():
        return []
    files = [p for p in directory.iterdir()
             if p.is_file() and p.suffix.lower() in AUDIO_SUFFIXES]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def human_file_name(path: Path) -> str:
    """``rec-20260920-000039.wav`` → ``09-20 00:00:39`` 之类的好读名字。"""
    stem = path.stem
    if stem.startswith("rec-") and len(stem) >= 18:
        body = stem[4:]
        try:
            dt = datetime.strptime(body, "%Y%m%d-%H%M%S")
            return dt.strftime("%m-%d %H:%M:%S")
        except ValueError:
            return stem
    return stem


def reveal_in_explorer(path: Path) -> None:
    """在文件资源管理器中定位文件（Windows）。"""
    p = Path(path)
    if not p.exists():
        return
    try:
        if os.name == "nt":
            os.system(f'explorer /select,"{p}"')
        else:
            os.startfile(str(p.parent))  # type: ignore[attr-defined]
    except Exception:
        pass
