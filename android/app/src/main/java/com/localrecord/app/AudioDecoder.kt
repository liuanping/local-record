package com.localrecord.app

import android.content.Context
import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import android.net.Uri
import android.util.Log
import java.nio.ByteOrder
import kotlin.math.roundToInt

/**
 * 用系统解码器把**任意音频**解成 16kHz 单声道 float，供转写使用。
 *
 * 支持 mp3 / m4a(aac) / wav / ogg / opus / flac / amr / 3gp —— 只要手机能播放，就能转写，
 * 因为这些格式全部走 Android 自带的 `MediaExtractor` + `MediaCodec`（不需要额外解码库、
 * 也不增加包体）。
 *
 * 边解边回调（流式），所以一小时的录音也不会把内存吃爆。
 */
object AudioDecoder {

    private const val TAG = "AudioDecoder"
    const val TARGET_RATE = 16000

    /** 音频文件后缀（导入时按此过滤/命名） */
    val SUPPORTED_EXT = setOf("mp3", "wav", "m4a", "aac", "ogg", "oga", "opus", "flac", "amr", "3gp", "mp4", "wma")

    /**
     * 流式解码。
     * @param onSamples 每解出一块 16k 单声道 float（约 0.1~0.5 秒）就回调；返回 false 可提前终止
     * @return 是否成功解码（false = 不支持的格式或读不了）
     */
    fun decodeStream(context: Context, uri: Uri, onSamples: (FloatArray) -> Boolean): Boolean {
        val extractor = MediaExtractor()
        try {
            context.contentResolver.openAssetFileDescriptor(uri, "r")?.use { afd ->
                extractor.setDataSource(afd.fileDescriptor, afd.startOffset, afd.length)
            } ?: run {
                Log.w(TAG, "打不开输入流：$uri")
                return false
            }

            var trackIndex = -1
            var format: MediaFormat? = null
            for (i in 0 until extractor.trackCount) {
                val f = extractor.getTrackFormat(i)
                val mime = f.getString(MediaFormat.KEY_MIME) ?: continue
                if (mime.startsWith("audio/")) {
                    trackIndex = i
                    format = f
                    break
                }
            }
            if (trackIndex < 0 || format == null) {
                Log.w(TAG, "文件里没有音频轨：$uri")
                return false
            }
            extractor.selectTrack(trackIndex)

            val mime = format.getString(MediaFormat.KEY_MIME) ?: ""
            val srcRate = intOr(format, MediaFormat.KEY_SAMPLE_RATE, 16000)
            val channels = intOr(format, MediaFormat.KEY_CHANNEL_COUNT, 1)
            Log.i(TAG, "解码中：mime=$mime 源采样率=$srcRate 声道=$channels")

            val resampler = Resampler(srcRate, channels, TARGET_RATE)

            // PCM（wav）没有解码器，直接从 extractor 读样本
            if (mime == "audio/raw") {
                return readRaw(extractor, resampler, onSamples)
            }

            val codec = try {
                MediaCodec.createDecoderByType(mime)
            } catch (e: Throwable) {
                Log.w(TAG, "没有 $mime 的解码器：${e.message}")
                return false
            }
            codec.configure(format, null, null, 0)
            codec.start()
            val info = MediaCodec.BufferInfo()
            var inputDone = false
            var outputDone = false
            var ok = false
            try {
                while (!outputDone) {
                    if (!inputDone) {
                        val inIdx = codec.dequeueInputBuffer(10_000)
                        if (inIdx >= 0) {
                            val buf = codec.getInputBuffer(inIdx)
                            val size = if (buf == null) -1 else extractor.readSampleData(buf, 0)
                            if (size < 0) {
                                codec.queueInputBuffer(inIdx, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM)
                                inputDone = true
                            } else {
                                codec.queueInputBuffer(inIdx, 0, size, extractor.sampleTime, 0)
                                extractor.advance()
                            }
                        }
                    }
                    val outIdx = codec.dequeueOutputBuffer(info, 10_000)
                    if (outIdx >= 0) {
                        if (info.size > 0) {
                            val out = codec.getOutputBuffer(outIdx)
                            if (out != null) {
                                out.position(info.offset)
                                out.limit(info.offset + info.size)
                                val shorts = ShortArray(info.size / 2)
                                out.order(ByteOrder.LITTLE_ENDIAN).asShortBuffer().get(shorts)
                                val mono = resampler.process(shorts)
                                if (mono.isNotEmpty() && !onSamples(mono)) return true
                            }
                        }
                        codec.releaseOutputBuffer(outIdx, false)
                        if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) outputDone = true
                    }
                }
                val tail = resampler.flush()
                if (tail.isNotEmpty()) onSamples(tail)
                ok = true
            } finally {
                try {
                    codec.stop()
                } catch (_: Throwable) {
                }
                codec.release()
            }
            return ok
        } catch (e: Throwable) {
            Log.e(TAG, "解码失败：$uri", e)
            return false
        } finally {
            try {
                extractor.release()
            } catch (_: Throwable) {
            }
        }
    }

    /** PCM（wav）直接读样本 */
    private fun readRaw(
        extractor: MediaExtractor,
        resampler: Resampler,
        onSamples: (FloatArray) -> Boolean,
    ): Boolean {
        val buf = java.nio.ByteBuffer.allocate(1 shl 16).order(ByteOrder.LITTLE_ENDIAN)
        while (true) {
            val size = extractor.readSampleData(buf, 0)
            if (size < 0) break
            buf.position(0)
            buf.limit(size)
            val shorts = ShortArray(size / 2)
            buf.asShortBuffer().get(shorts)
            val mono = resampler.process(shorts)
            if (mono.isNotEmpty() && !onSamples(mono)) return true
            extractor.advance()
        }
        val tail = resampler.flush()
        if (tail.isNotEmpty()) onSamples(tail)
        return true
    }

    private fun intOr(f: MediaFormat, key: String, def: Int): Int = try {
        if (f.containsKey(key)) f.getInteger(key) else def
    } catch (_: Throwable) {
        def
    }

    /**
     * 重采样 + 混单声道。
     * 保留上一块的最后一个样本，跨块线性插值，避免块边界出现"咔哒"。
     */
    private class Resampler(
        private val srcRate: Int,
        private val channels: Int,
        private val dstRate: Int,
    ) {
        private var lastSample = 0f
        private var pos = 0.0                  // 以源采样为单位的读取位置
        private var started = false

        fun process(interleaved: ShortArray): FloatArray {
            val frames = interleaved.size / channels
            if (frames == 0) return FloatArray(0)
            // 先混成单声道
            val mono = FloatArray(frames)
            for (i in 0 until frames) {
                var acc = 0f
                for (c in 0 until channels) acc += interleaved[i * channels + c] / 32768f
                mono[i] = acc / channels
            }
            if (srcRate == dstRate) {
                lastSample = mono[frames - 1]
                return mono
            }
            val ratio = srcRate.toDouble() / dstRate
            // 前后各补一个样本，保证跨块插值连续
            val ext = FloatArray(frames + 2)
            ext[0] = if (started) lastSample else mono[0]
            System.arraycopy(mono, 0, ext, 1, frames)
            ext[frames + 1] = mono[frames - 1]

            val out = ArrayList<Float>(((frames / ratio) + 2).toInt())
            var p = if (started) pos else 0.0
            while (p < frames) {
                val i0 = p.toInt()
                val frac = (p - i0).toFloat()
                val a = ext[i0]
                val b = ext[i0 + 1]
                out.add(a + (b - a) * frac)
                p += ratio
            }
            pos = p - frames
            lastSample = mono[frames - 1]
            started = true
            return FloatArray(out.size) { out[it] }
        }

        fun flush(): FloatArray {
            pos = 0.0
            started = false
            return FloatArray(0)
        }
    }

    /** 估算时长（秒），失败返回 0 —— 只用于界面显示 */
    fun durationSeconds(context: Context, uri: Uri): Int = try {
        val mmr = android.media.MediaMetadataRetriever()
        context.contentResolver.openAssetFileDescriptor(uri, "r")?.use { afd ->
            mmr.setDataSource(afd.fileDescriptor, afd.startOffset, afd.length)
            val ms = mmr.extractMetadata(android.media.MediaMetadataRetriever.METADATA_KEY_DURATION)?.toLongOrNull() ?: 0L
            (ms / 1000.0).roundToInt()
        } ?: 0
    } catch (_: Throwable) {
        0
    } finally {
    }
}
