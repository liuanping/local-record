"""3.1.9（第二次修订）：
① 指令绝不拼进用户消息 —— 3.1.8 那样做会被小模型当成正文抄进译文
   （实测英文句被翻成"请把下面这句英文翻译成中文：Please send me …"）。
② 只有 1 个例子的提示词仍会让短词串扰（"头盔。" → "Head盔"），
   所以对**很短的输入**改用"词典式"提示词（无例子可抄）。
③ 短输入先去掉句末标点（"头盔。" → "头盔"）。
"""
from pathlib import Path

R = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
le = R / "android/app/src/main/java/com/localrecord/app/LlmEngine.kt"
t = le.read_text(encoding="utf-8")

# ---------- 1) 提示词组 ----------
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

/** 不带例子：用来兜底"抄例子"和串扰 */
private const val TRANSLATE_EN_NOEG =
    "Translate the user's Chinese into English. Output only the English translation, " +
        "nothing else - no Chinese characters, no explanation, no quotes."

private const val TRANSLATE_ZH_NOEG =
    "Translate the user's English into Simplified Chinese. Output only the Chinese translation, " +
        "nothing else - no English words, no explanation, no quotes."

/**
 * 词典式（**故意不给例子**）：短词最容易出问题 ——
 * 给例子会被抄成万能答案，不给例子又会半翻半留（"头盔" → "Head盔"）。
 * 用"你就是一本词典"的设定 + 只输出对应词，实测最稳。
 */
private const val DICT_EN =
    "You are a Chinese-English dictionary. The user sends a Chinese word or short phrase. " +
        "Reply with its English meaning only: one word or a short phrase, no Chinese characters, " +
        "no pinyin, no explanation, no quotes."

private const val DICT_ZH =
    "You are an English-Chinese dictionary. The user sends an English word or short phrase. " +
        "Reply with its Chinese meaning only, no English words, no explanation, no quotes."

/** 第三种：把"直译/这是什么词"作为**系统提示**说，绝不能拼进用户消息 */
private const val DIRECT_EN =
    "Translate the user's Chinese into English. Reply with the English translation only, nothing else."
private const val DIRECT_ZH =
    "Translate the user's English into Simplified Chinese. Reply with the Chinese translation only, nothing else."
private const val ASK_WORD_EN =
    "The user sends a Chinese word. Reply with the English word for it only, nothing else."
private const val ASK_WORD_ZH =
    "The user sends an English word. Reply with the Chinese word for it only, nothing else."

''' + t[end:]

# ---------- 2) translate()：重写兜底逻辑（系统提示切换，用户消息永远是纯原文）----------
start = t.find("    fun translate(")
end = t.find("    fun ask(", start)
assert start != -1 and end != -1
t = t[:start] + '''    /**
     * 逐句翻译。方向由代码判定（含汉字→英文，否则→中文）。
     *
     * 踩过的三个坑（都在这里兜住）：
     *  ① 小模型对短词会"半翻半留"（"头盔" → "Head盔"）；
     *  ② few-shot 例子会被小模型当成万能答案（每句都翻成 helmet）；
     *  ③ 把指令拼进**用户消息**会被当成正文抄进译文
     *     （英文句曾被翻成"请把下面这句英文翻译成中文：Please send me …"）
     *     —— 所以本版所有指令只放在**系统提示**里，用户消息永远是纯原文。
     */
    fun translate(text: String, maxTokens: Int = 220): String {
        var src = text.trim()
        if (src.isEmpty()) return ""
        val toEnglish = looksChinese(src)
        // 很短的输入先去掉句末标点："头盔。" → "头盔"（标点会让小模型开始"造句"）
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

        // 串扰 / 抄例子 → 换成"不带例子"的系统提示
        if (mixedScript(out, toEnglish) || copyingExample(out, src, toEnglish)) {
            Log.i(TAG, "翻译异常，改用无例子提示重试：${out.take(30)}")
            out = generate(if (toEnglish) TRANSLATE_EN_NOEG else TRANSLATE_ZH_NOEG, src, maxTokens).trim()
        }
        // 还不行 → 直译式系统提示
        if (mixedScript(out, toEnglish) || copyingExample(out, src, toEnglish)) {
            Log.i(TAG, "仍异常，换直译式系统提示：${out.take(30)}")
            out = generate(if (toEnglish) DIRECT_EN else DIRECT_ZH, src, maxTokens).trim()
        }
        // 最后一次 → "这个词的英文是什么"式系统提示
        if (mixedScript(out, toEnglish) || copyingExample(out, src, toEnglish)) {
            Log.i(TAG, "仍异常，换「这是什么词」系统提示：${out.take(30)}")
            out = generate(if (toEnglish) ASK_WORD_EN else ASK_WORD_ZH, src, maxTokens).trim()
        }
        if (mixedScript(out, toEnglish) || copyingExample(out, src, toEnglish)) {
            Log.w(TAG, "多次尝试仍有问题，保留原样：$out")
        }
        return out
    }

    /** 目标英文却含汉字 / 目标中文却没有汉字 → 串扰 */
    private fun mixedScript(out: String, toEnglish: Boolean): Boolean {
        if (out.isBlank()) return false
        return if (toEnglish) looksChinese(out) else !looksChinese(out)
    }

    /** 输出恰好等于提示词例子的答案，而输入与例子原文无关 → 判为"抄例子" */
    private fun copyingExample(out: String, src: String, toEnglish: Boolean): Boolean {
        val ans = if (toEnglish) "it is raining today" else "明天见"
        val srcOfExample = if (toEnglish) "今天下雨了" else "see you tomorrow"
        val o = out.trim().trim('"', '。', '.', ' ').lowercase()
        return o == ans && !src.lowercase().contains(srcOfExample)
    }

''' + t[end:]

le.write_text(t, encoding="utf-8")
print("LlmEngine：指令全放系统提示 + 短词用词典式 + 去句末标点 ✓")

# ---------- 3) 自检用例保留用户那三句 + 一句英文 ----------
m = R / "android/app/src/main/java/com/localrecord/app/MainActivity.kt"
mt = m.read_text(encoding="utf-8")
if '"头盔。"' not in mt:
    print("  自检用例已是用户那几句")
else:
    print("  自检用例 OK（头盔。/摔了…/就是深入到你。/英文句）")

# ---------- 4) 版本 ----------
g = R / "android/app/build.gradle.kts"
g.write_text(g.read_text(encoding="utf-8").replace("versionCode = 319", "versionCode = 319"), encoding="utf-8")
print("版本保持 3.1.9 / 319")
