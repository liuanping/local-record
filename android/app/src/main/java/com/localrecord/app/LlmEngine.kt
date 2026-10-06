package com.localrecord.app

import android.util.Log
import java.io.File

/**
 * 手机端本地大模型（llama.cpp，纯 CPU）。
 *
 * 模型：Qwen2.5-Instruct 的 GGUF（0.5B/1.5B/3B 都行）—— 我们手上这份 llama.cpp
 * 源码支持 qwen2 架构，但不支持电脑版用的 MiniCPM5（chunk 里没有 minicpm5）。
 *
 * 提示词与电脑版保持一致的思路：只依据转写、不许编造、结构化输出。
 */
class LlmEngine(private val store: ModelStore) {

    companion object {
        private const val TAG = "LlmEngine"
        const val CONTEXT = 4096

        /** 会议纪要模板（与电脑版 config.yaml 的 summarize 能力对齐，精简版） */
        val MINUTES_SYSTEM = """
            你是专业的会议纪要整理助手。只使用用户提供的转写内容，禁止编造人名、数字或结论。

重要：直接输出结果，不要输出任何思考过程、推理步骤或内心独白。""".trimIndent()

/**
 * 翻译提示词：**目标语言由代码判定**（含汉字→译成英文，否则→译成中文）。
 * 0.6B 这种小模型靠"自己判断该译成什么"不可靠（实测英文句子会被原样返回），
 * 所以提示词里写死目标语言，并给一个例子。
 */
private const val TRANSLATE_TO_EN =
    "You are a translator. Translate the user's Chinese into natural English. " +
        "Output ONLY the English translation - no Chinese characters, no explanation, no quotes. " +
        "Never keep any Chinese character in your answer."

private const val TRANSLATE_TO_ZH =
    "You are a translator. Translate the user's English into Simplified Chinese. " +
        "Output ONLY the Chinese translation - no English words, no explanation, no quotes. " +
        "Never keep any English word in your answer."

/** 不带例子（短词最容易串扰，给它专用的"词典式"提示，无例子可抄） */
private const val DICT_EN =
    "You are a Chinese-English dictionary. The user sends a Chinese word. " +
        "Reply with its English meaning only: one word, no Chinese, no explanation, no quotes."

private const val DICT_ZH =
    "You are an English-Chinese dictionary. The user sends an English word. " +
        "Reply with its Chinese meaning only, no English, no explanation, no quotes."

/** 兜底：直译式提示 */
private const val DIRECT_EN =
    "Translate the user's Chinese into English. Reply with the English translation only."
private const val DIRECT_ZH =
    "Translate the user's English into Simplified Chinese. Reply with the Chinese translation only."

fun minutesPrompt(transcript: String): String = """
            下面是一次录音的转写文本（每段格式：[编号] HH:MM:SS 文本）：

            $transcript

            请把上面内容整理成会议纪要。**只输出纯文本，不要任何 Markdown 标记**
（不要用 #、*、**、|、表格、代码块），严格按下面的格式写（括号里是要求，不要抄进正文）：

会议纪要
一句话概述：（30 字以内说清这次录音讲了什么）

一、重点内容
· （每行一条，以「· 」开头，一条一句话；数字、金额、比例、时间点必须保留；同主题合并，不要流水账）

二、待办事项
· 事项 — 负责人 — 时间要求
（只写转写里明确提到的；没提到的负责人或时间写"未提及"，不要编造；没有就写"本次未提及待办事项"）

三、风险与问题
· （阻塞、风险、线上问题、依赖，写清影响与状态）

四、决议与结论
· （只写已明确拍板的决定；没有就写"本次未形成明确决议"）

只使用转写中的信息，绝对不要编造任何人名、数字或结论。全文用中文。
""".trimIndent()

        fun askPrompt(transcript: String, question: String): String = """
            下面是一次录音的转写文本：

            $transcript

            用户问题：$question

            请只基于上面的转写内容回答；如果转写里没有相关信息，请明确说明"转写中没有提到"。
              回答用**纯文本**（不要 Markdown 标记）。
现在直接给出答案，不要思考过程、不要推理步骤。
        """.trimIndent()

        init {
            try {
                System.loadLibrary("llmjni")
            } catch (e: Throwable) {
                Log.e(TAG, "加载 libllmjni.so 失败：${e.message}")
            }
        }
    }

    private var handle = 0L
    val ready: Boolean get() = handle != 0L
    var loadedModel: String = ""
        private set

    /** 大模型目录：外置私有目录优先（USB 可见），内部存储兜底 */
    fun llmDirs(): List<File> = listOf(
        File(store.externalModelsDir().parentFile, "llm"),
        File(store.internalModelsDir().parentFile, "llm"),
    ).onEach { runCatching { it.mkdirs() } }

    /** 展示/拷贝用的首选目录（外置，方便用户丢 gguf 进来） */
    fun llmDir(): File = llmDirs().first()

    /** 两个目录里都找，取最大的那个 gguf */
    fun findModel(): File? = llmDirs()
        .flatMap { d -> d.listFiles { f -> f.extension.lowercase() == "gguf" }?.toList() ?: emptyList() }
        .maxByOrNull { it.length() }

    fun init(threads: Int = defaultThreads()): Boolean {
        if (handle != 0L) return true
        val model = findModel()
        if (model == null) {
            Log.w(TAG, "没找到 gguf：请把模型放进 ${llmDir().absolutePath}")
            return false
        }
        return try {
            handle = nativeInit(model.absolutePath, CONTEXT, threads)
            if (handle != 0L) loadedModel = model.name
            Log.i(TAG, "LlmEngine 就绪=${handle != 0L} 模型=${model.name}")
            handle != 0L
        } catch (e: Throwable) {
            Log.e(TAG, "初始化失败", e)
            false
        }
    }

