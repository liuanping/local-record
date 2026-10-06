"""3.1.9（最终版）：例子教格式 + 防抄覆盖所有例子 + 指令只在系统提示里。

三轮实测得到的结论：
  A. 完全没有例子 → 小模型退化成"查词"（整句只输出一个单词：摔了… → broken ✗）
  B. 例子太多没防抄 → 抄第一个例子的答案（每句都 helmet ✗，用户真机遇到的就是这个）
  C. 指令拼进用户消息 → 被当成正文抄进译文（"请把下面这句英文翻译成中文：Please send…" ✗）
所以最终方案：
  ① 例子保留（一"词"一"句"，教会输出格式），但**防抄检查覆盖每一个例子的答案**；
  ② 一旦发现抄例子/串扰 → 换**不带例子**的系统提示重试，再不行换词典式/直译式；
  ③ 所有指令只在系统提示里，用户消息永远是纯原文。
"""
from pathlib import Path

R = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
le = R / "android/app/src/main/java/com/localrecord/app/LlmEngine.kt"
t = le.read_text(encoding="utf-8")

# ---------- 1) 提示词组（例子：一个词 + 一句话）----------
start = t.find("private const val TRANSLATE_TO_EN")
end = t.find("fun minutesPrompt", start)
assert start != -1 and end != -1
t = t[:start] + '''private const val TRANSLATE_TO_EN =
    "You are a translator. Translate the user's Chinese into English.\\n" +
        "Rules: output ONLY the English translation. Never keep any Chinese character. " +
        "No explanation, no pinyin, no quotes.\\n" +
        "Examples:\\n" +
        "头盔 -> helmet\\n" +
        "今天的会议改到下午三点 -> The meeting is moved to 3 p.m. today."

private const val TRANSLATE_TO_ZH =
    "You are a translator. Translate the user's English into Simplified Chinese.\\n" +
        "Rules: output ONLY the Chinese translation. Never keep any English word. " +
        "No explanation, no quotes.\\n" +
        "Examples:\\n" +
        "helmet -> 头盔\\n" +
        "Send me the report by Friday. -> 请在周五前把报告发给我。"

/** 不带例子：兜底"抄例子/串扰" */
private const val TRANSLATE_EN_NOEG =
    "Translate the user's Chinese into English. Output only the English translation, " +
        "nothing else - no Chinese characters, no explanation, no quotes."

private const val TRANSLATE_ZH_NOEG =
    "Translate the user's English into Simplified Chinese. Output only the Chinese translation, " +
        "nothing else - no English words, no explanation, no quotes."

/** 词典式（无例子）：给很短的词用 */
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

# ---------- 2) translate() ----------
start = t.find("    fun translate(")
end = t.find("    fun ask(", start)
assert start != -1 and end != -1
t = t[:start] + '''    /**
     * 逐句翻译。方向由代码判定（含汉字→英文，否则→中文）。
     *
     * 三轮实测踩的坑（这里都兜住）：
     *  ① 不给例子 → 小模型退化成"查词"（整句只回一个单词）；
     *  ② 给例子但没防抄 → 抄第一个例子的答案（每句都 helmet）；
     *  ③ 把指令拼进用户消息 → 被当成正文抄进译文。
     * 所以：例子保留（教输出格式），但**防抄检查覆盖每一个例子的答案**，
     * 一旦发现抄例子/串扰就换不带例子的提示重试；指令一律只在系统提示里。
     */
    fun translate(text: String, maxTokens: Int = 220): String {
        var src = text.trim()
        if (src.isEmpty()) return ""
        val toEnglish = looksChinese(src)
        // 很短的输入先去句末标点："头盔。" → "头盔"
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

        if (bad(out, src, toEnglish)) {
            Log.i(TAG, "翻译异常（串扰/抄例子），改用无例子提示：${out.take(30)}")
            out = generate(if (toEnglish) TRANSLATE_EN_NOEG else TRANSLATE_ZH_NOEG, src, maxTokens).trim()
        }
        if (bad(out, src, toEnglish)) {
            Log.i(TAG, "仍异常，换直译式提示：${out.take(30)}")
            out = generate(if (toEnglish) DIRECT_EN else DIRECT_ZH, src, maxTokens).trim()
        }
        if (bad(out, src, toEnglish)) {
            Log.w(TAG, "多次尝试仍有问题，保留原样：$out")
        }
        return out
    }

    /** 目标英文却含汉字 / 目标中文却没有汉字 → 串扰 */
    private fun mixedScript(out: String, toEnglish: Boolean): Boolean {
        if (out.isBlank()) return false
        return if (toEnglish) looksChinese(out) else !looksChinese(out)
    }

    /**
     * 是否"抄例子"：输出恰好等于某个例子的答案，但输入跟那个例子的原文无关。
     * 覆盖**所有**例子答案 —— 用户真机遇到的"每句都翻成 helmet"就是抄了「头盔 -> helmet」。
     */
    private fun copyingExample(out: String, src: String, toEnglish: Boolean): Boolean {
        val srcLow = src.lowercase()
        val pairs = if (toEnglish) listOf(
            "helmet" to "头盔",
            "the meeting is moved to 3 p.m. today" to "今天的会议改到下午三点",
        ) else listOf(
            "头盔" to "helmet",
            "请在周五前把报告发给我" to "send me the report by friday",
        )
        val o = out.trim().trim('"', '。', '.', ' ').lowercase()
        return pairs.any { (ans, exSrc) -> o == ans && !srcLow.contains(exSrc) }
    }

    private fun bad(out: String, src: String, toEnglish: Boolean): Boolean =
        mixedScript(out, toEnglish) || copyingExample(out, src, toEnglish)

''' + t[end:]

le.write_text(t, encoding="utf-8")
print("LlmEngine：例子教格式 + 防抄覆盖全部例子 + 指令只在系统提示 ✓")
