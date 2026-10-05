package com.localrecord.app

import android.content.Context
import android.net.Uri
import android.provider.DocumentsContract
import java.io.File

/**
 * 模型文件位置管理。
 *
 * 优先顺序（第一个存在的就用）：
 *  1. `Android/data/com.localrecord.app/files/models/`（外置私有目录，USB 可直接拷贝进去，无需权限）
 *  2. 应用内部 `files/models/`（用「导入模型」按钮从手机里选目录复制进来）
 *  3. `assets/models/`（如果把模型打进 APK 里）
 */
class ModelStore(private val context: Context) {

    companion object {
        const val DIR_NAME = "models"
        const val ASR_SUBDIR = "paraformer"
        const val PUNCT_SUBDIR = "punct"
        const val OCR_SUBDIR = "ocr"
        const val ASR_MODEL = "model.int8.onnx"
        const val ASR_TOKENS = "tokens.txt"
        const val PUNCT_MODEL = "model.onnx"
        const val PUNCT_TOKENS = "tokens.json"
        const val OCR_DET_MODEL = "det.onnx"
        const val OCR_REC_MODEL = "rec.onnx"
        const val VAD_SUBDIR = "vad"
        const val VAD_MODEL = "silero.onnx"
        const val LLM_MODEL = "Qwen3.5-2B-Q4_K_M.gguf"
    }

    /** 外置私有目录：/sdcard/Android/data/<pkg>/files/models —— 用户插 USB 就能往里拷 */
    fun externalModelsDir(): File =
        File(context.getExternalFilesDir(null), DIR_NAME).apply { mkdirs() }

    fun internalModelsDir(): File = File(context.filesDir, DIR_NAME).apply { mkdirs() }

    fun modelsDir(): File {
        val ext = externalModelsDir()
        if (hasAsr(ext)) return ext
        val inner = internalModelsDir()
        if (hasAsr(inner)) return inner
        return ext          // 都没有时，给外置路径（方便用户拷贝）
    }

    /**
     * 逐个文件查找：外置优先，找不到再找内部。
     *
     * 不能"整目录二选一" —— 实测出现过 ASR 在外置、标点在内置的情况，
     * 那样标点会被误判为不存在。
     */
    private fun firstExisting(rel: String): File {
        val ext = File(externalModelsDir(), rel)
        if (ext.isFile) return ext
        val inner = File(internalModelsDir(), rel)
        if (inner.isFile) return inner
        return ext
    }

    fun asrDir(): File = File(modelsDir(), ASR_SUBDIR)
    fun asrModel(): File = firstExisting("$ASR_SUBDIR/$ASR_MODEL")
    fun asrTokens(): File = firstExisting("$ASR_SUBDIR/$ASR_TOKENS")
    fun punctDir(): File = File(modelsDir(), PUNCT_SUBDIR)
    fun punctModel(): File = firstExisting("$PUNCT_SUBDIR/$PUNCT_MODEL")
    fun punctTokens(): File = firstExisting("$PUNCT_SUBDIR/$PUNCT_TOKENS")

    private fun hasAsr(dir: File): Boolean =
        File(File(dir, ASR_SUBDIR), ASR_MODEL).isFile

    fun asrReady(): Boolean = asrModel().isFile && asrTokens().isFile
    fun punctReady(): Boolean = punctModel().isFile && punctTokens().isFile

    // ---- OCR（文档问答）：PP-OCRv6 medium 的 det + rec ONNX ----
    fun ocrDetModel(): File = firstExisting("$OCR_SUBDIR/$OCR_DET_MODEL")
    fun ocrRecModel(): File = firstExisting("$OCR_SUBDIR/$OCR_REC_MODEL")
    fun ocrReady(): Boolean = ocrDetModel().isFile && ocrRecModel().isFile

    // ---- 神经网络 VAD（Silero）：精准断句，只有 2.3MB ----
    fun vadModel(): File = firstExisting("$VAD_SUBDIR/$VAD_MODEL")
    fun vadReady(): Boolean = vadModel().isFile

    /** 录音存放目录：同样放在外置私有目录，USB 可拷出 */
    fun recordingsDir(): File =
        File(context.getExternalFilesDir(null), "recordings").apply { mkdirs() }