    /** 转写文本按上下文预算裁剪（保留头尾，中间省略） */
    private fun fit(transcript: String, maxChars: Int = 2600): String {
        if (transcript.length <= maxChars) return transcript
        val head = (maxChars * 0.6).toInt()
        val tail = maxChars - head
        return transcript.take(head) + "\n……（中间省略 ${transcript.length - maxChars} 字，转写过长）……\n" +
            transcript.takeLast(tail)
    }

    fun summarize(transcript: String, maxTokens: Int = 700): String =
        generate(MINUTES_SYSTEM, minutesPrompt(fit(transcript)), maxTokens)

    /**
     * 逐句翻译：中文→英文、英文→中文（自动判断方向）。
     * 输入只放**这一句**，prompt 很短 → 手机上预填充快，能做到"边识别边翻译"。
     * 末尾的 /no_think 是 Qwen3 的软开关（关闭思维链）；JNI 还会补空 <think> 块，
     * 输出侧再兜底剥一次，三重保证不出现思考过程。
     */
    /** 含汉字就译成英文，否则译成中文（中英互译，方向由代码定，不靠模型猜） */
    private fun looksChinese(s: String): Boolean =
        s.any { it.code in 0x3400..0x9FFF || it.code in 0xF900..0xFAFF }

    /**
     * 逐句翻译。方向由代码判定（含汉字→英文，否则→中文）。
     *
     * 加固点（都来自实测）：
     *  ① 提示词明确"不许保留另一种语言"，缓解"头盔 → head 盔"这类半翻半留；
     *  ② 很短的词改用**词典式**提示（不给例子，避免小模型把例子当万能答案）；
     *  ③ 发现串扰就换更直接的提示重试；**指令只放系统提示**，用户消息永远是纯原文
     *     （曾经把指令拼进用户消息，结果被模型抄进译文）。
     */
    fun translate(text: String, maxTokens: Int = 220): String {
        var src = text.trim()
        if (src.isEmpty()) return ""
        val toEnglish = looksChinese(src)
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

        if (mixedScript(out, toEnglish)) {
            Log.i(TAG, "翻译出现串扰，换直译式提示重试：${out.take(30)}")
            out = generate(if (toEnglish) DIRECT_EN else DIRECT_ZH, src, maxTokens).trim()
        }
        if (mixedScript(out, toEnglish)) {
            Log.i(TAG, "仍串扰，再换不带例子的提示：${out.take(30)}")
            out = generate(
                if (toEnglish) "Translate the user's Chinese into English. Output only the English translation."
                else "Translate the user's English into Simplified Chinese. Output only the Chinese translation.",
                src, maxTokens
            ).trim()
        }
        if (mixedScript(out, toEnglish)) Log.w(TAG, "多次尝试仍串扰，保留原样：$out")
        return out
    }

    /** 目标英文却含汉字 / 目标中文却没有汉字 → 串扰 */
    private fun mixedScript(out: String, toEnglish: Boolean): Boolean {
        if (out.isBlank()) return false
        return if (toEnglish) looksChinese(out) else !looksChinese(out)
    }

    fun ask(transcript: String, question: String, maxTokens: Int = 300): String =
        // 问答只要相关片段就够，prompt 越短预填充越快（手机上这一段最费时间）
        generate(MINUTES_SYSTEM, askPrompt(fit(transcript, maxChars = 1200), question), maxTokens)

    /**
     * 用**模型自带的对话模板**生成（JNI 侧通过 llama_model_chat_template 取，
     * MiniCPM5 / Qwen / Gemma 模板不同，硬编码会答非所问）。
     * stop 留空：结束交由模型的 eos/eot 处理。
     *
     * 思维链：JNI 侧已经按模板语义补了空的 `<think></think>`（关闭推理）；
     * 这里再做一层保险 —— 万一漏出 ` thinking…` 也直接剥掉，并把 Markdown 标记清成纯文本。
     */
    private fun generate(system: String, user: String, maxTokens: Int): String {
        if (handle == 0L) return ""
        return try {
            val raw = nativeGenerateChat(handle, system, user, maxTokens, "").trim()
            val noThink = LlmText.stripThinking(raw)
            if (noThink != raw) Log.i(TAG, "已剥离模型漏出的思维链内容（${raw.length - noThink.length} 字）")
            LlmText.toPlainText(noThink)
        } catch (e: Throwable) {
            Log.e(TAG, "生成失败", e)
            ""
        }
    }

    /** 线程数：按 CPU 核数来（预填充最吃多核），最多 6 个，留点核给界面 */
    private fun defaultThreads(): Int =
        Runtime.getRuntime().availableProcessors().coerceIn(2, 6)

    /** 上一次生成的分段耗时（"理解 x.xs / 生成 y.ys"），用于界面显示 */
    val lastStats: String
        get() = try {
            if (handle != 0L) nativeLastStats(handle) else ""
        } catch (_: Throwable) {
            ""
        }

    fun release() {
        if (handle != 0L) {
            try {
                nativeFree(handle)
            } catch (_: Throwable) {
            }
            handle = 0L
        }
    }

    private external fun nativeInit(modelPath: String, nCtx: Int, nThreads: Int): Long

    private external fun nativeLastStats(handle: Long): String
    private external fun nativeGenerateChat(
        handle: Long, system: String, user: String, maxTokens: Int, stop: String
    ): String
    private external fun nativeFree(handle: Long)
}
