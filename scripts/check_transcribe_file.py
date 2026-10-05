"""验证「转写已有音频文件」这条链路（给 FileTranscribeWorker 用）。

场景：内置麦克风信噪比差 → 用手机等更好的设备录音，传到电脑导入录音库，
点「转写」把音频变成文字。本脚本直接跑 worker，检查：

* 有语音的文件 → 能出字，且内容与参考一致（命中率 ≥60%）；
* 纯噪声文件 → 一段都不出（复用静音判定 + 幻觉过滤）。

用法::

    .venv\\Scripts\\python.exe scripts\\check_transcribe_file.py
"""
from __future__ import annotations

import shutil
import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.asr import PUNCT_CHARS, FileTranscribeWorker  # noqa: E402

TMP = ROOT / "build" / "transcribe-check"
SELFTEST = ROOT / "storage" / "asr" / "selftest.wav"


def write_wav(path: Path, audio: np.ndarray, sr: int = 16000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
    return path


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        raw = w.readframes(w.getnframes())
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if sr != 16000:
        idx = (np.arange(int(len(a) * 16000 / sr)) * sr / 16000).astype(int)
        a = a[np.clip(idx, 0, len(a) - 1)]
    return a


def run(path: Path) -> tuple[list[str], str]:
    from PySide6.QtCore import QCoreApplication
    from app import config as config_mod
    cfg = config_mod.load_config()
    app = QCoreApplication.instance() or QCoreApplication([])
    segs: list[str] = []
    result: list[tuple[bool, str]] = []
    w = FileTranscribeWorker(cfg, path)
    w.segment.connect(lambda t, a, b: segs.append(t))
    w.done.connect(lambda ok, msg: result.append((ok, msg)))
    w.start()
    deadline = time.monotonic() + 120
    while w.isRunning() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.05)
    app.processEvents()
    return segs, (result[0][1] if result else "（无结果）")


def main() -> int:
    shutil.rmtree(TMP, ignore_errors=True)
    TMP.mkdir(parents=True, exist_ok=True)
    results: list[tuple[str, bool, str]] = []

    # 1) 真实语音文件（模拟"手机录好导入"）
    if SELFTEST.is_file():
        speech = np.concatenate([np.zeros(16000, np.float32), read_wav(SELFTEST),
                                 np.zeros(16000, np.float32)])
        p = write_wav(TMP / "speech.wav", speech)
        segs, msg = run(p)
        joined = "".join(segs)
        core = "".join(ch for ch in joined if ch not in PUNCT_CHARS)
        hit = sum(1 for ch in "今天的会议改到下午三点" if ch in core)
        results.append(("语音文件能转出文字", hit >= 8,
                        f"{len(segs)} 段，命中 {hit}/12：{joined[:50]}｜{msg}"))
    else:
        results.append(("语音文件能转出文字", False, "缺少 storage/asr/selftest.wav"))

    # 2) 纯噪声文件 → 不该出字
    rng = np.random.default_rng(0)
    n = 16000 * 20
    t = np.arange(n) / 16000.0
    noise = (0.6 * rng.normal(0, 1, n) + 0.4 * np.sin(2 * np.pi * 120 * t)).astype(np.float32)
    noise *= 10 ** (-26 / 20) / (float(np.sqrt((noise ** 2).mean())) + 1e-9)
    p2 = write_wav(TMP / "noise.wav", noise)
    segs2, msg2 = run(p2)
    results.append(("纯噪声文件不出字", len(segs2) == 0,
                    f"{len(segs2)} 段：{' | '.join(segs2[:3])}｜{msg2}"))

    # 3) 44.1kHz 立体声文件（模拟手机导入的格式）
    if SELFTEST.is_file():
        a = read_wav(SELFTEST)
        up = np.repeat(a, 3)               # 粗略当 48k 用
        stereo = np.stack([up, up], axis=1).reshape(-1)
        p3 = TMP / "stereo48k.wav"
        with wave.open(str(p3), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(48000)
            w.writeframes((np.clip(stereo, -1, 1) * 32767).astype(np.int16).tobytes())
        segs3, msg3 = run(p3)
        core3 = "".join(ch for ch in "".join(segs3) if ch not in PUNCT_CHARS)
        hit3 = sum(1 for ch in "今天的会议改到下午三点" if ch in core3)
        results.append(("立体声/非16k文件也能转写", hit3 >= 6,
                        f"{len(segs3)} 段，命中 {hit3}/12｜{msg3}"))

    print()
    for name, ok, detail in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} —— {detail}")
    good = all(r[1] for r in results)
    print("\n[PASS] 文件转写链路可用" if good else "\n[FAIL] 有检查项不通过")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