    /**
     * 把用户通过 SAF 选中的目录里的模型文件复制进来。
     *
     * **按文件名递归查找**（不要求目录层级）：用户选任何一层都行 ——
     *   model.int8.onnx + tokens.txt → models/paraformer/
     *   model.onnx + tokens.json     → models/punct/
     *   *.gguf                       → llm/
     * 这样把 `phone-files`（含 models/ 与 llm/）整个拷到手机任意位置后，
     * 选一次那一层目录就能全部导入。
     */
    fun importFromTree(treeUri: Uri, onProgress: (String) -> Unit): Boolean {
        val found = mutableMapOf<String, Uri>()          // 文件名 → uri
        collectFiles(treeUri, found, depth = 0)
        if (found.isEmpty()) {
            onProgress("这个目录里没找到文件")
            return false
        }
        val asrTarget = File(internalModelsDir(), ASR_SUBDIR).apply { mkdirs() }
        val punctTarget = File(internalModelsDir(), PUNCT_SUBDIR).apply { mkdirs() }
        val llmTarget = File(internalModelsDir().parentFile, "llm").apply { mkdirs() }

        data class Plan(val name: String, val target: File)
        val plans = mutableListOf<Plan>()
        found["model.int8.onnx"]?.let { plans += Plan("model.int8.onnx", File(asrTarget, ASR_MODEL)) }
        found["tokens.txt"]?.let { plans += Plan("tokens.txt", File(asrTarget, ASR_TOKENS)) }
        found["model.onnx"]?.let { plans += Plan("model.onnx", File(punctTarget, PUNCT_MODEL)) }
        found["tokens.json"]?.let { plans += Plan("tokens.json", File(punctTarget, PUNCT_TOKENS)) }
        found.entries.firstOrNull { it.key.endsWith(".gguf") }
            ?.let { plans += Plan(it.key, File(llmTarget, it.key)) }

        var copied = 0
        for (p in plans) {
            val uri = found[p.name] ?: continue
            try {
                val tmp = File(p.target.parentFile, p.target.name + ".part")
                context.contentResolver.openInputStream(uri)?.use { input ->
                    tmp.outputStream().use { output -> input.copyTo(output, 1 shl 20) }
                }
                p.target.delete()
                tmp.renameTo(p.target)
                copied++
                onProgress("已导入 ${p.name}（${p.target.length() / 1048576} MB）")
            } catch (e: Exception) {
                onProgress("导入 ${p.name} 失败：${e.message}")
            }
        }
        return copied > 0
    }

    /** 递归收集选中目录树里的文件（限制深度，避免个别 ROM 的怪结构） */
    private fun collectFiles(treeUri: Uri, out: MutableMap<String, Uri>, depth: Int) {
        if (depth > 4 || out.size > 50) return
        val docId = DocumentsContract.getTreeDocumentId(treeUri)
        val children = DocumentsContract.buildChildDocumentsUriUsingTree(treeUri, docId)
        context.contentResolver.query(
            children,
            arrayOf(
                DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                DocumentsContract.Document.COLUMN_DISPLAY_NAME,
                DocumentsContract.Document.COLUMN_MIME_TYPE,
            ),
            null, null, null,
        )?.use { c ->
            while (c.moveToNext()) {
                val id = c.getString(0)
                val name = c.getString(1) ?: continue
                val mime = c.getString(2)
                val childUri = DocumentsContract.buildDocumentUriUsingTree(treeUri, id)
                if (mime == DocumentsContract.Document.MIME_TYPE_DIR) {
                    collectFiles(childUri, out, depth + 1)
                } else {
                    out.putIfAbsent(name, childUri)
                }
            }
        }
    }

    /**
     * 首页状态栏文字：**只说"现在能做什么"**，不说"就绪/未就绪"这类内部状态。
     * 真的缺模型时，由界面上的「继续下载」入口 + 下载进度条来提示。
     */
    fun statusText(): String = when {
        asrReady() && punctReady() -> "点圆钮开始录音，自动断句、自动出字"
        asrReady() -> "点圆钮开始录音（标点模型还没下完，先出不带标点的文字）"
        else -> "点圆钮开始录音，转写能力需要先下载模型"
    }
}
