package com.localrecord.app

import android.util.Log
import java.io.File
import java.io.RandomAccessFile
import java.net.HttpURLConnection
import java.net.URL

/**
 * 应用内自动下载模型（用户不想手动拷贝 1.6GB 文件）。
 *
 * 行为（按用户要求）：
 *  * **不需要用户选择**：启动时发现缺哪个就自动下哪个，缺什么下什么；
 *  * **已有的不重复下载**：按精确字节数判断"已完成"，所以版本更新后也不会重下 1.6GB；
 *  * **全部走 ModelScope**（国内直连、支持 Range 续传）；ModelScope 失败才兜底 hf-mirror；
 *  * 断点续传（先写 `.part`，HTTP Range 续传）+ 大小校验（不一致视为失败）；
 *  * 目标目录是 app 自己的外置私有目录（`Android/data/<pkg>/files/`），**不需要存储权限**。
 */
class ModelDownloader(private val store: ModelStore) {

    companion object {
        private const val TAG = "ModelDownloader"
        private const val MS = "https://www.modelscope.cn/api/v1/models"
        private const val HF = "https://hf-mirror.com"

        /** ModelScope 的文件直链写法 */
        /** 换模型后删掉旧的 gguf（否则白占空间；findModel 取最大文件也可能拿错） */
    private fun cleanOldGguf(dir: java.io.File, keepName: String) {
        dir.listFiles { f ->
            f.isFile && f.extension.lowercase() == "gguf" && f.name != keepName
        }?.forEach { old ->
            android.util.Log.i("Download", "删除旧的大模型 ${old.name}（${old.length() / 1048576} MB）")
            if (!old.delete()) android.util.Log.w("Download", "删不掉 ${old.name}")
        }
    }

    private fun ms(repo: String, file: String) =
            "$MS/$repo/repo?Revision=master&FilePath=$file"
    }

    /** 一个模型文件（fallbackUrl 只在主源失败时用） */
    data class Artifact(
        val key: String,
        val title: String,
        val url: String,
        val dest: File,
        val expectBytes: Long,
        val required: Boolean,       // ASR 主模型必需
        val fallbackUrl: String? = null,
    ) {
        fun humanSize(): String = when {
            expectBytes >= 1 shl 30 -> "%.2f GB".format(expectBytes / 1073741824.0)
            else -> "%.0f MB".format(expectBytes / 1048576.0)
        }
    }

