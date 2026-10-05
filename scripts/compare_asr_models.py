"""对比不同 ASR 模型/精度的字错率（CER）与速度。

用法::

    .venv\\Scripts\\python.exe scripts\\compare_asr_models.py [--wav x.wav --text "标准答案"]

默认用 Windows 中文 TTS 合成的会议语音（209 字，已知标准答案），对比：

  SenseVoice int8   —— 当前线上用的模型（226MB）
  SenseVoice f32    —— 同版本全精度（929MB，量化损失有多大一看便知）
  Paraformer zh int8—— 另一个中文模型（227MB，非自回归，业界常用）

每种都跑「整段一次」和「8 秒一段」两种切分，输出 CER 与耗时，便于取舍
（准确率 vs 体积 vs 速度）。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from check_asr import (  # noqa: E402
    SCRIPT, cer, clean, decode, normalize, read_wav,
)

CMP = ROOT / "build" / "models-cmp"
CUR = ROOT / "storage" / "asr" / "sense-voice"


def make_sense_voice(model: Path, tokens: Path):
    import sherpa_onnx

    return sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(model), tokens=str(tokens), num_threads=4,
        decoding_method="greedy_search", language="zh", use_itn=True, debug=False)


def make_paraformer(model: Path, tokens: Path):
    import sherpa_onnx

    return sherpa_onnx.OfflineRecognizer.from_paraformer(
        paraformer=str(model), tokens=str(tokens), num_threads=4,
        sample_rate=16000, feature_dim=80, decoding_method="greedy_search", debug=False)


def peak_norm(x: np.ndarray) -> np.ndarray:
    p = float(np.abs(x).max()) if len(x) else 0.0
    return x * (0.9 / p) if p > 0.05 else x


def run_chunked(rec, samples: np.ndarray, sr: int, chunk_s: float = 8.0) -> tuple[str, float]:
    n = int(sr * chunk_s)
    out: list[str] = []
    t0 = time.monotonic()
    for i in range(0, len(samples), n):
        seg = samples[i:i + n]
        if len(seg) < sr:
            continue
        out.append(decode(rec, peak_norm(seg), sr))
    return "".join(out), time.monotonic() - t0


def run_full(rec, samples: np.ndarray, sr: int) -> tuple[str, float]:
    t0 = time.monotonic()
    text = decode(rec, peak_norm(samples), sr)
    return text, time.monotonic() - t0


def main() -> int:
    wav = ROOT / "build" / "asr-test" / "tts-meeting.wav"
    ref = SCRIPT
    if "--wav" in sys.argv:
        wav = Path(sys.argv[sys.argv.index("--wav") + 1])
    if "--text" in sys.argv:
        ref = sys.argv[sys.argv.index("--text") + 1]
    if not wav.is_file():
        print(f"缺少测试音频 {wav}，先跑 scripts/check_asr.py 生成")
        return 1
    samples, sr = read_wav(wav)
    print(f"音频 {wav.name}  {len(samples)/sr:.1f}s  标准答案 {len(normalize(ref))} 字\n")

    cands: list[tuple[str, Path, Path, object, float]] = []
    # (名称, 模型文件, tokens, 构造函数, 体积MB)
    sv_int8 = CUR / "model.int8.onnx"
    if sv_int8.is_file():
        cands.append(("SenseVoice int8（现用）", sv_int8, CUR / "tokens.txt", make_sense_voice, 226))
    if (CMP / "sense-voice-f32.onnx").is_file():
        cands.append(("SenseVoice f32", CMP / "sense-voice-f32.onnx",
                      CMP / "sense-voice-tokens.txt", make_sense_voice, 929))
    if (CMP / "paraformer-zh-int8.onnx").is_file():
        cands.append(("Paraformer zh int8", CMP / "paraformer-zh-int8.onnx",
                      CMP / "paraformer-tokens.txt", make_paraformer, 227))

    rows: list[tuple[str, float, float, float, float, float]] = []
    for name, model, tokens, factory, size in cands:
        try:
            t_load = time.monotonic()
            rec = factory(model, tokens)
            load_s = time.monotonic() - t_load
        except Exception as e:  # noqa: BLE001
            print(f"  {name}: 加载失败 {type(e).__name__}: {e}")
            continue
        text_full, t_full = run_full(rec, samples, sr)
        text_chunk, t_chunk = run_chunked(rec, samples, sr)
        cer_full = cer(ref, text_full)[0]
        cer_chunk = cer(ref, text_chunk)[0]
        rows.append((name, size, cer_full, cer_chunk, t_full, t_chunk))
        print(f"===== {name}（{size}MB，加载 {load_s:.1f}s）=====")
        print(f"  整段一次 : CER {cer_full*100:5.1f}%  用时 {t_full:5.1f}s")
        print(f"  8 秒切分 : CER {cer_chunk*100:5.1f}%  用时 {t_chunk:5.1f}s")
        print(f"  识别片段 : {text_chunk[:110]}")
        print()

    if rows:
        print("=== 汇总（按 8 秒切分 CER 排序，越低越好）===")
        print(f"  {'模型':<24}{'体积MB':>8}{'整段CER':>10}{'8秒CER':>10}{'8秒用时':>10}")
        for name, size, cf, cc, tf, tc in sorted(rows, key=lambda r: r[3]):
            print(f"  {name:<24}{size:>8}{cf*100:>9.1f}%{cc*100:>9.1f}%{tc:>9.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
