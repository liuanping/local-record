package com.localrecord.app

import android.util.Log
import com.k2fsa.sherpa.onnx.FeatureConfig
import com.k2fsa.sherpa.onnx.OfflineModelConfig
import com.k2fsa.sherpa.onnx.OfflineParaformerModelConfig
import com.k2fsa.sherpa.onnx.OfflinePunctuation
import com.k2fsa.sherpa.onnx.OfflinePunctuationConfig
import com.k2fsa.sherpa.onnx.OfflinePunctuationModelConfig
import com.k2fsa.sherpa.onnx.OfflineRecognizer
import com.k2fsa.sherpa.onnx.OfflineRecognizerConfig
import java.io.File
import java.io.RandomAccessFile
import kotlin.math.abs
import kotlin.math.log10
import kotlin.math.max
import kotlin.math.sqrt

/**
 * 离线语音识别（sherpa-onnx + Paraformer zh int8）+ 标点恢复（CT-Transformer）。
 *
 * 与电脑版保持同一套判定逻辑，避免"没人说话却识别出文字"：
 *  * 静音判定：自适应能量法（噪声底以上帧占比 < 6% 视为没人说话，直接不送模型）
 *  * 结果过滤：只有语气词、或连续 ≥4 个相同字（噪声幻觉）时丢弃
 */
class AsrEngine(private val store: ModelStore) {

    companion object {
        private const val TAG = "AsrEngine"
        const val SAMPLE_RATE = 16000
        const val SPEECH_MIN_RATIO = 0.06f
        private const val PUNCT_CHARS = "，。、！？；：（）《》〈〉【】「」『』…—～·,.!?;:\"'()[]{}<>- "
    }

    private var recognizer: OfflineRecognizer? = null
    private var punct: OfflinePunctuation? = null

    val ready: Boolean get() = recognizer != null
    val punctReady: Boolean get() = punct != null

    fun init(): Boolean {
        if (recognizer != null) return true
        if (!store.asrReady()) {
            Log.w(TAG, "模型文件不齐：期望 ${store.asrModel().absolutePath}（存在=" +
                    "${store.asrModel().isFile}）与 ${store.asrTokens().absolutePath}（存在=" +
                    "${store.asrTokens().isFile}）")
            return false
        }
        Log.i(TAG, "开始加载模型：${store.asrModel().absolutePath}")
        return try {
            val config = OfflineRecognizerConfig(
                featConfig = FeatureConfig(sampleRate = SAMPLE_RATE, featureDim = 80),
                modelConfig = OfflineModelConfig(
                    paraformer = OfflineParaformerModelConfig(model = store.asrModel().absolutePath),
                    tokens = store.asrTokens().absolutePath,
                    numThreads = 4,
                    provider = "cpu",
                    debug = false,
                ),
                decodingMethod = "greedy_search",
            )
            recognizer = OfflineRecognizer(config = config)
            if (store.punctReady()) {
                punct = try {
                    OfflinePunctuation(
                        config = OfflinePunctuationConfig(
                            model = OfflinePunctuationModelConfig(
                                ctTransformer = store.punctModel().absolutePath,
                                numThreads = 1, debug = false,
                            )
                        )
                    )
                } catch (e: Throwable) {
                    Log.w(TAG, "标点模型加载失败，继续用不带标点的结果：${e.message}")
                    null
                }
            }
            Log.i(TAG, "ASR 就绪：${store.asrModel().absolutePath}")
            true
        } catch (e: Throwable) {
            Log.e(TAG, "ASR 初始化失败", e)
            recognizer = null
            false
        }
    }

    fun release() {
        punct?.release(); punct = null
        recognizer?.release(); recognizer = null
    }

    /**
     * 识别一段音频（float32，16kHz），返回带标点的文本。
     *
     * **必须加锁**：实时转写线程和"转写已有录音"线程可能同时在跑，
     * sherpa-onnx 的 recognizer 不是线程安全的，并发 decode 会让识别直接失效
     * （症状：第一次有结果，之后再也出不来）。
     */
    @Synchronized
    fun recognize(samples: FloatArray): String {
        val rec = recognizer ?: return ""
        var stream: com.k2fsa.sherpa.onnx.OfflineStream? = null
        val text = try {
            stream = rec.createStream()
            stream.acceptWaveform(samples, SAMPLE_RATE)
            rec.decode(stream)
            rec.getResult(stream).text
        } catch (e: Throwable) {
            Log.e(TAG, "识别失败", e)
            ""
        } finally {
            try {
                stream?.release()      // 异常时也要释放，否则 native 内存泄漏
            } catch (_: Throwable) {
            }
        }
        val clean = text.replace(Regex("<\\|[^|]*\\|>"), "").trim()
        if (clean.isEmpty()) return ""
        return punct?.let {
            try { it.addPunctuation(clean) ?: clean } catch (e: Throwable) { clean }
        } ?: clean
    }

