package com.localrecord.app

import kotlin.math.log10
import kotlin.math.sqrt

/**
 * 音频质量判据（纯 Kotlin，不依赖 Android —— 所以能用 JVM 单元测试直接验证）。
 *
 * 背景：为了适配"手机麦克风原始电平只有 -55dB"这种低电平设备，VAD 不能写死绝对阈值
 * （写死就会把真实说话判成静音）。但只跟噪声底比又会放过噪声段（安静环境底噪极低时，
 * 任何比它高几 dB 的杂音都算"人声"），于是识别器会把噪声编成文字。
 *
 * 解决办法：不看绝对电平，看**这一段的动态范围**：
 *  * [quality] 返回 (信噪比 dB, 语音帧占比)。人说话时能量起伏大（p90 与 p10 差 12dB 以上），
 *    纯噪声（风扇、空调、键盘、电流底噪）则很平（差 2~6dB）；
 *  * [isNoiseOnly] 综合信噪比、语音帧占比、段长给出"这段该不该丢"。
 */
object AudioQuality {

    /** 语音帧占比下限：整段里至少要有这么多帧高于"噪声底 + 8dB" */
    const val MIN_SPEECH_RATIO = 0.20f

    /** 信噪比下限（dB）：低于这个基本就是稳态噪声 */
    const val MIN_SNR_DB = 8f

    /** 很短的段（<0.6 秒）要求更高的信噪比，避免"咔哒"一声被识别成字 */
    const val SHORT_SEG_SEC = 0.6f
    const val SHORT_SEG_MIN_SNR = 12f

    /**
     * 灵敏度档位：0=宽松 1=标准 2=严格。
     * 放宽/收紧的是**相对**门槛，不涉及绝对音量，所以对声音小的说话人（女声、气声、远场）
     * 依旧公平 —— 真正兜底的是下面的[harmonicity]（有声度）。
     */
    const val SENSITIVE = 0
    const val NORMAL = 1
    const val STRICT = 2

    private fun snrFloor(sensitivity: Int) = when (sensitivity) {
        SENSITIVE -> 5f
        STRICT -> 11f
        else -> 8f
    }

    private fun ratioFloor(sensitivity: Int) = when (sensitivity) {
        SENSITIVE -> 0.12f
        STRICT -> 0.30f
        else -> MIN_SPEECH_RATIO
    }


    /**
     * 段质量：(信噪比 dB, 语音帧占比)
     *
     * 信噪比 = 帧能量分布的 90 分位 − 10 分位（对稳态噪声很小、对语音很大）。
     * 语音帧占比 = 高于"10 分位 + 8dB"的帧比例。
     */
    fun quality(samples: FloatArray, sampleRate: Int = 16000): Pair<Float, Float> {
        val frame = (sampleRate * 0.02f).toInt().coerceAtLeast(64)
        val hop = (sampleRate * 0.01f).toInt().coerceAtLeast(32)
        if (samples.size < frame * 2) return 0f to 0f
        val n = 1 + (samples.size - frame) / hop
        val db = FloatArray(n)
        for (i in 0 until n) {
            val off = i * hop
            var sum = 0.0
            for (j in 0 until frame) {
                val v = samples[off + j].toDouble()
                sum += v * v
            }
            val rms = sqrt(sum / frame + 1e-12)
            db[i] = (20 * log10(rms + 1e-9)).toFloat()
        }
        val sorted = db.clone().apply { sort() }
        fun pct(p: Float) = sorted[(p * (n - 1)).toInt().coerceIn(0, n - 1)]
        val p10 = pct(0.10f)
        val p90 = pct(0.90f)
        val thr = p10 + 8f
        var hits = 0
        for (v in db) if (v > thr) hits++
        return (p90 - p10) to (hits.toFloat() / n)
    }

