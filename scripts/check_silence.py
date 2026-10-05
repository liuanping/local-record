"""静音/噪声判定方案对比：Silero VAD（sherpa-onnx）vs 自适应能量法。

目标：解决"没人说话却识别出文字"（模型对底噪产生幻觉）。
判据必须是**整段有没有人声**，而不是切分语音——切分方案之前实测反而更差。

用法::

    .venv\\Scripts\\python.exe scripts\\check_silence.py            # 用现有样本
    .venv\\Scripts\\python.exe scripts\\check_silence.py --record   # 额外录 6 秒环境噪声一起测
"""
from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

RECS = Path.home() / "AppData" / "Roaming" / "LocalRecord" / "recordings"
VAD_MODEL = ROOT / "storage" / "asr" / "vad" / "silero_vad.onnx"
SR = 16000


def load(p: Path) -> np.ndarray:
    with wave.open(str(p), "rb") as w:
        sr = w.getframerate()
        raw = w.readframes(w.getnframes())
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if sr != SR:
        idx = (np.arange(int(len(a) * SR / sr)) * sr / SR).astype(int)
        a = a[np.clip(idx, 0, len(a) - 1)]
    return a


# ------------------------------------------------------------ 候选判据 ----

def frame_db(a: np.ndarray, frame: int = 320, hop: int = 160) -> np.ndarray:
    """每 10ms 一帧的带内能量（dB），带内 = 300~3400Hz 的近似（用一阶差分 + 平滑）。"""
    if len(a) < frame:
        return np.zeros(0, dtype=np.float32)
    # 一阶差分粗高通，压掉低频轰鸣；再算 RMS
    d = np.diff(a, prepend=a[:1])
    n = 1 + (len(d) - frame) // hop
    idx = np.arange(frame)[None, :] + hop * np.arange(n)[:, None]
    frames = d[idx]
    rms = np.sqrt((frames ** 2).mean(axis=1) + 1e-12)
    return 20 * np.log10(rms + 1e-9)


def energy_has_speech(a: np.ndarray, rel_db: float = 8.0, abs_db: float = -50.0,
                      min_ratio: float = 0.15) -> tuple[bool, float, float]:
    """自适应能量法：噪声底以上的帧占比够高就认为有人声。

    返回 (是否有人声, 噪声底 dB, 超过阈值的帧占比)
    """
    db = frame_db(a)
    if db.size == 0:
        return False, -99.0, 0.0
    noise = float(np.percentile(db, 10))          # 噪声底：最安静的 10%
    thr = max(noise + rel_db, abs_db)
    ratio = float((db > thr).mean())
    return ratio >= min_ratio, noise, ratio


def silero_segments(a: np.ndarray, threshold: float = 0.5) -> list[tuple[float, float]]:
    import sherpa_onnx
    cfg = sherpa_onnx.VadModelConfig(
        silero_vad=sherpa_onnx.SileroVadModelConfig(
            model=str(VAD_MODEL), threshold=threshold,
            min_silence_duration=0.25, min_speech_duration=0.1, window_size=512),
        sample_rate=SR)
    cap = int(SR * (len(a) / SR + 10))
    vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=max(30, int(cap / SR)))
    for i in range(0, len(a), 512):
        vad.accept_waveform(a[i:i + 512])
    vad.flush()
    out = []
    while not vad.empty():
        out.append((vad.front.start / SR, len(vad.front.samples) / SR))
        vad.pop()
    return out


def main() -> int:
    samples: list[tuple[str, np.ndarray, bool]] = []   # (名字, 音频, 期望有人声)
    tts = ROOT / "storage" / "asr" / "selftest.wav"
    if tts.is_file():
        samples.append(("合成语音(自检音频)", load(tts), True))
    for name in ("rec-20261002-085801.wav", "rec-20261002-083439.wav"):
        p = RECS / name
        if p.is_file():
            samples.append((f"真实录音 {name[4:16]}", load(p), True))

    # 纯噪声：用静音段（首尾 0.5s）拼一个"没人说话"的样本 + 现场录制
    rng = np.random.default_rng(0)
    samples.append(("白噪声(低电平)", (rng.normal(0, 0.02, SR * 6)).astype(np.float32), False))
    if "--record" in sys.argv:
        import sounddevice as sd
        rec = sd.rec(SR * 6, samplerate=SR, channels=1, dtype="float32")
        sd.wait()
        samples.append(("现场环境噪声 6s", rec.reshape(-1), False))
    # 真实录音的首尾静音拼起来（他们的噪声底）
    p = RECS / "rec-20261002-083439.wav"
    if p.is_file():
        a = load(p)
        quiet = np.concatenate([a[:SR * 2], a[-SR * 2:]])
        samples.append(("真实录音首尾(应无声)", quiet, False))

    print(f"{'样本':<28}{'期望':<8}{'能量法':<26}{'Silero VAD(0.5)':<18}{'Silero(0.3)'}")
    ok_energy = ok_silero = 0
    for name, audio, expect in samples:
        has, noise, ratio = energy_has_speech(audio)
        segs = silero_segments(audio, 0.5)
        segs3 = silero_segments(audio, 0.3)
        spk = sum(s[1] for s in segs)
        spk3 = sum(s[1] for s in segs3)
        e_ok = has == expect
        s_ok = (spk > 0.3) == expect
        ok_energy += e_ok
        ok_silero += s_ok
        print(f"{name:<28}{'有人声' if expect else '无人声':<8}"
              f"{('有人声' if has else '无人声') + f'(底{noise:.0f}dB,{ratio*100:.0f}%)':<26}"
              f"{('有' if spk > 0.3 else '无') + f'({spk:.1f}s)':<18}"
              f"{('有' if spk3 > 0.3 else '无') + f'({spk3:.1f}s)'}")
    print(f"\n能量法判对 {ok_energy}/{len(samples)}    Silero VAD 判对 {ok_silero}/{len(samples)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
