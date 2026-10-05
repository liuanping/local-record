"""验证 Silero VAD（sherpa-onnx 实现，与 Android 端同一套 C++）。

重点回答两个问题：
  1. 真人语音 vs 纯噪声，切段是否准确？
  2. **低电平**（用户手机原始电平只有 -55dB）时还能不能切出来？要不要先做增益归一化？
"""
import wave

import numpy as np
import sherpa_onnx

ROOT = r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main"
MODEL = f"{ROOT}\\storage\\asr\\vad\\silero.onnx"
SR = 16000


def read_wav(path):
    with wave.open(path) as w:
        sr = w.getframerate()
        data = w.readframes(w.getnframes())
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0, sr


def make_vad(threshold=0.5, min_sil=0.35, min_speech=0.2):
    cfg = sherpa_onnx.VadModelConfig()
    cfg.silero_vad.model = MODEL
    cfg.silero_vad.threshold = threshold
    cfg.silero_vad.min_silence_duration = min_sil
    cfg.silero_vad.min_speech_duration = min_speech
    cfg.silero_vad.window_size = 512
    cfg.sample_rate = SR
    cfg.num_threads = 2
    return sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=60)


def run(samples, threshold=0.5):
    vad = make_vad(threshold)
    vad.accept_waveform(samples)
    vad.flush()
    out = []
    while not vad.empty():
        seg = vad.front
        out.append((seg.start / SR, len(seg.samples) / SR))
        vad.pop()
    return out


def db(x):
    return 20 * np.log10(np.sqrt((x ** 2).mean()) + 1e-9)


def normalize(samples, target_peak=0.6):
    """简单增益归一化：把峰值拉到 target_peak（模拟"先 AGC 再喂 VAD"）"""
    peak = float(np.abs(samples).max())
    if peak < 1e-6:
        return samples
    return samples * (target_peak / peak)


def main():
    speech, sr = read_wav(f"{ROOT}\\storage\\asr\\selftest.wav")
    rng = np.random.default_rng(7)
    noise = (rng.random(SR * 20, dtype=np.float32) - 0.5) * 0.004

    print(f"语音样本 {len(speech)/sr:.2f}s 电平 {db(speech):.1f} dBFS 峰值 {20*np.log10(np.abs(speech).max()):.1f} dBFS")
    print(f"噪声样本 20.00s 电平 {db(noise):.1f} dBFS")

    mixed = np.concatenate([noise[:SR * 3], speech, noise[:SR * 3], speech, noise[:SR * 3]])
    print(f"混合样本 {len(mixed)/sr:.2f}s（噪声-语音-噪声-语音-噪声）")

    # 低电平模拟：整体衰减 40dB，接近用户手机的 -55dB 级别
    quiet = speech * 0.01
    quiet_mixed = mixed * 0.01
    print(f"衰减后语音电平 {db(quiet):.1f} dBFS（模拟手机低电平麦克风）")
    print()

    cases = [
        ("① 语音(原始)", speech),
        ("② 语音(衰减40dB)", quiet),
        ("③ 语音(衰减40dB + 归一化)", normalize(quiet)),
        ("④ 噪声", noise),
        ("⑤ 噪声(归一化)", normalize(noise)),
        ("⑥ 混合(衰减 + 归一化)", normalize(quiet_mixed)),
    ]
    for label, data in cases:
        for thr in (0.5, 0.35):
            segs = run(data, thr)
            total = sum(d for _, d in segs)
            desc = ", ".join(f"{s:.2f}s+{d:.2f}s" for s, d in segs[:5])
            print(f"{label:26s} thr={thr}: {len(segs)} 段，共 {total:.2f}s   {desc}")


if __name__ == "__main__":
    main()