    // ------------------------------------------------------------ 判定 ----

    /**
     * 这段音频里有没有人声：噪声底以上帧占比 ≥ minRatio。
     *
     * 判据统一放在 [AudioQuality]（纯 Kotlin，有 JVM 单元测试）：
     * 用"原始能量 + 自适应噪声底"，**不写死绝对下限**（写死会把低电平麦克风的真实说话判成静音）。
     */
    fun speechPresent(samples: FloatArray, minRatio: Float = AudioQuality.MIN_SPEECH_RATIO): Boolean {
        val (_, ratio) = AudioQuality.quality(samples, SAMPLE_RATE)
        return ratio >= minRatio
    }

    // 说明：原来这里有两个"激进过滤"函数（isMeaningless 把 3 字以内的语气词当无效、
    // looksLikeHallucination 把连续 4 个相同字当幻觉），导致"哈哈哈""哈哈哈哈"这种
    // **真实说的话**被丢掉（用户反馈）。现已统一改用 [TextFilter]：
    // 正常说话一律展示，"噪声幻觉"规则只在低信噪比段生效。

    // ------------------------------------------------------ 文件转写 ----

    data class Segment(val text: String, val startSec: Float, val endSec: Float)

    /**
     * 转写已有 wav（16bit PCM）。返回 (有效段, 跳过的段数)。
     * 用于"用手机别的 App 录好/电脑录好再导入转写"的场景。
     *
     * **和实时录音用同一个 VAD 切段**（原来这里是固定 8 秒一刀切，会从词中间切断导致漏字）。
     */
    fun transcribe(
        wav: File,
        onSegment: (Segment) -> Unit = {},
        shouldStop: () -> Boolean = { false },
    ): Pair<Int, Int> {
        val (samples, _) = readWav(wav) ?: return 0 to 0
        val vad = Vad(SAMPLE_RATE)
        var emitted = 0
        var skipped = 0

        fun handle(seg: FloatArray, startSec: Float) {
            var peak = 0f
            for (v in seg) {
                val a = abs(v)
                if (a > peak) peak = a
            }
            if (peak < 0.002f || !speechPresent(seg)) {
                skipped++
                return
            }
            val gain = if (peak > 0.05f) 0.9f / peak else 1f
            if (gain != 1f) for (j in seg.indices) seg[j] *= gain
            val text = recognize(seg)
            if (text.isNotEmpty() && !TextFilter.shouldDrop(text, lowSnr = false)) {
                onSegment(
                    Segment(text, startSec, startSec + seg.size.toFloat() / SAMPLE_RATE)
                )
                emitted++
            } else skipped++
        }

        val block = SAMPLE_RATE / 10                     // 100ms 一块喂进去
        var i = 0
        while (i < samples.size) {
            if (shouldStop()) break
            val end = minOf(i + block, samples.size)
            vad.feed(samples.copyOfRange(i, end)) { seg, start -> handle(seg, start) }
            i = end
        }
        vad.flush { seg, start -> handle(seg, start) }
        return emitted to skipped
    }

    /** 读 16bit PCM wav（单/多声道都行），返回 (float 采样, 采样率) */
    fun readWav(file: File): Pair<FloatArray, Int>? = try {
        RandomAccessFile(file, "r").use { raf ->
            val header = ByteArray(44)
            raf.readFully(header)
            val channels = (header[22].toInt() and 0xFF) or ((header[23].toInt() and 0xFF) shl 8)
            val sampleRate = (header[24].toInt() and 0xFF) or ((header[25].toInt() and 0xFF) shl 8) or
                ((header[26].toInt() and 0xFF) shl 16) or ((header[27].toInt() and 0xFF) shl 24)
            val dataLen = (raf.length() - 44).toInt()
            val raw = ByteArray(dataLen)
            raf.readFully(raw)
            val frames = dataLen / 2 / max(1, channels)
            val out = FloatArray(frames)
            for (i in 0 until frames) {
                var acc = 0f
                for (c in 0 until channels) {
                    val idx = (i * channels + c) * 2
                    val lo = raw[idx].toInt() and 0xFF
                    val hi = raw[idx + 1].toInt()
                    acc += (((hi shl 8) or lo).toShort().toFloat()) / 32768f
                }
                out[i] = acc / max(1, channels)
            }
            // 非 16k 时线性重采样到 16k
            val resampled = if (sampleRate != SAMPLE_RATE && sampleRate > 0) {
                val n = (frames.toLong() * SAMPLE_RATE / sampleRate).toInt()
                FloatArray(n) { k ->
                    val src = (k.toLong() * sampleRate / SAMPLE_RATE).toInt().coerceIn(0, frames - 1)
                    out[src]
                }
            } else out
            resampled to sampleRate
        }
    } catch (e: Throwable) {
        Log.e(TAG, "读 wav 失败：${file.name}", e)
        null
    }
}
