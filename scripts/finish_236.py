"""把提示词改成纯文本（不用 Markdown），并加一层思维链兜底说明。"""
import re
from pathlib import Path

ROOT = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
f = ROOT / "android/app/src/main/java/com/localrecord/app/LlmEngine.kt"
t = f.read_text(encoding="utf-8")

# 1) 会议纪要提示词：Markdown 模板 → 纯文本格式
start = t.find("请把上面内容整理成会议纪要。")
end = t.find('""".trimIndent()', start)
assert start != -1 and end != -1, "找不到会议纪要提示词"
new_min = """请把上面内容整理成会议纪要。**只输出纯文本，不要任何 Markdown 标记**
（不要用 #、*、**、|、表格、代码块），严格按下面的格式写（括号里是要求，不要抄进正文）：

会议纪要
一句话概述：（30 字以内说清这次录音讲了什么）

一、重点内容
· （每行一条，以「· 」开头，一条一句话；数字、金额、比例、时间点必须保留；同主题合并，不要流水账）

二、待办事项
· 事项 — 负责人 — 时间要求
（只写转写里明确提到的；没提到的负责人或时间写"未提及"，不要编造；没有就写"本次未提及待办事项"）

三、风险与问题
· （阻塞、风险、线上问题、依赖，写清影响与状态）

四、决议与结论
· （只写已明确拍板的决定；没有就写"本次未形成明确决议"）

只使用转写中的信息，绝对不要编造任何人名、数字或结论。全文用中文。
"""
t = t[:start] + new_min + t[end:]

# 2) 问答提示词：加纯文本要求
old_ask = '请只基于上面的转写内容回答；如果转写里没有相关信息，请明确说明"转写中没有提到"。'
assert old_ask in t, "找不到问答提示词"
t = t.replace(old_ask, old_ask + """
              回答用**纯文本**（不要 Markdown 标记），条理清楚、直接给结论，别啰嗦。""", 1)

f.write_text(t, encoding="utf-8")
print("LlmEngine 提示词已改为纯文本 ✓")

# 3) 版本号
g = ROOT / "android/app/build.gradle.kts"
gt = g.read_text(encoding="utf-8")
gt = gt.replace("versionCode = 235", "versionCode = 236").replace('versionName = "2.3.5"', 'versionName = "2.3.6"')
g.write_text(gt, encoding="utf-8")
print("版本号 -> 2.3.6 / 236")

# 4) README
readme = ROOT / "android/README-android.md"
r = readme.read_text(encoding="utf-8")
if "**2.3.6**" not in r:
    anchor = "* **2.3.5**："
    entry = """* **2.3.6**：**大模型结果改为弹窗显示 + 纯文本输出**（用户需求）：
  * 思维链**确认是关的**：JNI（`llm_jni.cpp`）在套用对话模板时，若模板含 `<think>` 就补一个
    **空的 `<think></think>`**，模型直接答题；会议纪要与问答走的是同一个 JNI，所以两条路都关着。
    本轮在 Kotlin 层再加一层保险：`stripThinking()` 会把漏出的 ` thinking…` 剥掉并打日志。
  * 生成结果（会议纪要 / AI 回答）**弹窗显示**（可滚动、字体更大更易读，带「⧉ 复制」和「关闭」），
    不再混在转写列表里；关闭后可在「生成会议纪要」那一行点「查看纪要 / 查看回答」再看。
  * **不用 Markdown**：提示词改为「只输出纯文本，不要 # * ** | 表格」，并加了 `toPlainText()` 兜底
    清洗（去 #、**、表格分隔行，表格行转成「a — b — c」，`- ` 列表转「· 」）——弹窗里不做 Markdown
    渲染，纯文本更整齐。

"""
    assert anchor in r
    readme.write_text(r.replace(anchor, entry + anchor, 1), encoding="utf-8")
    print("README 已加 2.3.6")

# 5) 快照说明
snap = ROOT / "SNAPSHOT-INFO.txt"
s = snap.read_text(encoding="utf-8")
s = s.replace("版本：Android 2.3.5（对应 git 标签 android-v2.3.5）",
              "版本：Android 2.3.6（对应 git 标签 android-v2.3.6）")
s = s.replace("本版新增（2.3.5，相对 2.3.4）", """本版新增（2.3.6，相对 2.3.5）
------------------------------
1. 大模型结果改为弹窗显示（可滚动、可复制），不再混在转写列表里；关闭后可点「查看纪要/查看回答」再看。
2. 提示词改为纯文本输出（不要 Markdown），并加 toPlainText() 兜底清洗，弹窗排版更整齐。
3. 思维链：JNI 侧已关闭（补空 think 块）；本轮在 Kotlin 侧再加 stripThinking() 保险。

上一版新增（2.3.5，相对 2.3.4）""", 1)
snap.write_text(s, encoding="utf-8")
print("SNAPSHOT-INFO 已更新")
