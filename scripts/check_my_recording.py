"""用**你自己的录音**量识别准确率（字错率 CER）。

用法（两步）：

1. 打开 app 点录音，**照着下面这段念**（大约 25 秒，念错字没关系，按标准文本算）：

   今天的会议改到下午三点，请大家准时参加。
   第一个模块已经完成联调，测试用例覆盖了百分之八十五。
   第二个模块遇到一点阻塞，主要卡在第三方的接口联调上。
   下周一上午十点开复盘会，请大家提前把数据准备好。

2. 然后运行（会自动取**最新一条录音**）：

   .venv\\Scripts\\python.exe scripts\\check_my_recording.py

   想指定文件 / 换标准文本：

   .venv\\Scripts\\python.exe scripts\\check_my_recording.py --wav 某录音.wav --text "标准文本"

输出：当前引擎在不同段长下的 CER（越低越好）+ 识别文本，用来判断
「是麦克风环境不行」还是「换个模型/段长能救」。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from check_asr import cer, decode, normalize, read_wav  # noqa: E402

#: 请照读的标准文本（中英混说，与脚本顶部提示一致）
REFERENCE = (
    "今天的会议改到下午三点，请大家准时参加。"
    "第一个模块已经完成联调，测试用例覆盖了百分之八十五。"
    "第二个模块遇到一点阻塞，主要卡在第三方的接口联调上。"
    "the API response time must be under two hundred milliseconds."
    "下周一上午十点开复盘会，请大家提前把数据准备好。"
)


def norm_text(text: str) -> str:
    """去掉标点空白并统一小写：英文大小写差异不该算成错字。"""
    return normalize(text).lower()


def newest_recording() -> Path | None:
    from app.paths import recordings_dir
    d = recordings_dir()
    if not d.is_dir():
        return None
    files = sorted(d.glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def build_engine(cfg):
    """按 config.yaml 的 backend 建引擎（paraformer / sense_voice）。"""
    import sherpa_onnx

    from app.config import storage_path
    backend = str(cfg["asr"].get("backend", "paraformer")).lower()
    if backend == "sense_voice":
        sv = cfg["asr"]["sense_voice"]
        d = storage_path(cfg["asr"], "sense_voice.model_dir")
        return sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(d / sv["model_filename"]), tokens=str(d / sv["tokens_filename"]),
            num_threads=4, decoding_method="greedy_search",
            language=sv.get("language", "zh"), use_itn=True, debug=False), backend
    pf = cfg["asr"]["paraformer"]
    d = storage_path(cfg["asr"], "paraformer.model_dir")
    return sherpa_onnx.OfflineRecognizer.from_paraformer(
        paraformer=str(d / pf["model_filename"]), tokens=str(d / pf["tokens_filename"]),
        num_threads=4, sample_rate=16000, feature_dim=80,
        decoding_method="greedy_search", debug=False), backend


def main() -> int:
    from app import config as config_mod
    wav = None
    ref = REFERENCE
    if "--wav" in sys.argv:
        wav = Path(sys.argv[sys.argv.index("--wav") + 1])
    if "--text" in sys.argv:
        ref = sys.argv[sys.argv.index("--text") + 1]
    if wav is None:
        wav = newest_recording()
    if wav is None or not Path(wav).is_file():
        print("没找到录音。先在 app 里录一段（照 check_my_recording.py 顶部那段念），再运行本脚本。")
        return 1

    cfg = config_mod.load_config()
    cfg["asr"]["sample_rate"] = 16000
    samples, sr = read_wav(Path(wav))
    print(f"录音: {Path(wav).name}  {len(samples)/sr:.1f}s  峰值={np.abs(samples).max():.3f}")
    print(f"标准答案 {len(norm_text(ref))} 字\n")
    # 顺便报一下电平情况，帮助判断是不是麦克风/环境问题
    p10 = float(np.percentile(np.abs(samples), 10))
    print(f"底噪参考（10 分位幅度）={p10:.4f}   峰值={np.abs(samples).max():.3f}")

    rec, backend = build_engine(cfg)
    print(f"引擎: {backend}\n")

    def norm(x: np.ndarray) -> np.ndarray:
        p = float(np.abs(x).max()) if len(x) else 0.0
        return x * (0.9 / p) if p > 0.05 else x

    rows = []
    for label, chunk_s in (("整段一次", None), ("12 秒/段", 12.0),
                           ("8 秒/段（默认）", 8.0), ("4 秒/段", 4.0)):
        if chunk_s is None:
            text = decode(rec, norm(samples), sr)
        else:
            n = int(sr * chunk_s)
            parts = [decode(rec, norm(samples[i:i + n]), sr)
                     for i in range(0, len(samples), n) if len(samples[i:i + n]) >= sr]
            text = "".join(parts)
        rate, dist, total = cer(norm_text(ref), norm_text(text))
        rows.append((label, rate, dist, total, text))

    print("=== 结果（CER 越低越好）===")
    for label, rate, dist, total, _ in sorted(rows, key=lambda r: r[1]):
        print(f"  {label:<16} CER {rate*100:5.1f}%  错 {dist}/{total} 字")
    best = min(rows, key=lambda r: r[1])
    print(f"\n最好：{best[0]}  CER {best[1]*100:.1f}%")
    print(f"识别文本：{best[4][:150]}")
    print("\n把这份输出发我，就能判断问题在麦克风还是模型/参数。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