    val artifacts: List<Artifact> by lazy {
        val asrDir = File(store.externalModelsDir(), ModelStore.ASR_SUBDIR)
        val punctDir = File(store.externalModelsDir(), ModelStore.PUNCT_SUBDIR)
        val llmDir = File(store.externalModelsDir().parentFile, "llm")
        val ocrDir = File(store.externalModelsDir(), ModelStore.OCR_SUBDIR)
        val vadDir = File(store.externalModelsDir(), ModelStore.VAD_SUBDIR)
        asrDir.mkdirs(); punctDir.mkdirs(); llmDir.mkdirs(); ocrDir.mkdirs(); vadDir.mkdirs()
        listOf(
            Artifact(
                "asr-model", "转写模型（Paraformer，中英混说）",
                ms("pengzhendong/sherpa-onnx-paraformer-zh", "model.int8.onnx"),
                File(asrDir, ModelStore.ASR_MODEL), 227_330_205L, required = true,
                fallbackUrl = "$HF/csukuangfj/sherpa-onnx-paraformer-zh-2024-03-09/resolve/main/model.int8.onnx",
            ),
            Artifact(
                "asr-tokens", "转写词表",
                ms("pengzhendong/sherpa-onnx-paraformer-zh", "tokens.txt"),
                File(asrDir, ModelStore.ASR_TOKENS), 75_354L, required = true,
                fallbackUrl = "$HF/csukuangfj/sherpa-onnx-paraformer-zh-2024-03-09/resolve/main/tokens.txt",
            ),
            // 神经网络 VAD（Silero）：2.3MB，断句准确度远高于能量法，放在必要模型里
            Artifact(
                "vad", "断句模型（神经网络 VAD）",
                "$HF/deepghs/silero-vad-onnx/resolve/main/silero_vad.onnx",
                File(vadDir, ModelStore.VAD_MODEL), 2_327_524L, required = true,
            ),
            Artifact(
                "punct-model", "标点模型（CT-Transformer）",
                ms("csukuangfj/sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12", "model.onnx"),
                File(punctDir, ModelStore.PUNCT_MODEL), 294_372_519L, required = false,
                fallbackUrl = "$HF/csukuangfj/sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12/resolve/main/model.onnx",
            ),
            Artifact(
                "punct-tokens", "标点词表",
                ms("csukuangfj/sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12", "tokens.json"),
                File(punctDir, ModelStore.PUNCT_TOKENS), 4_207_480L, required = false,
                fallbackUrl = "$HF/csukuangfj/sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12/resolve/main/tokens.json",
            ),
            // ---- OCR（文档问答）：与电脑版同一套 PP-OCRv6 medium ONNX ----
            Artifact(
                "ocr-det", "文档检测模型（PP-OCRv6 det）",
                ms("PaddlePaddle/PP-OCRv6_medium_det_onnx", "inference.onnx"),
                File(ocrDir, ModelStore.OCR_DET_MODEL), 62_032_837L, required = false,
            ),
            Artifact(
                "ocr-rec", "文档识别模型（PP-OCRv6 rec）",
                ms("PaddlePaddle/PP-OCRv6_medium_rec_onnx", "inference.onnx"),
                File(ocrDir, ModelStore.OCR_REC_MODEL), 76_554_979L, required = false,
            ),
            // ---- 大模型**放最后**：只有"会议纪要/问答"用它，不该挡着前面的功能 ----
            // 说明：本版本已移除本地大模型，所以不再下载 gguf（体积/内存都省下来）
        )
    }

    /** 必要模型（转写+标点+OCR）总量 —— 用于告诉用户"还差多少就能干活" */
    fun essentialBytes(): Long = artifacts.filter { it.key != "llm" }.sumOf { it.expectBytes }

    /** 大文件（大模型）：流量网络下默认等 WiFi */
    fun isBigArtifact(a: Artifact): Boolean = a.expectBytes > 500L * 1024 * 1024

    /** 缺哪些文件（全部，不给用户选择） */
    fun missing(): List<Artifact> = artifacts.filter { !done(it) }

    /** 内部存储里的同名位置（手动导入/旧版本可能放在这，避免更新后重复下载） */
    private fun altPath(a: Artifact): File = try {
        File(store.internalModelsDir().parentFile,
            a.dest.relativeTo(store.externalModelsDir().parentFile).path)
    } catch (e: Exception) {
        a.dest
    }

    private fun ok(f: File, expect: Long) = f.isFile && (expect <= 0 || f.length() == expect)

    /** 外置或内部任一处已有**完整**文件，就算完成 */
    fun done(a: Artifact): Boolean = ok(a.dest, a.expectBytes) || ok(altPath(a), a.expectBytes)

    /**
     * 下载一个文件（含多轮重试）。主源失败自动试备源，整轮失败再重试 [retries] 轮。
     * 断网时外层会先等网络恢复，所以这里的重试主要处理瞬时抖动。
     * onProgress(已下载字节, 总字节, 速度MB/s)；onRetry(第几轮, 共几轮)
     */
    fun download(
        a: Artifact,
        onProgress: (Long, Long, Double) -> Unit = { _, _, _ -> },
        shouldStop: () -> Boolean = { false },
        onRetry: (Int, Int) -> Unit = { _, _ -> },
        retries: Int = 3,
    ): Boolean {
        if (done(a)) return true
        val sources = listOfNotNull(a.url, a.fallbackUrl)
        for (attempt in 1..retries) {
            if (shouldStop()) return false
            for ((idx, src) in sources.withIndex()) {
                if (shouldStop()) return false
                if (downloadOne(a, src, onProgress, shouldStop)) return true
                if (idx + 1 < sources.size) {
                    Log.i(TAG, "${a.key} 主源失败，改用备源重试")
                }
            }
            if (attempt < retries) {
                onRetry(attempt, retries)
                try {
                    Thread.sleep(2000L * attempt)      // 退避 2s / 4s
                } catch (_: InterruptedException) {
                }
            }
        }
        Log.w(TAG, "${a.key} 重试 $retries 轮仍失败，已下载部分保留（下次从这里续传）")
        return false
    }

