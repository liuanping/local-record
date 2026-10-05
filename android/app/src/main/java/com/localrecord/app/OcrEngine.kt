package com.localrecord.app

import android.content.Context
import android.graphics.Bitmap
import android.util.Log
import java.io.File
import kotlin.math.exp
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/**
 * 手机端 OCR（文档问答），复用电脑版同一套 PP-OCRv6 medium ONNX 模型。
 *
 * 管道与电脑版（paddleocr + onnxruntime）一致：
 *   1. 检测（det，DB 算法）：缩放到最长边 ≤960 且 32 的倍数 → BGR 归一化 → 概率图
 *   2. DB 后处理：阈值 0.2 二值化 → 连通域 → 平均分 <0.45 丢弃 → 按 unclip 1.4 外扩
 *   3. 识别（rec）：裁切每行 → 高度 48 → 归一化 → CTC 贪心解码（字典 18707 字符，来自 assets）
 *
 * 推理走自己的 JNI（`ocr_jni.cpp`），直接 dlopen sherpa 已经带进来的 libonnxruntime.so。
 */
class OcrEngine(private val store: ModelStore, private val context: Context) {

    companion object {
        private const val TAG = "OcrEngine"

        // det 预处理/后处理参数（取自模型的 inference.yml）
        private const val DET_LIMIT_SIDE = 960
        private const val DET_THRESH = 0.2f
        private const val DET_BOX_THRESH = 0.45f
        private const val DET_UNCLIP = 1.4f
        private val DET_MEAN = floatArrayOf(0.485f, 0.456f, 0.406f)
        private val DET_STD = floatArrayOf(0.229f, 0.224f, 0.225f)

        // rec
        private const val REC_HEIGHT = 48
        private const val REC_MAX_W = 1280
        private const val BLANK = 0
        private const val DICT_ASSET = "ocr_rec_dict.txt"

        init {
            try {
                System.loadLibrary("ocrjni")
            } catch (e: Throwable) {
                Log.e(TAG, "加载 libocrjni.so 失败：${e.message}")
            }
        }
    }

    private var handle = 0L
    private var dict: List<String> = emptyList()
    private var firstRecLog = true

    val ready: Boolean get() = handle != 0L

    data class Line(val text: String, val score: Float, val left: Int, val top: Int,
                    val right: Int, val bottom: Int)

