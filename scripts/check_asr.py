"""语音识别准确率自检（字错率 CER），用于比较不同分段策略/模型。

用法::

    # 用 Windows 中文 TTS 合成一段"已知文本"的会议语音，再按三种模式识别并算 CER
    .venv\\Scripts\\python.exe scripts\\check_asr.py

    # 用自己的录音 + 手工标准答案
    .venv\\Scripts\\python.exe scripts\\check_asr.py --wav rec.wav --text "标准答案文本"

模式（--mode）：
  chunk4  当前实现：每攒够 4 秒盲切一刀，逐段识别
  full    整段一次性识别（离线模型的上限，仅用于对比，界面不能这么用）
  vad     按静音切分（本次要落地的改进）

CER = 编辑距离(识别, 标准答案) / 标准答案字数；同时打印每段识别结果便于肉眼看错在哪。
"""
from __future__ import annotations

import argparse
import re
import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SENSE_VOICE_DIR = ROOT / "storage" / "asr" / "sense-voice"
SAMPLE_RATE = 16000

# 会议风格的中文语料（不含阿拉伯数字，避免 ITN 带来的口径差异）
SCRIPT = (
    "大家好，今天我们过一下这个季度的交付情况。"
    "第一个模块已经完成了联调，测试用例覆盖了百分之八十五。"
    "第二个模块遇到一点阻塞，主要卡在第三方的接口联调上。"
    "我们计划把风险同步给采购，下周三之前给出替代方案。"
    "第三个模块按原计划下周上线，需要运维配合灰度发布。"
    "另外客服反馈了两个线上问题，优先级比较高，本周内要修。"
    "人力方面，小王下周休假三天，排期要往前挪一挪。"
    "预算还剩百分之二十，主要用于压测环境的扩容。"
    "下周一上午十点开复盘会，请大家提前把数据准备好。"
    "好，今天就到这里，散会。"
)

PUNCT = "，。、！？；：""''（）《》〈〉【】…—～·,.!?;:\"'()[]{}<>- \t\n\r"


def normalize(text: str) -> str:
    return "".join(ch for ch in text if ch not in PUNCT)


def cer(ref: str, hyp: str) -> tuple[float, int, int]:
    """字错率（编辑距离）。"""
    r, h = normalize(ref), normalize(hyp)
    if not r:
        return 0.0, 0, 0
    prev = list(range(len(h) + 1))
    for i, rc in enumerate(r, 1):
        cur = [i] + [0] * len(h)
        for j, hc in enumerate(h, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc))
        prev = cur
    dist = prev[-1]
    return dist / len(r), dist, len(r)


# ---------------------------------------------------------------- 造音频 ----

def tts_wav(path: Path, text: str = SCRIPT, rate: int = 0) -> Path:
    """用 Windows 中文语音合成 16k 单声道 WAV（离线，标准答案已知）。"""
    from System.Speech.Synthesis import SpeechSynthesizer  # type: ignore  # noqa: F401
    raise RuntimeError("占位：实际通过 PowerShell 调用，见 build_tts_wav()")


def build_tts_wav(path: Path, text: str = SCRIPT) -> Path:
    """调用 PowerShell/System.Speech 合成 16k 单声道 wav。"""
    import subprocess
    path.parent.mkdir(parents=True, exist_ok=True)
    ps = f'''
Add-Type -AssemblyName System.Speech
$sp = New-Object System.Speech.Synthesis.SpeechSynthesizer
$sp.SelectVoice("Microsoft Huihui Desktop")
$sp.Rate = 0
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$sp.SetOutputToWaveFile("{path}", $fmt)
$sp.Speak("{text}")
$sp.Dispose()
'''
    tmp = path.with_suffix(".ps1")
    tmp.write_text(ps, encoding="utf-8-sig")
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", str(tmp)], check=True, capture_output=True)
    tmp.unlink(missing_ok=True)
    return path


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        width = w.getsampwidth()
        raw = w.readframes(w.getnframes())
    dtype = {1: np.uint8, 2: np.int16, 4: np.int32}[width]
    data = np.frombuffer(raw, dtype=dtype).astype(np.float32)
    if dtype is np.int16:
        data /= 32768.0
    elif dtype is np.int32:
        data /= 2147483648.0
    else:
        data = (data - 128.0) / 128.0
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    return data, sr


# ---------------------------------------------------------------- 识别 ----

def make_recognizer():
    import sherpa_onnx
    return sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(SENSE_VOICE_DIR / "model.int8.onnx"),
        tokens=str(SENSE_VOICE_DIR / "tokens.txt"),
        num_threads=4, decoding_method="greedy_search",
        language="zh", use_itn=True, debug=False)