    private fun downloadOne(
        a: Artifact,
        url: String,
        onProgress: (Long, Long, Double) -> Unit,
        shouldStop: () -> Boolean,
    ): Boolean {
        val part = File(a.dest.parentFile, a.dest.name + ".part")
        var existing = if (part.isFile) part.length() else 0L
        if (existing >= a.expectBytes && a.expectBytes > 0) {   // 上次其实下完了
            part.delete(); existing = 0
        }
        var conn: HttpURLConnection? = null
        try {
            conn = (URL(url).openConnection() as HttpURLConnection).apply {
                connectTimeout = 20_000
                readTimeout = 60_000
                instanceFollowRedirects = true
                setRequestProperty("User-Agent", "LocalRecordAndroid/1.2")
                if (existing > 0) setRequestProperty("Range", "bytes=$existing-")
            }
            val code = conn.responseCode
            if (code !in 200..299) {
                Log.w(TAG, "${a.key} HTTP $code")
                return false
            }
            if (existing > 0 && code != 206) {          // 服务端不支持续传 → 从头来
                Log.i(TAG, "${a.key} 服务端不支持续传，重新下载")
                existing = 0
            }
            val total = if (a.expectBytes > 0) a.expectBytes
            else (existing + conn.contentLengthLong).coerceAtLeast(0)
            val t0 = System.currentTimeMillis()
            var got = existing
            conn.inputStream.use { input ->
                RandomAccessFile(part, "rw").use { raf ->
                    if (existing == 0L) raf.setLength(0) else raf.seek(existing)
                    val buf = ByteArray(1 shl 16)
                    var lastReport = 0L
                    while (true) {
                        if (shouldStop()) { Log.i(TAG, "${a.key} 用户取消"); return false }
                        val n = input.read(buf)
                        if (n <= 0) break
                        raf.write(buf, 0, n)
                        got += n
                        val now = System.currentTimeMillis()
                        if (now - lastReport > 400) {       // 限流上报，别刷爆 UI
                            lastReport = now
                            val mbps = (got - existing) / 1048576.0 / ((now - t0) / 1000.0).coerceAtLeast(0.1)
                            onProgress(got, total, mbps)
                        }
                    }
                }
            }
            onProgress(got, total, 0.0)
            if (a.expectBytes > 0 && part.length() != a.expectBytes) {
                Log.w(TAG, "${a.key} 大小不符：期望 ${a.expectBytes}，实际 ${part.length()}")
                return false
            }
            a.dest.delete()
            val ok = part.renameTo(a.dest)
            Log.i(TAG, "${a.key} 完成 ok=$ok 大小=${a.dest.length()}")
            return ok
        } catch (e: Throwable) {
            Log.w(TAG, "${a.key} 下载失败（可续传）：${e.message}")
            return false
        } finally {
            conn?.disconnect()
        }
    }

    /** 某个文件当前进度（用于界面显示） */
    fun progressOf(a: Artifact): Pair<Long, Long> {
        if (done(a)) return a.expectBytes to a.expectBytes
        val part = File(a.dest.parentFile, a.dest.name + ".part")
        val have = if (part.isFile) part.length() else 0L
        return have to a.expectBytes
    }

    fun statusText(): String {
        val need = missing()
        if (need.isEmpty()) return "模型齐全"
        val mb = need.sumOf { it.expectBytes } / 1048576.0
        return "还需下载 %d 个文件（%.0f MB）".format(need.size, mb)
    }
}
