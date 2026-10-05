"""2.4.0 收尾：正确的版本号 + 上一版没跑到的提示词强化。"""
from pathlib import Path

ROOT = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")

# 1) 版本号（当前是 238 / 2.3.8，直接改成 240 / 2.4.0）
g = ROOT / "android/app/build.gradle.kts"
t = g.read_text(encoding="utf-8")
t = t.replace("versionCode = 238", "versionCode = 240")
t = t.replace('versionName = "2.3.8"', 'versionName = "2.4.0"')
t = t.replace("versionCode = 239", "versionCode = 240").replace('versionName = "2.3.9"', 'versionName = "2.4.0"')
g.write_text(t, encoding="utf-8")
for line in t.splitlines():
    if "version" in line and ("Code" in line or "Name" in line):
        print("  " + line.strip())

# 2) 提示词强化（2.3.9 的内容，之前那次构建被中断没写进去）
f = ROOT / "android/app/src/main/java/com/localrecord/app/LlmEngine.kt"
kt = f.read_text(encoding="utf-8")
old_sys = 'val MINUTES_SYSTEM = """'
i = kt.find(old_sys)
j = kt.find('"""', i + len(old_sys))
body = kt[i + len(old_sys):j]
if "不要输出任何思考过程" not in body:
    kt = kt[:i + len(old_sys)] + body.rstrip() + \
        "\n\n重要：直接输出结果，不要输出任何思考过程、推理步骤或内心独白。" + kt[j:]
    print("  系统提示词已加「不要推理」✓")
tail = '回答用**纯文本**（不要 Markdown 标记），条理清楚、直接给结论，别啰嗦。'
if tail in kt:
    kt = kt.replace(tail, '回答用**纯文本**（不要 Markdown 标记）。\n'
                          '现在直接给出答案，不要思考过程、不要推理步骤。', 1)
    print("  问答提示词已强化 ✓")
if "maxTokens: Int = 400" in kt:
    kt = kt.replace("fun ask(transcript: String, question: String, maxTokens: Int = 400): String =",
                    "fun ask(transcript: String, question: String, maxTokens: Int = 300): String =")
    print("  问答上限 400 → 300 ✓")
f.write_text(kt, encoding="utf-8")
print("LlmEngine 更新完成")
