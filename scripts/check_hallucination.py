"""静音/噪声不产生文字，真实语音照常识别的回归检查。

背景：用户实测"没人说话却识别出文字"（模型对底噪硬凑字：
「吃葡萄不吐葡萄皮」「证证证证证证证证证」）。本脚本验证修复：

1. `speech_present()` 判据在真实样本上的表现（语音=有人声，噪声=无人声）；
2. 文本层幻觉过滤：连续重复字（如「证证证证」）被丢弃；
3. **走 app 真实链路**（ASRWorker + 队列）：喂纯噪声 → 不出任何段；
   喂真实语音 → 正常出段。

用法::

    .venv\\Scripts\\python.exe scripts\\check_hallucination.py
"""
from __future__ import annotations

import queue
import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.asr import (  # noqa: E402
    ASREngine, ASRWorker, PUNCT_CHARS, is_meaningless, looks_like_hallucination,
    speech_present,
)

SR = 16000
RECS = Path.home() / "AppData" / "Roaming" / "LocalRecord" / "recordings"
SELFTEST = ROOT / "storage" / "asr" / "selftest.wav"


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        raw = w.readframes(w.getnframes())
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if sr != SR:
        idx = (np.arange(int(len(a) * SR / sr)) * sr / SR).astype(int)
        a = a[np.clip(idx, 0, len(a) - 1)]
    return a


def noise_like_user(seconds: float = 40.0, floor_db: float = -26.0) -> np.ndarray:
    """构造"和用户环境类似"的噪声：宽带 + 低频轰鸣，电平按实测 -26 dBFS。"""
    rng = np.random.default_rng(0)
    n = int(SR * seconds)
    t = np.arange(n) / SR
    broadband = rng.normal(0, 1, n).astype(np.float32)
    rumble = (0.7 * np.sin(2 * np.pi * 120 * t) + 0.3 * np.sin(2 * np.pi * 240 * t)).astype(np.float32)
    x = 0.6 * broadband + 0.4 * rumble
    x *= (10 ** (floor_db / 20.0)) / (np.sqrt((x ** 2).mean()) + 1e-9)
    return x.astype(np.float32)


def run_worker(audio: np.ndarray, chunk_seconds: float = 8.0) -> list[str]:
    """把音频喂进 ASRWorker（与 app 同一条链路），返回识别出的段。"""
    from PySide6.QtCore import QCoreApplication
    from app import config as config_mod

    cfg = config_mod.load_config()
    cfg["asr"]["chunk_seconds"] = chunk_seconds
    app = QCoreApplication.instance() or QCoreApplication([])
    q: "queue.Queue" = queue.Queue()
    worker = ASRWorker(cfg, q)
    segs: list[str] = []
    worker.segment.connect(lambda t, a, b: segs.append(t))
    worker.start()
    t0 = time.monotonic()
    while time.monotonic() - t0 < 8.0:
        app.processEvents()
        time.sleep(0.02)
    step = SR // 10
    for i in range(0, len(audio), step):
        q.put((audio[i:i + step] * 32767).astype(np.int16).reshape(-1, 1))
        app.processEvents()
    time.sleep(0.5)
    worker.shutdown()
    deadline = time.monotonic() + 90
    while worker.isRunning() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.05)
    app.processEvents()
    return segs


def main() -> int:
    results: list[tuple[str, bool, str]] = []

    # 1) 判据：语音 vs 噪声
    if SELFTEST.is_file():
        a = read_wav(SELFTEST)
        has, noise, ratio = speech_present(a, SR)
        results.append(("真实语音判为有人声", has,
                        f"噪声底 {noise:.0f}dB，有声帧 {ratio*100:.1f}%"))
    for name in ("rec-20261002-085801.wav", "rec-20261002-083439.wav"):
        p = RECS / name
        if p.is_file():
            a = read_wav(p)
            has, noise, ratio = speech_present(a, SR)
            results.append((f"真实录音 {name[:20]} 判为有人声", has,
                            f"噪声底 {noise:.0f}dB，有声帧 {ratio*100:.1f}%"))
    for label, audio in (("宽带噪声", noise_like_user(6, -26.0)),
                         ("极低电平噪声", noise_like_user(6, -45.0))):
        has, noise, ratio = speech_present(audio, SR)
        results.append((f"{label} 判为无人声", not has,
                        f"噪声底 {noise:.0f}dB，有声帧 {ratio*100:.1f}%"))

    # 2) 文本层幻觉过滤（阈值 run_len=4：连续 4 个相同字才丢，避免误杀"好好好"这类口语）
    hallu = [
        "好的，我的我的的的证证证证证证证证证证据的证的证见。",
    ]
    for t in hallu:
        results.append((f"幻觉文本被过滤: {t[:12]}…", looks_like_hallucination(t), t[:24]))
    # 这条最长重复只有 3 个（"见见见"），文本过滤**故意**不catch，避免误杀正常口语；
    # 它出现在"没人说话"的场景，由静音判定（speech_present）在识别前拦住 —— 见下面第 3 项。
    borderline = "被被上诉人、被告人诉诉意见护的的议见见见及据证据意见辩见意见。"
    results.append(("3 连重复不误杀（交给静音判定处理）",
                    not looks_like_hallucination(borderline),
                    "文本过滤只认 ≥4 连重复；该句由 speech_present 在识别前丢弃"))
    normal = ["今天的会议改到下午三点，请大家准时参加。",
              "第一个模块已经完成联调，测试用例覆盖了百分之八十五。",
              "大家好好好，我们开始吧。"]      # 3 个重复字不该误杀
    for t in normal:
        results.append((f"正常文本不被误杀: {t[:10]}…",
                        not is_meaningless(t) and not looks_like_hallucination(t), t[:24]))

    # 3) 走 app 真实链路：纯噪声不应出段
    noise = noise_like_user(40.0)
    segs = run_worker(noise)
    results.append(("app 链路：40 秒纯噪声 → 0 段", len(segs) == 0,
                    f"出段 {len(segs)}：" + " | ".join(segs[:3])))

    # 4) 走 app 真实链路：真实语音应正常出段
    if SELFTEST.is_file():
        speech = read_wav(SELFTEST)
        segs2 = run_worker(np.concatenate([np.zeros(SR, np.float32), speech,
                                           np.zeros(SR, np.float32)]))
        joined = "".join(segs2)
        core = "".join(ch for ch in joined if ch not in PUNCT_CHARS)
        hit = sum(1 for ch in "今天的会议改到下午三点" if ch in core)
        results.append(("app 链路：真实语音照常出段", hit >= 8,
                        f"出段 {len(segs2)}，命中 {hit}/12：{joined[:60]}"))

    print()
    for name, ok, detail in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} —— {detail}")
    good = all(r[1] for r in results)
    print("\n[PASS] 静音不产生文字、语音照常识别" if good else "\n[FAIL] 有检查项不通过")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
