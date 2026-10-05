package com.localrecord.app

import android.util.Log
import com.k2fsa.sherpa.onnx.SileroVadModelConfig
import com.k2fsa.sherpa.onnx.Vad
import com.k2fsa.sherpa.onnx.VadModelConfig
import java.io.File

/**
 * 神经网络 VAD（Silero，经 sherpa-onnx 的 C++ 实现，和电脑端的 Python 验证是同一套代码）。
 *
 * 为什么用它替代手写能量法：能量/信噪比/有声度那一套本质上是在"漏字"和"噪声出字"之间做权衡，
 * 永远要调参。Silero 是专门训练来区分语音/噪声/音乐的，实测（电脑端，同一模型）：
 * ```
 * 纯语音：1 段，0.16s 起 + 4.53s      ← 精确覆盖说话部分
 * 纯噪声：0 段                        ← 完全不误报
 * 混合（噪-语-噪-语-噪）：2 段，3.17s 起 / 10.46s 起   ← 3 秒噪声被正确跳过
 * ```
 *
 * 本类还负责两件"用户体验"上的事：
 *  1. **段前补白 0.35 秒**（见 [PREROLL_SEC]）—— 神经网络 VAD 要确认 0.2~0.25 秒才判定成段，
 *     说话开头那一点（尤其轻声辅音）会落在段外，听起来就是"漏第一个字"；
 *  2. **记录每段的"人声帧证据"**（[lastSpeechWindows] / [lastSpeechRatio]）—— 按 512 采样
 *     （32ms）逐窗询问 VAD"这窗是人声吗"，这样上层判断"要不要丢这段文字"时看的是
 *     **音频证据**（人声帧数/占比），而不是"文字像不像噪声"（后者会把"哈哈哈"这种真话误杀）。
 */
class SileroVad(private val store: ModelStore) {

    companion object {
        private const val TAG = "SileroVad"
        const val SAMPLE_RATE = 16000

        /** 一帧的采样数（Silero 要求 512） */
        private const val WIN = 512

        /** 判定阈值：0.5 是官方推荐起点；这里用 0.45 让它**更早**发现语音起点（少漏字） */
        private const val THRESHOLD = 0.45f

        /** 停这么久没声就算一段结束 */
        private const val MIN_SILENCE = 0.6f

        /** 至少说这么久才算一段（太小会把咳嗽/敲桌子也切出来；0.2 秒兼顾"别漏开头"） */
        private const val MIN_SPEECH = 0.2f

        /** 单段上限：太长会拖慢出字（识别是整段做的） */
        private const val MAX_SPEECH = 18f

        /**
         * **段前补多少音频**（秒）——修"漏第一个字"。
         *
         * 补白不超过上一段的结束位置，所以不会重复内容。
         */
        private const val PREROLL_SEC = 0.35f
    }

    private var vad: Vad? = null

    // ---- 段前补白用的环形缓冲（保存最近 PREROLL_SEC 秒的音频）----
    private val ringSize = (SAMPLE_RATE * PREROLL_SEC).toInt()
    private val ring = FloatArray(ringSize)
    private var ringCount = 0          // 缓冲里已有的样本数（<= ringSize）
    private var ringWrite = 0          // 下一个写入位置
    private var streamPos = 0L         // 已喂进 VAD 的样本总数（绝对位置）
    private var lastEnd = 0L           // 上一段结束的绝对位置，避免补白时重复上一段
    private var carry = FloatArray(0)  // 不足一窗的残留样本（保证每次只喂整窗）

    // ---- 逐窗"是否人声"记录（环形，容量足够覆盖最长段 18 秒 + 补白）----
    private val flagSlots = 1024
    private val speechFlags = BooleanArray(flagSlots)
    private var flagOldest = 0L        // 还留着的最早窗序号
    private var flagNext = 0L          // 下一个待记录窗序号

    /** 最近一段（VAD 自己判定的人声范围，不含补白）里被判为人声的窗数 */
    var lastSpeechWindows = 0
        private set

    /** 最近一段里人声窗占比（0~1） */
    var lastSpeechRatio = 0f
        private set

    val ready: Boolean get() = vad != null

    fun init(): Boolean {
        if (vad != null) return true
        val model: File = store.vadModel()
        if (!model.isFile) {
            Log.w(TAG, "没有 VAD 模型（${model.absolutePath}），将退回能量法断句")
            return false
        }
        return try {
            val config = VadModelConfig(
                sileroVadModelConfig = SileroVadModelConfig(
                    model = model.absolutePath,
                    threshold = THRESHOLD,
                    minSilenceDuration = MIN_SILENCE,
                    minSpeechDuration = MIN_SPEECH,
                    windowSize = WIN,
                    maxSpeechDuration = MAX_SPEECH,
                ),
                sampleRate = SAMPLE_RATE,
                numThreads = 1,
            )
            vad = Vad(config = config)
            Log.i(TAG, "Silero VAD 就绪：${model.name}")
            true
        } catch (e: Throwable) {
            Log.e(TAG, "Silero VAD 加载失败，退回能量法", e)
            vad = null
            false
        }
    }

    /** 每次开始录音/转写前重置内部状态（同一个实例会被反复用） */
    fun reset() {
        try {
            vad?.reset()
        } catch (_: Throwable) {
        }
        ringCount = 0
        ringWrite = 0
        streamPos = 0L
        lastEnd = 0L
        carry = FloatArray(0)
        flagOldest = 0L
        flagNext = 0L
        lastSpeechWindows = 0
        lastSpeechRatio = 0f
    }