def clean(text: str) -> str:
    return " ".join(re.sub(r"<\|[^|]*\|>", "", text).replace("[PAD]", "").split())


def decode(rec, samples: np.ndarray, sr: int) -> str:
    st = rec.create_stream()
    st.accept_waveform(sr, samples)
    rec.decode_stream(st)
    return clean(st.result.text)


def normalize_peak(chunk: np.ndarray) -> np.ndarray:
    peak = float(np.abs(chunk).max()) if len(chunk) else 0.0
    return chunk * (0.9 / peak) if peak > 0.05 else chunk


def mode_chunk(samples: np.ndarray, sr: int, chunk_s: float = 4.0) -> list[str]:
    rec = make_recognizer()
    n = int(sr * chunk_s)
    out = []
    for i in range(0, len(samples), n):
        seg = samples[i:i + n]
        if len(seg) < sr * 0.4:
            continue
        out.append(decode(rec, normalize_peak(seg), sr))
    return out


def mode_full(samples: np.ndarray, sr: int) -> list[str]:
    return [decode(make_recognizer(), normalize_peak(samples), sr)]


def mode_vad(samples: np.ndarray, sr: int, min_s: float = 1.5,
             max_s: float = 12.0, sil_s: float = 0.35) -> list[str]:
    """能量 VAD 分段：自适应噪声底 → 找语音区间 → 在静音处切。

    比"盲切 4 秒"强在：不切断词、每段更长（离线模型喜欢 5~15 秒）、
    纯静音段直接丢弃（避免模型对着噪声瞎编）。
    """
    frame = int(sr * 0.02)                    # 20ms
    if len(samples) < frame * 2:
        return []
    n = len(samples) // frame
    frames = samples[:n * frame].reshape(n, frame)
    rms = np.sqrt((frames ** 2).mean(axis=1) + 1e-12)
    db = 20 * np.log10(rms + 1e-9)
    noise = float(np.percentile(db, 15))      # 噪声底
    thr = max(noise + 8.0, -55.0)             # 高出噪声底 8dB 才算语音
    voiced = db > thr

    # 形态学：补掉短空隙、削掉短爆发
    gap_max = int(0.25 / 0.02)
    run_min = int(0.10 / 0.02)
    i = 0
    while i < len(voiced):
        if not voiced[i]:
            j = i
            while j < len(voiced) and not voiced[j]:
                j += 1
            if i > 0 and j < len(voiced) and (j - i) <= gap_max:
                voiced[i:j] = True
            i = j
        else:
            i += 1
    i = 0
    while i < len(voiced):
        if voiced[i]:
            j = i
            while j < len(voiced) and voiced[j]:
                j += 1
            if (j - i) < run_min:
                voiced[i:j] = False
            i = j
        else:
            i += 1

    # 找连续语音区间
    spans: list[list[int]] = []
    i = 0
    while i < len(voiced):
        if voiced[i]:
            j = i
            while j < len(voiced) and voiced[j]:
                j += 1
            spans.append([i, j])
            i = j
        else:
            i += 1

    # 合并太近的区间；过长的按 max_s 切开
    merged: list[list[int]] = []
    sil_max = int(sil_s / 0.02)
    for sp in spans:
        if merged and sp[0] - merged[-1][1] <= sil_max:
            merged[-1][1] = sp[1]
        else:
            merged.append(sp)
    max_frames = int(max_s / 0.02)
    final: list[list[int]] = []
    for a, b in merged:
        while b - a > max_frames:
            final.append([a, a + max_frames])
            a += max_frames
        if b - a >= int(min_s / 0.02):
            final.append([a, b])

    rec = make_recognizer()
    out = []
    for a, b in final:
        # 前后各留 0.15s 余量，避免把首尾音切掉
        pad = int(0.15 / 0.02)
        s = max(0, (a - pad)) * frame
        e = min(len(samples), (b + pad) * frame)
        out.append(decode(rec, normalize_peak(samples[s:e]), sr))
    print(f"    VAD 切出 {len(final)} 段，时长 "
          f"{[round((b - a) * 0.02, 1) for a, b in final]}")
    return out


