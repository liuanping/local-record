package com.localrecord.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** 大模型输出后处理的单元测试：思维链必须被剥掉，Markdown 必须变成好看的纯文本。 */
class LlmTextTest {

    @Test
    fun thinkingIsStripped() {
        assertEquals("今天的会议改到下午三点。", LlmText.stripThinking("今天的会议改到下午三点。"))
        assertEquals(
            "答案在这里。",
            LlmText.stripThinking("<think>让我想想…用户问的是时间。\n先找转写里的时间点。</think>答案在这里。")
        )
        // 只有开头没有结尾（被 maxTokens 截断）：后面全是推理内容，整段丢掉
        assertEquals("", LlmText.stripThinking("<think>想了一半就被截断了……"))
        // 正文后面跟了没闭合的 think：保留正文
        assertEquals("正文结束。", LlmText.stripThinking("正文结束。<think>多余的推理"))
    }

    @Test
    fun miniCpmThinkingIsStripped() {
        // 实测：MiniCPM5 用的是 [Start thinking] … [End thinking]，不是 <think>
        val raw = "[Start thinking]\n用户问的是薛其坤。\n转写里写的是物理学奖。\n[End thinking]\n薛其坤可能获得物理学奖。"
        val out = LlmText.stripThinking(raw)
        println("MiniCPM5 剥离结果：$out")
        assertEquals("薛其坤可能获得物理学奖。", out)
        // 被截断的（只有开始标记）
        assertEquals("", LlmText.stripThinking("[Start thinking]推理到一半就被截断了"))
        // 只有结束标记
        assertEquals("结论。", LlmText.stripThinking("推理内容……[End thinking]结论。"))
    }

    @Test
    fun thinkingNeverLeaks() {
        val out = LlmText.stripThinking("<think>推理1</think>正文<think>推理2</think>结尾")
        assertFalse("不能残留 think 标签", out.contains("<think>") || out.contains("</think>"))
        assertTrue("正文要保留", out.contains("正文") && out.contains("结尾"))
    }

    @Test
    fun markdownBecomesPlainText() {
        val md = """
            ## 会议纪要
            **一句话概述**：讨论了交付节奏。
            ### 一、重点内容
            - 会议改到下午三点
            - 交付时间未变
            | 事项 | 负责人 | 时间要求 |
            |---|---|---|
            | 出周报 | 张三 | 周五 |
        """.trimIndent()
        val plain = LlmText.toPlainText(md)
        println("清洗结果：\n$plain")
        assertFalse("不应再有 # 标题", plain.contains("#"))
        assertFalse("不应再有 ** 粗体", plain.contains("**"))
        assertFalse("不应再有表格竖线", plain.contains("|"))
        assertTrue("列表应变成「· 」", plain.contains("· 会议改到下午三点"))
        assertTrue("表格行应变成「· a — b — c」", plain.contains("· 出周报 — 张三 — 周五"))
        assertTrue("正文内容要保留", plain.contains("会议纪要") && plain.contains("交付时间未变"))
    }

    @Test
    fun plainTextStaysIntact() {
        val s = "会议纪要\n一句话概述：没问题。\n\n一、重点内容\n· 甲\n· 乙"
        assertEquals(s, LlmText.toPlainText(s))
    }
}