    fun release() {
        try {
            vad?.release()
        } catch (_: Throwable) {
        }
        vad = null
    }

    /** 流式喂音频；每切出一段就回调 (音频, 起点秒)。段的人声证据见 [lastSpeechWindows]/[lastSpeechRatio] */
    fun feed(samples: FloatArray, onSegment: (FloatArray, Float) -> Unit) {
        val v = vad ?: return
        if (samples.isEmpty()) return
        // 先存进环形缓冲（供补白用）
        pushRing(samples)
        // 拼上上次的残留，凑成整窗再喂：这样每喂一窗就能问一次"这窗是人声吗"
        val buf = if (carry.isEmpty()) samples else FloatArray(carry.size + samples.size).also {
            System.arraycopy(carry, 0, it, 0, carry.size)
            System.arraycopy(samples, 0, it, carry.size, samples.size)
        }
        var off = 0
        while (off + WIN <= buf.size) {
            val win = buf.copyOfRange(off, off + WIN)
            v.acceptWaveform(win)
            streamPos += WIN
            recordSpeechFlag(streamPos / WIN - 1, v.isSpeechDetected())
            off += WIN
        }
        carry = if (off == buf.size) FloatArray(0) else buf.copyOfRange(off, buf.size)
        drain(v, onSegment)
    }

    /** 收尾：把最后一段交出来（停止录音/文件读完时调用） */
    fun flush(onSegment: (FloatArray, Float) -> Unit) {
        val v = vad ?: return
        try {
            v.flush()
        } catch (_: Throwable) {
        }
        drain(v, onSegment)
    }

    private fun pushRing(samples: FloatArray) {
        for (x in samples) {
            ring[ringWrite] = x
            ringWrite++
            if (ringWrite >= ringSize) ringWrite = 0
            if (ringCount < ringSize) ringCount++
        }
    }

    /** 取绝对位置 [from, to) 的样本（取不到的部分用静音补齐） */
    private fun ringSlice(from: Long, to: Long): FloatArray {
        val n = (to - from).toInt()
        if (n <= 0) return FloatArray(0)
        val out = FloatArray(n)
        val oldest = streamPos - ringCount          // 缓冲区里最早那个样本的绝对位置
        val abs = if (from < oldest) oldest else from
        val skip = (abs - from).toInt()             // 太早的部分取不到 → 补静音
        var idx = ((abs % ringSize) + ringSize) % ringSize
        var i = skip
        while (i < n) {
            out[i] = ring[idx.toInt()]
            idx++
            if (idx >= ringSize) idx = 0
            i++
        }
        return out
    }

    private fun recordSpeechFlag(idx: Long, isSpeech: Boolean) {
        speechFlags[(idx % flagSlots).toInt()] = isSpeech
        if (idx + 1 > flagNext) flagNext = idx + 1
        val oldestAllowed = flagNext - flagSlots
        if (flagOldest < oldestAllowed) flagOldest = oldestAllowed
    }

    /** 统计绝对样本区间 [fromSample, toSample) 里的人声窗数与人声占比 */
    private fun speechStats(fromSample: Long, toSample: Long): Pair<Int, Float> {
        val w0 = fromSample / WIN
        val w1 = (toSample + WIN - 1) / WIN
        var total = 0
        var hit = 0
        var w = if (w0 > flagOldest) w0 else flagOldest
        while (w < w1) {
            total++
            if (speechFlags[(w % flagSlots).toInt()]) hit++
            w++
        }
        val ratio = if (total <= 0) 0f else hit.toFloat() / total
        return hit to ratio
    }

    private fun drain(v: Vad, onSegment: (FloatArray, Float) -> Unit) {
        var guard = 0
        while (!v.empty() && guard++ < 1000) {
            try {
                val seg = v.front()
                val raw = seg.samples
                val segStart = seg.start.toLong()
                val segEnd = segStart + raw.size
                // 人声证据：只看 VAD 自己判定的范围（不含补白，补白是静音会稀释占比）
                val (hit, ratio) = speechStats(segStart, segEnd)
                lastSpeechWindows = hit
                lastSpeechRatio = ratio
                // 段前补白：起点往前推 0.35 秒，但不超过上一段结束位置
                val from = maxOf(lastEnd, segStart - ringSize)
                val pad = if (segStart > from) ringSlice(from, segStart) else FloatArray(0)
                val out = if (pad.isEmpty()) raw else FloatArray(pad.size + raw.size).also {
                    System.arraycopy(pad, 0, it, 0, pad.size)
                    System.arraycopy(raw, 0, it, pad.size, raw.size)
                }
                if (out.isNotEmpty()) {
                    Log.d(
                        TAG,
                        "分段：%.2fs 起 +%.2fs（补白 %.2fs，人声 %d 窗 / %.0f%%）".format(
                            from.toFloat() / SAMPLE_RATE,
                            out.size.toFloat() / SAMPLE_RATE,
                            pad.size.toFloat() / SAMPLE_RATE,
                            hit,
                            ratio * 100,
                        )
                    )
                    onSegment(out, from.toFloat() / SAMPLE_RATE)
                }
                lastEnd = maxOf(lastEnd, segEnd)
            } catch (t: Throwable) {
                Log.w(TAG, "取分段失败：${t.message}")
                break
            } finally {
                try {
                    v.pop()
                } catch (_: Throwable) {
                }
            }
        }
    }
}
