"""3.1.1 收尾：版本号 + 文档（只用单行替换，避免 CRLF 坑）。"""
from pathlib import Path

R = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")

g = R / "android/app/build.gradle.kts"
t = g.read_text(encoding="utf-8")
t = t.replace("versionCode = 310", "versionCode = 311").replace('versionName = "3.1.0"', 'versionName = "3.1.1"')
g.write_text(t, encoding="utf-8")
print("版本 -> 3.1.1 / 311 ✓")

readme = R / "android/README-android.md"
r = readme.read_text(encoding="utf-8")
if "**3.1.1**" not in r:
    entry = """* **3.1.1**：按用户反馈改翻译开关的交互（原话："开关比较奇怪"、"打开后不该把历史的都翻译，说久了会跟不上"）：
  1. **开关位置**：从底部一个孤立的 Switch 挪到转写列表**顶部**，做成与「⇣ 最新 / ⧉ 复制 / 清空」
     同风格的小内联链接（`翻译 开` / `翻译 关`，绿色=开），并且**常显**（列表空着也能先打开）。
  2. **不再翻历史**：打开开关只翻译**之后**新识别出的句子，之前的保持原文。
  3. **积压保护**：待翻译队列最多留 **5 句**，超了丢最旧的，并给那一句标
     「（说得太快，这句没来得及翻）」—— 翻译永远追着最新一句，不会越拖越远。
  4. 少于 2 个有效字符的段（"嗯""好"）不翻译，省时间。

"""
    r = r.replace("* **3.1.0**：", entry + "* **3.1.0**：", 1)
    readme.write_text(r, encoding="utf-8")
    print("README 已加 3.1.1 ✓")

snap = R / "SNAPSHOT-INFO.txt"
s = snap.read_text(encoding="utf-8")
s = s.replace("版本：Android 3.1.0（对应 git 标签 android-v3.1.0）", "版本：Android 3.1.1（对应 git 标签 android-v3.1.1）")
if "本版新增（3.1.1" not in s:
    s = s.replace("本版新增（3.1.0，相对 3.0.1）", """本版新增（3.1.1，相对 3.1.0）
------------------------------
翻译开关挪到转写列表顶部（小内联链接、常显）；打开只翻译之后的句子、不再翻历史；
待翻译队列上限 5 句、超了丢最旧并在界面标注；过短的段不翻译。

上一版新增（3.1.0，相对 3.0.1）""", 1)
    snap.write_text(s, encoding="utf-8")
print("SNAPSHOT-INFO 已更新 ✓")
