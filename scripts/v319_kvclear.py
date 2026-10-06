"""3.1.9 关键修复：每次生成前清空 KV 缓存（这才是"每句都翻成 helmet"的真正原因）。

发现：llm_jni.cpp 从头到尾没有清上下文 —— 每次 translate() 都在**接着上一次的上下文**继续，
于是第一句答了 helmet，后面几句全被带着继续说 helmet（用户真机截图正是这个现象），
而且同一个词越翻越乱。修复：generate 开始时调 llama_memory_clear。

同时把提示词改回**已验证好用**的简单版（单例子单行），短词仍走词典式提示。
"""
from pathlib import Path

R = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
CPP = R / "android/app/src/main/cpp/llm_jni.cpp"
APP = R / "android/app/src/main/java/com/localrecord/app"

# ---------- 1) JNI：每次生成前清空上下文 ----------
c = CPP.read_text(encoding="utf-8")
anchor = "    const long long t_gen = now_ms();      // 只统计\"生成\"耗时（预填充算在 prompt 里）"
if "llama_memory_clear" not in c:
    assert anchor in c, "找不到 generate 开始处"
    c = c.replace(anchor, """    // ★ 关键：每次生成前**清空上下文**。
    //   不清的话，本次 prompt 会接在上一次的 prompt+回答后面，模型会顺着上一次的答案继续编
    //   —— 表现就是"每句都翻成同一个词"（用户真机实测：三段转写全被翻成 helmet）。
    llama_memory_clear(llama_get_memory(h->ctx), true);
    LOGI("已清空上下文（KV 缓存），本次为独立的一次生成");

""" + anchor, 1)
    CPP.write_text(c, encoding="utf-8")
    print("llm_jni.cpp：生成前已加入 llama_memory_clear ✓")
else:
    print("llm_jni.cpp 已有清理逻辑")

# ---------- 2) 提示词改回简单版（单例子、单行字符串）----------
le = APP / "LlmEngine.kt"
t = le.read_text(encoding="utf-8")
start = t.find("private const val TRANSLATE_TO_EN")
end = t.find("fun minutesPrompt", start)
assert start != -1 and end != -1
t = t[:start] + '''private const val TRANSLATE_TO_EN =
    "You are a translator. Translate the user's Chinese into natural English. " +
        "Output ONLY the English translation - no Chinese, no explanation, no quotes. " +
        "Example: 今天下雨了 -> It is raining today."

private const val TRANSLATE_TO_ZH =
    "You are a translator. Translate the user's English into Simplified Chinese. " +
        "Output ONLY the Chinese translation - no English, no explanation, no quotes. " +
        "Example: See you tomorrow. -> 明天见。"

/** 不带例子：兜底"抄例子/串扰" */
private const val TRANSLATE_EN_NOEG =
    "Translate the user's Chinese into English. Output only the English translation, " +
        "nothing else - no Chinese characters, no explanation, no quotes."

private const val TRANSLATE_ZH_NOEG =
    "Translate the user's English into Simplified Chinese. Output only the Chinese translation, " +
        "nothing else - no English words, no explanation, no quotes."

/** 词典式（无例子）：给很短的词用（"头盔。" → helmet 实测最稳） */
private const val DICT_EN =
    "You are a Chinese-English dictionary. The user sends a Chinese word. " +
        "Reply with its English meaning only: one word, no Chinese, no explanation, no quotes."

private const val DICT_ZH =
    "You are an English-Chinese dictionary. The user sends an English word. " +
        "Reply with its Chinese meaning only, no English, no explanation, no quotes."

/** 直译式（无例子）：最后一次尝试 */
private const val DIRECT_EN =
    "Translate the user's Chinese into English. Reply with the English translation only."
private const val DIRECT_ZH =
    "Translate the user's English into Simplified Chinese. Reply with the Chinese translation only."

''' + t[end:]
le.write_text(t, encoding="utf-8")
print("LlmEngine：提示词改回简单单例子版（短词仍走词典式）✓")

# ---------- 3) 版本 ----------
g = R / "android/app/build.gradle.kts"
g.write_text(g.read_text(encoding="utf-8").replace("versionCode = 319", "versionCode = 319"), encoding="utf-8")
print("版本保持 3.1.9 / 319 ✓")
