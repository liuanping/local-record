"""逐个测输入设备的底噪/电平，定位"麦克风给的是噪声"这类问题。

用法::

    .venv\\Scripts\\python.exe scripts\\check_mic.py [每个设备测几秒]

对每个可用输入设备各开一小段流，报告 RMS/峰值/dBFS，并标注哪个是系统默认。
判断标准（安静房间对着麦克风不说话时）：
  RMS < 0.005 (-46dBFS)  → 干净
  0.005~0.02             → 一般
  > 0.02 (-34dBFS)       → 很吵：多半选错设备了，或麦克风加强/环境噪声过大
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import sounddevice as sd  # noqa: E402


def measure(device: int, seconds: float = 1.5) -> tuple[float, float, float] | None:
    """返回 (RMS, 峰值, 1.5kHz 以上能量占比)。"""
    sr = 16000
    try:
        rec = sd.rec(int(sr * seconds), samplerate=sr, channels=1,
                     dtype="float32", device=device)
        sd.wait()
    except Exception as e:  # noqa: BLE001
        print(f"    打不开: {type(e).__name__}: {e}")
        return None
    a = rec.reshape(-1)
    rms = float(np.sqrt((a ** 2).mean()))
    peak = float(np.abs(a).max())
    # 高频占比：人声（哪怕只是正常的麦克风本底噪声）会有明显的 1.5kHz 以上能量；
    # 只有低频轰鸣／被降噪削掉的设备，这个比例会低到个位数百分比
    sys.path.insert(0, str(ROOT))
    from app.asr import speech_band_ratio
    return rms, peak, speech_band_ratio(a, sr)


def main() -> int:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 1.5
    try:
        default_in = sd.default.device[0]
    except Exception:
        default_in = -1
    try:
        default_name = sd.query_devices(kind="input")["name"]
    except Exception as e:  # noqa: BLE001
        default_name = f"(查不到: {e})"

    print(f"系统默认输入设备: [{default_in}] {default_name}")
    print(f"每个设备测 {seconds}s —— 对着麦克风说几句话效果最准\n")
    print(f"{'索引':<5}{'设备名':<36}{'RMS':>9}{'峰值':>8}{'dBFS':>8}{'高频占比':>10}  判定")
    devices = sd.query_devices()
    for idx, dev in enumerate(devices):
        if int(dev.get("max_input_channels", 0)) <= 0:
            continue
        name = str(dev.get("name", "?"))[:34]
        mark = "  ← 默认" if idx == default_in else ""
        res = measure(idx, seconds)
        if res is None:
            print(f"{idx:<5}{name:<36}{'-':>9}{'-':>8}{'-':>8}{'-':>10}  打不开{mark}")
            continue
        rms, peak, ratio = res
        dbfs = 20 * np.log10(max(rms, 1e-9))
        # 判定重点看高频占比：没有语音频段 = 这个设备/设置收不到人声
        if ratio >= 0.20:
            verdict = "能收到人声频段（说话时应更高）"
        elif ratio >= 0.08:
            verdict = "偏低，勉强"
        else:
            verdict = "❌ 几乎只有低频轰鸣（收不到人声）"
        print(f"{idx:<5}{name:<36}{rms:>9.4f}{peak:>8.3f}{dbfs:>8.1f}"
              f"{ratio*100:>9.1f}%  {verdict}{mark}")
    print("\n判定说明：高频占比低（<8%）说明这个输入设备在当前设置下**收不到人声频段**。"
          "\n常见原因：麦克风音量被拉到很低而「麦克风加强」很高 / 开了强降噪(APO) / "
          "默认输入切到了没有麦克风的设备（蓝牙耳机、HDMI 显示器、立体声混音）。"
          "\n建议：在「声音设置 → 输入 → 设备属性」里换一个设备，并把音量调到 70~80、"
          "加强调低、关掉音频增强。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
