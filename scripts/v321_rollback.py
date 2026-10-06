"""3.2.1：回退到 3.1.7 的行为（用户要求），只保留两处修复。

用户原话：回退到 3.1.7，然后提示词加固一下就好了。
（3.1.8/3.1.9 我改的提示词翻车了、3.2.0 的"翻译优先级"改动把翻译弄没了。）

保留：
  ① 提示词加固：明确"不许中英混用" + 短词走词典式提示（无例子可抄）+ 串扰兜底；
  ② KV 缓存清理：这是"每句都翻成同一个词"的真正修复，不保留的话多句会互相污染。
回退：
  3.2.0 的"录音期间不加载/预热/补翻"那一整套流程（用户反馈：这样反而完全不能翻了）。
"""
import subprocess
from pathlib import Path

R = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
APP = R / "android/app/src/main/java/com/localrecord/app"

# ---------- 1) 三个文件回到 3.1.7 ----------
files = [
    "android/app/src/main/java/com/localrecord/app/MainActivity.kt",
    "android/app/src/main/java/com/localrecord/app/LlmEngine.kt",
    "android/app/src/main/cpp/llm_jni.cpp",
]
subprocess.run(["git", "checkout", "v3.1.7", "--", *files], cwd=R, check=True)
print("已把 MainActivity / LlmEngine / llm_jni.cpp 回退到 v3.1.7 ✓")

# ---------- 2) 补回：KV 缓存清理 ----------
cpp = R / files[2]
c = cpp.read_text(encoding="utf-8")
if "llama_memory_clear" not in c:
    anchor = '    const long long t_gen = now_ms();'
    assert anchor in c, "找不到 generate 开始处"
    c = c.replace(anchor, """    // 每次生成前清空上下文：不清的话本次 prompt 会接在上一次的问+答后面，
    // 模型会顺着上次的答案继续编（表现：多句都被翻成同一个词）
    llama_memory_clear(llama_get_memory(h->ctx), true);
    LOGI("已清空上下文（KV 缓存），本次为独立的一次生成");

""" + anchor, 1)
    cpp.write_text(c, encoding="utf-8")
    print("  ✓ llm_jni.cpp：已补回 KV 清理")
else:
    print("  · llm_jni.cpp 已有 KV 清理")

# ---------- 3) 补回：提示词加固 ----------
le = APP / "LlmEngine.kt"
t = le.read_text(encoding="utf-8")
start = t.find("private const val TRANSLATE_TO_EN")
end = t.find("fun minutesPrompt", start)
assert start != -1 and end != -1, "找不到提示词段"
t = t[:start] + '''private const val TRANSLATE_TO_EN =
    "You are a translator. Translate the user's Chinese into natural English. " +
        "Output ONLY the English translation - no Chinese characters, no explanation, no quotes. " +
        "Never keep any Chinese character in your answer."

private const val TRANSLATE_TO_ZH =
    "You are a translator. Translate the user's English into Simplified Chinese. " +
        "Output ONLY the Chinese translation - no English words, no explanation, no quotes. " +
        "Never keep any English word in your answer."

/** 不带例子（短词最容易串扰，给它专用的"词典式"提示，无例子可抄） */
private const val DICT_EN =
    "You are a Chinese-English dictionary. The user sends a Chinese word. " +
        "Reply with its English meaning only: one word, no Chinese, no explanation, no quotes."

private const val DICT_ZH =
    "You are an English-Chinese dictionary. The user sends an English word. " +
        "Reply with its Chinese meaning only, no English, no explanation, no quotes."

/** 兜底：直译式提示 */
private const val DIRECT_EN =
    "Translate the user's Chinese into English. Reply with the English translation only."
private const val DIRECT_ZH =
    "Translate the user's English into Simplified Chinese. Reply with the Chinese translation only."

''' + t[end:]

# translate()：短词走词典式 + 串扰兜底（多次不同系统提示，用户消息永远是纯原文）
start = t.find("    fun translate(")
end = t.find("    fun ask(", start)
assert start != -1 and end != -1, "找不到 translate()"
t = t[:start] + '''    /**
     * 逐句翻译。方向由代码判定（含汉字→英文，否则→中文）。
     *
     * 加固点（都来自实测）：
     *  ① 提示词明确"不许保留另一种语言"，缓解"头盔 → head 盔"这类半翻半留；
     *  ② 很短的词改用**词典式**提示（不给例子，避免小模型把例子当万能答案）；
     *  ③ 发现串扰就换更直接的提示重试；**指令只放系统提示**，用户消息永远是纯原文
     *     （曾经把指令拼进用户消息，结果被模型抄进译文）。
     */
    fun translate(text: String, maxTokens: Int = 220): String {
        var src = text.trim()
        if (src.isEmpty()) return ""
        val toEnglish = looksChinese(src)
        if (src.length <= 6) src = src.trimEnd('。', '，', '！', '？', '.', ',', '!', '?', '、', ';', '；')
        val short = src.length <= 6

        var out = generate(
            when {
                short && toEnglish -> DICT_EN
                short -> DICT_ZH
                toEnglish -> TRANSLATE_TO_EN
                else -> TRANSLATE_TO_ZH
            },
            src, maxTokens
        ).trim()

        if (mixedScript(out, toEnglish)) {
            Log.i(TAG, "翻译出现串扰，换直译式提示重试：${out.take(30)}")
            out = generate(if (toEnglish) DIRECT_EN else DIRECT_ZH, src, maxTokens).trim()
        }
        if (mixedScript(out, toEnglish)) {
            Log.i(TAG, "仍串扰，再换不带例子的提示：${out.take(30)}")
            out = generate(
                if (toEnglish) "Translate the user's Chinese into English. Output only the English translation."
                else "Translate the user's English into Simplified Chinese. Output only the Chinese translation.",
                src, maxTokens
            ).trim()
        }
        if (mixedScript(out, toEnglish)) Log.w(TAG, "多次尝试仍串扰，保留原样：$out")
        return out
    }

    /** 目标英文却含汉字 / 目标中文却没有汉字 → 串扰 */
    private fun mixedScript(out: String, toEnglish: Boolean): Boolean {
        if (out.isBlank()) return false
        return if (toEnglish) looksChinese(out) else !looksChinese(out)
    }

''' + t[end:]
le.write_text(t, encoding="utf-8")
print("  ✓ LlmEngine：已补回提示词加固（含短词词典式 + 串扰兜底）")

# ---------- 4) 版本 ----------
g = R / "android/app/build.gradle.kts"
gt = g.read_text(encoding="utf-8")
gt = gt.replace("versionCode = 320", "versionCode = 321").replace("3.2.0", "3.2.1")
g.write_text(gt, encoding="utf-8")
print("版本 -> 3.2.1 / 321 ✓")

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
print(f"LlmEngine 括号平衡 = {depth}（应为 0）")
