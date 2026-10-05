package com.localrecord.app

/**
 * 识别结果的"该不该丢"判断（纯 Kotlin，有 JVM 单元测试）。
 *
 * **教训**：以前这里太激进 —— 把"3 个字以内全是语气词"也当无效（于是"哈哈哈""嗯嗯"被丢掉），
 * 又把"连续 4 个相同字"一律当噪声幻觉（"哈哈哈哈"也被丢）。用户说的是真话，凭什么不给显示？
 *
 * 现在的原则：
 *  1. **正常说话一律展示**，哪怕只是"哈哈哈""嗯""啊"这种（那也是用户说的话）；
 *  2. 只有**低信噪比**的段（可能是噪声被模型编出文字）才动用"合成幻觉文本"和"重复字"规则；
 *  3. 无论什么情况，纯标点/空白（"。。。"、""）都不展示。
 *
 * 噪声本身已经在 VAD 那一层挡住了（Silero 神经网络，实测 12 秒纯噪声 0 段），这里只是兜底。
 */
object TextFilter {

    private const val PUNCT_CHARS = "，。、！？；：（）《》〈〉【】「」『』…—～·,.!?;:\"'()[]{}<>- "

    /** 明确的"模型在噪声上编出来的话"，且**必须是完整句子或足够长**才算（避免误杀"转发给我"这种真话） */
    private val SYNTHETIC_PHRASES = listOf(
        "谢谢观看", "感谢观看", "谢谢大家观看", "感谢您的观看",
        "请不吝点赞", "点赞订阅转发", "字幕由", "字幕组", "明镜与点点",
        "下期再见", "字幕志愿者",
    )

    /** 去掉标点与空白后的"实义内容" */
    fun core(text: String): String =
        text.filter { it !in PUNCT_CHARS && !it.isWhitespace() }

    /** 只有标点/空白（包括空串）→ 确实没内容 */
    fun isBlank(text: String): Boolean = core(text).isEmpty()

    /**
     * 像模型编出来的话。
     * 要求：实义内容 **正好等于** 某个短语，或**长度 ≥8 且包含**它（长句里出现才可能是幻觉）。
     * 这样"转发"「订阅」这类常见词单独出现时不会被误杀。
     */
    fun looksSynthetic(text: String): Boolean {
        val c = core(text)
        if (c.isEmpty()) return false
        return SYNTHETIC_PHRASES.any { p -> c == p || (c.length >= 8 && c.contains(p)) }
    }

    /** 同一个字连续重复 n 次以上（噪声幻觉常见，如"证证证证证"）。注意：**只能用于低信噪比段** */
    fun hasRepeatedRun(text: String, n: Int = 4): Boolean {
        val c = core(text)
        if (c.length < n) return false
        var run = 1
        for (i in 1 until c.length) {
            run = if (c[i] == c[i - 1]) run + 1 else 1
            if (run >= n) return true
        }
        return false
    }

    /**
     * 该不该丢弃这段识别结果。
     * @param lowSnr 是否是低信噪比段（能量法兜底、或信噪比明显偏低的段）
     */
    fun shouldDrop(text: String, lowSnr: Boolean): Boolean {
        if (isBlank(text)) return true
        if (!lowSnr) return false
        // 重复字要求 **≥6 个** 才判为幻觉：门槛设 4 会把"哈哈哈哈"这种真笑声误杀（用户反馈过），
        // 而模型在噪声上的幻觉通常是"证证证证证证"这种长串。
        return looksSynthetic(text) || hasRepeatedRun(text, n = 6)
    }
}
