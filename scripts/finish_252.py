"""2.5.2：加"prompt 末尾"日志（决定性诊断）+ 版本号/文档。"""
from pathlib import Path

ROOT = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")

g = ROOT / "android/app/build.gradle.kts"
t = g.read_text(encoding="utf-8")
t = t.replace("versionCode = 251", "versionCode = 252").replace('versionName = "2.5.1"', 'versionName = "2.5.2"')
g.write_text(t, encoding="utf-8")
print("版本号 -> 2.5.2 / 252")

readme = ROOT / "android/README-android.md"
r = readme.read_text(encoding="utf-8")
if "**2.5.2**" not in r:
    anchor = "* **2.5.1**："
    entry = """* **2.5.2**：**把"到底喂给模型什么"打出来**（排查"7 个字 17.9 秒"的最后一环）。
  * 实测各段长度：系统提示词 **73 字（≈51 token）**、问答模板固定说明 189 字、你的 OCR 文字 175 字
    → 问答 prompt 合计约 **446 字 ≈ 310 token**（**并不长**，预填充不该是主要瓶颈）。
  * 所以剩下的可能是「首次调用要加载 1.28GB 模型」或「模型仍在推理」。
  * 新增日志：把**实际 prompt 的末尾 80 字**（换行转义）打出来 ——
    末尾是 `assistant\\n<think>\\n\\n</think>\\n\\n` = 思维链已关；裸 `assistant\\n` = 没关。
    这一行可以彻底终结"关没关"的争论（也覆盖了"模板解析失败退回手写 ChatML"的盲点）。

"""
    readme.write_text(r.replace(anchor, entry + anchor, 1), encoding="utf-8")
    print("README 已加 2.5.2")

snap = ROOT / "SNAPSHOT-INFO.txt"
s = snap.read_text(encoding="utf-8")
s = s.replace("版本：Android 2.5.1（对应 git 标签 android-v2.5.1）",
              "版本：Android 2.5.2（对应 git 标签 android-v2.5.2）")
s = s.replace("本版新增（2.5.1，相对 2.5.0）", """本版新增（2.5.2，相对 2.5.1）
------------------------------
新增"prompt 末尾 80 字"日志，用于判定思维链是否真的关闭（覆盖模板解析失败退回 ChatML 的情况）。
实测 prompt 长度：系统提示词 73 字、问答整条约 446 字≈310 token（并不长）。

上一版新增（2.5.1，相对 2.5.0）""", 1)
snap.write_text(s, encoding="utf-8")
print("SNAPSHOT-INFO 已更新")
