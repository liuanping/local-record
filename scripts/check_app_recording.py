"""跑真实 app（含 GUI）自动录一段，把"转写区内容"打出来 —— 复现"说话但没出字"。

与 scripts/smoke_app.py 的区别：smoke 只验证界面能建起来；本脚本会
**真的点录音、录 N 秒、再停止**，然后打印：

* 转写区最终文本（win.note_view.toPlainText()）
* 段数、ASR 胶囊状态、活动行文字
* 录音是否真的产出了 wav、峰值多少

隔离方式：LOCAL_RECORD_DIR 指向项目根（用真实 storage/asr 模型），
APPDATA 指向临时目录（不污染你的真实录音/日志），并把 LlamaServer 换成
"构造即失败"的桩（避免拉起大模型）。

用法::

    .venv\\Scripts\\python.exe scripts\\check_app_recording.py [秒数]
"""
from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SMOKE = ROOT / "build" / "app-rec"
os.environ["QT_QPA_PLATFORM"] = "offscreen" if "--offscreen" in sys.argv else "windows"
os.environ["LOCAL_RECORD_DIR"] = str(ROOT)          # 用真实 storage（ASR 模型在）
os.environ["APPDATA"] = str(SMOKE / "appdata")      # 隔离日志/录音

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import app.main as app_main  # noqa: E402
from app.llama_server import LlamaServerError  # noqa: E402
from app.main_window import MainWindow  # noqa: E402

RESULT: dict = {}


def prepare() -> None:
    shutil.rmtree(SMOKE, ignore_errors=True)
    (SMOKE / "appdata").mkdir(parents=True, exist_ok=True)


def main() -> int:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].replace(".", "").isdigit() else 20.0
    prepare()

    class NoServer:
        def __init__(self, *_a, **_k):
            raise LlamaServerError("check_app_recording: 跳过真实 llama-server")

    app_main.LlamaServer = NoServer
    QMessageBox.warning = staticmethod(lambda *a, **k: None)      # type: ignore
    QMessageBox.information = staticmethod(lambda *a, **k: None)  # type: ignore

    def find_win():
        for w in QApplication.topLevelWidgets():
            if isinstance(w, MainWindow):
                return w
        return None

    def start():
        win = find_win()
        RESULT["win"] = win
        if win is None:
            print("[FAIL] 找不到主窗口")
            return
        print(f"[{time.strftime('%H:%M:%S')}] 点开始录音…（现在请说话）")
        win.toggle_record_clicked.emit()

    def stop():
        win = RESULT.get("win")
        if win is None:
            return
        print(f"[{time.strftime('%H:%M:%S')}] 点停止录音…")
        win.toggle_record_clicked.emit()

    def dump():
        win = RESULT.get("win")
        app = QApplication.instance()
        if win is not None and app is not None:
            for _ in range(50):          # 给队列/信号一点时间派发
                app.processEvents()
                time.sleep(0.02)
            text = win.note_view.toPlainText().strip()
            RESULT["text"] = text
            RESULT["segs"] = len(win.transcript_items)
            print("\n=== 转写区结果 ===")
            print(f"段数: {len(win.transcript_items)}")
            print(f"ASR 胶囊: {win.asr_pill.state} / {win.asr_pill.label.text()}")
            print(f"活动行: {win.activity_label.text()}")
            print(f"转写文本({len(text)} 字): {text[:200] if text else '(空)'}")
        rec_dir = SMOKE / "appdata" / "LocalRecord" / "recordings"
        wavs = sorted(rec_dir.glob("*.wav")) if rec_dir.is_dir() else []
        print(f"录音文件: {[w.name for w in wavs]}")
        app2 = QApplication.instance()
        if app2 is not None:
            app2.quit()

    original_exec = QApplication.exec

    def fake_exec(self) -> int:
        QTimer.singleShot(800, start)
        QTimer.singleShot(int(800 + seconds * 1000), stop)
        QTimer.singleShot(int(800 + seconds * 1000 + 4000), dump)
        return original_exec()

    QApplication.exec = fake_exec  # type: ignore[assignment]
    try:
        code = app_main.main()
    except Exception:
        import traceback
        traceback.print_exc()
        return 1
    finally:
        QApplication.exec = original_exec  # type: ignore[assignment]

    log = SMOKE / "appdata" / "LocalRecord" / "logs" / "app.log"
    if log.is_file():
        print("\n=== app.log 关键行 ===")
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            if any(k in line for k in ("ASR", "录音", "人声", "识别", "ERROR", "WARNING",
                                       "启动完成")):
                print("  " + line[-160:])

    # 判定：出字了 → PASS；没出字但录音本身没有可用的人声内容 → 也算 PASS。
    # 注意：不能用"高频占比"当判据（实测优质 TTS 语音与纯噪声在该指标上重叠），
    # 所以这里只报数值供参考，真正的判据是有没有识别出文字。
    text = RESULT.get("text") or ""
    ratio = None
    rec_dir = SMOKE / "appdata" / "LocalRecord" / "recordings"
    wavs = sorted(rec_dir.glob("*.wav")) if rec_dir.is_dir() else []
    if wavs:
        import wave
        import numpy as np
        from app.asr import speech_band_ratio
        with wave.open(str(wavs[-1]), "rb") as w:
            sr = w.getframerate()
            raw = w.readframes(w.getnframes())
        a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        ratio = speech_band_ratio(a, sr)
        print(f"\n录音 1.5kHz 以上占比: {ratio*100:.1f}%（仅供参考，不是判据）")
    if text:
        print("\n[PASS] app 转写区出字了")
        return 0
    print("\n[WARN] 转写区为空 —— 若刚才确实有人说话，说明链路有问题；"
          "若房间安静，属正常（无人声可识别）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
