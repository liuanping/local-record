"""3.1.0 第六步：修两个真问题。
① 翻译方向在代码里判定（含汉字→译成英文；否则→译成中文），提示词写明目标语言并给一个例子
   —— 0.6B 小模型靠"自动判断方向"不可靠，实测英文句子被原样返回。
② JNI：Qwen3 模板只输出 `<think>` 不闭合（enable_thinking 未定义时走 else 分支），
   会让模型自由推理 → 检测到"开了没关"就补 `</think>`，强制空思考块。
"""
from pathlib import Path

R = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
APP = R / "android/app/src/main/java/com/localrecord/app"

# ---------- ① LlmEngine：方向由代码决定 ----------
le = APP / "LlmEngine.kt"
t = le.read_text(encoding="utf-8")

old_sys_start = t.find("/** 翻译用的系统提示词")
old_sys_end = t.find("fun minutesPrompt", old_sys_start)
assert old_sys_start != -1 and old_sys_end != -1, "找不到翻译提示词段"
new_sys = '''/**
 * 翻译提示词：**目标语言由代码判定**（含汉字→译成英文，否则→译成中文）。
 * 0.6B 这种小模型靠"自己判断该译成什么"不可靠（实测英文句子会被原样返回），
 * 所以提示词里写死目标语言，并给一个例子。
 */
private const val TRANSLATE_TO_EN =
    "You are a translator. Translate the user's Chinese into natural English. " +
        "Output ONLY the English translation - no Chinese, no explanation, no quotes. " +
        "Example: 今天下雨了 -> It is raining today."

private const val TRANSLATE_TO_ZH =
    "你是翻译。把用户给的英文翻译成简体中文。只输出中文译文，不要英文、不要解释、不要引号。" +
        "例如：See you tomorrow. -> 明天见。"

'''
t = t[:old_sys_start] + new_sys + t[old_sys_end:]

# 替换 translate()
start = t.find("    fun translate(")
end = t.find("    fun ask(", start)
assert start != -1 and end != -1, "找不到 translate()"
new_fn = '''    /** 含汉字就译成英文，否则译成中文（中英互译，方向由代码定，不靠模型猜） */
    private fun looksChinese(s: String): Boolean =
        s.any { it.code in 0x3400..0x9FFF || it.code in 0xF900..0xFAFF }

    fun translate(text: String, maxTokens: Int = 220): String {
        val src = text.trim()
        if (src.isEmpty()) return ""
        return generate(
            if (looksChinese(src)) TRANSLATE_TO_EN else TRANSLATE_TO_ZH,
            src,
            maxTokens
        )
    }

'''
t = t[:start] + new_fn + t[end:]
le.write_text(t, encoding="utf-8")
print("LlmEngine：翻译方向改由代码判定 + 写死目标语言 + 例子 ✓")

# ---------- ② JNI：补上未闭合的 <think> ----------
cpp = R / "android/app/src/main/cpp/llm_jni.cpp"
c = cpp.read_text(encoding="utf-8")
old = '''        const size_t lastAssistant = out.rfind("assistant");
        const bool templateAlready = lastAssistant != std::string::npos &&
                                     out.find("<think>", lastAssistant) != std::string::npos;
        if (templateAlready) {
            LOGI("模板已自带空思考块，不再手工补（按官方默认关闭思维链）");
        } else if (t.find("[Start thinking]") != std::string::npos) {'''
assert old in c, "找不到 JNI 的模板判断段"
new = '''        const size_t lastAssistant = out.rfind("assistant");
        const size_t openAt = lastAssistant == std::string::npos
                                  ? std::string::npos
                                  : out.find("<think>", lastAssistant);
        // 关键：模板可能"只开了 <think> 没闭合"（Qwen3 在 enable_thinking 未定义时就是这种），
        // 那种情况下模型会自由推理 → 必须补一个 </think> 让它变成空思考块。
        const bool hasOpen = openAt != std::string::npos;
        const bool hasClose = hasOpen && out.find("</think>", openAt) != std::string::npos;
        if (hasOpen && hasClose) {
            LOGI("模板已自带完整空思考块，不干预");
        } else if (hasOpen && !hasClose) {
            out += "\\n</think>\\n\\n";
            LOGI("模板只开了 <think> 未闭合，已补 </think>（强制空思考）");
        } else if (t.find("[Start thinking]") != std::string::npos) {'''
c = c.replace(old, new, 1)
cpp.write_text(c, encoding="utf-8")
print("llm_jni：未闭合的 <think> 会补 </think> ✓")

# ---------- 版本注释更新 ----------
readme = R / "android/README-android.md"
r = readme.read_text(encoding="utf-8")
r = r.replace("""  * 三重关闭思维链：`/no_think` 提示 + JNI 判断模板是否已自带空 `<think>` 块 +
    输出侧 `stripThinking` 兜底。""",
"""  * **翻译方向由代码判定**：含汉字→译成英文，否则→译成中文；提示词里写死目标语言并给一个例子
    （0.6B 小模型"自己判断方向"不可靠 —— 实测英文句子会被原样返回）。
  * **三重关闭思维链**：JNI 检测模板若"只开了 `<think>` 未闭合"就补 `</think>` 强制空思考块
    （Qwen3 在 `enable_thinking` 未定义时正是这种模板）+ 输出侧 `stripThinking` 兜底。""")
readme.write_text(r, encoding="utf-8")
print("README 说明已更新 ✓")
