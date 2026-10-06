package com.localrecord.app

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.media.audiofx.NoiseSuppressor
import android.util.Log
import java.io.File
import java.io.RandomAccessFile
import java.util.concurrent.LinkedBlockingQueue
import kotlin.math.log10
import kotlin.math.max
import kotlin.math.sqrt

/**
 * 录音：16kHz 单声道 PCM，落盘成 wav。
 *
 * 用 `VOICE_RECOGNITION` 音源（多数机型自带降噪/AGC），并在可用时挂上
 * NoiseSuppressor / AcousticEchoCanceler —— 实测电脑版的内置麦克风信噪比很差，
 * 手机端把系统降噪打开能明显改善。
 *
 * 采集到的块同时塞进 [chunks] 队列交给识别线程，边录边转写。
 */
class Recorder(
    private val outFile: File,
    private val sampleRate: Int = 16000,
) {
    companion object {
        private const val TAG = "Recorder"
    }

    /**
     * 是否挂系统的降噪/回声消除。
     * **默认关**：实测有手机（用户反馈）开着 NoiseSuppressor 时麦克风原始电平只有 -55dB
     * （正常应 -25~-35dB），相当于把声音压掉了 20dB，识别自然不稳定。界面上一键可切换对比。
     */
    @Volatile var useEnhancements: Boolean = false

    val chunks = LinkedBlockingQueue<ShortArray>()

    @Volatile var level: Float = 0f        // 0~1，给 UI 电平条
        private set
    @Volatile var levelDb: Float = -90f    // 差分后的电平（dB），界面直接显示数字用
        private set
    @Volatile var rawDb: Float = -90f      // 原始信号电平（dB），判断"麦克风到底有没有收到声音"
        private set
    @Volatile var peakRawDb: Float = -90f  // 本次录音见过的最大原始电平（判断电平是否骤降）
        private set
    @Volatile var peak: Float = 0f         // 本次录音峰值（原始）
        private set
    @Volatile var elapsedSec: Float = 0f
        private set
    @Volatile var running: Boolean = false
        private set

    /** 录音过程中的错误信息（null 表示正常）；界面直接显示，不会再"静默不出字" */
    @Volatile var error: String? = null
        private set

    private var record: AudioRecord? = null
    private var thread: Thread? = null
    private var noiseSuppressor: NoiseSuppressor? = null
    private var echoCanceler: AcousticEchoCanceler? = null
    private val frames = ArrayList<ShortArray>(1024)

    @SuppressLint("MissingPermission")
    fun start(): Boolean = startInternal(clearBuffers = true)

    /**
     * 麦克风掉了之后**原地重启**（保留已录内容、时长接着走）。
     * 目的：一次 AudioRecord 异常不该让整场录音从此没有字。
     */
    fun restart(): Boolean {
        if (running) return true
        try {
            record?.release()
        } catch (_: Exception) {
        }
        record = null
        thread = null
        return startInternal(clearBuffers = false)
    }

    @SuppressLint("MissingPermission")
    private fun startInternal(clearBuffers: Boolean): Boolean {
        if (running) return true
        val minBuf = AudioRecord.getMinBufferSize(
            sampleRate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT
        )
        if (minBuf <= 0) return false
        val bufSize = max(minBuf * 2, sampleRate / 5 * 2)   // ≥200ms
        val rec = try {
            AudioRecord(
                MediaRecorder.AudioSource.VOICE_RECOGNITION,
                sampleRate, AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT, bufSize
            )
        } catch (e: Exception) {
            Log.e(TAG, "AudioRecord 创建失败", e)
            return false
        }
        if (rec.state != AudioRecord.STATE_INITIALIZED) {
            rec.release(); return false
        }
        // 系统级降噪/回声消除：**默认不挂**（见 useEnhancements 注释），可用开关打开
        try {
            if (useEnhancements) {
                if (NoiseSuppressor.isAvailable()) {
                    noiseSuppressor = NoiseSuppressor.create(rec.audioSessionId)?.also { it.enabled = true }
                }
                if (AcousticEchoCanceler.isAvailable()) {
                    echoCanceler = AcousticEchoCanceler.create(rec.audioSessionId)?.also { it.enabled = true }
                }
                Log.i(TAG, "已启用系统降噪/回声消除")
            } else {
                Log.i(TAG, "未启用系统降噪（useEnhancements=false）")
            }
        } catch (e: Exception) {
            Log.w(TAG, "降噪/回声消除启用失败（忽略）：${e.message}")
        }
        record = rec
        if (clearBuffers) {
            frames.clear()
            chunks.clear()
            level = 0f; peak = 0f; elapsedSec = 0f
            peakRawDb = -90f
        }
        error = null
        rec.startRecording()
        running = true
        thread = Thread({ loop(rec) }, "record-loop").also { it.start() }
        return true
    }

    private fun loop(rec: AudioRecord) {
        val buf = ShortArray(sampleRate / 10)          // 100ms
        // 从已录长度接着算（restart 后时长不断档）
        var total = frames.sumOf { it.size.toLong() }
        var badReads = 0
        while (running) {
            val n = try {
                rec.read(buf, 0, buf.size)
            } catch (t: Throwable) {
                // 旧代码这里异常会**静默打死录音线程** —— 表现就是"录着录着再也没有字了"
                Log.e(TAG, "AudioRecord.read 异常（第 ${badReads + 1} 次）", t)
                error = "麦克风读取异常：${t.message}"
                badReads++
                if (badReads > 20) break
                try {
                    Thread.sleep(100)
                } catch (_: InterruptedException) {
                    break
                }
                continue
            }
            if (n < 0) {                                // 负值是 AudioRecord 的错误码
                badReads++
                Log.w(TAG, "AudioRecord.read 返回 $n（第 $badReads 次）")
                error = "麦克风读取失败（错误码 $n）"
                if (badReads > 20) break
                try {
                    Thread.sleep(100)
                } catch (_: InterruptedException) {
                    break
                }
                continue
            }
            if (n == 0) continue
            badReads = 0
            error = null
            val block = buf.copyOf(n)
            frames.add(block)
            chunks.offer(block)
            total += n
            elapsedSec = total.toFloat() / sampleRate
            // 电平：低频轰鸣没有参考价值，这里用一阶差分近似高通后再算 RMS
            var sum = 0.0
            var rawSum = 0.0
            var pk = 0f
            for (i in 1 until n) {
                val d = (block[i].toInt() - block[i - 1].toInt()) / 32768.0
                sum += d * d
                val raw = block[i].toInt() / 32768.0
                rawSum += raw * raw
                val a = kotlin.math.abs(block[i].toInt()) / 32768f
                if (a > pk) pk = a
            }
            val rms = sqrt(sum / max(1, n - 1) + 1e-12)
            val rawRms = sqrt(rawSum / max(1, n - 1) + 1e-12)
            val db = (20 * log10(max(rms, 1e-9))).toFloat()
            levelDb = db
            rawDb = (20 * log10(max(rawRms, 1e-9))).toFloat()
            if (rawDb > peakRawDb) peakRawDb = rawDb
            // 刻度放宽并做一点 gamma：正常说话（约 -45~-20dB）就能看到明显起伏，
            // 原来的 (db+48)/48 太钝，看着像"没在录"
            val norm = ((db + 55f) / 38f).coerceIn(0f, 1f)
            val target = Math.pow(norm.toDouble(), 0.7).toFloat()
            level += (target - level) * (if (target > level) 0.55f else 0.10f)
            if (pk > peak) peak = pk
        }
        Log.i(TAG, "录音线程结束：$total 采样（${"%.1f".format(total / sampleRate.toFloat())} 秒）")
    }

    /** 停止录音并写 wav；返回文件（无音频则 null） */
    fun stop(): File? {
        if (!running && record == null) return null
        running = false
        thread?.join(1500)
        thread = null
        try {
            record?.stop()
        } catch (_: Exception) {
        }
        noiseSuppressor?.release(); noiseSuppressor = null
        echoCanceler?.release(); echoCanceler = null
        record?.release(); record = null

        if (frames.isEmpty()) return null
        val total = frames.sumOf { it.size }
        outFile.parentFile?.mkdirs()
        RandomAccessFile(outFile, "rw").use { raf ->
            raf.setLength(0)
            raf.write(wavHeader(total))
            val bytes = ByteArray(2)
            for (block in frames) {
                for (s in block) {          // 小端 16bit
                    bytes[0] = (s.toInt() and 0xFF).toByte()
                    bytes[1] = ((s.toInt() shr 8) and 0xFF).toByte()
                    raf.write(bytes)
                }
            }
        }
        frames.clear()
        return outFile
    }

    private fun wavHeader(samples: Int): ByteArray {
        val dataLen = samples * 2
        val h = ByteArray(44)
        fun put(off: Int, s: String) { for (i in s.indices) h[off + i] = s[i].code.toByte() }
        fun i32(off: Int, v: Int) {
            h[off] = (v and 0xFF).toByte(); h[off + 1] = ((v shr 8) and 0xFF).toByte()
            h[off + 2] = ((v shr 16) and 0xFF).toByte(); h[off + 3] = ((v shr 24) and 0xFF).toByte()
        }
        fun i16(off: Int, v: Int) {
            h[off] = (v and 0xFF).toByte(); h[off + 1] = ((v shr 8) and 0xFF).toByte()
        }
        put(0, "RIFF"); i32(4, 36 + dataLen); put(8, "WAVE")
        put(12, "fmt "); i32(16, 16); i16(20, 1); i16(22, 1)
        i32(24, sampleRate); i32(28, sampleRate * 2); i16(32, 2); i16(34, 16)
        put(36, "data"); i32(40, dataLen)
        return h
    }
}
