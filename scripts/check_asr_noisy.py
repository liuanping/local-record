"""低信噪比场景下的识别对比：原始 / 高通 / 谱减降噪。

用法::

    .venv\\Scripts\\python.exe scripts\\check_asr_noisy.py [信噪比dB] [噪声wav]

默认：把"已知文本的中文 TTS 语音"（build/asr-test/tts-meeting.wav）与一段**真实房间噪声**
按给定信噪比混合，然后比较三种前处理的字错率（CER）：

    raw     —— 直接送（当前实现的做法）
    hp      —— 先高通 120Hz（去掉风扇/空调的低频轰鸣）
    hp+gate —— 高通后再做谱减降噪（估计噪声谱，逐帧抑制）

噪声文件默认取 build/asr-live/ 下最近一条录音（用 check_asr_live.py 录到的真实环境噪声）；
没有的话用白噪声兜底。
"""
from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(Path(__file__).parent))
from check_asr import SCRIPT, cer, decode, make_recognizer, normalize, read_wav  # noqa: E402

SPEECH = ROOT / "build" / "asr-test" / "tts-meeting.wav"
LIVE_DIR = ROOT / "build" / "asr-live"


# ------------------------------------------------------------ 前处理 ----

def highpass(x: np.ndarray, sr: int, fc: float = 120.0, taps: int = 257) -> np.ndarray:
    """高通 = 原信号 − 低通（窗函数法 FIR，够用且无需 scipy）。"""
    n = np.arange(taps) - (taps - 1) / 2.0
    h = np.sinc(2 * fc / sr * n) * np.hamming(taps)
    h /= h.sum()
    return x - np.convolve(x, h, mode="same")


def spectral_gate(x: np.ndarray, sr: int, n_fft: int = 512, hop: int = 128,
                  over: float = 2.0, floor: float = 0.08,
                  noise_frames: float = 0.6) -> np.ndarray:
    """谱减降噪：用开头噪声段估噪声谱，逐帧按信噪比抑制。"""
    win = np.hanning(n_fft).astype(np.float32)
    pad = n_fft
    xp = np.concatenate([np.zeros(pad, np.float32), x.astype(np.float32),
                         np.zeros(pad, np.float32)])
    frames = 1 + (len(xp) - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(frames)[:, None]
    spec = np.fft.rfft(xp[idx] * win, axis=1)
    mag, phase = np.abs(spec), np.angle(spec)

    k = max(1, int(noise_frames * sr / hop))
    noise = np.median(mag[:k], axis=0, keepdims=True)
    gain = np.maximum(floor, 1.0 - over * noise / np.maximum(mag, 1e-8))
    clean = np.fft.irfft(mag * gain * np.exp(1j * phase), axis=1).astype(np.float32)

    out = np.zeros(len(xp), np.float32)
    wsum = np.zeros(len(xp), np.float32)
    for i in range(frames):
        s = i * hop
        out[s:s + n_fft] += clean[i] * win
        wsum[s:s + n_fft] += win ** 2
    out /= np.maximum(wsum, 1e-8)
    return out[pad:pad + len(x)]


def mix_at_snr(speech: np.ndarray, noise: np.ndarray, snr_db: float) -> np.ndarray:
    """按目标信噪比把噪声加到语音上（噪声循环平铺）。"""
    if len(noise) < len(speech):
        noise = np.tile(noise, int(np.ceil(len(speech) / max(1, len(noise)))))
    noise = noise[:len(speech)]
    sp = np.sqrt((speech ** 2).mean()) + 1e-9
    npw = np.sqrt((noise ** 2).mean()) + 1e-9
    target_noise = sp / (10 ** (snr_db / 20.0))
    return speech + noise * (target_noise / npw)


def peak_norm(x: np.ndarray) -> np.ndarray:
    p = float(np.abs(x).max())
    return x * (0.9 / p) if p > 0.05 else x


def main() -> int:
    snr_db = float(sys.argv[1]) if len(sys.argv) > 1 else 3.0
    noise_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None

    if not SPEECH.is_file():
        print(f"缺少测试语音 {SPEECH}（先跑 scripts/check_asr.py 生成）")
        return 1
    speech, sr = read_wav(SPEECH)

    if noise_path is None:
        cands = sorted(LIVE_DIR.glob("*.wav"), key=lambda p: p.stat().st_mtime,
                       reverse=True) if LIVE_DIR.is_dir() else []
        noise_path = cands[0] if cands else None
    if noise_path is not None and noise_path.is_file():
        noise, _ = read_wav(noise_path)
        print(f"噪声来源（真实房间噪声）: {noise_path.name}  {len(noise)/sr:.1f}s")
    else:
        rng = np.random.default_rng(0)
        noise = rng.normal(0, 1, len(speech)).astype(np.float32)
        print("噪声来源: 白噪声（没找到真实噪声录音）")

    noisy = mix_at_snr(speech, noise, snr_db)
    n_rms = np.sqrt((noise[:len(speech)] ** 2).mean())
    print(f"目标信噪比 {snr_db:+.1f} dB ｜ 语音 RMS {np.sqrt((speech**2).mean()):.4f} "
          f"噪声 RMS {n_rms:.4f}（{20*np.log10(n_rms+1e-9):.1f} dBFS）")
    print(f"标准答案 {len(normalize(SCRIPT))} 字\n")

    variants = [
        ("raw（现状）", lambda a: a),
        ("hp 120Hz", lambda a: highpass(a, sr)),
        ("hp+gate", lambda a: spectral_gate(highpass(a, sr), sr)),
    ]
    rec = make_recognizer()
    rows = []
    for name, fn in variants:
        processed = peak_norm(fn(noisy).astype(np.float32))
        text = decode(rec, processed, sr)
        rate, dist, total = cer(SCRIPT, text)
        rows.append((name, rate, dist, total, text))
        print(f"  {name:12} CER {rate*100:5.1f}%  错 {dist:3}/{total}")
        print(f"      {text[:100]}")

    print("\n=== 汇总（CER 越低越好）===")
    for name, rate, dist, total, _ in sorted(rows, key=lambda r: r[1]):
        print(f"  {name:12} CER {rate*100:5.1f}%  错 {dist:3}/{total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
