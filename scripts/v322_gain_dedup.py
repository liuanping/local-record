"""3.2.2：修两处直接导致"识别错误率高 + 重复"的问题。

用户反馈：依然会重复、识别错误率很高（并且一直说"声音很小"）。

根因（我在自己代码里找到的 bug）：
1. emitSegment 里的音量归一化写成 `if (peak > 0.05f) 0.9f/peak else 1f`
   —— **音量小的段落直接不放大**，原样送去识别。麦克风偏小的手机正好落在这个分支里，
   于是识别错误率高；而 Paraformer 在低电平输入上还会吐"重复句"（幻觉）。
   改成：不管大小都归一到目标峰值，最多放大 10 倍（带限幅），并打印 peak/gain 便于排查。
2. 与上一段**完全相同**的长文本（≥6 字）直接丢弃 —— 这是 VAD/识别重复或低电平幻觉的典型表现，
   用户说的"依然会重复"多半就是它。
"""
from pathlib import Path

R = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
APP = R / "android/app/src/main/java/com/localrecord/app"
m = APP / "MainActivity.kt"
t = m.read_text(encoding="utf-8")

# ---------- ① 音量归一化：不管大小都拉 ----------
old_gain = """        val gain = if (peak > 0.05f) 0.9f / peak else 1f
        if (gain != 1f) for (i in seg.indices) seg[i] *= gain"""
assert old_gain in t, "找不到音量归一化那段"
new_gain = """        // 音量归一化：**不管声音大小都拉到目标电平**。
        // 原来写成 `if (peak > 0.05f) 0.9f / peak else 1f` —— 音量小的段落直接不放大，
        // 原样送去识别 → 麦克风偏小的手机识别错误率高，而且低电平上识别器容易吐"重复幻觉"。
        // 目标峰值 0.5，最多放大 10 倍（再大就把底噪一起抬起来），并做限幅。
        val targetPeak = 0.5f
        val gain = if (peak > 1e-4f) (targetPeak / peak).coerceAtMost(10f) else 1f
        if (gain > 1.02f || gain < 0.98f) {
            for (i in seg.indices) {
                seg[i] = (seg[i] * gain).coerceIn(-1f, 1f)
            }
        }
        android.util.Log.i("Audio", "分段音量 peak=%.4f gain=%.1fx（${seg.size} 采样）".format(peak, gain))"""
t = t.replace(old_gain, new_gain, 1)
print("✓ 音量归一化改成"不管大小都拉"（最多 ×10，带限幅）")

# ---------- ② 丢弃与上一段完全相同的长文本 ----------
anchor = """        val end = startSec + seg.size.toFloat() / AsrEngine.SAMPLE_RATE
        runOnUiThread {
            segments.add(Seg(text, startSec, end, fmt(startSec)))"""
assert anchor in t, "找不到加段落的锚点"
new_anchor = """        // 去重：与上一段**完全相同**且不短（≥6 字）的文字，基本是 VAD/识别重复或低电平幻觉。
        // 用户反馈"依然会重复"，这一条直接把重复段挡在列表外。
        if (text.length >= 6 && text == lastSegmentText) {
            android.util.Log.i("Segments", "丢弃重复段（与上一段相同）：${text.take(24)}")
            runOnUiThread { status = "这一段和上一段重复，已跳过" }
            return
        }
        val end = startSec + seg.size.toFloat() / AsrEngine.SAMPLE_RATE
        runOnUiThread {
            lastSegmentText = text
            segments.add(Seg(text, startSec, end, fmt(startSec)))"""
t = t.replace(anchor, new_anchor, 1)
print("✓ 重复段自动丢弃")

# ---------- ③ 记录上一段文本（清空时一起复位）----------
anchor2 = "    private val segments = mutableStateListOf<Seg>()"
assert anchor2 in t
t = t.replace(anchor2, anchor2 + """
    /** 上一段转写文本：用于丢弃"与上一段完全相同"的重复/幻觉段 */
    @Volatile private var lastSegmentText = \"\"""", 1)
t = t.replace("""        segments.clear()
        translations.clear()""", """        segments.clear()
        lastSegmentText = ""
        translations.clear()""", 1)
print("✓ lastSegmentText 状态（清空时复位）")

m.write_text(t, encoding="utf-8")

# 自检
depth, ins = 0, False
for ch in t:
    if ch == '"':
        ins = not ins
    if not ins:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
print(f"MainActivity 括号平衡 = {depth}（应为 0）")
for kw in ["targetPeak", "lastSegmentText", "丢弃重复段", "分段音量"]:
    print(f"  {kw}: {t.count(kw)} 处")

# ---------- ④ 版本 ----------
g = R / "android/app/build.gradle.kts"
g.write_text(g.read_text(encoding="utf-8").replace("versionCode = 321", "versionCode = 322").replace("3.2.1", "3.2.2"), encoding="utf-8")
print("版本 -> 3.2.2 / 322 ✓")
