"""2.3.9：提示词层面直接禁止推理 + 降低问答输出上限 + 过程可观测。"""
from pathlib import Path

ROOT = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
f = ROOT / "android/app/src/main/java/com/localrecord/app/LlmEngine.kt"
t = f.read_text(encoding="utf-8")

# 1) 系统提示词：明确禁止输出思考过程
old_sys = 'val MINUTES_SYSTEM = """'
i = t.find(old_sys)
assert i != -1
j = t.find('"""', i + len(old_sys))
sys_body = t[i + len(old_sys):j]
if "不要输出" not in sys_body:
    new_sys = (sys_body.rstrip() +
               "\n\n重要：直接输出结果。**不要输出任何思考过程、推理步骤、内心独白**，"
               "也不要写 [Start thinking]、[End thinking]、<think> 这类标记。")
    t = t[:i + len(old_sys)] + new_sys + t[j:]

# 2) 问答提示词：在最后（离生成最近）再强调一次直接回答
old_tail = '回答用**纯文本**（不要 Markdown 标记），条理清楚、直接给结论，别啰嗦。'
assert old_tail in t
t = t.replace(old_tail,
              '回答用**纯文本**（不要 Markdown 标记）。\n'
              '现在**直接给出答案**，不要任何思考过程、不要推理步骤、不要输出 [Start thinking] 之类标记。', 1)

# 3) 问答输出上限 400 → 200（20~50 字的答案用不了 400 token）
t = t.replace("fun ask(transcript: String, question: String, maxTokens: Int = 400): String =",
              "fun ask(transcript: String, question: String, maxTokens: Int = 200): String =")

f.write_text(t, encoding="utf-8")
print("LlmEngine 提示词已加"禁止推理"要求，问答上限 200 token ✓")

# 4) 版本号
g = ROOT / "android/app/build.gradle.kts"
gt = g.read_text(encoding="utf-8")
gt = gt.replace("versionCode = 238", "versionCode = 239").replace('versionName = "2.3.8"', 'versionName = "2.3.9"')
g.write_text(gt, encoding="utf-8")
print("版本号 -> 2.3.9 / 239")

# 5) README
readme = ROOT / "android/README-android.md"
r = readme.read_text(encoding="utf-8")
if "**2.3.9**" not in r:
    anchor = "* **2.3.8**："
    entry = """* **2.3.9**：**继续治"20 多字要 32 秒"**（2.3.8 的标记修复不够）：
  * 挖出 GGUF 里的对话模板原文后确认：模板里控制思考的是 `enable_thinking`，
    `false` 时插入 `<think>\\n\\n</think>\\n\\n` —— **app 发的 prompt 已经完全等价于官方关闭写法**，
    但 MiniCPM5 **仍然自顾自地推理**（它会自己写出 `[Start thinking]`，这个标记不在模板里，是模型学的）。
  * 所以改成**提示词层面直接禁止**：system 里明确"不要输出任何思考过程、推理步骤，不要写
    [Start thinking]/<think> 这类标记"，并在问答提示词**最后**（离生成最近处）再强调一次。
  * 问答输出上限 400 → **200 token**；JNI 现在打印
    `生成完成：N token / X.X 秒 / Y.Y token每秒`，**一眼看出是模型在推理还是机器本身慢**。
  * 判断方法：token 数 ≈30 却要 30 秒 = 机器慢（正常）；token 数 150+ = 模型在推理（本版就是要治这个）。

"""
    assert anchor in r
    readme.write_text(r.replace(anchor, entry + anchor, 1), encoding="utf-8")
    print("README 已加 2.3.9")

snap = ROOT / "SNAPSHOT-INFO.txt"
s = snap.read_text(encoding="utf-8")
s = s.replace("版本：Android 2.3.8（对应 git 标签 android-v2.3.8）",
              "版本：Android 2.3.9（对应 git 标签 android-v2.3.9）")
s = s.replace("本版新增（2.3.8，相对 2.3.7）", """本版新增（2.3.9，相对 2.3.8）
------------------------------
1. 提示词层面直接禁止推理（system + 问答末尾双重强调），因为模板层面的 enable_thinking=false
   对 MiniCPM5 不管用（它会自己写 [Start thinking]）。
2. 问答输出上限 400 → 200 token。
3. JNI 打印「生成完成：N token / X.X 秒 / Y.Y token每秒」，用来判断"慢"到底是推理太多还是机器慢。

上一版新增（2.3.8，相对 2.3.7）""", 1)
snap.write_text(s, encoding="utf-8")
print("SNAPSHOT-INFO 已更新")
