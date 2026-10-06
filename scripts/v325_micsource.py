"""3.2.5：麦克风音源可对比（关=原始 MIC / 开=VOICE_RECOGNITION）+ 状态栏显示音量

背景：用户"声音小 + 漏字"，前面的代码层修复（预卷 1.0s、保底静音 0.35s、音量归一化 ×10）
在模拟器上识别完整，说明剩下的是**手机麦克风输入**这一环。

VOICE_RECOGNITION 在不少国产 ROM 上会做激进降噪/AGC，把小声说话直接吃掉
（表现就是"声音很小 + 漏字"）。所以改成：
   降噪 关（默认）→ AudioSource.MIC          （原始信号，通常更响、不被 ROM 处理）
   降噪 开        → AudioSource.VOICE_RECOGNITION + NS/AEC（原来的行为）
用户只要拨一下「降噪」开关就能 A/B 对比，不用等新包。

同时把实测音量显示到状态栏（"峰值 -XXdB / 放大 Nx"），用户读一眼就能反馈。
"""
import re
from pathlib import Path

R = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
rec = R / "android/app/src/main/java/com/localrecord/app/Recorder.kt"
m = R / "android/app/src/main/java/com/localrecord/app/MainActivity.kt"

# ---------- ① 音源按开关走 ----------
t = rec.read_text(encoding="utf-8")
old = """        val rec = try {
            AudioRecord(
                MediaRecorder.AudioSource.VOICE_RECOGNITION,
                sampleRate, AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT, bufSize
            )
        } catch (e: Exception) {"""
assert old in t, "找不到 AudioRecord 创建处"
new = """        // 音源选择（对识别质量影响很大）：
        //   降噪 关（默认）→ MIC：原始信号，通常更响，不会被 ROM 的降噪/AGC 吃掉小声说话；
        //   降噪 开        → VOICE_RECOGNITION + NS/AEC：系统那套为远场语音做的处理。
        // 之前无论开关都固定用 VOICE_RECOGNITION，部分机型会把小声说话处理没（用户反馈"声音小+漏字"）。
        val source = if (useEnhancements) {
            MediaRecorder.AudioSource.VOICE_RECOGNITION
        } else {
            MediaRecorder.AudioSource.MIC
        }
        android.util.Log.i(TAG, "录音音源=" + if (useEnhancements) "VOICE_RECOGNITION（降噪开）" else "MIC（降噪关）")
        val rec = try {
            AudioRecord(
                source,
                sampleRate, AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT, bufSize
            )
        } catch (e: Exception) {"""
rec.write_text(t.replace(old, new, 1), encoding="utf-8")
print("Recorder：降噪关→MIC（更响），降噪开→VOICE_RECOGNITION ✓")

# ---------- ② 状态栏显示峰值/放大倍数 ----------
mt = m.read_text(encoding="utf-8")
old_status = '''            status = if (fromSilero) {
                "已转写 ${segments.size} 段（人声 $speechWin 窗 / ${(speechPct * 100).toInt()}%）"'''
if old_status in mt:
    mt = mt.replace(old_status, '''            val peakDb = if (pk > 0f) (20 * kotlin.math.log10(pk.toDouble())).toInt() else -90
            status = if (fromSilero) {
                "已转写 ${segments.size} 段（人声 $speechWin 窗 / ${(speechPct * 100).toInt()}%，峰值 ${peakDb}dB / 放大 %.1fx）".format(usedGain)''', 1)
    print("状态栏：加入 峰值dB / 放大倍数 ✓")
else:
    print("· 未找到状态栏文案（跳过）")

# emitSegment 里把 peak/gain 暴露给上面的文案
if "val usedGain" not in mt:
    mt = mt.replace("""        val targetPeak = 0.5f
        val gain = if (peak > 1e-4f) (targetPeak / peak).coerceAtMost(10f) else 1f""",
"""        val targetPeak = 0.5f
        val gain = if (peak > 1e-4f) (targetPeak / peak).coerceAtMost(10f) else 1f
        val pk = peak
        val usedGain = gain""", 1)
    print("emitSegment：暴露 pk / usedGain ✓")
m.write_text(mt, encoding="utf-8")

# ---------- ③ 版本 ----------
g = R / "android/app/build.gradle.kts"
gt = g.read_text(encoding="utf-8")
gt = re.sub(r"versionCode = \d+", "versionCode = 325", gt, count=1)
gt = re.sub(r'versionName = "[^"]*"', 'versionName = "3.2.5"', gt, count=1)
g.write_text(gt, encoding="utf-8")
print("版本 -> 3.2.5 / 325 ✓")
