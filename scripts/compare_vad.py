"""对比三种 VAD 在"真人语音"和"纯噪声"上的表现，挑出最准的那个。

用 sherpa-onnx 的 Python API（和 Android 端是同一套 C++ 实现，结论可直接迁移）。
"""
import sys
import time
import urllib.request
import wave

import numpy as np

ROOT = r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main"
UA = {"User-Agent": "Mozilla/5.0 Chrome/120"}

MODELS = {
    "silero": "https://hf-mirror.com/deepghs/silero-vad-onnx/resolve/main/silero_vad.onnx",
    "ten": "https://hf-mirror.com/TEN-framework/ten-vad/resolve/main/onnx/ten-vad.onnx",
}


def download(name, url, dst_dir):
    from pathlib import Path

    dst = Path(dst_dir) / f"{name}.onnx"
    if dst.is_file() and dst.stat().st_size > 10_000:
        print(f"  已有 {dst} ({dst.stat().st_size/1e6:.2f} MB)")
        return str(dst)
    try:
        raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=300).read()
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(raw)
        print(f"  下载 {name}: {len(raw)/1e6:.2f} MB → {dst}")
        return str(dst)
    except Exception as e:
        print(f"  下载 {name} 失败: {type(e).__name__} {getattr(e, 'code', '')}")
        return None


def read_wav(path):
    with wave.open(path) as w:
        sr = w.getframerate()
        data = w.readframes(w.getnframes())
    a = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
    return a, sr


def segments(vad, samples, sr):
    """喂完整段音频，返回 [(start_sec, dur_sec)]"""
    out = []
    win = 512
    for i in range(0, len(samples), win):
        chunk = samples[i:i + win]
        if len(chunk) < win:
            chunk = np.pad(chunk, (0, win - len(chunk)))
        vad.accept_waveform(chunk)
        while not vad.empty():
            seg = vad.front
            out.append((seg.start / sr, len(seg.samples) / sr))
            vad.pop()
    vad.flush()
    while not vad.empty():
        seg = vad.front
        out.append((seg.start / sr, len(seg.samples) / sr))
        vad.pop()
    return out


def main():
    import sherpa_onnx

    model_dir = f"{ROOT}\\storage\\asr\\vad"
    paths = {k: download(k, u, model_dir) for k, u in MODELS.items()}

    speech, sr = read_wav(f"{ROOT}\\storage\\asr\\selftest.wav")
    print(f"真人语音样本：{len(speech)/sr:.2f} 秒，峰值 {20*np.log10(np.abs(speech).max()+1e-9):.1f} dBFS")
    rng = np.random.default_rng(7)
    noise = (rng.random(sr * 20, dtype=np.float32) - 0.5) * 0.004  # 20 秒低电平噪声
    print(f"噪声样本：20.00 秒，电平 {20*np.log10(np.sqrt((noise**2).mean())+1e-9):.1f} dBFS")

    # 拼接：噪声 + 语音 + 噪声 + 语音（考验边界）
    mixed = np.concatenate([noise[:sr * 3], speech, noise[:sr * 3], speech, noise[:sr * 3]])

    for name, path in paths.items():
        if not path:
            continue
        for thr in (0.5, 0.35):
            t0 = time.time()
            cfg = sherpa_onnx.VadModelConfig()
            if name == "silero":
                cfg.silero_vad.model = path
                cfg.silero_vad.threshold = thr
                cfg.silero_vad.min_silence_duration = 0.5
                cfg.silero_vad.min_speech_duration = 0.25
                cfg.silero_vad.window_size = 512
            else:
                cfg.ten_vad.model = path
                cfg.ten_vad.threshold = thr
                cfg.ten_vad.min_silence_duration = 0.5
                cfg.ten_vad.min_speech_duration = 0.25
                cfg.ten_vad.window_size = 256
            cfg.sample_rate = sr
            cfg.num_threads = 4
            vad = sherpa_onnx.Vad(cfg)
            segs_speech = segments(vad, speech, sr)
            vad2 = sherpa_onnx.Vad(cfg)
            segs_noise = segments(vad2, noise, sr)
            vad3 = sherpa_onnx.Vad(cfg)
            segs_mix = segments(vad3, mixed, sr)
            dt = time.time() - t0
            print(f"\n=== {name} threshold={thr} （{dt:.2f}s）===")
            print(f"  纯语音: {len(segs_speech)} 段 " + ", ".join(f"{s:.2f}s+{d:.2f}s" for s, d in segs_speech))
            print(f"  纯噪声: {len(segs_noise)} 段 " + ", ".join(f"{s:.2f}s+{d:.2f}s" for s, d in segs_noise))
            print(f"  混合:   {len(segs_mix)} 段 " + ", ".join(f"{s:.2f}s+{d:.2f}s" for s, d in segs_mix[:6]))


if __name__ == "__main__":
    sys.exit(main())