    /**
     * 有声度（谐波性）0~1：**与音量、音高都无关**的判据。
     *
     * 取能量最大的 40ms 帧做归一化自相关，在 lag 对应 **70~400Hz** 的范围内找峰值
     * （男声基频约 70~150Hz、女声约 200~400Hz 都在范围内）。
     * 说话（元音/浊音）周期性明显 → 峰值高（0.4~0.9）；稳态噪声 → 峰值低（<0.25）。
     *
     * 这一条是给"声音小 / 女声 / 远场"兜底的：哪怕能量低、SNR 不高，
     * 只要确实是有声语音，就不会被当成噪声丢掉。
     */
    fun harmonicity(samples: FloatArray, sampleRate: Int = 16000): Float {
        val frame = (sampleRate * 0.04f).toInt()
        if (samples.size < frame) return 0f
        // 找能量最大的那一帧（40ms，步长 20ms）
        val hop = frame / 2
        var bestOff = 0
        var bestE = -1.0
        var off = 0
        while (off + frame <= samples.size) {
            var e = 0.0
            for (i in 0 until frame) {
                val v = samples[off + i].toDouble()
                e += v * v
            }
            if (e > bestE) {
                bestE = e
                bestOff = off
            }
            off += hop
        }
        if (bestE <= 1e-12) return 0f
        val minLag = (sampleRate / 400f).toInt().coerceAtLeast(2)
        val maxLag = (sampleRate / 70f).toInt()
        // **先去直流（减均值）**：不去的正常数信号自相关恒为 1，
        // 会把"咔哒/直流跳变/削顶"误判成有声语音（实测踩过）。
        var mean = 0.0
        for (i in 0 until frame) mean += samples[bestOff + i]
        mean /= frame
        val x = DoubleArray(frame) { samples[bestOff + it] - mean }
        var r0 = 0.0
        for (i in 0 until frame) r0 += x[i] * x[i]
        if (r0 <= 1e-12) return 0f
        var best = 0.0
        for (lag in minLag..maxLag) {
            var r = 0.0
            var e1 = 0.0
            var e2 = 0.0
            for (i in 0 until frame - lag) {
                val a = x[i]
                val b = x[i + lag]
                r += a * b
                e1 += a * a
                e2 += b * b
            }
            val denom = sqrt(e1 * e2) + 1e-12
            val norm = r / denom
            if (norm > best) best = norm
        }
        return best.toFloat().coerceIn(0f, 1f)
    }

    /**
     * 过零率（每秒过零次数）。
     *
     * 用途：挡掉**直流跳变 / 阶跃 / 极低频轰鸣**。这类信号的自相关天然很高
     * （阶跃自己跟自己高度相关，实测有声度 0.70），光去均值挡不住；
     * 但它们几乎没有过零，而语音（含浊音）每秒过零 100~600 次。
     */
    fun zeroCrossRate(samples: FloatArray, sampleRate: Int = 16000): Float {
        if (samples.size < 2) return 0f
        var mean = 0.0
        for (v in samples) mean += v
        mean /= samples.size
        var crossings = 0
        var prev = samples[0] - mean
        for (i in 1 until samples.size) {
            val cur = samples[i] - mean
            if ((prev <= 0 && cur > 0) || (prev >= 0 && cur < 0)) crossings++
            prev = cur
        }
        return crossings.toFloat() / (samples.size.toFloat() / sampleRate)
    }

    /** 语音的过零率下限（次/秒）：低于这个基本是直流/低频噪声 */
    const val MIN_ZCR = 15f

    /**
     * 纯噪声段（应当丢弃，不送去识别）。
     *
     * 判定顺序（先看"有没有声"，再看"信噪比够不够"）：
     *  1. 明确的有声语音（harmonicity ≥0.35 且段长 ≥0.3s 且**过零率 ≥15/s**）→ 一定留住
     *     （声音小、女声、远场都能靠这条过）；
     *  2. 否则再看信噪比/语音帧占比/段长。
     */
    fun isNoiseOnly(samples: FloatArray, sampleRate: Int = 16000, sensitivity: Int = NORMAL): Boolean {
        val (snr, ratio) = quality(samples, sampleRate)
        val harm = harmonicity(samples, sampleRate)
        val zcr = zeroCrossRate(samples, sampleRate)
        val sec = samples.size.toFloat() / sampleRate
        if (harm >= 0.35f && sec >= 0.3f && zcr >= MIN_ZCR) return false
        if (snr < snrFloor(sensitivity)) return true
        if (ratio < ratioFloor(sensitivity)) return true
        if (sec < SHORT_SEG_SEC && snr < SHORT_SEG_MIN_SNR) return true
        return false
    }

}
