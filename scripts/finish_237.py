"""2.3.7：文档 + 版本号。"""
from pathlib import Path

ROOT = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")

g = ROOT / "android/app/build.gradle.kts"
t = g.read_text(encoding="utf-8")
t = t.replace("versionCode = 236", "versionCode = 237").replace('versionName = "2.3.6"', 'versionName = "2.3.7"')
g.write_text(t, encoding="utf-8")
print("版本号 -> 2.3.7 / 237")

readme = ROOT / "android/README-android.md"
r = readme.read_text(encoding="utf-8")
if "**2.3.7**" not in r:
    anchor = "* **2.3.6**："
    entry = """* **2.3.7**：**结果只在弹窗显示 + 新录音/新图片自动清空**（用户要求）：
  * 既然结果用弹窗展示，转写列表里就不再重复显示「会议纪要 / AI 回答」内嵌块
    （文档问答页内嵌的「AI 回答」块同样移除），列表只放转写本身。
  * **点「录」开始新录音时自动清空**上一次的转写与生成内容（含弹窗），避免新旧混在一起；
    文档问答**选新图时**同样立刻清空上一张的识别文字与回答。
  * 吸顶行的「清空」链接也会一并关掉弹窗。
  * 实证日志：`加入第 1..9 段` → 点「录」→ `清空转写（新开录音），之前 9 段`。

"""
    assert anchor in r
    readme.write_text(r.replace(anchor, entry + anchor, 1), encoding="utf-8")
    print("README 已加 2.3.7")

snap = ROOT / "SNAPSHOT-INFO.txt"
s = snap.read_text(encoding="utf-8")
s = s.replace("版本：Android 2.3.6（对应 git 标签 android-v2.3.6）",
              "版本：Android 2.3.7（对应 git 标签 android-v2.3.7）")
s = s.replace("本版新增（2.3.6，相对 2.3.5）", """本版新增（2.3.7，相对 2.3.6）
------------------------------
1. 生成结果只在弹窗显示：列表里不再内嵌「会议纪要 / AI 回答」块（文档问答页同理）。
2. 点「录」开始新录音时自动清空上一次的转写与生成内容；文档问答选新图时清空上一张的结果。
3. 吸顶行的「清空」也会关掉弹窗。

上一版新增（2.3.6，相对 2.3.5）""", 1)
snap.write_text(s, encoding="utf-8")
print("SNAPSHOT-INFO 已更新")