    fun init(threads: Int = 4): Boolean {
        if (handle != 0L) return true
        val det = store.ocrDetModel()
        val rec = store.ocrRecModel()
        if (!det.isFile || !rec.isFile) {
            Log.w(TAG, "OCR 模型缺失：det=${det.isFile}(${det.absolutePath}) rec=${rec.isFile}")
            return false
        }
        if (dict.isEmpty()) {
            dict = try {
                context.assets.open(DICT_ASSET).bufferedReader(Charsets.UTF_8)
                    .readLines()
                    // PP-OCR 的字典里，**空格字符在文件中就是一行空白**（' '、'\u3000' 等），
                    // readLines() 读出来是空字符串；CTC 解码到它时 append("") 等于什么都没加，
                    // 于是英文单词全部连在一起（用户反馈"Risk2026报告"）。
                    // 这里把所有空白条目统一还原成一个半角空格。
                    .map { if (it.isBlank()) " " else it }
            } catch (e: Throwable) {
                Log.e(TAG, "读字典失败：${e.message}")
                emptyList()
            }
        }
        return try {
            handle = nativeInit(det.absolutePath, rec.absolutePath, threads)
            Log.i(TAG, "OCR 就绪=${handle != 0L} 字典=${dict.size} 字符")
            handle != 0L
        } catch (e: Throwable) {
            Log.e(TAG, "初始化失败", e)
            false
        }
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

    /** 识别整张图，按阅读顺序（上→下、左→右）返回每行文字 */
    fun recognize(src: Bitmap): List<Line> {
        if (handle == 0L) return emptyList()
        val boxes = detect(src)
        if (boxes.isEmpty()) return emptyList()
        val lines = ArrayList<Line>(boxes.size)
        for (b in boxes) {
            val r = recognizeBox(src, b) ?: continue
            if (r.text.isNotBlank()) lines.add(r)
        }
        return lines
    }

    /** 拼成一整段文本（给大模型当上下文） */
    fun toText(lines: List<Line>): String = lines.joinToString("\n") { it.text }

    // ------------------------------------------------------------ det ----

    private data class Box(val left: Int, val top: Int, val right: Int, val bottom: Int)
        : Comparable<Box> {
        override fun compareTo(other: Box): Int {
            val dy = top - other.top
            return if (dy > 12 || dy < -12) top - other.top else left - other.left
        }
    }

    private fun detect(src: Bitmap): List<Box> {
        // 缩放：最长边 ≤960，且 32 的倍数（模型输入要求）
        val maxSide = max(src.width, src.height)
        val ratio = if (maxSide > DET_LIMIT_SIDE) DET_LIMIT_SIDE.toFloat() / maxSide else 1f
        var w = (src.width * ratio).roundToInt().coerceAtLeast(32)
        var h = (src.height * ratio).roundToInt().coerceAtLeast(32)
        w = ((w + 31) / 32) * 32
        h = ((h + 31) / 32) * 32
        val scaled = Bitmap.createScaledBitmap(src, w, h, true)
        val px = IntArray(w * h)
        scaled.getPixels(px, 0, w, 0, 0, w, h)

        val input = FloatArray(3 * h * w)
        val plane = h * w
        for (i in 0 until plane) {
            val c = px[i]
            val r = ((c shr 16) and 0xFF) / 255f
            val g = ((c shr 8) and 0xFF) / 255f
            val b = (c and 0xFF) / 255f
            // 模型按 BGR 训练（inference.yml: img_mode: BGR）
            input[i] = (b - DET_MEAN[0]) / DET_STD[0]
            input[plane + i] = (g - DET_MEAN[1]) / DET_STD[1]
            input[2 * plane + i] = (r - DET_MEAN[2]) / DET_STD[2]
        }
        val outDims = LongArray(4)
        val prob = try {
            nativeRun(handle, true, input, longArrayOf(1, 3, h.toLong(), w.toLong()), outDims)
        } catch (e: Throwable) {
            Log.e(TAG, "det 推理异常", e)
            null
        }
        if (prob == null) {
            Log.w(TAG, "det 无输出")
            return emptyList()
        }
        val ph = if (outDims[2] > 0) outDims[2].toInt() else h
        val pw = if (outDims[3] > 0) outDims[3].toInt() else w
        Log.i(TAG, "det 输入 ${w}x$h → 输出 ${pw}x$ph（值域 ${prob.minOrNull()}~${prob.maxOrNull()}）")

        // 连通域（8 邻域）找文本框
        val total = pw * ph
        val bin = BooleanArray(total)
        for (i in 0 until min(total, prob.size)) bin[i] = prob[i] > DET_THRESH
        val visited = BooleanArray(total)
        val stack = IntArray(total)
        val out = ArrayList<Box>()
        for (start in 0 until total) {
            if (!bin[start] || visited[start]) continue
            var sp = 0
            stack[sp++] = start
            visited[start] = true
            var minX = pw; var maxX = -1; var minY = ph; var maxY = -1
            var sum = 0.0
            var cnt = 0
            while (sp > 0) {
                val p = stack[--sp]
                val y = p / pw
                val x = p - y * pw
                if (x < minX) minX = x
                if (x > maxX) maxX = x
                if (y < minY) minY = y
                if (y > maxY) maxY = y
                sum += prob[p]
                cnt++
                for (dy in -1..1) {
                    val ny = y + dy
                    if (ny < 0 || ny >= ph) continue
                    for (dx in -1..1) {
                        val nx = x + dx
                        if (nx < 0 || nx >= pw) continue
                        val np = ny * pw + nx
                        if (bin[np] && !visited[np]) {
                            visited[np] = true
                            if (sp < total) stack[sp++] = np
                        }
                    }
                }
            }
            if (cnt < 6) continue
            val score = (sum / cnt).toFloat()
            if (score < DET_BOX_THRESH) continue
            val bw = maxX - minX + 1
            val bh = maxY - minY + 1
            if (bw < 3 || bh < 3) continue
            // unclip 外扩：offset = area * ratio / perimeter
            val offset = cnt.toFloat() * DET_UNCLIP / (2f * (bw + bh))
            val inv = 1f / ratio
            out.add(
                Box(
                    ((minX - offset) * inv).roundToInt().coerceIn(0, src.width - 1),
                    ((minY - offset) * inv).roundToInt().coerceIn(0, src.height - 1),
                    ((maxX + offset) * inv).roundToInt().coerceIn(0, src.width - 1),
                    ((maxY + offset) * inv).roundToInt().coerceIn(0, src.height - 1),
                )
            )
        }
        Log.i(TAG, "检测到 ${out.size} 个文本框")
        return out.sorted()
    }

    // ------------------------------------------------------------ rec ----

    private fun recognizeBox(src: Bitmap, b: Box): Line? {
        val left = b.left.coerceIn(0, src.width - 1)
        val top = b.top.coerceIn(0, src.height - 1)
        val right = b.right.coerceIn(left + 1, src.width)
        val bottom = b.bottom.coerceIn(top + 1, src.height)
        val cw = right - left
        val ch = bottom - top
        if (cw < 4 || ch < 4) return null
        val crop = Bitmap.createBitmap(src, left, top, cw, ch)
        var rw = (REC_HEIGHT.toFloat() * cw / ch).roundToInt().coerceAtLeast(16)
        rw = ((rw + 7) / 8) * 8
        rw = rw.coerceAtMost(REC_MAX_W)
        val line = Bitmap.createScaledBitmap(crop, rw, REC_HEIGHT, true)
        val px = IntArray(rw * REC_HEIGHT)
        line.getPixels(px, 0, rw, 0, 0, rw, REC_HEIGHT)

        val plane = rw * REC_HEIGHT
        val input = FloatArray(3 * plane)
        for (i in 0 until plane) {
            val c = px[i]
            val r = ((c shr 16) and 0xFF) / 255f
            val g = ((c shr 8) and 0xFF) / 255f
            val bl = (c and 0xFF) / 255f
            // rec 侧：(v/255 - 0.5)/0.5，BGR
            input[i] = (bl - 0.5f) / 0.5f
            input[plane + i] = (g - 0.5f) / 0.5f
            input[2 * plane + i] = (r - 0.5f) / 0.5f
        }
        val outDims = LongArray(3)
        val logits = try {
            nativeRun(handle, false, input,
                longArrayOf(1, 3, REC_HEIGHT.toLong(), rw.toLong()), outDims)
        } catch (e: Throwable) {
            Log.e(TAG, "rec 推理异常", e)
            null
        } ?: return null

        // 形状 [1, T, C]（少数导出是 [T, 1, C]，取最后一维当类别数）
        var tCount: Int
        var cCount: Int
        if (outDims.size >= 3 && outDims[2] > 0) {
            tCount = outDims[1].toInt()
            cCount = outDims[2].toInt()
        } else if (outDims.size >= 2) {
            tCount = outDims[0].toInt()
            cCount = outDims[1].toInt()
        } else return null
        if (tCount <= 0 || cCount <= 0 || tCount.toLong() * cCount > logits.size) {
            Log.w(TAG, "rec 输出形状异常 dims=${outDims.toList()} size=${logits.size}")
            return null
        }
        if (firstRecLog) {
            firstRecLog = false
            Log.i(TAG, "rec 首次输出：dims=${outDims.toList()} T=$tCount C=$cCount 字典=${dict.size}")
        }
        // 判断输出是"概率"还是"logits"：概率的话每步之和 ≈ 1
        var probLike = true
        if (cCount > 0) {
            var s = 0.0
            for (c in 0 until cCount) s += logits[c]
            probLike = s in 0.5..1.5
        }
        Log.i(TAG, "rec 输出类型：${if (probLike) "概率" else "logits"}")

        val sb = StringBuilder()
        var prev = -1
        var confSum = 0.0
        var confCnt = 0
        for (t in 0 until tCount) {
            val base = t * cCount
            var best = 0
            var bestV = Float.NEGATIVE_INFINITY
            for (c in 0 until cCount) {
                val v = logits[base + c]
                if (v > bestV) {
                    bestV = v
                    best = c
                }
            }
            if (best != BLANK && best != prev) {
                val idx = best - 1
                if (idx in dict.indices) sb.append(dict[idx])
                // 输出是概率就直接用峰值；是 logits 才做 softmax（否则分数会算成 0）
                confSum += if (probLike) {
                    bestV.toDouble()
                } else {
                    var sum = 0.0
                    for (c in 0 until cCount) sum += exp((logits[base + c] - bestV).toDouble())
                    1.0 / sum
                }
                confCnt++
            }
            prev = best
        }
        if (sb.isEmpty()) return null
        val score = if (confCnt > 0) (confSum / confCnt).toFloat() else 0f
        return Line(sb.toString(), score, left, top, right, bottom)
    }

    // -------------------------------------------------------- native ----

    private external fun nativeInit(detPath: String, recPath: String, threads: Int): Long
    private external fun nativeRun(
        handle: Long, useDet: Boolean, input: FloatArray, inDims: LongArray, outDims: LongArray
    ): FloatArray?
    private external fun nativeFree(handle: Long)
}
