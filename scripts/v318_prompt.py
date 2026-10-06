"""3.1.8：翻译提示词加固（防中英串扰）+ 自检加入"头盔"等短词用例。

用户实测："头盔" 被翻成 "head 盔"（半翻半留）。
做法：
1. 提示词里**明确禁止混用**另一种语言，并给 few-shot 例子（含单词、短语、整句）
   —— 0.6B 这种小模型跟例子比跟规则靠谱。
2. 代码侧最多试三种问法：原提示 → 直译式指令 → "这个词的英文是什么"式问法；
   每次都用语言检测判断有没有串扰。
3. 自检用例改成 4 条（头盔 / 会议纪要 / 整句 / 英文句），跑完直接看输出。
"""
from pathlib import Path

R = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
APP = R / "android/app/src/main/java/com/localrecord/app"
le = APP / "LlmEngine.kt"
t = le.read_text(encoding="utf-8")

# ---------- 1) 提示词加 few-shot + 禁止混用 ----------
start = t.find("private const val TRANSLATE_TO_EN")
end = t.find("fun minutesPrompt", start)
assert start != -1 and end != -1
t = t[:start] + '''private const val TRANSLATE_TO_EN =
    "You are a translator. Translate the user's Chinese into English.\\n" +
        "Rules: output ONLY the English translation. Never keep any Chinese character in your answer.\\n" +
        "No explanation, no pinyin, no quotes.\\n" +
        "Examples:\\n" +
        "头盔 -> helmet\\n" +
        "会议纪要 -> meeting minutes\\n" +
        "今天的会议改到下午三点 -> The meeting is moved to 3 p.m. today."

private const val TRANSLATE_TO_ZH =
    "You are a translator. Translate the user's English into Simplified Chinese.\\n" +
        "Rules: output ONLY the Chinese translation. Never keep any English word in your answer.\\n" +
        "No explanation, no quotes.\\n" +
        "Examples:\\n" +
        "helmet -> 头盔\\n" +
        "meeting minutes -> 会议纪要\\n" +
        "Send me the report by Friday. -> 请在周五前把报告发给我。"

/** 第二次：更直接的直译式指令 */
private const val RETRY_TO_EN = "Translate into English: "
private const val RETRY_TO_ZH = "把下面这句英文翻译成中文："

/** 第三次：短词/短语用"这个词的英文是什么"的问法（小模型对"词"更容易答对） */
private const val WORD_TO_EN = "What is the English word for this? Reply with the English translation only: "
private const val WORD_TO_ZH = "What does this English mean in Chinese? Reply with the Chinese translation only: "

''' + t[end:]

# ---------- 2) translate()：三种问法 + 语言检测 ----------
start = t.find("    fun translate(")
end = t.find("    fun ask(", start)
assert start != -1 and end != -1
t = t[:start] + '''    /**
     * 逐句翻译。方向由代码判定（含汉字→英文，否则→中文）。
     *
     * 实测问题：小模型对**简单词**容易"半翻半留"（"头盔" → "head 盔"）。
     * 所以这里最多试三种问法，每步都用 [mixedScript] 检查有没有中英串扰：
     *   ① 带 few-shot 例子的系统提示  ② 直译式指令  ③ "这个词的英文是什么"式问法
     */
    fun translate(text: String, maxTokens: Int = 220): String {
        val src = text.trim()
        if (src.isEmpty()) return ""
        val toEnglish = looksChinese(src)
        val sys = if (toEnglish) TRANSLATE_TO_EN else TRANSLATE_TO_ZH
        var out = generate(sys, src, maxTokens).trim()

        if (mixedScript(out, toEnglish)) {
            Log.i(TAG, "翻译出现中英串扰，换直译问法重试：${out.take(30)}")
            out = generate(sys, (if (toEnglish) RETRY_TO_EN else RETRY_TO_ZH) + src, maxTokens).trim()
        }
        if (mixedScript(out, toEnglish)) {
            Log.i(TAG, "仍然串扰，换"这是什么词"问法：${out.take(30)}")
            out = generate(sys, (if (toEnglish) WORD_TO_EN else WORD_TO_ZH) + src, maxTokens).trim()
        }
        if (mixedScript(out, toEnglish)) {
            Log.w(TAG, "三种问法都还串扰，保留原样：$out")
        }
        return out
    }

    /** 目标英文却含汉字 / 目标中文却没有汉字 → 视为串扰 */
    private fun mixedScript(out: String, toEnglish: Boolean): Boolean {
        if (out.isBlank()) return false
        return if (toEnglish) looksChinese(out) else !looksChinese(out)
    }

''' + t[end:]

le.write_text(t, encoding="utf-8")
print("LlmEngine：提示词加 few-shot + 三种问法兜底 ✓")

# ---------- 3) 自检用例换成用户报的短词 ----------
m = APP / "MainActivity.kt"
mt = m.read_text(encoding="utf-8")
old = '''                for (s in listOf(
                    "今天的会议改到下午三点，请大家准时参加。",
                    "Please send me the updated report by Friday."
                )) {'''
new = '''                for (s in listOf(
                    "头盔",
                    "会议纪要",
                    "今天的会议改到下午三点，请大家准时参加。",
                    "Please send me the updated report by Friday."
                )) {'''
assert old in mt, "自检用例锚点没找到"
mt = mt.replace(old, new, 1)
m.write_text(mt, encoding="utf-8")
print("自检用例已加入「头盔」「会议纪要」 ✓")

# ---------- 4) 版本 ----------
g = R / "android/app/build.gradle.kts"
gt = g.read_text(encoding="utf-8").replace("versionCode = 317", "versionCode = 318").replace("3.1.7", "3.1.8")
g.write_text(gt, encoding="utf-8")
print("版本 -> 3.1.8 / 318 ✓")
