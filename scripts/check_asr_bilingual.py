"""中英混说识别对比（CER），并测试降噪对识别的影响。

背景：Paraformer zh 只支持中文；用户要求**中英文都能识别**。
候选：SenseVoice（多语种，language=zh / auto）、Whisper（base/small，int8）。

测试音频：用 Windows 自带中英文语音合成一段**中英混说**内容（标准答案已知）：
  中文用 Microsoft Huihui Desktop，英文用 Microsoft Zira Desktop，逐段合成再拼接。

用法::

    .venv\\Scripts\\python.exe scripts\\check_asr_bilingual.py            # 干净音频
    .venv\\Scripts\\python.exe scripts\\check_asr_bilingual.py --noise    # 叠加真实房间噪声（低信噪比）
    .venv\\Scripts\\python.exe scripts\\check_asr_bilingual.py --denoise  # 额外测 GTCRN 降噪前后
"""
from __future__ import annotations

import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from check_asr import cer, clean, normalize, read_wav  # noqa: E402

CMP = ROOT / "build" / "models-cmp"
OUT = ROOT / "build" / "asr-bilingual"
CUR_SV = ROOT / "storage" / "asr" / "sense-voice"

#: 中英混说内容：(语言, 文本)
SEGMENTS: list[tuple[str, str]] = [
    ("zh", "今天的会议我们讨论三个重点。"),
    ("en", "First, the API response time must be under two hundred milliseconds."),
    ("zh", "第二，下周发布之前必须完成回归测试。"),
    ("en", "Second, we need a regression test before the release next week."),
    ("zh", "第三，如果预算不够，就先做最小可用版本。"),
    ("en", "Third, if the budget is not enough, we ship an M V P first."),
    ("zh", "另外小王负责跟第三方对接接口联调。"),
]
REFERENCE = "".join(t for _, t in SEGMENTS)

VOICE = {"zh": "Microsoft Huihui Desktop", "en": "Microsoft Zira Desktop"}


