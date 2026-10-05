package com.localrecord.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.DataInputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * VAD 动态断句的 JVM 单元测试（不需要模拟器）。
 *
 * 用例：
 *  1. 3 遍真实语音（每遍尾部自带 0.5s 静音）+ 每遍之间插 1.5s 静音 → 应该切成 **3 段**，
 *     而不是固定 8 秒那样切成 1~2 段；
 *  2. 40 秒低电平噪声（安静环境）→ **一段都不该出**（幻觉防护）。
 */
class VadTest {

    private fun readWav(path: String): FloatArray {
        val input = javaClass.getResourceAsStream(path) ?: error("测试音频缺失：$path")
        DataInputStream(input).use { din ->
            val header = ByteArray(44)
            din.readFully(header)
            val channels = (header[22].toInt() and 0xFF) or ((header[23].toInt() and 0xFF) shl 8)
            val bytes = din.readBytes()
            val buf = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
            val frames = bytes.size / 2 / channels
            return FloatArray(frames) { i ->
                var acc = 0f
                for (c in 0 until channels) acc += buf.getShort((i * channels + c) * 2) / 32768f
                acc / channels
            }
        }
    }

    @Test
    fun segmentsOnSilenceGaps() {
        val speech = readWav("/selftest.wav")
        val silence = FloatArray(16000 * 3 / 2)          // 1.5 秒静音
        val stream = ArrayList<Float>(speech.size * 3 + silence.size * 3)
        repeat(3) {
            speech.forEach { v -> stream.add(v) }
            silence.forEach { v -> stream.add(v) }
        }

        val vad = Vad()
        val segs = ArrayList<Pair<FloatArray, Float>>()
        var i = 0
        while (i < stream.size) {
            val n = minOf(1600, stream.size - i)         // 100ms 一块
            val block = FloatArray(n) { stream[i + it] }
            vad.feed(block) { a, s -> segs.add(a to s) }
            i += n
        }
        vad.flush { a, s -> segs.add(a to s) }

        println("=== VAD 切出 ${segs.size} 段 ===")
        segs.forEachIndexed { k, (a, s) ->
            println("  SEG$k 起点=${"%.2f".format(s)}s 时长=${"%.2f".format(a.size / 16000f)}s")
        }
        assertEquals("3 遍语音、每段间 1.5s 静音 → 应该正好 3 段", 3, segs.size)
        segs.forEach { assertTrue("每段应该 ≥4 秒", it.first.size / 16000f >= 4.0f) }
        // 起点应依次递增（0 / 6.8 / 13.6 附近）
        assertTrue("第二段起点应比第一段晚 5 秒以上", segs[1].second - segs[0].second > 5f)
        // 关键回归：段之间不能重叠（pre-roll 越过已交付位置会让同一句话被识别两遍）
        for (k in 1 until segs.size) {
            val prevEnd = segs[k - 1].second + segs[k - 1].first.size / 16000f
            assertTrue(
                "第 $k 段起点 ${segs[k].second} 早于上一段结束 $prevEnd → 内容会重复",
                segs[k].second >= prevEnd - 0.01f
            )
        }
    }

    @Test
    fun noiseProducesNoSegment() {
        val vad = Vad()
        val rnd = java.util.Random(7)
        var count = 0
        repeat(400) {                                     // 40 秒
            val block = FloatArray(1600) { (rnd.nextFloat() - 0.5f) * 0.002f }
            vad.feed(block) { _, _ -> count++ }
        }
        vad.flush { _, _ -> count++ }
        println("=== 40 秒低电平噪声 → ${count} 段 ===")
        assertEquals("安静环境不应切出任何段", 0, count)
    }
}
