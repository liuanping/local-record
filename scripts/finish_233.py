"""2.3.3：把"过度过滤"改掉 —— 统一用 TextFilter，删掉旧的激进规则。"""
import re
from pathlib import Path

ROOT = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
APP = ROOT / "android/app/src/main/java/com/localrecord/app"
TEST = ROOT / "android/app/src/test/java/com/localrecord/app"

# 1) AsrEngine.transcribe 改用 TextFilter
p = APP / "AsrEngine.kt"
t = p.read_text(encoding="utf-8")
old = "if (text.isNotEmpty() && !isMeaningless(text) && !looksLikeHallucination(text)) {"
new = "if (text.isNotEmpty() && !TextFilter.shouldDrop(text, lowSnr = false)) {"
assert old in t
t = t.replace(old, new)

# 删掉旧的激进判断函数（连同注释）
pattern = re.compile(
    r"\n    /\*\*[^/]*?\*/\n    fun isMeaningless\(text: String\): Boolean \{.*?\n    \}\n"
    r"\n    /\*\*[^/]*?\*/\n    fun looksLikeHallucination\(text: String, runLen: Int = 4\): Boolean \{.*?\n    \}\n",
    re.S,
)
t, n1 = pattern.subn("\n", t)
print(f"AsrEngine: 删除 isMeaningless/looksLikeHallucination {n1} 组")
# FILLER 常量已无人使用
t2, n2 = re.subn(r"\n *private val FILLER = \"[^\"]*\"\.toSet\(\)\n", "\n", t)
print(f"AsrEngine: 删除 FILLER {n2} 处")
p.write_text(t2, encoding="utf-8")

# 2) AudioQuality 删掉 isNoisePhrase 与 NOISE_PHRASES
q = APP / "AudioQuality.kt"
qt = q.read_text(encoding="utf-8")
pat2 = re.compile(
    r"\n    /\*\*\n     \* 经典\"噪声幻觉\"文本.*?\n     \*/\n    private val NOISE_PHRASES = listOf\(.*?\n    \)\n", re.S
)
qt, n3 = pat2.subn("\n", qt)
print(f"AudioQuality: 删除 NOISE_PHRASES {n3} 处")
pat3 = re.compile(r"\n    /\*\* 低信噪比段上的\"噪声幻觉文本\"黑名单 \*/\n    fun isNoisePhrase\(text: String\): Boolean \{.*?\n    \}\n", re.S)
qt, n4 = pat3.subn("\n", qt)
print(f"AudioQuality: 删除 isNoisePhrase {n4} 处")
q.write_text(qt, encoding="utf-8")

# 3) 测试里去掉对 isNoisePhrase 的断言
tp = TEST / "AudioQualityTest.kt"
tt = tp.read_text(encoding="utf-8")
tt = re.sub(r"\n *assertTrue\(AudioQuality\.isNoisePhrase\([^\n]*\n", "\n", tt)
tt = re.sub(r"\n *assertFalse\(AudioQuality\.isNoisePhrase\([^\n]*\n", "\n", tt)
# 该测试函数若已空，删掉整个函数
tt = re.sub(
    r"\n    @Test\n    fun noisePhraseBlocklist\(\) \{\n( *\n)*    \}\n",
    "\n",
    tt,
)
tp.write_text(tt, encoding="utf-8")
print("AudioQualityTest: 已移除 isNoisePhrase 相关断言")

# 4) 版本号
g = ROOT / "android/app/build.gradle.kts"
gt = g.read_text(encoding="utf-8")
gt = gt.replace("versionCode = 232", "versionCode = 233").replace('versionName = "2.3.2"', 'versionName = "2.3.3"')
g.write_text(gt, encoding="utf-8")
print("版本号 → 2.3.3 / 233 ✓")

# 5) README
readme = ROOT / "android/README-android.md"
r = readme.read_text(encoding="utf-8")
if "**2.3.3**" not in r:
    anchor = "* **2.3.2**："
    entry = """* **2.3.3**：**修"有些话不展示"**（用户反馈：说"哈哈哈"这类看不到）。
  原因是我之前的"防噪声幻觉"规则太激进：`isMeaningless` 把"3 个字以内全是语气词"一律丢掉
  （"哈哈哈""嗯嗯"中招），`looksLikeHallucination` 把"连续 4 个相同字"一律当幻觉（"哈哈哈哈"中招）。
  **真实说的话凭什么不给显示**。现在规则改成：
  * 只有**纯标点/空白**才一定丢；
  * "合成幻觉文本"（谢谢观看/请不吝点赞/下期再见…）与"重复字"规则**只在低信噪比段**才用，
    正常说话（信噪比 ≥10dB，即 Silero 切出来的绝大多数段）一律原样展示；
  * 黑名单从"点赞/订阅/转发/字幕"这类常见词改成**完整短语**（避免误杀"转发给我"）。
  噪声本身已在 VAD 层挡住（Silero，12 秒纯噪声 0 段），文字层只是兜底。
  新增 `TextFilter`（纯 Kotlin）+ 5 个 JVM 单元测试，专门锁住"哈哈哈/嗯/啊必须展示"。

"""
    assert anchor in r
    readme.write_text(r.replace(anchor, entry + anchor, 1), encoding="utf-8")
    print("README 已加 2.3.3 ✓")

# 6) 快照说明
snap = ROOT / "SNAPSHOT-INFO.txt"
s = snap.read_text(encoding="utf-8")
s = s.replace("版本：Android 2.3.2（对应 git 标签 android-v2.3.2）",
              "版本：Android 2.3.3（对应 git 标签 android-v2.3.3）")
s = s.replace("本版新增（2.3.2，相对 2.3.1）", """本版新增（2.3.3，相对 2.3.2）
------------------------------
修「有些话不展示」：以前"3 字以内全是语气词"（哈哈哈/嗯嗯）和"连续 4 个相同字"（哈哈哈哈）
被当作无效丢掉。现在真实说话一律展示，"噪声幻觉"规则只在低信噪比段生效；黑名单改为完整短语。
新增 TextFilter + 单元测试锁住该行为。

上一版新增（2.3.2，相对 2.3.1）""", 1)
snap.write_text(s, encoding="utf-8")
print("SNAPSHOT-INFO 已更新 ✓")
