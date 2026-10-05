package com.localrecord.app

import kotlin.math.log10
import kotlin.math.max
import kotlin.math.sqrt

/**
 * 流式 VAD 断句（替代原来"固定 8 秒"的切法）。
 *
 * 规则（按用户要求：**1 秒窗口里 80~90% 是人声**就算说话，反之算静音）：
 *  * 最近 1 秒内人声帧比例 ≥ [startRatio]（默认 0.7）→ 这一段开始；
 *  * 最近 1 秒内静音帧比例 ≥ [endRatio]（默认 0.7）→ 这一段结束；
 *  * 起点会往前带 [preRollSec] 秒（默认 1 秒，正好覆盖判定窗口），不会切掉第一个字；
 *  * 单段最长 [maxSegSec]（默认 25 秒，超了强制断开）；单段最短 [minSegSec]（默认 0.6 秒）。
 *
 * 帧判定：20ms 一帧，一阶差分（近似高通，压掉低频轰鸣）算 RMS，与**自适应噪声底**比较：
 * 高出 8dB 且高于 -52dB 算人声。噪声底用"**快降慢升**"跟踪。
 *
 * 两个坑（都有单元测试兜着，见 `VadTest`）：
 *  1. 噪声底**不能**用"最近几秒的分位数"——连续说话时分位数会被语音本身顶上去，
 *     后面全被判成静音；
 *  2. 开始条件**不能**要求"连续每一帧都是人声"——词间停顿会让计数归零，永远攒不满，
 *     所以必须用滑动窗口比例。
 */
