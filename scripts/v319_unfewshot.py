"""3.1.9：撤销 few-shot 例子（它让 0.6B 把例子当答案，导致每句都翻成 helmet）。

用户实测（真机截图）：
    头盔。               → helmet   ✓ 对
    摔了，你看这个，你看。 → helmet   ✗ 错（抄了例子）
    就是深入到你。        → helmet   ✗ 错（抄了例子）

改法：
1. 提示词**改回 3.1.8 之前**的写法（只有一句规则 + 一个例子，实测那个版本不会抄）。
2. 保留 3.1.8 加的"多种问法兜底"（它本身有效，能救短词）。
3. 新增**防抄例子**判断：如果输出恰好等于例子的答案、而输入跟例子的原文无关 → 判定为抄例子，
   改用**不带任何例子**的提示词重试。这样彻底杜绝这类问题。
"""
import re
from pathlib import Path

R = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
APP = R / "android/app/src/main/java/com/localrecord/app"
le = APP / "LlmEngine.kt"
t = le.read_text(encoding="utf-8")

# ---------- 1) 提示词改回去 + 增加"无例子"版本 ----------
start = t.find("private const val TRANSLATE_TO_EN")
end = t.find("fun minutesPrompt", start)
assert start != -1 and end != -1, "找不到提示词段"
t = t[:start] + '''private const val TRANSLATE_TO_EN =
    "You are a translator. Translate the user's Chinese into natural English. " +
        "Output ONLY the English translation - no Chinese, no explanation, no quotes. " +
        "Example: 今天下雨了 -> It is raining today."

private const val TRANSLATE_TO_ZH =
    "You are a translator. Translate the user's English into Simplified Chinese. " +
        "Output ONLY the Chinese translation - no English, no explanation, no quotes. " +
        "Example: See you tomorrow. -> 明天见。"

/**
 * 不带任何例子的版本 —— 用来兜底"模型抄例子"的情况。
 * 教训：0.6B 这种小模型会把 few-shot 例子的**答案**当成万能答案
 * （实测每句都翻成 helmet），所以一旦发现抄例子就切换到这两个提示词。
 */
private const val TRANSLATE_EN_NOEG =
    "Translate the following Chinese into English. Output only the English translation, " +
        "nothing else - no Chinese, no explanation, no quotes."

private const val TRANSLATE_ZH_NOEG =
    "Translate the following English into Simplified Chinese. Output only the Chinese translation, " +
        "nothing else - no English, no explanation, no quotes."

/** 第二次：更直接的直译式指令 */
private const val RETRY_TO_EN = "Translate into English: "
private const val RETRY_TO_ZH = "把下面这句英文翻译成中文："

/** 第三次：短词/短语用"这个词的英文是什么"的问法 */
private const val WORD_TO_EN = "What is the English word for this? Reply with the English translation only: "
private const val WORD_TO_ZH = "What does this English mean in Chinese? Reply with the Chinese translation only: "

''' + t[end:]

