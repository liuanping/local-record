"""音频链路自检：播放引擎 + 录音电平/落盘（开发辅助，不参与打包）。

运行::

    .venv\\Scripts\\python.exe scripts\\check_audio.py

* 播放：载入录音库里的第一个 wav，播放 1.5 秒，验证位置在走、能暂停/继续/定位；
  没有可用输出设备时会走错误分支（打印提示），不会崩。
* 录音：直接给 Recorder 回调喂合成音频，验证电平计算与 wav 落盘/回读时长。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QCoreApplication  # noqa: E402

from app.paths import recordings_dir  # noqa: E402
from app.player import AudioClip, AudioPlayer  # noqa: E402
from app.recorder import Recorder  # noqa: E402
from app.utils import scan_audio_files, wav_duration  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILED.append(name)


def test_recorder() -> None:
    print("\n== 录音链路（合成音频喂回调）==")
    out_dir = ROOT / "build" / "audio-test"
    out_dir.mkdir(parents=True, exist_ok=True)
    rec = Recorder(sample_rate=16000, channels=1, dtype="int16", save_dir=out_dir)

    sr = 16000
    block = sr // 10                      # 100ms
    silence = np.zeros((block, 1), dtype=np.int16)
    tone = (np.sin(2 * np.pi * 440 * np.arange(block) / sr) * 12000).astype(np.int16)

    # 静音段：电平应接近 0
    for _ in range(3):
        rec._callback(silence.reshape(-1, 1), block, None, None)
    quiet = rec.level
    check("静音时电平接近 0", quiet < 0.2, f"level={quiet:.3f}")

    # 正弦段：电平应明显抬起
    for _ in range(5):
        rec._callback(tone.reshape(-1, 1), block, None, None)
    loud = rec.level
    check("有声时电平明显抬升", loud > quiet + 0.2, f"level={loud:.3f}")
    check("已录时长按帧数计算", abs(rec.elapsed - 0.8) < 0.001, f"elapsed={rec.elapsed:.3f}s")

    path = rec._save_wav()
    check("wav 落盘成功", path.is_file(), str(path))
    dur = wav_duration(path)
    check("wav 时长与采集一致", dur is not None and abs(dur - 0.8) < 0.05,
          f"duration={dur}")

    # 回读：int16 与峰值
    clip = AudioClip.load(path)
    check("播放引擎可回读刚录的 wav", clip.duration > 0.7,
          f"dur={clip.duration:.2f}s ch={clip.channels} sr={clip.samplerate}")
    peaks = clip.peaks(120)
    check("波形包络数量正确", len(peaks) == 120)
    check("包络反映有声内容", max(abs(hi) for _lo, hi in peaks) > 0.1,
          f"peak={max(abs(hi) for _lo, hi in peaks):.3f}")


def test_player() -> None:
    print("\n== 播放链路（sounddevice 输出）==")
    import sounddevice as sd
    try:
        outs = [d for d in sd.query_devices() if d["max_output_channels"] > 0]
    except Exception as e:
        print(f"  查询音频设备失败：{e}")
        outs = []
    print(f"  输出设备数量：{len(outs)}")
    try:
        print(f"  默认输出：{sd.query_devices(kind='output')['name']}")
    except Exception as e:
        print(f"  无默认输出设备：{e}")

    files = scan_audio_files(recordings_dir())
    if not files:
        print("  录音库里没有 wav，跳过播放测试（先录一段）")
        return
    target = files[0]
    print(f"  测试文件：{target.name}")

    player = AudioPlayer(volume=0.5)
    states: list[str] = []
    errors: list[str] = []
    finished: list[bool] = []
    player.stateChanged.connect(states.append)
    player.errorOccurred.connect(errors.append)
    player.finished.connect(lambda: finished.append(True))

    ok = player.load(target)
    check("载入 wav 成功", ok and player.duration > 0,
          f"duration={player.duration:.2f}s")

    player.play()
    app = QCoreApplication.instance()
    deadline = time.time() + 1.5
    positions = []
    while time.time() < deadline:
        app.processEvents()
        positions.append(player.position)
        time.sleep(0.02)

    if errors:
        print(f"  播放报错（可能是无声卡环境）：{errors[0].splitlines()[0]}")
        check("播放失败时给出明确错误而非崩溃", True)
    else:
        check("播放位置在推进", positions[-1] > positions[0],
              f"{positions[0]:.2f}s → {positions[-1]:.2f}s")
        player.pause()
        app.processEvents()
        check("暂停后状态为 paused", player.is_paused, player.state)
        p_before = player.position
        for _ in range(10):
            app.processEvents()
            time.sleep(0.02)
        check("暂停后位置不再变化", abs(player.position - p_before) < 0.05,
              f"{p_before:.2f}s → {player.position:.2f}s")
        player.play()
        app.processEvents()
        check("继续播放恢复 playing", player.is_playing, player.state)
        player.seek(0.5)
        check("拖动定位生效", abs(player.position - 0.5) < 0.02,
              f"pos={player.position:.2f}s")
        player.stop()
        app.processEvents()
        check("停止后回到 idle 且位置归零",
              player.state == "idle" and player.position == 0.0)

    # 播放到结尾应发 finished
    player.load(target)
    player.seek(max(0.0, player.duration - 0.4))
    player.play()
    deadline = time.time() + 3.0
    while time.time() < deadline and not finished:
        app.processEvents()
        time.sleep(0.02)
    if errors:
        print("  无输出设备，跳过 finished 校验")
    else:
        check("播放结束发出 finished 信号", bool(finished))


def main() -> int:
    app = QCoreApplication(sys.argv)
    test_recorder()
    test_player()
    print("\n================ 结果 ================")
    if FAILED:
        print(f"失败 {len(FAILED)} 项：{', '.join(FAILED)}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
