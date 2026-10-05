"""对照实验：喇叭静音前后，麦克风底噪有没有变化。

背景：用户怀疑笔记本喇叭会辐射低频噪声被麦克风收进去（其录音里有一串
110~160Hz 离散峰）。本脚本对比"输出未静音 / 已静音"两种状态下麦克风的底噪。

用法::

    .venv\\Scripts\\python.exe scripts/check_speaker_noise.py
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd

ROOT = Path(__file__).resolve().parent.parent
SR = 16000


def measure(seconds: float = 5.0) -> np.ndarray:
    rec = sd.rec(int(SR * seconds), samplerate=SR, channels=1, dtype="float32")
    sd.wait()
    return rec.reshape(-1)


def toggle_mute() -> None:
    """发送系统静音键（VK_VOLUME_MUTE=173）。"""
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(New-Object -ComObject WScript.Shell).SendKeys([char]173)"],
        capture_output=True, timeout=20)


def stats(a: np.ndarray, label: str) -> dict:
    rms = float(np.sqrt((a ** 2).mean()))
    peak = float(np.abs(a).max())
    S = np.abs(np.fft.rfft(a * np.hanning(len(a)))) ** 2
    f = np.fft.rfftfreq(len(a), 1.0 / SR)
    tot = float(S.sum()) + 1e-12
    lf = float(S[(f >= 50) & (f < 300)].sum()) / tot
    hf = float(S[f >= 1000].sum()) / tot
    # 找 50~400Hz 内最强的窄带峰
    band = (f >= 50) & (f <= 400)
    fb, Sb = f[band], S[band]
    top = int(fb[np.argmax(Sb)])
    print(f"  {label:16} RMS={rms:.4f} ({20*np.log10(max(rms,1e-9)):6.1f} dBFS)  "
          f"峰值={peak:.3f}  50-300Hz占比={lf*100:4.1f}%  1kHz以上={hf*100:4.1f}%  "
          f"最强低频峰≈{top}Hz")
    return {"rms": rms, "lf": lf, "peak": peak, "top": top}


def main() -> int:
    print("测 2 轮：喇叭开 / 喇叭静音（每轮 5 秒，请保持安静）\n")
    a1 = measure()
    s1 = stats(a1, "喇叭未静音")
    toggle_mute()
    time.sleep(1.5)
    a2 = measure()
    s2 = stats(a2, "喇叭已静音")
    toggle_mute()          # 恢复
    time.sleep(1.0)

    d_rms = 20 * np.log10(max(s2["rms"], 1e-9)) - 20 * np.log10(max(s1["rms"], 1e-9))
    print(f"\n  底噪变化: {d_rms:+.1f} dB（负值=静音后更安静）")
    if d_rms <= -6:
        print("  → 结论：**喇叭确实在往麦克风里灌噪声**，录音时静音输出能明显改善")
    elif d_rms <= -2:
        print("  → 结论：静音后有轻微改善（2~6dB），可以顺手做")
    else:
        print("  → 结论：静音几乎没影响 → 噪声不是喇叭，多半是风扇/机箱振动或麦克风自噪")
    print("  （已把系统静音状态恢复原样）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