# ---------- 2) translate()：加防抄例子 + 无例子兜底 ----------
start = t.find("    fun translate(")
end = t.find("    fun ask(", start)
assert start != -1 and end != -1, "找不到 translate()"
t = t[:start] + '''    /**
     * 逐句翻译。方向由代码判定（含汉字→英文，否则→中文）。
     *
     * 实测两类坑，都要兜：
     *  ① 小模型对**简单词**会"半翻半留"（"头盔" → "head 盔"）；
     *  ② 加了 few-shot 例子后，小模型会把**例子的答案当成万能答案**
     *     （"摔了，你看这个" 也被翻成 helmet）—— 所以本版把例子减到 1 个，
     *     并新增 [copyingExample] 判断，一旦发现抄例子就换**不带例子**的提示词。
     */
    fun translate(text: String, maxTokens: Int = 220): String {
        val src = text.trim()
        if (src.isEmpty()) return ""
        val toEnglish = looksChinese(src)

        var out = generate(if (toEnglish) TRANSLATE_TO_EN else TRANSLATE_TO_ZH, src, maxTokens).trim()

        // 抄例子（或中英串扰）→ 换成不带例子的提示词重试
        if (mixedScript(out, toEnglish) || copyingExample(out, src, toEnglish)) {
            Log.i(TAG, "翻译异常（串扰或抄例子），改用无例子提示词重试：${out.take(30)}")
            out = generate(if (toEnglish) TRANSLATE_EN_NOEG else TRANSLATE_ZH_NOEG, src, maxTokens).trim()
        }
        // 还不行 → 直译式指令
        if (mixedScript(out, toEnglish) || copyingExample(out, src, toEnglish)) {
            Log.i(TAG, "仍异常，换直译问法：${out.take(30)}")
            out = generate(
                if (toEnglish) TRANSLATE_EN_NOEG else TRANSLATE_ZH_NOEG,
                (if (toEnglish) RETRY_TO_EN else RETRY_TO_ZH) + src, maxTokens
            ).trim()
        }
        // 再不行 → "这个词的英文是什么"
        if (mixedScript(out, toEnglish) || copyingExample(out, src, toEnglish)) {
            Log.i(TAG, "仍异常，换「这是什么词」问法：${out.take(30)}")
            out = generate(
                if (toEnglish) TRANSLATE_EN_NOEG else TRANSLATE_ZH_NOEG,
                (if (toEnglish) WORD_TO_EN else WORD_TO_ZH) + src, maxTokens
            ).trim()
        }
        if (mixedScript(out, toEnglish) || copyingExample(out, src, toEnglish)) {
            Log.w(TAG, "三种问法都没得到干净结果，保留原样：$out")
        }
        return out
    }

    /** 目标英文却含汉字 / 目标中文却没有汉字 → 串扰 */
    private fun mixedScript(out: String, toEnglish: Boolean): Boolean {
        if (out.isBlank()) return false
        return if (toEnglish) looksChinese(out) else !looksChinese(out)
    }

    /**
     * 是否在"抄例子"：输出恰好等于提示词例子的答案，但输入跟例子的原文无关。
     * 例：中→英的例子里 今天下雨了 -> It is raining today.，
     * 若输入不是那句却输出 "It is raining today." 就是抄例子。
     */
    private fun copyingExample(out: String, src: String, toEnglish: Boolean): Boolean {
        val ans = if (toEnglish) "it is raining today" else "明天见"
        val srcOfExample = if (toEnglish) "今天下雨了" else "see you tomorrow"
        val o = out.trim().trim('"', '。', '.', ' ').lowercase()
        return o == ans && !src.lowercase().contains(srcOfExample)
    }

''' + t[end:]

le.write_text(t, encoding="utf-8")
print("LlmEngine：提示词改回单例子 + 防抄例子兜底 ✓")

# ---------- 3) 自检用例 = 用户真机上的那三句 ----------
m = APP / "MainActivity.kt"
mt = m.read_text(encoding="utf-8")
old = '''                for (s in listOf(
                    "头盔",
                    "会议纪要",
                    "今天的会议改到下午三点，请大家准时参加。",
                    "Please send me the updated report by Friday."
                )) {'''
new = '''                for (s in listOf(
                    "头盔。",
                    "摔了，你看这个，你看。",
                    "就是深入到你。",
                    "Please send me the updated report by Friday."
                )) {'''
assert old in mt, "自检用例锚点没找到"
m.write_text(mt.replace(old, new, 1), encoding="utf-8")
print("自检用例换成用户真机那三句 ✓")

# ---------- 4) 版本 ----------
g = R / "android/app/build.gradle.kts"
g.write_text(g.read_text(encoding="utf-8").replace("versionCode = 318", "versionCode = 319").replace("3.1.8", "3.1.9"), encoding="utf-8")
print("版本 -> 3.1.9 / 319 ✓")
