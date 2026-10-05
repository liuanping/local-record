package com.localrecord.app

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 识别结果过滤的单元测试。
 *
 * 重点（用户反馈）：**真实说的话必须展示** —— 包括"哈哈哈""嗯""啊"这类听起来没内容的。
 * 只有低信噪比段才允许动用"噪声幻觉"规则，纯标点/空白才丢。
 *
 * 注：上层是否算"低信噪比/证据弱"由 VAD 的人声帧数与占比决定（见 SileroVad.lastSpeechWindows），
 * 这里只测文字层面的规则本身。
 */
class TextFilterTest {

    @Test
    fun laughterAndFillersAreKept() {
        // 用户原话："为什么把有一些话不展示识别结果，好像抛弃掉了，比如我说哈哈哈之类的"
        val kept = listOf(
            "哈哈哈", "哈哈哈哈", "哈哈哈哈哈", "呵呵", "嘿嘿", "嗯", "啊", "哦",
            "嗯嗯", "哈哈哈，太好笑了", "哈哈", "嘻嘻", "呀", "唉",
        )
        for (t in kept) {
            assertFalse("「$t」是真实说的话，不该被丢", TextFilter.shouldDrop(t, lowSnr = false))
            assertFalse("「$t」即使低信噪比也不该仅因为像语气词就丢", TextFilter.shouldDrop(t, lowSnr = true))
        }
    }

    @Test
    fun realSpeechIsAlwaysKept() {
        val kept = listOf(
            "今天的会议改到下午三点请大家准时参加",
            "转发给我一下",
            "记得点赞",
            "这个订阅了没有",
            "字幕做得不错",
            "下周三交付第一个模块",
        )
        for (t in kept) {
            assertFalse("「$t」必须保留（低信噪比下也不该丢）", TextFilter.shouldDrop(t, lowSnr = true))
        }
    }

    @Test
    fun onlyBlankOrPunctuationIsAlwaysDropped() {
        for (t in listOf("", " ", "。。。", "，", "…", "　")) {
            assertTrue("「$t」没内容，应该丢", TextFilter.shouldDrop(t, lowSnr = false))
        }
    }

    @Test
    fun syntheticNoiseTextDroppedOnlyWhenLowSnr() {
        // 这些是模型在纯噪声上最常编出来的话
        for (t in listOf("谢谢观看", "请不吝点赞", "点赞订阅转发", "下期再见")) {
            assertTrue("低信噪比下的「$t」应丢", TextFilter.shouldDrop(t, lowSnr = true))
            assertFalse("正常说话里的「$t」不该丢", TextFilter.shouldDrop(t, lowSnr = false))
        }
    }

    @Test
    fun repeatedRunOnlyMattersAtLowSnr() {
        assertTrue("低信噪比下的长重复字是幻觉", TextFilter.shouldDrop("证证证证证证", lowSnr = true))
        assertTrue("低信噪比下更长的一串更该丢", TextFilter.shouldDrop("的的的的的的的的", lowSnr = true))
        assertFalse("正常说话里的重复字要展示", TextFilter.shouldDrop("哈哈哈哈", lowSnr = false))
        assertFalse("低信噪比下的笑声也要展示（门槛 6，笑声一般 4~5 个）", TextFilter.shouldDrop("哈哈哈哈", lowSnr = true))
        assertFalse("低信噪比下的 5 个笑也保留", TextFilter.shouldDrop("哈哈哈哈哈", lowSnr = true))
        assertFalse("长句里的重复不算幻觉", TextFilter.shouldDrop("他一直在说哈哈哈很久了", lowSnr = true))
    }
}