def synth(text: str, lang: str, path: Path) -> Path:
    """用指定语音合成 16k 单声道 wav。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    ps = f'''
Add-Type -AssemblyName System.Speech
$sp = New-Object System.Speech.Synthesis.SpeechSynthesizer
$sp.SelectVoice("{VOICE[lang]}")
$sp.Rate = 0
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$sp.SetOutputToWaveFile("{path}", $fmt)
$sp.Speak("{text}")
$sp.Dispose()
'''
    script = path.with_suffix(".ps1")
    script.write_text(ps, encoding="utf-8-sig")
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", str(script)], check=True, capture_output=True)
    script.unlink(missing_ok=True)
    return path


def build_mixed(path: Path) -> Path:
    """逐段合成后拼接（段间留 0.2s 静音）。"""
    if path.is_file():
        return path
    OUT.mkdir(parents=True, exist_ok=True)
    pieces: list[np.ndarray] = []
    for i, (lang, text) in enumerate(SEGMENTS):
        part = synth(text, lang, OUT / f"seg{i:02d}.wav")
        with wave.open(str(part), "rb") as w:
            sr = w.getframerate()
            data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        pieces.append(data.astype(np.float32) / 32768.0)
        pieces.append(np.zeros(int(sr * 0.2), dtype=np.float32))
    audio = np.concatenate(pieces)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((audio * 32767).astype(np.int16).tobytes())
    return path


def capture_noise(seconds: float = 6.0) -> np.ndarray:
    """录一段当前房间噪声（用于合成低信噪比测试）。"""
    import sounddevice as sd
    rec = sd.rec(int(16000 * seconds), samplerate=16000, channels=1, dtype="float32")
    sd.wait()
    return rec.reshape(-1)


def mix_at_snr(speech: np.ndarray, noise: np.ndarray, snr_db: float) -> np.ndarray:
    if len(noise) < len(speech):
        noise = np.tile(noise, int(np.ceil(len(speech) / max(1, len(noise)))))
    noise = noise[:len(speech)]
    sp = float(np.sqrt((speech ** 2).mean())) + 1e-9
    nw = float(np.sqrt((noise ** 2).mean())) + 1e-9
    return speech + noise * (sp / (10 ** (snr_db / 20.0)) / nw)


def recognize_all(rec_factory, audio: np.ndarray, sr: int) -> tuple[str, float]:
    import time
    rec = rec_factory()
    n = int(sr * 8)
    parts, t0 = [], time.monotonic()
    for i in range(0, len(audio), n):
        seg = audio[i:i + n]
        if len(seg) < sr:
            continue
        p = float(np.abs(seg).max())
        s = seg * (0.9 / p) if p > 0.05 else seg
        st = rec.create_stream()
        st.accept_waveform(sr, s)
        rec.decode_stream(st)
        parts.append(clean(st.result.text))
    return "".join(parts), time.monotonic() - t0


def main() -> int:
    import sherpa_onnx
    from check_asr_noisy import highpass, spectral_gate

    wav = build_mixed(OUT / "mixed-zh-en.wav")
    audio, sr = read_wav(wav)
    print(f"测试音频 {wav.name}  {len(audio)/sr:.1f}s（中英混说，8 秒切分）")
    print(f"标准答案 {len(normalize(REFERENCE))} 字\n")

    if "--noise" in sys.argv:
        noise = capture_noise()
        n_rms = float(np.sqrt((noise ** 2).mean()))
        audio = mix_at_snr(audio, noise, 3.0)
        print(f"已叠加真实房间噪声（信噪比 +3 dB；噪声 RMS {n_rms:.4f} / "
              f"{20*np.log10(max(n_rms,1e-9)):.1f} dBFS）\n")

    variants: list[tuple[str, object]] = []
    pf_dir = ROOT / "storage" / "asr" / "paraformer"
    if (pf_dir / "model.int8.onnx").is_file():
        variants.append(("Paraformer zh int8（只支持中文）", (
            lambda: sherpa_onnx.OfflineRecognizer.from_paraformer(
                paraformer=str(pf_dir / "model.int8.onnx"),
                tokens=str(pf_dir / "tokens.txt"), num_threads=4,
                sample_rate=16000, feature_dim=80,
                decoding_method="greedy_search", debug=False))))
    if (CUR_SV / "model.int8.onnx").is_file():
        for lang in ("zh", "auto"):
            variants.append((f"SenseVoice int8 (language={lang})", (
                lambda l=lang: sherpa_onnx.OfflineRecognizer.from_sense_voice(
                    model=str(CUR_SV / "model.int8.onnx"),
                    tokens=str(CUR_SV / "tokens.txt"), num_threads=4,
                    decoding_method="greedy_search", language=l, use_itn=True, debug=False))))
    for tag in ("base", "small"):
        enc = CMP / f"{tag}-encoder.int8.onnx"
        dec = CMP / f"{tag}-decoder.int8.onnx"
        tok = CMP / f"{tag}-tokens.txt"
        if enc.is_file() and dec.is_file() and tok.is_file():
            variants.append((f"Whisper {tag} int8", (
                lambda e=enc, d=dec, t=tok: sherpa_onnx.OfflineRecognizer.from_whisper(
                    encoder=str(e), decoder=str(d), tokens=str(t), num_threads=4,
                    language="zh", task="transcribe", tail_paddings=-1, debug=False))))

    rows = []
    for name, factory in variants:
        try:
            text, dt = recognize_all(factory, audio, sr)
        except Exception as e:  # noqa: BLE001
            print(f"===== {name} =====\n  失败: {type(e).__name__}: {e}\n")
            continue
        rate, dist, total = cer(REFERENCE, text)
        rows.append((name, rate, dist, total, dt, text))
        print(f"===== {name} =====")
        print(f"  CER {rate*100:5.1f}%  错 {dist}/{total} 字  用时 {dt:5.1f}s")
        print(f"  {text[:170]}")
        print()

    # 降噪前后对比（只对默认引擎做，用简单谱减，看 DSP 能不能救）
    if "--denoise" in sys.argv and variants:
        name, factory = variants[0]
        for label, fn in (("原始", lambda a: a),
                          ("高通 120Hz", lambda a: highpass(a, sr)),
                          ("高通+谱减降噪", lambda a: spectral_gate(highpass(a, sr), sr))):
            text, dt = recognize_all(factory, fn(audio).astype(np.float32), sr)
            rate, dist, total = cer(REFERENCE, text)
            rows.append((f"{name} + {label}", rate, dist, total, dt, text))
            print(f"===== {name} + {label} =====")
            print(f"  CER {rate*100:5.1f}%  错 {dist}/{total} 字  用时 {dt:5.1f}s")
            print(f"  {text[:140]}")
            print()

    if rows:
        print("=== 汇总（CER 越低越好）===")
        for name, rate, dist, total, dt, _ in sorted(rows, key=lambda r: r[1]):
            print(f"  {name:<34} CER {rate*100:5.1f}%  {dt:5.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
