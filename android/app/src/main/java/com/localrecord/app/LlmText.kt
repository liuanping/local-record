package com.localrecord.app

/**
 * 大模型输出的后处理（纯 Kotlin，有 JVM 单元测试）：
 *  * [stripThinking]：剥掉漏出来的思维链（`<think>…</think>`）；
 *  * [toPlainText]：把 Markdown 清成纯文本 —— 弹窗里不做 Markdown 渲染（要额外库、排版也未必好看），
 *    所以让输出本身就干净。
 */
object LlmText {

    /**
     * 剥掉漏出来的思维链。**注意两种标记**：
     *  * MiniCPM5 系用 `[Start thinking] … [End thinking]`（实测：模型自己会打印这个）
     *  * Qwen 系用 ` thinking…<｜end▁of▁thinking｜>`
     */
    fun stripThinking(text: String): String {
        var s = text
        for (pair in listOf("[Start thinking]" to "[End thinking]", "<think>" to "</think>")) {
            val (open, close) = pair
            while (true) {
                val a = s.indexOf(open)
                val b = s.indexOf(close)
                when {
                    a >= 0 && b > a -> s = s.substring(0, a) + s.substring(b + close.length)
                    b >= 0 -> s = s.substring(b + close.length)
                    a >= 0 -> s = s.substring(0, a)          // 只有开始标记（被截断）→ 后面全是推理
                    else -> break
                }
            }
        }
        s = s.replace(Regex("(?s)<think>.*?</think>"), "")
        return s.trim()
    }

    /** Markdown → 纯文本：去标题井号/粗体星号/表格分隔行；表格行转「· a — b — c」；`- ` 列表转「· 」 */
    fun toPlainText(text: String): String {
        val sb = StringBuilder()
        for (line in text.lines()) {
            var l = line.trimEnd()
            // |---|---| 这种表格分隔行直接丢掉
            if (l.trim().matches(Regex("^\\|?[\\s:\\-]*-{2,}[\\s:|\\-]*$"))) continue
            l = l.replace(Regex("^\\s*#{1,6}\\s*"), "")
            l = l.replace("**", "").replace("__", "")
            l = l.replace(Regex("^\\s*[-*+]\\s+"), "· ")
            val t = l.trim()
            if (t.startsWith("|") && t.endsWith("|")) {
                val cells = t.trim('|').split('|').map { it.trim() }.filter { it.isNotEmpty() }
                if (cells.isNotEmpty()) l = "· " + cells.joinToString(" — ")
            }
            sb.append(l).append('\n')
        }
        return sb.toString().trim()
    }
}
