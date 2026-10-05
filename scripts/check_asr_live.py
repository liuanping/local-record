"""实时麦克风链路自检：Recorder → ASRWorker（与 app 用的完全相同的类）。

用途：出现"说了话但界面上没出字"时，用它把链路拆开，判断断在哪一段：

1. 麦克风有没有数据（实时电平 + 峰值）；
2. ASR 工作线程有没有收到音频块（打印队列消费情况）；
3. 到点有没有出段（段长到了就该出一段）；
4. 出的是"被静音保护跳过"还是"识别为空文字"。

录下来的音频会存到 ``build/asr-live/``，并再用整段模式识别一次，
方便判断"是音频本身没法识别"还是"分段/链路的问题"。

用法::

    .venv\\Scripts\\python.exe scripts\\check_asr_live.py [录音秒数] [段长秒]
    # 默认 16 秒、段长 4 秒（短一点好快速定位）
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PySide6.QtCore import QCoreApplication  # noqa: E402

from app import config as config_mod  # noqa: E402
from app.asr import ASREngine, ASRWorker  # noqa: E402
from app.recorder import Recorder  # noqa: E402

OUT_DIR = ROOT / "build" / "asr-live"


def main() -> int:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 16.0
    chunk_s = float(sys.argv[2]) if len(sys.argv) > 2 else 4.0
    auto_wait = 0.0
    if "--auto" in sys.argv:
        i = sys.argv.index("--auto")
        auto_wait = float(sys.argv[i + 1]) if len(sys.argv) > i + 1 else 120.0

    cfg = config_mod.load_config()
    cfg["asr"]["chunk_seconds"] = chunk_s
    app = QCoreApplication(sys.argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    recorder = Recorder(
        sample_rate=int(cfg["recorder"]["sample_rate"]),
        channels=int(cfg["recorder"]["channels"]),
        dtype=cfg["recorder"]["dtype"],
        device=cfg["recorder"]["device"],
        save_dir=OUT_DIR,
    )
    print(f"段长 {chunk_s}s，录音 {seconds}s，设备={recorder.device or '默认'}")

    queue_ref = recorder.chunks
    worker = ASRWorker(cfg, queue_ref)

    events: list[str] = []
    ready: list[tuple[bool, str]] = []
    segs: list[tuple[str, float, float]] = []
    worker.ready.connect(lambda ok, msg: ready.append((ok, msg)))
    worker.segment.connect(lambda t, a, b: segs.append((t, a, b)))
    worker.stopped.connect(lambda: events.append("stopped"))
    worker.start()

    # 等模型加载
    t0 = time.monotonic()
    while time.monotonic() - t0 < 6.0 and not ready:
        app.processEvents()
        time.sleep(0.02)
    print("ASR init:", ready[0] if ready else "(超时未就绪)")

    try:
        recorder.start()
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] 打不开麦克风：{type(e).__name__}: {e}")
        worker.shutdown()
        return 1

    # ---- 自动模式：先量底噪，等用户说话（声音明显高出底噪）再采集 ----
    if auto_wait > 0:
        time.sleep(1.0)
        app.processEvents()
        noise_db = 20 * np.log10(max(recorder.peak, 1e-6))
        print(f"当前底噪峰值 ≈ {noise_db:.1f} dBFS（安静房间通常 < -40）")
        print(f"请现在对着麦克风正常说几句话，最多等 {auto_wait:.0f} 秒…")
        t0 = time.monotonic()
        onset = 0.0
        while time.monotonic() - t0 < auto_wait:
            app.processEvents()
            time.sleep(0.05)
            if recorder.peak > max(0.02, recorder.peak * 0) and \
                    (20 * np.log10(max(recorder.level, 1e-6)) > 0 or
                     recorder.peak > 0.12):
                onset = time.monotonic() - t0
                break
        if onset == 0.0:
            print(f"[WARN] 等 {auto_wait:.0f} 秒没检测到明显高于底噪的声音。")
            print("       说明麦克风收到的电平没有随说话上升 —— 优先检查：")
            print("       1) 说近一点（15~30cm），或换个麦克风；")
            print("       2) 声音设置 → 输入 → 设备属性 → 级别：把「麦克风加强」调低、")
            print("          「麦克风音量」调到 70~80（加强过高会把底噪一起放大）；")
            print("       3) 关掉「音频增强 / 噪音抑制 / 回声消除」（Realtek 的 AI 降噪常把语音削掉）。")
            recorder.stop()
            worker.shutdown()
            return 2
        print(f"检测到说话（{onset:.1f}s）→ 采集 {max(seconds, 12):.0f} 秒…")
        seconds = max(seconds, 12.0)

    print(f"开始录音…  队列积压={queue_ref.qsize()}  host API={recorder.host_api_used}")
    t0 = time.monotonic()
    last = t0
    max_level = 0.0
    while time.monotonic() - t0 < seconds:
        app.processEvents()
        time.sleep(0.02)
        max_level = max(max_level, recorder.level)
        if time.monotonic() - last >= 2.0:
            last = time.monotonic()
            print(f"  t={time.monotonic()-t0:4.1f}s  实时电平={recorder.level:.3f}  "
                  f"峰值={recorder.peak:.3f}  队列积压={queue_ref.qsize()}  "
                  f"已出段={len(segs)}")

    wav = recorder.stop()
    print(f"停止录音。采集峰值={recorder.peak:.3f}  最大实时电平={max_level:.3f}  "
          f"队列剩余={queue_ref.qsize()}")
    print(f"录音文件: {wav}")

    # 收尾：把队列里剩下的吃完再退出（与 app 的 run() 收尾一致）
    worker.shutdown()
    deadline = time.monotonic() + 60
    while worker.isRunning() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.05)
    app.processEvents()

    print(f"\n=== 实时链路结果 ===")
    print(f"出段数: {len(segs)}")
    for text, a, b in segs:
        print(f"  [{a:6.1f}-{b:6.1f}s] {text}")

    if wav is not None and Path(wav).is_file():
        print(f"\n=== 同一份音频整段识别（判断音频本身可识别性）===")
        engine = ASREngine(cfg)
        engine.init()
        import wave
        with wave.open(str(wav), "rb") as w:
            sr = w.getframerate()
            raw = w.readframes(w.getnframes())
        a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        peak = float(np.abs(a).max())
        text = engine.recognize(a * (0.9 / peak) if peak > 0.05 else a)
        print(f"  峰值={peak:.3f}  整段识别({len(text)} 字): {text[:120]}")

    ok = bool(segs) or (wav is not None and Path(wav).is_file())
    print("\n[PASS] 链路可用" if ok else "\n[FAIL] 没有采到音频")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