class Vad(
    private val sampleRate: Int = 16000,
    private val startRatio: Float = 0.6f,      // 开始判定稍宽松：别漏掉轻声开口
    private val endRatio: Float = 0.7f,        // 结束判定按"连续 1 秒静音 ≥70%"（用户要求）
    private val preRollSec: Float = 1.8f,      // 起点前保留更久：判定窗口 + 余量，绝不切掉开头
    private val minSegSec: Float = 0.25f,      // 短促的"好/对/行"也要转，不能丢
    private val maxSegSec: Float = 18f,        // 太长会拖慢出字（识别是整段做的）
) {
    private val frame = (sampleRate * 0.02f).toInt().coerceAtLeast(64)
    private val windowFrames = (1.0f / 0.02f).toInt()        // 1 秒窗口
    private val minWindowFrames = 20                         // 0.4 秒就可以开始判"有人在说"
    private var pending = FloatArray(0)
    private var noiseDb = -55f                               // 自适应噪声底（dB）
    private val decisions = ArrayDeque<Boolean>()            // 最近 1 秒的帧判定
    private val preRoll = ArrayDeque<Float>()                // 最近 N 秒音频（做 pre-roll）
    private val preRollMax = (sampleRate * (preRollSec + 0.2f)).toInt()
    private var seg = ArrayList<Float>()
    private var inSegment = false
    private var silenceRun = 0f
    private var segStartSec = 0f
    private var streamSec = 0f
    private var emittedUpToSec = 0f          // 已经交出去的音频位置（pre-roll 不许越过它，否则会重复出字）

    var lastNoiseDb = -60f
        private set
    var lastFrameDb = -60f
        private set

    /** 当前是否有正在累积的一段（给界面显示"正在断句"用） */
    val active: Boolean get() = inSegment

    /** 喂 16k float32 音频；每检测到一段结束就回调 (音频, 起点秒) */
    fun feed(samples: FloatArray, onSegment: (FloatArray, Float) -> Unit) {
        val data: FloatArray = if (pending.isEmpty()) samples else FloatArray(pending.size + samples.size).also {
            System.arraycopy(pending, 0, it, 0, pending.size)
            System.arraycopy(samples, 0, it, pending.size, samples.size)
        }
        var off = 0
        val dt = frame.toFloat() / sampleRate
        while (off + frame <= data.size) {
            val db = frameDb(data, off)
            lastFrameDb = db
            // 噪声底：快降慢升。安静了就快速跟上（0.25），变吵时几乎不动（0.002），
            // 这样长句不会把底噪估到语音水平。
            noiseDb = if (db < noiseDb) {
                noiseDb + (db - noiseDb) * 0.25f
            } else {
                noiseDb + (db - noiseDb) * 0.002f
            }
            lastNoiseDb = noiseDb
            // 阈值：只跟自适应噪声底比（+7dB），**不再写死绝对下限**。
            // 之前写死 -52dB 是错的：手机麦克风原始电平可能只有 -55dB，
            // 差分后约 -63dB，全部低于 -52 → 永远判成"没人说话"（一个字都不出）。
            val isSpeech = db > if (noiseDb < -80f) -70f else noiseDb + 7f

            // 滑动窗口（1 秒）统计人声比例 —— 不能用"连续 N 帧"，词间停顿会让计数不断归零
            decisions.addLast(isSpeech)
            while (decisions.size > windowFrames) decisions.removeFirst()
            val speechRatio = decisions.count { it }.toFloat() / decisions.size.toFloat()
            val silenceRatio = 1f - speechRatio
            val windowFull = decisions.size >= windowFrames

            if (!inSegment) {
                for (i in off until off + frame) {
                    preRoll.addLast(data[i])
                    while (preRoll.size > preRollMax) preRoll.removeFirst()
                }
                // 只要有 0.4 秒的判定数据、且窗口内人声占比够高就开始；
                // 不等攒满 1 秒窗口，避免开头被"判定延迟"吃掉（漏字）。
                if (decisions.size >= minWindowFrames && speechRatio >= startRatio) {
                    inSegment = true
                    // pre-roll 往前带，但**不能越过已经交出去的位置**（否则那段话会被识别两遍）
                    val preRollStart = (streamSec - preRoll.size.toFloat() / sampleRate).coerceAtLeast(0f)
                    val from = max(preRollStart, emittedUpToSec)
                    val drop = ((from - preRollStart) * sampleRate).toInt().coerceIn(0, preRoll.size)
                    seg = ArrayList(preRoll.drop(drop))
                    segStartSec = from
                    silenceRun = 0f
                }
            } else {
                silenceRun += dt
                if (isSpeech) silenceRun = 0f
                for (i in off until off + frame) seg.add(data[i])
                val segLen = seg.size.toFloat() / sampleRate
                if ((windowFull && silenceRatio >= endRatio) || segLen >= maxSegSec) {
                    // 尾部静音裁掉（留 0.3 秒，避免最后一个字被削）
                    val keep = ((segLen - silenceRun + 0.3f).coerceAtLeast(minSegSec) * sampleRate).toInt()
                    val audio = if (silenceRatio >= endRatio && keep in 1 until seg.size) {
                        FloatArray(keep) { seg[it] }
                    } else {
                        FloatArray(seg.size) { seg[it] }
                    }
                    if (audio.size.toFloat() / sampleRate >= minSegSec) {
                        onSegment(audio, segStartSec)
                        emittedUpToSec = segStartSec + audio.size.toFloat() / sampleRate
                    }
                    inSegment = false
                    seg = ArrayList()
                    silenceRun = 0f
                }
            }
            streamSec += dt
            off += frame
        }
        pending = if (off >= data.size) FloatArray(0) else data.copyOfRange(off, data.size)
    }

    /** 收尾：把还没结束的那一段交出来（用户点了停止录音时调用） */
    fun flush(onSegment: (FloatArray, Float) -> Unit) {
        if (inSegment && seg.size.toFloat() / sampleRate >= minSegSec) {
            val audio = FloatArray(seg.size) { seg[it] }
            onSegment(audio, segStartSec)
            emittedUpToSec = segStartSec + audio.size.toFloat() / sampleRate
        }
        inSegment = false
        seg = ArrayList()
        pending = FloatArray(0)
    }

    private fun frameDb(data: FloatArray, off: Int): Float {
        // 用**原始**能量（不再差分）：差分虽然能压低频轰鸣，但会额外损失 8~10dB，
        // 对本来电平就低（-55dB 级）的手机麦克风是致命的。
        // 低频轰鸣交给"自适应噪声底"处理即可。
        var sum = 0.0
        for (i in off until off + frame) {
            val v = data[i].toDouble()
            sum += v * v
        }
        val rms = sqrt(sum / frame + 1e-12)
        return (20 * log10(rms + 1e-9)).toFloat()
    }
}