def mode_app(samples: np.ndarray, sr: int, chunk_seconds: float | None = None) -> list[str]:
    """走 **app 自己的 ASRWorker**（QThread + 队列），验证真实链路。

    需要跑事件循环，否则跨线程信号不会派发。
    """
    import queue

    from PySide6.QtCore import QCoreApplication

    from app import config as config_mod
    from app.asr import ASRWorker

    cfg = config_mod.load_config()
    if chunk_seconds:
        cfg["asr"]["chunk_seconds"] = float(chunk_seconds)
    app = QCoreApplication.instance() or QCoreApplication([])
    q: "queue.Queue" = queue.Queue()
    worker = ASRWorker(cfg, q)
    segs: list[str] = []
    worker.segment.connect(lambda t, a, b: segs.append(t))
    worker.start()
    # 等模型加载完（ASREngine.init 大约 1~3s）
    t0 = time.monotonic()
    while time.monotonic() - t0 < 4.0:
        app.processEvents()
        time.sleep(0.02)
    data = (samples * 32767.0).astype(np.int16).reshape(-1, 1)
    step = sr // 10                      # 100ms 一块，模拟麦克风回调
    for i in range(0, len(data), step):
        q.put(data[i:i + step])
        app.processEvents()
    time.sleep(0.5)
    worker.shutdown()
    deadline = time.monotonic() + 60
    while worker.isRunning() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.05)
    app.processEvents()
    return segs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", default="")
    ap.add_argument("--text", default="")
    ap.add_argument("--mode", default="all",
                    choices=["all", "chunk4", "full", "vad", "app"])
    ap.add_argument("--chunk", type=float, default=4.0, help="chunk4 模式的段长（秒）")
    ap.add_argument("--vad-min", type=float, default=1.5)
    ap.add_argument("--vad-max", type=float, default=12.0)
    ap.add_argument("--vad-sil", type=float, default=0.35)
    ap.add_argument("--sweep", action="store_true",
                    help="扫描不同段长/VAD 参数，找 CER 与耗时的平衡点")
    args = ap.parse_args()

    tmp = ROOT / "build" / "asr-test"
    if args.wav:
        wav_path, ref = Path(args.wav), (args.text or SCRIPT)
    else:
        wav_path = tmp / "tts-meeting.wav"
        ref = args.text or SCRIPT
        if not wav_path.is_file():
            print(f"合成测试语音（Windows 中文 TTS）→ {wav_path}")
            build_tts_wav(wav_path, ref)
    samples, sr = read_wav(wav_path)
    print(f"音频: {wav_path.name}  {len(samples)/sr:.1f}s  {sr}Hz  "
          f"峰值={np.abs(samples).max():.3f}")
    print(f"标准答案 {len(normalize(ref))} 字\n")

    if args.sweep:
        cases: list[tuple[str, callable]] = [
            ("整段(上限)", lambda s, r: mode_full(s, r)),
            ("盲切 4s(旧)", lambda s, r: mode_chunk(s, r, 4.0)),
            ("盲切 8s(新)", lambda s, r: mode_chunk(s, r, 8.0)),
            ("盲切 12s", lambda s, r: mode_chunk(s, r, 12.0)),
            ("app 链路 8s", lambda s, r: mode_app(s, r, 8.0)),
        ]
        rows = []
        for name, fn in cases:
            t0 = time.monotonic()
            segs = fn(samples, sr)
            joined = "".join(segs)
            rate, dist, total = cer(ref, joined)
            rows.append((name, rate, dist, total, time.monotonic() - t0, len(segs)))
            print(f"  {name:16} CER {rate*100:5.1f}%  错 {dist:3}/{total}  "
                  f"{len(segs):2} 段  用时 {rows[-1][4]:5.1f}s")
        print("\n=== 汇总（按 CER 排序）===")
        for name, rate, dist, total, dt, nseg in sorted(rows, key=lambda r: r[1]):
            print(f"  {name:16} CER {rate*100:5.1f}%  {nseg:2} 段  用时 {dt:5.1f}s")
        return 0

    modes = ["chunk4", "full", "vad"] if args.mode == "all" else [args.mode]
    results = {}
    for m in modes:
        t0 = time.monotonic()
        print(f"--- 模式 {m} ---")
        if m == "chunk4":
            segs = mode_chunk(samples, sr, args.chunk)
        elif m == "full":
            segs = mode_full(samples, sr)
        elif m == "app":
            segs = mode_app(samples, sr)      # 走 app 自己的 ASRWorker（含标点恢复）
        else:
            segs = mode_vad(samples, sr, args.vad_min, args.vad_max, args.vad_sil)
        joined = "".join(segs)
        rate, dist, total = cer(ref, joined)
        results[m] = (rate, dist, total, time.monotonic() - t0)
        print(f"  CER {rate*100:.1f}%  错 {dist}/{total} 字  用时 {results[m][3]:.1f}s")
        print(f"  识别: {joined[:120]}{'…' if len(joined) > 120 else ''}")
        print()
    if len(results) > 1:
        best = min(results.items(), key=lambda kv: kv[1][0])
        print("=== 汇总（CER 越低越好）===")
        for m, (rate, dist, total, dt) in results.items():
            print(f"  {m:8} CER {rate*100:5.1f}%  错 {dist:3}/{total}  用时 {dt:5.1f}s")
        print(f"  最好: {best[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
