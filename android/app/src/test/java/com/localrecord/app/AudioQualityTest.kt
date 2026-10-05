package com.localrecord.app

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.PI
import kotlin.math.sin
import kotlin.random.Random

/**
 * 音频质量判据的 JVM 单元测试（不需要模拟器）。
 *
 * 目标：**真说话要留住**（哪怕手机麦克风电平只有 -55dB），**纯噪声要丢掉**。
 */
class AudioQualityTest {

    private val sr = 16000

    /** 模拟人声：基频 + 谐波，带 4Hz 音节包络（说话时的能量起伏） */
    private fun speechLike(seconds: Float, level: Float, seed: Int = 1, f0: Float = 130f): FloatArray {
        val n = (sr * seconds).toInt()
        val rnd = Random(seed)
        return FloatArray(n) { i ->
            val t = i.toFloat() / sr
            val env = (0.25f + 0.75f * (0.5f - 0.5f * kotlin.math.cos(2f * PI.toFloat() * 4f * t)))
            var v = 0f
            for (h in 1..12) {
                v += (1f / h) * sin(2f * PI.toFloat() * f0 * h * t + h * 0.7f)
            }
            v *= env * level
            v + (rnd.nextFloat() - 0.5f) * level * 0.05f      // 一点本底
        }
    }

    @Test
    fun femaleAndQuietVoicesAreKept() {
        // 用户担心："靠电平判断，女声怎么办？"
        // 女声基频高（约 220~300Hz）且同距离下通常更小声，必须照样留住。
        val cases = listOf(
            Triple("女声 f0=220Hz 小声", 220f, 0.0009f),      // ≈ -58 dBFS
            Triple("女声 f0=300Hz 很小声", 300f, 0.0005f),    // ≈ -63 dBFS
            Triple("男声 f0=110Hz 小声", 110f, 0.0009f),
            Triple("男声 f0=130Hz 正常", 130f, 0.003f),
        )
        for ((label, f0, level) in cases) {
            val s = speechLike(3.0f, level, f0 = f0)
            val (snr, ratio) = AudioQuality.quality(s, sr)
            val harm = AudioQuality.harmonicity(s, sr)
            val dropped = AudioQuality.isNoiseOnly(s, sr)
            println("$label：snr=${"%.1f".format(snr)}dB ratio=${"%.2f".format(ratio)} 有声度=${"%.2f".format(harm)} → ${if (dropped) "丢弃" else "保留"}")
            assertTrue("$label 不该被当成噪声丢掉（有声度 %.2f）".format(harm), !dropped)
        }
    }

    @Test
    fun femaleVoiceMixedWithNoiseIsKept() {
        // 更接近现实：女声 + 不低的环境噪声（SNR 只有几 dB），仍应保留（靠有声度兜底）
        val speech = speechLike(3.0f, 0.0025f, f0 = 240f)
        val noise = noiseLike(3.0f, 0.0012f, seed = 9)
        val mix = FloatArray(speech.size) { speech[it] + noise[it] }
        val (snr, ratio) = AudioQuality.quality(mix, sr)
        val harm = AudioQuality.harmonicity(mix, sr)
        println("女声+噪声：snr=${"%.1f".format(snr)}dB ratio=${"%.2f".format(ratio)} 有声度=${"%.2f".format(harm)}")
        assertTrue("有噪声环境下的女声不该被丢", !AudioQuality.isNoiseOnly(mix, sr))
    }

    @Test
    fun harmonicitySeparatesVoicedFromNoise() {
        val voiced = speechLike(1.5f, 0.003f, f0 = 250f)
        val noise = noiseLike(1.5f, 0.003f)
        val hv = AudioQuality.harmonicity(voiced, sr)
        val hn = AudioQuality.harmonicity(noise, sr)
        println("有声度：语音=${"%.2f".format(hv)} 噪声=${"%.2f".format(hn)}")
        assertTrue("语音有声度应明显高于噪声", hv > hn + 0.2f)
        // 关键：噪声的有声度必须**低于保留下限 0.35**，否则噪声会被误留
        for (lvl in listOf(0.001f, 0.003f, 0.01f, 0.05f)) {
            val h = AudioQuality.harmonicity(noiseLike(2.0f, lvl, seed = 5), sr)
            println("  噪声 level=$lvl 有声度=${"%.2f".format(h)}")
            assertTrue("噪声的有声度必须低于 0.35（level=$lvl，实测 $h）", h < 0.35f)
        }
    }

    /** 模拟稳态噪声：白噪声（风扇/空调/电流底噪的近似） */
    private fun noiseLike(seconds: Float, level: Float, seed: Int = 2): FloatArray {
        val rnd = Random(seed)
        return FloatArray((sr * seconds).toInt()) { (rnd.nextFloat() - 0.5f) * 2f * level }
    }

    @Test
    fun speechAtLowLevelIsKept() {
        // 用户实测：麦克风原始电平只有 -55dB 左右，这种低电平必须仍然判为"有人说话"
        val level = 0.0018f                                  // ≈ -55 dBFS
        val speech = speechLike(3.0f, level)
        val (snr, ratio) = AudioQuality.quality(speech, sr)
        println("低电平语音：snr=${"%.1f".format(snr)}dB ratio=${"%.2f".format(ratio)}")
        assertTrue("低电平语音不应被判成噪声", !AudioQuality.isNoiseOnly(speech, sr))
    }

    @Test
    fun stationaryNoiseIsRejected() {
        for (lvl in listOf(0.001f, 0.003f, 0.01f)) {         // 不同响度的稳态噪声
            val noise = noiseLike(3.0f, lvl)
            val (snr, ratio) = AudioQuality.quality(noise, sr)
            println("噪声 level=$lvl：snr=${"%.1f".format(snr)}dB ratio=${"%.2f".format(ratio)}")
            assertTrue("稳态噪声应被判成噪声（level=$lvl）", AudioQuality.isNoiseOnly(noise, sr))
        }
    }

    @Test
    fun shortClickIsRejected() {
        // 极短的低信噪比"咔哒"（敲桌子、放杯子）不该送去识别
        val n = (sr * 0.3f).toInt()
        val click = FloatArray(n) { i -> if (i in 100..300) 0.05f else 0.0005f }
        println("短促直流跳变：snr=${"%.1f".format(AudioQuality.quality(click, sr).first)}dB 有声度=${"%.2f".format(AudioQuality.harmonicity(click, sr))}")
        assertTrue("直流跳变应被丢弃", AudioQuality.isNoiseOnly(click, sr))

        // 更真实的"咔哒/敲桌子"：**宽带**脉冲 + 快速衰减（自相关低、无声调）
        // 注意：不能用交替 ±1 的方波——那不是咔哒，是 8kHz 蜂鸣，
        // 它在偶数 lag 上自相关=1，本来就会被当"有声"（这类蜂鸣靠神经网络 VAD 挡）。
        val burst = FloatArray(n) { i ->
            val t = (i - 100).coerceAtLeast(0)
            if (i < 100) 0.0004f
            else {
                val broadband = Random(i * 31 + 7).nextFloat() - 0.5f
                0.12f * kotlin.math.exp(-t / 40f) * broadband
            }
        }
        println("宽带敲击：有声度=${"%.2f".format(AudioQuality.harmonicity(burst, sr))} 过零率=${"%.0f".format(AudioQuality.zeroCrossRate(burst, sr))}/s")
        assertTrue("宽带敲击应被丢弃", AudioQuality.isNoiseOnly(burst, sr))
    }
    // 文本层面的"噪声幻觉"判断已移到 TextFilter（见 TextFilterTest）
}
