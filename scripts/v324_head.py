"""3.2.4：修头部截断（真正落地）+ 让分段日志可见。

发现的问题：
1. "分段：X 起 +Y（补白 Z）" 那条日志用的是 Log.d —— 默认被 logcat 过滤，等于没有，
   所以一直看不到补白到底生效没有。改成 Log.i。
2. 段前补白受 lastEnd 限制：如果上一段刚结束不久，补白会很小甚至为 0 →
   识别器没有引导音频，开头第一个字就容易被吞。改成：
   **保底再补 0.35 秒静音**（真实音频能取多少取多少，不够的用静音补齐）。
3. 预卷 0.7 → 1.0 秒（麦克风小时 VAD 判定更晚）。
"""
import re
import subprocess
from pathlib import Path

R = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
vad = R / "android/app/src/main/java/com/localrecord/app/SileroVad.kt"

# 确认文件是 3.1.7 血统（应该在）
t = vad.read_text(encoding="utf-8")
t = t.replace("private const val PREROLL_SEC = 0.7f", "private const val PREROLL_SEC = 1.0f")
vad.write_text(t, encoding="utf-8")
print("预卷 0.7s → 1.0s ✓")

t = vad.read_text(encoding="utf-8")

# ① 分段日志改成 Log.i（原来 Log.d 被默认过滤，等于没有）
old_log = """                    Log.d(
                        TAG,"""
if old_log in t:
    t = t.replace(old_log, """                    Log.i(
                        TAG,""", 1)
    print("分段日志 Log.d → Log.i ✓")

# ② 保底引导静音：真实补白不足 MIN_LEAD 时，用静音补齐到 MIN_LEAD
old_pad = """                val from = maxOf(lastEnd, segStart - ringSize)
                val pad = if (segStart > from) ringSlice(from, segStart) else FloatArray(0)
                val out = if (pad.isEmpty()) raw else FloatArray(pad.size + raw.size).also {
                    System.arraycopy(pad, 0, it, 0, pad.size)
                    System.arraycopy(raw, 0, it, pad.size, raw.size)
                }"""
assert old_pad in t, "找不到补白那段"
new_pad = """                // 段前补白：优先取**真实音频**（不重复上一段），再保底补静音。
                // 保底很重要：识别器需要一点"引导音频"，否则开头第一个字常被吞掉
                // （用户反馈的"截掉头"）。真实音频不够时用静音补齐，绝不重复上一段内容。
                val from = maxOf(lastEnd, segStart - ringSize)
                val realPad = if (segStart > from) ringSlice(from, segStart) else FloatArray(0)
                val minLead = (SAMPLE_RATE * MIN_LEAD_SEC).toInt()
                val silence = if (realPad.size < minLead) FloatArray(minLead - realPad.size) else FloatArray(0)
                val pad = if (silence.isEmpty()) realPad else FloatArray(silence.size + realPad.size).also {
                    System.arraycopy(silence, 0, it, 0, silence.size)      // 静音在前
                    System.arraycopy(realPad, 0, it, silence.size, realPad.size)
                }
                val out = if (pad.isEmpty()) raw else FloatArray(pad.size + raw.size).also {
                    System.arraycopy(pad, 0, it, 0, pad.size)
                    System.arraycopy(raw, 0, it, pad.size, raw.size)
                }"""
t = t.replace(old_pad, new_pad, 1)
print("保底引导静音（%.2fs）已加入 ✓" % 0.35)

# ③ 新常量
t = t.replace("private const val PREROLL_SEC = 1.0f",
              """private const val PREROLL_SEC = 1.0f

    /** 保底引导静音：识别器需要一点前导音频，否则开头第一个字容易被吞 */
    private const val MIN_LEAD_SEC = 0.35f""", 1)

# ④ 日志里把"补白"拆成"真实补白 + 静音"，便于排查
t = t.replace('''                        "分段：%.2fs 起 +%.2fs（补白 %.2fs，人声 %d 窗 / %.0f%%）".format(
                            from.toFloat() / SAMPLE_RATE,
                            out.size.toFloat() / SAMPLE_RATE,
                            pad.size.toFloat() / SAMPLE_RATE,''',
'''                        "分段：%.2fs 起 +%.2fs（真实补白 %.2fs + 静音 %.2fs，人声 %d 窗 / %.0f%%）".format(
                            from.toFloat() / SAMPLE_RATE,
                            out.size.toFloat() / SAMPLE_RATE,
                            realPad.size.toFloat() / SAMPLE_RATE,
                            silence.size.toFloat() / SAMPLE_RATE,''', 1)

vad.write_text(t, encoding="utf-8")

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
print(f"SileroVad 括号平衡 = {depth}（应为 0）")
for kw in ["MIN_LEAD_SEC", "realPad", "Log.i(", "PREROLL_SEC = 1.0f"]:
    print(f"  {kw}: {t.count(kw)} 处")

# 版本
g = R / "android/app/build.gradle.kts"
gt = g.read_text(encoding="utf-8")
gt = re.sub(r"versionCode = \d+", "versionCode = 324", gt, count=1)
gt = re.sub(r'versionName = "[^"]*"', 'versionName = "3.2.4"', gt, count=1)
g.write_text(gt, encoding="utf-8")
print("版本 -> 3.2.4 / 324 ✓")
