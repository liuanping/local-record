"""3.0.1：① 底部加项目介绍 ② 新转写也清空旧内容 ③ 修 OCR 英文空格丢失。"""
import re
from pathlib import Path

ROOT = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
APP = ROOT / "android/app/src/main/java/com/localrecord/app"

# ---------- ③ OCR 空格：字典里的空白条目当成空格 ----------
ocr = APP / "OcrEngine.kt"
t = ocr.read_text(encoding="utf-8")
old = "            dict = try {"
i = t.find(old)
assert i != -1
# 找到 dict 赋值那一段，改为把空白行映射成空格
seg_end = t.find("        }", i)
seg = t[i:seg_end]
print("原字典加载片段：\n" + seg[:400])
new_seg = """            dict = try {
                val raw = context.assets.open(DICT_ASSET).bufferedReader(Charsets.UTF_8)
                    .readLines()
                // PP-OCR 的字典里，**空格字符在文件里是一行空白**；直接 readLines 会得到空字符串，
                // 于是 CTC 解码到它时 append("") = 什么都没加 → 英文单词全连在一起。
                // 这里把"空白条目"统一当作一个空格（字典里这类条目本身就是各种空格字符）。
                raw.map { if (it.isBlank()) " " else it }
            } catch"""
t = t[:i] + new_seg + t[seg_end + len("            "):]
t = t.replace("""                Log.w(TAG, "字典读取失败：${e.message}")
                emptyList()
            }""", """                Log.w(TAG, "字典读取失败：${e.message}")
                emptyList()
            }""")
ocr.write_text(t, encoding="utf-8")
print("\nOcrEngine：字典空白条目 → 空格 ✓")

# ---------- ② 新转写（含导入音频）也清空上一次内容 ----------
m = APP / "MainActivity.kt"
mt = m.read_text(encoding="utf-8")
anchor = "    private fun transcribe(f: File) {"
assert anchor in mt
mt = mt.replace(anchor, """    private fun transcribe(f: File) {
        // 新做一次识别：先清掉上一次的转写内容，避免新旧混在一起（和"新录音清空"保持一致）
        clearSegments("新转写")
""", 1)
print("MainActivity：转写前清空旧内容 ✓")

# ---------- ① 底部：项目介绍 + 开源说明（约 50 字）----------
old_row = """            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                // 降噪开关：开启后重挂系统降噪/回声消除（有些手机会把声音压得很小，所以默认关）
                OutlinedButton("""
assert old_row in mt
mt = mt.replace(old_row, """            Row(verticalAlignment = Alignment.CenterVertically) {
                // 降噪开关：开启后重挂系统降噪/回声消除（有些手机会把声音压得很小，所以默认关）
                OutlinedButton(""", 1)

# 把这一行的收尾补上介绍文字（找到该按钮之后的 })
old_tail = """                ) { Text(if (enhanceOn) "降噪 开" else "降噪 关", fontSize = 11.sp) }
            }"""
assert old_tail in mt
mt = mt.replace(old_tail, """                ) { Text(if (enhanceOn) "降噪 开" else "降噪 关", fontSize = 11.sp) }
                Spacer(Modifier.width(10.dp))
                Text(
                    "本地录音：录音转写与图片识别全部在手机本地完成，不联网、不上传任何内容。" +
                        "代码完全开源，安全放心。",
                    color = Color(0xFF6B7686), fontSize = 9.sp, maxLines = 3
                )
            }""", 1)
print("MainActivity：底部加入项目介绍与开源说明 ✓")

m.write_text(mt, encoding="utf-8")

# ---------- 版本号 + 文档 ----------
g = ROOT / "android/app/build.gradle.kts"
gt = g.read_text(encoding="utf-8")
gt = gt.replace("versionCode = 300", "versionCode = 301").replace('versionName = "3.0.0"', 'versionName = "3.0.1"')
g.write_text(gt, encoding="utf-8")

readme = ROOT / "android/README-android.md"
r = readme.read_text(encoding="utf-8")
if "**3.0.1**" not in r:
    a = "* **3.0.0**："
    entry = """* **3.0.1**：三处小改进（用户反馈）：
  1. 底部不再只放一个孤零零的「降噪」按钮，旁边补了一句项目介绍（约 50 字）：
     「本地录音：录音转写与图片识别全部在手机本地完成，不联网、不上传任何内容。代码完全开源，安全放心。」
  2. **新做一次转写（含导入音频后自动转写）也会先清空**上一次的转写内容，和"新录音清空"保持一致。
  3. **修 OCR 英文单词连在一起**：PP-OCR 的字典里，空格字符在文件中是**一行空白**，
     `readLines()` 会读成空字符串，CTC 解码到它时等于什么都没加 → 英文单词全部粘连。
     现在把字典里的空白条目统一当作一个空格（这类条目本身就是各种空格字符）。

"""
    readme.write_text(r.replace(a, entry + a, 1), encoding="utf-8")
    print("README 已加 3.0.1")

snap = ROOT / "SNAPSHOT-INFO.txt"
s = snap.read_text(encoding="utf-8")
s = s.replace("版本：Android 3.0.0（对应 git 标签 android-v3.0.0）",
              "版本：Android 3.0.1（对应 git 标签 android-v3.0.1）")
s = s.replace("本版新增（3.0.0，相对 2.5.2）", """本版新增（3.0.1，相对 3.0.0）
------------------------------
1. 底部加项目介绍与开源说明（约 50 字），不再只放一个降噪按钮。
2. 新转写（含导入音频自动转写）前先清空上一次内容。
3. 修 OCR 英文单词粘连：字典里的空白条目（空格字符）现在被正确当作空格。

上一版新增（3.0.0，相对 2.5.2）""", 1)
snap.write_text(s, encoding="utf-8")
print("SNAPSHOT-INFO 已更新")
