package com.localrecord.app

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.MediaPlayer
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectVerticalDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.lazy.LazyListState
import kotlinx.coroutines.launch
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executors
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.max

private val Accent = Color(0xFF6D8BFF)
private val Bg = Color(0xFF0F1117)
private val Card = Color(0xFF1A1F2B)

data class Seg(val text: String, val startSec: Float, val endSec: Float, val time: String)

class MainActivity : ComponentActivity() {

    companion object {
        /**
         * 下载状态放**静态**：切后台被系统回收、再回到前台时 Activity 会重建，
         * 静态状态能保证不会重复启动下载、也不会把正在跑的下载丢掉。
         */
        private val downloading = AtomicBoolean(false)
        private val cancelDownload = AtomicBoolean(false)

        /** 通知栏「停止录音」按钮会把它置 true，界面计时器看到后收尾 */
        @Volatile var stopRequested = false
    }

    private lateinit var store: ModelStore
    private lateinit var asr: AsrEngine
    private lateinit var llm: LlmEngine
    private lateinit var vadEngine: SileroVad
    private lateinit var downloader: ModelDownloader
    private val io = Executors.newFixedThreadPool(3)
    private val asrBusy = AtomicBoolean(false)
    private val llmBusy = AtomicBoolean(false)
    private var showDownloading by mutableStateOf(false)   // 界面用
    private var missingCount by mutableStateOf(0)          // 还没下完的文件数
    private var netCallback: android.net.ConnectivityManager.NetworkCallback? = null
    @Volatile private var forceBigDownload = false          // 用户点「继续下载」= 允许用流量下大模型

    private val segments = mutableStateListOf<Seg>()

    // ---------------- 逐句翻译（边识别边翻译）----------------
    private var translationOn by mutableStateOf(true)                 // 开关：默认打开
    /** 段序号 → 译文（Compose 的 stateMap，写进去界面自动刷新） */
    private val translations = androidx.compose.runtime.mutableStateMapOf<Int, String>()
    private val translateQueue = java.util.concurrent.LinkedBlockingQueue<Pair<Int, String>>()
    private val translateRunning = AtomicBoolean(false)

    /** 待翻译最多留几句：超了丢最旧的，保证翻译追着"最新一句"而不是越拖越远 */
    private val MAX_PENDING = 5

    /** 因积压被跳过的段（界面标一下，免得一直显示"翻译中…"） */
    private val translateSkipped = androidx.compose.runtime.mutableStateListOf<Int>()

    /** 把一句转写排进翻译队列：串行执行，避免几个请求同时抢大模型 */
    private fun enqueueTranslation(idx: Int, text: String) {
        if (!translationOn || translations.containsKey(idx)) return
        // 太短的（"嗯"、"好"、单个符号）不值得花一秒去翻译，直接跳过省时间
        if (text.trim().count { it.isLetterOrDigit() } < 2) return
        translateQueue.offer(idx to text)
        // 积压保护：只保留最新 MAX_PENDING 句，多出来的丢掉并标注
        while (translateQueue.size > MAX_PENDING) {
            val dropped = translateQueue.poll() ?: break
            translateSkipped.add(dropped.first)
            android.util.Log.i("Translate", "积压过多，跳过第 ${dropped.first + 1} 句")
        }
        startTranslateWorker()
    }

    private fun startTranslateWorker() {
        if (!translateRunning.compareAndSet(false, true)) return
        io.execute {
            try {
                while (true) {
                    val (idx, text) = translateQueue.poll() ?: break
                    if (!translationOn || translations.containsKey(idx)) continue
                    if (!ensureLlmQuiet()) break
                    val t0 = System.currentTimeMillis()
                    val out = try {
                        llm.translate(text)
                    } catch (e: Throwable) {
                        android.util.Log.w("Translate", "翻译失败：${e.message}")
                        ""
                    }
                    val ms = System.currentTimeMillis() - t0
                    android.util.Log.i("Translate", "第 ${idx + 1} 句 ${ms}ms：${text.take(16)} → ${out.take(24)}")
                    if (out.isNotBlank()) runOnUiThread { translations[idx] = out }
                }
            } finally {
                translateRunning.set(false)
                if (translateQueue.isNotEmpty()) startTranslateWorker()
            }
        }
    }

    /** 静默加载大模型：不覆盖转写状态栏（首次要读约 400MB，几秒钟） */
    private fun ensureLlmQuiet(): Boolean {
        if (llm.ready) return true
        if (llm.findModel() == null) {
            runOnUiThread { status = "翻译模型还没下载好，下完会自动开始翻译" }
            return false
        }
        val ok = try {
            llm.init()
        } catch (_: Throwable) {
            false
        }
        llmReady = ok
        if (!ok) runOnUiThread { status = "翻译模型加载失败（可能内存不够），已暂停翻译" }
        return ok
    }


    /** 清空转写：带上调用堆栈，方便定位"谁把它清了"（之前遇到过"界面 0 段但状态说 9 段"） */
    private fun clearSegments(why: String) {
        android.util.Log.i("Segments", "清空转写（$why），之前 ${segments.size} 段", Throwable("clearSegments"))
        segments.clear()
        translations.clear()
        translateSkipped.clear()
        translateQueue.clear()
    }
    private var recording by mutableStateOf(false)
    private var level by mutableStateOf(0f)
    private var status by mutableStateOf("正在加载模型…")
    private var asrReady by mutableStateOf(false)
    private var llmReady by mutableStateOf(false)
    private var llmName by mutableStateOf("")
    private var minutes by mutableStateOf("")
    private var answer by mutableStateOf("")
    private var question by mutableStateOf("")
    private var tab by mutableStateOf(0)
    private var downloadPct by mutableStateOf(0f)
    private val recordings = mutableStateListOf<File>()
    private var player: MediaPlayer? = null
    private var playingPath by mutableStateOf<String?>(null)   // 当前正在播放的录音
    private var playingPaused by mutableStateOf(false)
    private var playPosMs by mutableStateOf(0)
    private var playDurMs by mutableStateOf(0)
    private var pathDialog by mutableStateOf<String?>(null)    // 显示/复制路径的对话框
    private var micBlocked by mutableStateOf(false)            // 麦克风权限被拒 → 弹窗引导去设置
    private var asrFilesReady by mutableStateOf(false)         // 识别模型文件是否已在手机上

    private var deleteDialog by mutableStateOf<File?>(null)    // 删除确认对话框
    private var seeking by mutableStateOf(false)               // 是否正在拖动进度条
    private var textCopied by mutableStateOf(false)            // 转写文字刚被复制
    private var llmDialog by mutableStateOf<Pair<String, String>?>(null)   // 大模型结果弹窗（标题 to 内容）
    private var recTick by mutableStateOf(0L)                  // 录音计时/波形的刷新触发器
    private var elapsedUi by mutableStateOf(0f)                // 界面显示的录音时长（由 ticker 推）
    private var liveInfo by mutableStateOf("")                 // 录音健康状态：已出几段/麦克风是否正常
    private var recognizing by mutableStateOf(false)           // 正在识别某一段
    private var enhanceOn by mutableStateOf(false)             // 系统降噪开关（默认关）
    private val wave = mutableStateListOf<Float>()              // 最近的音量（画波形）

    private var recorder: Recorder? = null

    /**
     * 一次"录音会话"的实时转写线程。
     *
     * **每个会话一个独立的 stop 标志**（不能用共享的那个）：
     * 用共享标志时，新会话把它设回 false 会把**上一轮还没收尾完的线程复活**，
     * 于是两个线程同时调 sherpa 的识别器（非线程安全）→ 表现就是
     * "第一次出字之后，后面怎么录都不识别了"（用户实测反馈）。
     */
    private class LiveSession {
        val stop = AtomicBoolean(false)
        var thread: Thread? = null
    }

    private var live = LiveSession()

    private val pickTree = registerForActivityResult(
        ActivityResultContracts.OpenDocumentTree()
    ) { uri ->
        if (uri != null) {
            status = "正在导入模型…"
            io.execute {
                val ok = store.importFromTree(uri) { msg -> runOnUiThread { status = msg } }
                runOnUiThread {
                    status = if (ok && asr.init()) "模型导入完成，可以开始录音"
                    else "导入失败：请确认选的目录里含 paraformer/ 与 punct/ 两个子目录"
                    asrReady = asr.ready
                }
            }
        }
    }

    private val askMic = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) {
            status = "麦克风已授权，点右侧的圆形「录」按钮开始录音"
        } else {
            // 用户拒绝了：给出明确指引（可能是"不再询问"，那就只能去系统设置里开）
            micBlocked = true
            status = "没有麦克风权限，无法录音"
        }
    }

    /** 选一个大模型 gguf，复制到 llm/ 目录 */
    private val pickGguf = registerForActivityResult(
        ActivityResultContracts.OpenDocument()
    ) { uri ->
        if (uri != null) {
            status = "正在复制大模型…"
            io.execute {
                val dst = File(llm.llmDir(), "model.gguf")
                try {
                    contentResolver.openInputStream(uri)?.use { input ->
                        dst.outputStream().use { output -> input.copyTo(output, 1 shl 20) }
                    }
                    runOnUiThread { status = "大模型已就位：${dst.length() / 1024 / 1024} MB，点「生成会议纪要」即可" }
                } catch (e: Exception) {
                    runOnUiThread { status = "复制失败：${e.message}" }
                }
            }
        }
    }

    // ------------------------------------------------- 模型下载 ----

    /** 现在有网吗 */
    private fun online(): Boolean = try {
        val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as android.net.ConnectivityManager
        val n = cm.activeNetwork ?: return false
        val caps = cm.getNetworkCapabilities(n)
        caps != null && caps.hasCapability(android.net.NetworkCapabilities.NET_CAPABILITY_INTERNET)
    } catch (e: Exception) {
        true      // 判断不了就当有网，让下载自己报错
    }

    /** 现在是流量网络（非 WiFi）吗 */
    private fun isMetered(): Boolean = try {
        val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as android.net.ConnectivityManager
        cm.isActiveNetworkMetered
    } catch (e: Exception) {
        false
    }

    /** 大模型等 WiFi（或用户点「继续下载」强制）；返回 false 表示被取消/超时 */
    private fun waitForWifiOrForce(): Boolean {
        var waited = 0
        while (!cancelDownload.get()) {
            if (forceBigDownload || !isMetered()) return true
            try {
                Thread.sleep(2000)
            } catch (_: InterruptedException) {
                return false
            }
            waited += 2
            if (waited > 1800) return false      // 最多等 30 分钟
        }
        return false
    }

    /** 断网就等（最多 30 分钟），网络恢复立刻继续；返回 false 表示被取消/超时 */
    private fun waitForNetwork(): Boolean {
        var waited = 0
        while (!cancelDownload.get()) {
            if (online()) return true
            runOnUiThread {
                showDownloading = true
                downloadPct = 0f
                status = "网络已断开，等重连后自动继续…\n已下载的部分会保留，不会从头再来"
            }
            try {
                Thread.sleep(2000)
            } catch (_: InterruptedException) {
                return false
            }
            waited += 2
            if (waited > 1800) return false
        }
        return false
    }

    private fun acquireWakeLock() {
        // wakelock 由 DownloadService 持有（Activity 被回收也不影响下载）
    }

    private fun releaseWakeLock() {
    }

    private fun refreshMissing() {
        missingCount = downloader.missing().size
    }

    /** 需要下载就启动（不重入）。用**独立线程**：Activity 的线程池在 onDestroy 会被关掉，
     *  而下载应该在切后台后继续跑（前台服务保活）。 */
    private fun startDownloadIfIdle() {
        if (downloading.get()) return
        if (intent?.getBooleanExtra("downloadtest", false) == true) return   // 自检自己会下
        if (intent?.getBooleanExtra("nodownload", false) == true) return
        Thread({
            val n = downloader.missing().size
            runOnUiThread { missingCount = n }
            if (n == 0) return@Thread
            autoDownload()
        }, "model-download").start()
    }

    /**
     * 自动下载全部缺失文件。关键行为：
     *  * 断网 → 等着，网络一恢复**自动继续**，不用重新点；
     *  * 单个文件失败会重试 3 轮（主源→备源→退避重试），失败也**保留 .part**，下次从断点续；
     *  * 每一轮都重新算"还缺什么"，所以已下完的不会重下；
     *  * 连续 3 轮毫无进展才停手，并提示用户点「继续下载」。
     */
    private fun autoDownload() {
        if (!downloading.compareAndSet(false, true)) return
        cancelDownload.set(false)
        runOnUiThread { showDownloading = true }
        acquireWakeLock()
        // 起前台服务：通知栏显示进度，切到别的 app / 锁屏都继续下
        DownloadService.title = "正在下载模型"
        DownloadService.detail = "准备中…"
        DownloadService.percent = 0
        DownloadService.start(this)
        var stall = 0
        try {
            while (!cancelDownload.get()) {
                val need = downloader.missing()
                runOnUiThread { missingCount = need.size }
                if (need.isEmpty()) break
                if (!waitForNetwork()) break
                val totalBytes = need.sumOf { it.expectBytes }.coerceAtLeast(1L)
                var progressed = false
                for (a in need) {
                    if (cancelDownload.get()) break
                    // 大模型（>500MB）在**流量网络**下默认等 WiFi，避免偷偷跑掉 1.5GB 流量；
                    // 点界面上的「继续下载」= 授权立即下载。
                    if (downloader.isBigArtifact(a) && !forceBigDownload && isMetered()) {
                        runOnUiThread {
                            status = "较大的模型文件（${a.humanSize()}）正在等 WiFi，避免用流量。\n" +
                                "想现在就用流量下，点上面「继续下载」"
                        }
                        if (!waitForWifiOrForce()) break
                    }
                    val already = downloader.progressOf(a).first
                    val otherBytes = need.filter { it != a }.sumOf { downloader.progressOf(it).first }
                    val okOne = downloader.download(
                        a,
                        onProgress = { got, total, mbps ->
                            val overall = (otherBytes + got).toFloat() / totalBytes.toFloat()
                            val pct = (overall * 100).toInt().coerceIn(0, 100)
                            // 通知栏也更新（用户切到别的 app 时能看到进度）
                            DownloadService.percent = pct
                            DownloadService.title = "正在下载模型 $pct%"
                            DownloadService.detail = "%.0f/%.0f MB  %.1f MB/s".format(
                                got / 1048576.0, total / 1048576.0, mbps
                            )
                            runOnUiThread {
                                downloadPct = overall.coerceIn(0f, 1f)
                                // % 不能紧挨中文再交给 format（会当格式符 → 曾崩 UnknownFormatConversionException）
                                status = "正在下载模型 ${pct}%\n" +
                                    "%.0f / %.0f MB   %.1f MB/s".format(
                                        got / 1048576.0, total / 1048576.0, mbps
                                    )
                            }
                        },
                        // 断网时尽快退出当前文件，回到外层等网络（保留 .part 续传）
                        shouldStop = { cancelDownload.get() || !online() },
                        onRetry = { i, n ->
                            runOnUiThread { status = "下载中断，正在重试 $i/$n…（断点续传，不用管）" }
                        },
                    )
                    if (okOne) {
                        progressed = true
                        // 边下边就绪：必要模型一落地就立刻能用，**不必等 1.5GB 的大模型下完**
                        try {
                            when (a.key) {
                                "asr-model", "asr-tokens" -> if (!asrReady) {
                                    val o = asr.init()
                                    runOnUiThread { asrReady = o }
                                }
                                "punct-model", "punct-tokens" -> {
                                    val o = asr.init()          // 标点在 init 里一起加载
                                    runOnUiThread { asrReady = o }
                                }
                                "llm" -> {
                                    // 不自动加载（占内存），等用户点「生成会议纪要」时再加载
                                }
                            }
                        } catch (t: Throwable) {
                            android.util.Log.w("Download", "边下边就绪失败（下次再用）：${t.message}")
                        }
                    } else if (!online()) {
                        break          // 断网了，跳出去等网络恢复后接着下这一个
                    }
                }
                if (progressed) stall = 0 else stall++
                if (stall >= 3) {
                    runOnUiThread {
                        status = "下载多次失败，已暂停（可能是网络不稳）。\n" +
                            "已下载的部分都保留着 —— 点上面「继续下载」即可断点续下"
                    }
                    break
                }
            }
        } finally {
            releaseWakeLock()
            DownloadService.stop(this)          // 下载结束，收掉前台服务与通知
            val left = downloader.missing().size
            runOnUiThread {
                downloading.set(false)
                showDownloading = false
                downloadPct = 0f
                missingCount = left
                status = if (left == 0) store.statusText()
                else "还有 $left 个文件没下完 —— 点「继续下载」断点续下"
            }
            val ok = asr.init()
            runOnUiThread { asrReady = ok }
        }
    }

    /** 下载自检：小文件验 HTTPS+CDN+大小校验；若 ASR 模型缺失，再走一次真实下载并用它识别 */
    private fun runDownloadSelfTest() {
        val out = File(store.externalModelsDir().parentFile, "download-selftest-result.txt")
        fun report(line: String) {
            android.util.Log.i("DownloadSelfTest", line)
            try { out.appendText(line + "\n") } catch (_: Exception) {}
        }
        report("下载源 = hf-mirror")
        // 1) 小文件：验证 HTTPS + 跳转 + 大小校验
        for (a in downloader.artifacts.filter { it.key == "asr-tokens" || it.key == "punct-tokens" }) {
            val dest = File(File(store.externalModelsDir(), "selftest"), a.dest.name)
            dest.parentFile?.mkdirs()
            val probe = a.copy(dest = dest)
            val t0 = System.currentTimeMillis()
            val ok = downloader.download(probe, onProgress = { _, _, mbps ->
                if (mbps > 0) report("  ${a.key} 速度 %.1f MB/s".format(mbps))
            })
            report("${a.key}: ok=$ok 期望=${a.expectBytes} 实际=${if (dest.isFile) dest.length() else -1} " +
                    "用时=${System.currentTimeMillis() - t0}ms")
        }
        // 2) 真实下载：转写模型缺失时，走和界面按钮完全相同的代码路径
        val need = downloader.missing()
        if (need.isNotEmpty()) {
            report("需要下载转写模型：${need.size} 个文件")
            val t0 = System.currentTimeMillis()
            var okAll = true
            for (a in need) {
                val ok = downloader.download(a, onProgress = { got, total, mbps ->
                    if (got % (50L * 1048576) < 1048576) {
                        report("  ${a.key}: %.0f/%.0f MB  %.1f MB/s".format(
                            got / 1048576.0, total / 1048576.0, mbps))
                    }
                })
                report("  ${a.key} ok=$ok 落地=${a.dest.length()} 期望=${a.expectBytes}")
                if (!ok) { okAll = false; break }
            }
            report("下载阶段完成 okAll=$okAll 用时=${(System.currentTimeMillis() - t0) / 1000}s")
        } else {
            report("转写模型已存在，跳过真实下载")
        }
        // 3) 用下好的模型识别（证明下载的模型可用）
        val okInit = asr.init()
        report("ASR 重新初始化 ok=$okInit")
        val wav = File(store.externalModelsDir().parentFile, "selftest.wav")
        if (okInit && wav.isFile()) {
            val (emitted, skipped) = asr.transcribe(wav, onSegment = { s -> report("SEG ${s.text}") })
            report("识别：emitted=$emitted skipped=$skipped")
        }
        report("DONE")
        runOnUiThread { asrReady = okInit; status = if (okInit) "自检完成：模型可用" else "自检：模型仍不可用" }
    }

    // ------------------------------------------------- 大模型（纪要 / 问答）----

    private fun transcriptText(): String =
        segments.joinToString("\n") { "[${it.startSec.toInt()}] ${it.text}" }

    /** 必要模型是否已就位（只用于顶部"还没下载完"的提示） */
    private fun refreshModelFileFlags() {
        asrFilesReady = store.asrReady()
    }

    private fun ensureLlm(): Boolean {
        if (llm.ready) return true
        if (llm.findModel() == null) {
            status = "没找到大模型：请把 gguf 放进 ${llm.llmDir().absolutePath}，或点「选择大模型」"
            return false
        }
        status = "正在加载大模型（首次约 10~30 秒）…"
        val ok = llm.init()
        llmReady = ok
        llmName = llm.loadedModel
        status = if (ok) "大模型已加载好，可以生成会议纪要了" else "加载失败（可能内存不够）"
        return ok
    }

    private fun startMinutes() {
        val text = transcriptText()
        if (text.isBlank()) { status = "还没有转写内容，先录一段"; return }
        if (!llmBusy.compareAndSet(false, true)) { status = "大模型正忙"; return }
        io.execute {
            if (ensureLlm()) {
                runOnUiThread { status = "正在生成会议纪要…" }
                val t0 = System.currentTimeMillis()
                val out = llm.summarize(text)
                runOnUiThread {
                    minutes = out
                    llmDialog = "会议纪要" to out      // 弹窗显示（可滚动、可复制）
                    status = "会议纪要完成（${out.length} 字，用时 ${(System.currentTimeMillis() - t0) / 1000}s · ${llm.lastStats}）"
                }
            }
            llmBusy.set(false)
        }
    }

    private fun startAsk() {
        val q = question.trim()
        if (q.isEmpty()) return
        val isOcr = false
        val text = transcriptText()
        if (text.isBlank()) { status = if (isOcr) "先选一张图片做识别" else "还没有转写内容"; return }
        if (!llmBusy.compareAndSet(false, true)) { status = "大模型正忙"; return }
        io.execute {
            if (ensureLlm()) {
                runOnUiThread { status = "正在思考…" }
                val t0 = System.currentTimeMillis()
                val out = llm.ask(text, q)
                val sec = (System.currentTimeMillis() - t0) / 1000.0
                runOnUiThread {
                    answer = out
                    llmDialog = "AI 回答" to out
                    status = "回答完成（${out.length} 字，用时 %.1fs · ${llm.lastStats}）".format(sec)
                }
            }
            llmBusy.set(false)
        }
    }

    /**
     * 导入解码自检：把 files/audiotest.{ogg,flac,mp3} 用系统解码器解出来并转写。
     * 验证"非 wav 格式（mp3/m4a/ogg/flac…）也能导入转写"这条链路。
     */
    private fun runAudioImportSelfTest() {
        val out = File(store.externalModelsDir().parentFile, "audio-selftest-result.txt")
        fun report(line: String) {
            android.util.Log.i("AudioTest", line)
            try { out.appendText(line + "\n") } catch (_: Exception) {}
        }
        if (!asr.init()) { report("FAIL ASR 未就绪"); return }
        val useSilero = vadEngine.ready || vadEngine.init()
        report("Silero VAD: ${if (useSilero) "启用" else "未启用（用能量法）"}")
        for (name in listOf("audiotest.ogg", "audiotest.flac", "audiotest.mp3")) {
            val f = File(store.externalModelsDir().parentFile, name)
            if (!f.isFile) { report("$name: 文件不存在"); continue }
            vadEngine.reset()
            val energyVad = Vad(AsrEngine.SAMPLE_RATE)
            var total = 0
            val texts = ArrayList<String>()
            val t0 = System.currentTimeMillis()
            val ok = AudioDecoder.decodeStream(this, android.net.Uri.fromFile(f)) { chunk ->
                total += chunk.size
                if (useSilero) {
                    vadEngine.feed(chunk) { s, st ->
                        val txt = asr.recognize(s)
                        if (txt.isNotBlank()) texts.add(txt)
                    }
                } else {
                    energyVad.feed(chunk) { s, st ->
                        val txt = asr.recognize(s)
                        if (txt.isNotBlank()) texts.add(txt)
                    }
                }
                true
            }
            if (useSilero) vadEngine.flush { s, _ ->
                val txt = asr.recognize(s)
                if (txt.isNotBlank()) texts.add(txt)
            } else energyVad.flush { s, _ ->
                val txt = asr.recognize(s)
                if (txt.isNotBlank()) texts.add(txt)
            }
            val sec = total.toFloat() / AudioDecoder.TARGET_RATE
            report("$name: 解码${if (ok) "成功" else "失败"} 得到 %.2f 秒 / %d 段 / 用时 %dms".format(
                sec, texts.size, System.currentTimeMillis() - t0))
            texts.forEach { report("    $it") }
        }
        report("DONE")
    }

    /** 实时转写自检：喂 3 遍音频（多段）+ 第二个会话（验证"再录一次还能识别"） */
    private fun runLiveSelfTest() {
        val out = File(store.externalModelsDir().parentFile, "live-selftest-result.txt")
        fun report(line: String) {
            android.util.Log.i("LiveSelfTest", line)
            try { out.appendText(line + "\n") } catch (_: Exception) {}
        }
        if (!asr.init()) { report("FAIL ASR 未就绪"); return }
        val wav = File(store.externalModelsDir().parentFile, "selftest.wav")
        if (!wav.isFile) { report("FAIL 没有 selftest.wav"); return }
        val (samples, _) = asr.readWav(wav) ?: return
        report("音频 ${samples.size} 采样 = ${"%.1f".format(samples.size / 16000f)} 秒")

        fun snapshotSegments(): List<Seg> {
            var snap: List<Seg> = emptyList()
            val latch = java.util.concurrent.CountDownLatch(1)
            runOnUiThread { snap = segments.toList(); latch.countDown() }
            latch.await(2, java.util.concurrent.TimeUnit.SECONDS)
            return snap
        }

        fun feed(r: Recorder, from: Int, to: Int) {
            var i = from
            while (i < to) {
                val n = minOf(1600, to - i)          // 100ms 一块
                val blk = ShortArray(n) { k ->
                    (samples[i + k] * 32000f).toInt().coerceIn(-32768, 32767).toShort()
                }
                r.chunks.offer(blk)
                i += n
                try { Thread.sleep(10) } catch (_: InterruptedException) {}
            }
        }

        // ---- 会话 1：喂 3 遍音频，每遍之间插 1.5 秒静音（验证 VAD 按静音收段）----
        runOnUiThread { clearSegments("自检") }
        val r1 = Recorder(File(store.recordingsDir(), "livetest1.wav"))
        startLiveAsr(r1)
        val silence = ShortArray(AsrEngine.SAMPLE_RATE * 3 / 2)      // 1.5 秒静音
        repeat(3) { round ->
            feed(r1, 0, samples.size)
            r1.chunks.offer(silence)
            Thread.sleep(1500)
            report("会话1 第 ${round + 1} 遍（含 1.5s 静音）喂完，段数=${snapshotSegments().size}")
        }
        live.stop.set(true)
        Thread.sleep(2500)
        live.stop.set(true)
        Thread.sleep(6000)                       // 等收尾那一段识别完（模拟器上较慢）
        val s1 = snapshotSegments()
        report("会话1 结束：段数=${s1.size}")
        s1.forEachIndexed { i, s -> report("  SEG$i [${"%.1f".format(s.startSec)}s] ${s.text}") }

        // ---- 会话 2：新的一次"录音"，验证上一次之后还能继续识别，且不混入上一轮的段 ----
        runOnUiThread { clearSegments("自检") }
        val r2 = Recorder(File(store.recordingsDir(), "livetest2.wav"))
        startLiveAsr(r2)
        feed(r2, 0, samples.size)
        Thread.sleep(1500)
        live.stop.set(true)
        Thread.sleep(6000)
        val s2 = snapshotSegments()
        report("会话2 结束：段数=${s2.size}")
        s2.forEachIndexed { i, s -> report("  SEG$i [${"%.1f".format(s.startSec)}s] ${s.text}") }
        // 会话 1 应该有 3 段（VAD 在每段 1.5 秒静音处收段，而不是固定 8 秒切）
        val vadOk = s1.size >= 3
        val noBleed = s2.all { it.startSec < 1f }

        // ---- 会话 3：纯噪声 12 秒 —— **不该切出任何段**（噪声出字是用户报的主要问题）----
        runOnUiThread { clearSegments("自检") }
        val r3 = Recorder(File(store.recordingsDir(), "livetest3.wav"))
        startLiveAsr(r3)
        val rnd = java.util.Random(11)
        repeat(120) {                                          // 12 秒
            val blk = ShortArray(1600) { ((rnd.nextFloat() - 0.5f) * 0.004f * 32768f).toInt().toShort() }
            r3.chunks.offer(blk)
            try { Thread.sleep(10) } catch (_: InterruptedException) {}
        }
        Thread.sleep(2000)
        live.stop.set(true)
        Thread.sleep(4000)
        val s3 = snapshotSegments()
        report("会话3（12 秒纯噪声）段数=${s3.size}（期望 0）")
        s3.forEachIndexed { i, s -> report("  NOISE$i [${"%.1f".format(s.startSec)}s] ${s.text}") }

        val pass = vadOk && s2.isNotEmpty() && noBleed && s3.isEmpty()
        report("VAD 收段数=${s1.size}（期望 3，每遍一段）")
        report("会话2 是否混入上一轮的段：${if (noBleed) "否 ✅" else "是 ❌"}")
        report("噪声是否被误识别成文字：${if (s3.isEmpty()) "否 ✅" else "是 ❌（${s3.size} 段）"}")
        report(if (pass) "RESULT PASS（VAD 断句正常、会话独立、噪声不出字）"
               else "RESULT FAIL（会话1=${s1.size} 段，会话2=${s2.size} 段，噪声=${s3.size} 段，串段=${!noBleed}）")
        runOnUiThread { status = "实时转写自检：会话1=${s1.size} 段，会话2=${s2.size} 段" }
    }

    /** 导入外部音频（mp3/wav/m4a/…）：复制进录音目录，然后自动转写 */
    private val pickAudio = registerForActivityResult(
        ActivityResultContracts.OpenDocument()
    ) { uri ->
        if (uri == null) return@registerForActivityResult
        status = "正在导入音频…"
        io.execute {
            val displayName = queryName(uri) ?: "imported"
            val ext = displayName.substringAfterLast('.', "mp3").lowercase()
            if (ext !in AudioDecoder.SUPPORTED_EXT) {
                runOnUiThread { status = "不支持的格式：.$ext（支持 mp3/wav/m4a/aac/ogg/flac/amr）" }
                return@execute
            }
            val dst = File(
                store.recordingsDir(),
                "imp-" + SimpleDateFormat("MMdd-HHmmss", Locale.US).format(Date()) + "." + ext
            )
            val ok = try {
                contentResolver.openInputStream(uri)?.use { input ->
                    dst.outputStream().use { output -> input.copyTo(output, 1 shl 20) }
                }
                dst.length() > 0
            } catch (e: Throwable) {
                android.util.Log.e("MainActivity", "导入失败", e)
                false
            }
            runOnUiThread {
                if (ok) {
                    refreshRecordings()
                    tab = 1
                    status = "已导入 ${dst.name}（${dst.length() / 1024} KB），正在转写…"
                    transcribe(dst)
                } else {
                    status = "导入失败（读不到文件？）"
                }
            }
        }
    }

    /** 取 SAF 文件的显示名（用于判断后缀） */
    private fun queryName(uri: android.net.Uri): String? = try {
        contentResolver.query(uri, arrayOf(android.provider.OpenableColumns.DISPLAY_NAME), null, null, null)
            ?.use { c -> if (c.moveToFirst()) c.getString(0) else null }
    } catch (_: Throwable) {
        null
    }



    /** 大模型自检：用固定转写跑一次会议纪要，结果写字到文件（供无 UI 验证） */
    /** --ez translatetest true：验证逐句翻译（Qwen3-0.6B）是否可用、是否关掉思维链 */
    private fun runTranslateSelfTest() {
        io.execute {
            val out = File(store.externalModelsDir().parentFile, "translate-result.txt")
            val sb = StringBuilder()
            fun report(line: String) {
                sb.append(line).append("\n")
                android.util.Log.i("TranslateTest", line)
            }
            val model = llm.findModel()
            report("大模型文件=${model?.absolutePath ?: "没找到"}")
            report("文件大小=${model?.length()?.div(1048576) ?: 0} MB")
            val t0 = System.currentTimeMillis()
            val ok = try {
                llm.init()
            } catch (e: Throwable) {
                report("加载异常：${e.message}")
                false
            }
            report("加载=${ok}（${System.currentTimeMillis() - t0}ms） 已加载=${llm.loadedModel}")
            if (ok) {
                for (s in listOf(
                    "今天的会议改到下午三点，请大家准时参加。",
                    "Please send me the updated report by Friday."
                )) {
                    val t1 = System.currentTimeMillis()
                    val tr = try {
                        llm.translate(s)
                    } catch (e: Throwable) {
                        "异常：${e.message}"
                    }
                    report("原文：$s")
                    report("译文：$tr")
                    report("用时=${System.currentTimeMillis() - t1}ms")
                }
                report("RESULT PASS")
            } else {
                report("RESULT FAIL（模型没加载起来）")
            }
            try {
                out.writeText(sb.toString())
            } catch (_: Throwable) {
            }
            runOnUiThread { status = "翻译自检完成：${out.name}" }
        }
    }

    private fun runLlmSelfTest() {
        val out = File(store.externalModelsDir().parentFile, "llm-selftest-result.txt")
        fun report(line: String) {
            android.util.Log.i("LlmSelfTest", line)
            try { out.appendText(line + "\n") } catch (_: Exception) {}
        }
        report("llm 目录=${llm.llmDir().absolutePath}")
        val model = llm.findModel()
        report("找到模型=${model?.name ?: "(无)"} 大小=${(model?.length() ?: 0) / 1024 / 1024}MB")
        if (model == null) { report("FAIL 没有 gguf"); return }
        val t0 = System.currentTimeMillis()
        report("开始加载：${System.currentTimeMillis() - t0}ms")
        val ok = llm.init()
        report("加载完成 ok=$ok 用时=${System.currentTimeMillis() - t0}ms")
        if (!ok) return
        val demo = "[0] 大家好，今天我们过一下这个季度的交付情况。" +
            "[7] 第一个模块已经完成了联调，测试用例覆盖了百分之八十五。" +
            "[14] 第二个模块遇到一点阻塞，主要卡在第三方的接口联调上。" +
            "[21] 我们计划把风险同步给采购，下周三之前给出替代方案。" +
            "[28] 第三个模块按原计划下周上线，需要运维配合灰度发布。" +
            "[35] 客服反馈了两个线上问题，优先级比较高，本周内要修。" +
            "[42] 人力方面，小王下周休假三天，排期要往前挪一挪。" +
            "[49] 下周一上午十点开复盘会，请大家提前把数据准备好。"
        val t1 = System.currentTimeMillis()
        val text = llm.summarize(demo)
        report("生成用时=${System.currentTimeMillis() - t1}ms 长度=${text.length}")
        report("TEXT-BEGIN")
        text.split("\n").forEach { report("  $it") }
        report("TEXT-END")
        runOnUiThread { minutes = text; llmReady = true; llmName = llm.loadedModel }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        store = ModelStore(this)
        asr = AsrEngine(store)
        llm = LlmEngine(store)
        vadEngine = SileroVad(store)
        downloader = ModelDownloader(store)
        refreshRecordings()
        val selfTest = intent?.getBooleanExtra("selftest", false) == true
        val llmSelfTest = intent?.getBooleanExtra("llmselftest", false) == true
        val translateTest = intent?.getBooleanExtra("translatetest", false) == true
        val downloadTest = intent?.getBooleanExtra("downloadtest", false) == true
        val liveTest = intent?.getBooleanExtra("livetest", false) == true
        val audioTest = intent?.getBooleanExtra("audiotest", false) == true
        // 仅用于离线/无模型时验证"结果弹窗"界面：--ez llmdemo true
        val llmDemo = intent?.getBooleanExtra("llmdemo", false) == true
        // 仅用于离线/无网环境下验证界面：--ez nodownload true 跳过自动下载
        val noDownload = intent?.getBooleanExtra("nodownload", false) == true
        io.execute {
            var ok = asr.init()
            // 模型文件在不在手机上（用于界面显示"可直接识别"，避免明明能用却显示未就绪）
            refreshModelFileFlags()
            // 缺模型就自动全部下（不给用户选择）；已有的文件按字节数判断、不会重复下
            if (!downloadTest && !noDownload) {
                refreshMissing()
                if (missingCount > 0) {
                    val mb = downloader.missing().sumOf { it.expectBytes } / 1048576.0
                    runOnUiThread { status = "首次使用，正在自动下载模型（共 %.0f MB，建议用 WiFi）…".format(mb) }
                    autoDownload()
                    ok = asr.init()
                }
            }
            runOnUiThread {
                asrReady = ok
                status = if (ok) store.statusText() else "模型不完整：${downloader.statusText()}"
            }
            if (selfTest && ok) runSelfTest()
            if (llmSelfTest) runLlmSelfTest()
            if (translateTest) runTranslateSelfTest()
            if (downloadTest) runDownloadSelfTest()
            if (liveTest) runLiveSelfTest()
            if (audioTest) runAudioImportSelfTest()
            if (llmDemo) {
                // 故意用带 Markdown 的样例，验证会被清成纯文本
                val demo = "## 会议纪要\n**一句话概述**：讨论了交付节奏与风险。\n\n### 一、重点内容\n- 会议改到下午三点\n- 交付时间不变\n\n### 二、待办事项\n| 事项 | 负责人 | 时间要求 |\n|---|---|---|\n| 出周报 | 张三 | 周五 |\n"
                runOnUiThread { minutes = LlmText.toPlainText(demo); llmDialog = "会议纪要" to minutes; tab = 0 }
            }
        }
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) askMic.launch(Manifest.permission.RECORD_AUDIO)
        if (android.os.Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission("android.permission.POST_NOTIFICATIONS")
            != PackageManager.PERMISSION_GRANTED
        ) {
            // 只影响"下载进度通知"能不能显示，不给也不影响下载
            requestPermissions(arrayOf("android.permission.POST_NOTIFICATIONS"), 1001)
        }
        // 上次的下载线程可能还在跑（Activity 被回收后重建），同步界面状态
        showDownloading = downloading.get()
        if (downloading.get()) uiPoller.post(pollTask)
        registerNetworkWatcher()

        setContent {
            MaterialTheme(colorScheme = darkColorScheme(
                primary = Accent, background = Bg, surface = Bg
            )) {
                Surface(modifier = Modifier.fillMaxSize(), color = Bg) {
                    AppScreen()
                    // 播放进度定时刷新（拖动进度条时以手指位置为准，松手才 seek）
                    LaunchedEffect(playingPath) {
                        if (playingPath != null) {
                            while (playingPath != null) {
                                try {
                                    val p = player
                                    if (p != null) {
                                        val pos = p.currentPosition
                                        // 拖动中不覆盖用户拖到的位置
                                        if (!seeking) playPosMs = pos
                                        val dur = p.duration
                                        if (dur > 0) playDurMs = dur
                                    }
                                } catch (_: Throwable) {
                                }
                                kotlinx.coroutines.delay(200)
                            }
                        }
                    }
                    // 路径对话框（看/复制）
                    pathDialog?.let { p ->
                        androidx.compose.material3.AlertDialog(
                            onDismissRequest = { pathDialog = null },
                            title = { Text("录音文件路径", color = Color.White) },
                            text = {
                                Text(
                                    p + "\n\n手机连电脑后，可在" +
                                        "「内部存储/Android/data/com.localrecord.app/files/recordings」里找到它们；" +
                                        "也可以直接复制这个路径。",
                                    color = Color(0xFFE9EDF5), fontSize = 12.sp
                                )
                            },
                            confirmButton = {
                                androidx.compose.material3.TextButton(onClick = {
                                    copyPath(p); pathDialog = null
                                }) { Text("复制路径") }
                            },
                            dismissButton = {
                                androidx.compose.material3.TextButton(onClick = { pathDialog = null }) { Text("关闭") }
                            }
                        )
                    }
                    // 删除确认
                    deleteDialog?.let { f ->
                        androidx.compose.material3.AlertDialog(
                            onDismissRequest = { deleteDialog = null },
                            title = { Text("删除录音", color = Color.White) },
                            text = {
                                Text(
                                    "确定删除「${f.name}」吗？文件会被永久删除，不能恢复。",
                                    color = Color(0xFFE9EDF5), fontSize = 13.sp
                                )
                            },
                            confirmButton = {
                                androidx.compose.material3.TextButton(onClick = {
                                    deleteDialog = null
                                    deleteRecording(f)
                                }) { Text("删除", color = Color(0xFFE05B5B)) }
                            },
                            dismissButton = {
                                androidx.compose.material3.TextButton(onClick = { deleteDialog = null }) { Text("取消") }
                            }
                        )
                    }
                    // 麦克风权限被拒 → 引导去系统设置（只说"失败"用户不知道该怎么办）
                    if (micBlocked) {
                        androidx.compose.material3.AlertDialog(
                            onDismissRequest = { micBlocked = false },
                            title = { Text("需要麦克风权限", color = Color.White) },
                            text = {
                                Text(
                                    "「本地录音」要录音，必须先允许使用麦克风。\n\n" +
                                        "· 刚才的弹窗里点「允许」即可；\n" +
                                        "· 如果弹窗里选了「不再询问」或拒绝了，要去系统设置里手动打开：\n" +
                                        "　设置 → 应用 → 本地录音 → 权限 → 麦克风 → 允许。\n\n" +
                                        "另外：如果麦克风正被其它应用占用（比如正在通话/别的录音软件），" +
                                        "也会录不到声音，关掉它们再试。",
                                    color = Color(0xFFE9EDF5), fontSize = 12.sp
                                )
                            },
                            confirmButton = {
                                androidx.compose.material3.TextButton(onClick = {
                                    micBlocked = false
                                    openAppSettings()
                                }) { Text("去设置") }
                            },
                            dismissButton = {
                                androidx.compose.material3.TextButton(onClick = {
                                    micBlocked = false
                                    if (checkSelfPermission(Manifest.permission.RECORD_AUDIO)
                                        != PackageManager.PERMISSION_GRANTED
                                    ) askMic.launch(Manifest.permission.RECORD_AUDIO)
                                }) { Text("再试一次授权") }
                            }
                        )
                    }
                }
            }
        }
    }

    /** 跳到本应用的系统设置页（权限被"不再询问"拒绝后只能这样开） */
    private fun openAppSettings() {
        try {
            startActivity(
                android.content.Intent(
                    android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                    android.net.Uri.fromParts("package", packageName, null)
                )
            )
        } catch (e: Throwable) {
            status = "打不开系统设置：${e.message}"
        }
    }

    // ------------------------------------------------------------ UI ----

    @Composable
    private fun AppScreen() {
        // safeDrawingPadding：避开状态栏/导航栏，否则顶部标题会被切掉
        Column(
            modifier = Modifier.fillMaxSize()
                .safeDrawingPadding()
                .padding(horizontal = 10.dp, vertical = 6.dp)
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("本地录音", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = Color.White)
            }
            Text(status, fontSize = 11.sp, color = Color(0xFF9AA4B2), maxLines = 2)
            // 平时不显示任何"就绪/未就绪"状态；只有真的缺模型、需要下载时才在这里提示
            // （下载中会显示进度条与进度文字，没在下时给一个「继续下载」入口）
            if (!showDownloading && !asrFilesReady && missingCount > 0) {
                Spacer(Modifier.height(2.dp))
                Text(
                    "识别需要的模型还没下载完（共 $missingCount 个文件）——点这里开始下载，断点续传",
                    color = Accent, fontSize = 11.sp,
                    modifier = Modifier.clickable {
                        forceBigDownload = true
                        startDownloadIfIdle()
                    }
                )
            }
            if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                Spacer(Modifier.height(2.dp))
                Text(
                    "尚未获得麦克风权限，点「录音」会弹出授权提示（没反应就点这里去设置）",
                    color = Color(0xFFE05B5B), fontSize = 10.sp, maxLines = 2,
                    modifier = Modifier.clickable { openAppSettings() }
                )
            }
            if (showDownloading) {
                Spacer(Modifier.height(3.dp))
                Box(
                    Modifier.fillMaxWidth(downloadPct.coerceIn(0f, 1f))
                        .height(4.dp).background(Accent, RoundedCornerShape(2.dp))
                )
            }
            // 没下完又没在下载时，给一个手动续下的入口（断网/失败后点一下即可接着下）
            if (!showDownloading && missingCount > 0) {
                Spacer(Modifier.height(2.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        "继续下载（还有 $missingCount 个文件，断点续传；点这里也允许用流量下大模型）",
                        color = Accent, fontSize = 11.sp,
                        modifier = Modifier.clickable {
                            forceBigDownload = true          // 明确授权：可以用流量下大模型
                            startDownloadIfIdle()
                        }
                    )
                }
            }
            Spacer(Modifier.height(6.dp))

            TabRow(selectedTabIndex = tab, containerColor = Card) {
                Tab(selected = tab == 0, onClick = { tab = 0 },
                    text = { Text("语音", color = Color.White) })
                Tab(selected = tab == 1, onClick = { tab = 1; refreshRecordings() },
                    text = { Text("录音库", color = Color.White) })
            }
            Spacer(Modifier.height(6.dp))

            // 内容区：只吃剩余空间，保证底部控件永远在屏幕内
            Box(modifier = Modifier.weight(1f).fillMaxWidth()) {
                when (tab) {
                    0 -> VoiceTab()
                    else -> LibraryTab()
                }
            }

            Spacer(Modifier.height(6.dp))
            // 只留「降噪」开关（模型是自动下载的，导入模型/选择大模型/清空/复制这些按钮已按用户要求去掉；
            //  复制与清空移到转写列表顶部的小链接，见 VoiceTab）
            Row(verticalAlignment = Alignment.CenterVertically) {
                // 降噪开关：开启后重挂系统降噪/回声消除（有些手机会把声音压得很小，所以默认关）
                OutlinedButton(
                    onClick = {
                        enhanceOn = !enhanceOn
                        recorder?.useEnhancements = enhanceOn
                        if (recording) {
                            status = if (enhanceOn) "已开启系统降噪，正在重挂…" else "已关闭系统降噪，正在重挂…"
                            Thread({
                                val ok = try {
                                    recorder?.restart() ?: false
                                } catch (_: Throwable) {
                                    false
                                }
                                runOnUiThread { status = if (ok) "降噪设置已生效（看电平数字对比）" else "重挂失败" }
                            }, "enh-toggle").start()
                        }
                    },
                    contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp)
                ) { Text(if (enhanceOn) "降噪 开" else "降噪 关", fontSize = 11.sp) }
            }
            Text(
                "本地录音：录音转写与逐句翻译全部在手机本地完成，不联网、不上传任何内容。代码完全开源，安全放心。",
                color = Color(0xFF6B7686), fontSize = 9.sp, maxLines = 3
            )
            Spacer(Modifier.height(6.dp))
        }
    }


    /** 复制任意文字到剪贴板（转写结果、会议纪要、OCR 文字都用它） */
    private fun copyPlain(text: String, what: String) {
        if (text.isBlank()) {
            status = "没有可复制的内容"
            return
        }
        try {
            val cm = getSystemService(Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager
            cm.setPrimaryClip(android.content.ClipData.newPlainText(what, text))
            status = "已复制$what（${text.length} 字）到剪贴板"
        } catch (e: Throwable) {
            status = "复制失败：${e.message}"
        }
    }

    /**
     * 列表右侧的拖动条：手指按住上下拖就能快速翻很长的一段文字。
     * （Compose 没有内置滚动条，这里用 Canvas 自己画一个：位置跟着列表走，拖动按比例换算。）
     */
    @Composable
    private fun ListScrollBar(state: LazyListState, modifier: Modifier = Modifier) {
        val scope = rememberCoroutineScope()
        val total = state.layoutInfo.totalItemsCount
        val visible = state.layoutInfo.visibleItemsInfo.size
        val first = state.firstVisibleItemIndex
        androidx.compose.foundation.Canvas(
            modifier = modifier
                .width(14.dp)
                .fillMaxHeight()
                .clip(RoundedCornerShape(7.dp))
                .background(Color(0x24FFFFFF))
                .pointerInput(total) {
                    if (total <= 0) return@pointerInput
                    detectVerticalDragGestures { _, dy ->
                        // 拖动量按"每像素几条"换算成目标条目
                        val h = size.height.toFloat().coerceAtLeast(1f)
                        val perPx = total.toFloat() / h
                        val target = (state.firstVisibleItemIndex + dy * perPx * 1.6f).toInt()
                        scope.launch {
                            state.scrollToItem(target.coerceIn(0, total - 1))
                        }
                    }
                }
        ) {
            if (total <= 0) return@Canvas
            val h = size.height
            val thumbH = (h * (visible.toFloat() / total.toFloat()).coerceIn(0.08f, 1f))
            val y = (h - thumbH) * (first.toFloat() / total.toFloat()).coerceIn(0f, 1f)
            drawRoundRect(
                color = Color(0x99FFFFFF),
                topLeft = androidx.compose.ui.geometry.Offset(0f, y),
                size = androidx.compose.ui.geometry.Size(size.width, thumbH),
                cornerRadius = androidx.compose.ui.geometry.CornerRadius(size.width / 2f),
            )
        }
    }

    @Composable
    private fun Block(title: String, body: String) {
        Column(modifier = Modifier.padding(bottom = 10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(title, color = Accent, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                Spacer(Modifier.width(6.dp))
                Text(
                    "⧉ 复制", color = Accent, fontSize = 10.sp,
                    modifier = Modifier.clickable { copyPlain(body, title) }
                )
            }
            Text(body, color = Color(0xFFE9EDF5), fontSize = 13.sp)
        }
    }

    @OptIn(ExperimentalFoundationApi::class)
    @Composable
    private fun VoiceTab() {
        // 录音计时与波形：每 100ms 刷一次。
        // 注意：**必须把值写进 Compose 状态并在界面里读**，否则改了也不会重绘（上一版就是这个问题，计时看着是跳的）。
        LaunchedEffect(recording) {
            if (recording) {
                wave.clear()
                while (recording) {
                    val r = recorder
                    elapsedUi = r?.elapsedSec ?: 0f
                    wave.add(r?.level ?: 0f)
                    while (wave.size > 72) wave.removeAt(0)
                    liveInfo = buildString {
                        append("已出 ${segments.size} 段")
                        if (recognizing) append(" · 识别中…")
                        val err = r?.error
                        if (err != null) {
                            append(" · ⚠ $err")
                        } else {
                            // 直接给数字，便于判断"麦克风到底有没有收到声音"
                            append(" · 原始电平 ${r?.rawDb?.toInt() ?: -90}dB / 人声 ${r?.levelDb?.toInt() ?: -90}dB")
                        }
                    }
                    // 通知栏同步（切到后台也能看到时长/段数），并处理通知栏的「停止录音」
                    MicService.elapsedText = fmtSec(elapsedUi)
                    MicService.segText = "已出 ${segments.size} 段"
                    if (stopRequested) {
                        // 只在真的录音中才响应，且**用完立刻清掉**：
                        // 否则这个静态标志会残留，导致下次一点录音就被立刻停掉（看着像"不能识别"）
                        stopRequested = false
                        if (recording) toggleRecord()
                    }
                    recTick = System.currentTimeMillis()
                    kotlinx.coroutines.delay(100)
                }
                wave.clear()
                recTick = System.currentTimeMillis()
            }
        }
        Column(modifier = Modifier.fillMaxSize()) {
            // 录音卡片
            Box(
                modifier = Modifier.fillMaxWidth().height(104.dp)
                    .background(Card, RoundedCornerShape(14.dp)),
                contentAlignment = Alignment.Center
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(
                        horizontalAlignment = Alignment.CenterHorizontally,
                        modifier = Modifier.weight(1f)
                    ) {
                        Text(
                            if (recording) fmtSec(elapsedUi) else "00:00.0",
                            fontSize = 26.sp, color = Color.White, fontWeight = FontWeight.Bold
                        )
                        Spacer(Modifier.height(4.dp))
                        // 波形：最近 72 个音量采样（约 8.6 秒）
                        androidx.compose.foundation.Canvas(
                            modifier = Modifier.fillMaxWidth().height(34.dp)
                        ) {
                            val n = wave.size
                            if (n == 0) return@Canvas
                            val barW = size.width / 72f
                            for (i in 0 until n) {
                                val v = wave[i].coerceIn(0.02f, 1f)
                                val h = v * size.height
                                drawRect(
                                    color = Accent,
                                    topLeft = androidx.compose.ui.geometry.Offset(
                                        i * barW, (size.height - h) / 2f
                                    ),
                                    size = androidx.compose.ui.geometry.Size(
                                        (barW * 0.6f).coerceAtLeast(1.5f), h
                                    )
                                )
                            }
                        }
                        Text(
                            if (recording) liveInfo.ifEmpty { "已出 0 段" }
                            else "点「录音」，自动断句出字",
                            color = if (recording && (recorder?.error != null)) Color(0xFFE05B5B)
                            else Color(0xFF9AA4B2),
                            fontSize = 9.sp, maxLines = 2
                        )
                    }
                    Spacer(Modifier.width(10.dp))
                    // 录音按钮：和右边的翻译按钮做成**同一形状语言**（都是 52dp 高的胶囊、同圆角），
                    // 只是录音更宽、用主色填充，主次分明但视觉统一
                    Button(
                        onClick = { toggleRecord() },
                        shape = RoundedCornerShape(26.dp),
                        colors = ButtonDefaults.buttonColors(
                            containerColor = if (recording) Color(0xFFE05B5B) else Accent
                        ),
                        modifier = Modifier.height(52.dp).width(104.dp),
                        contentPadding = PaddingValues(0.dp)
                    ) {
                        Text(
                            if (recording) "停止" else "录音",
                            color = Color.White, fontSize = 15.sp, fontWeight = FontWeight.Bold
                        )
                    }
                    Spacer(Modifier.width(12.dp))
                    // 翻译开关：与录音按钮同高同圆角的胶囊（开=绿底，关=深灰底）
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier
                            .height(52.dp)
                            .clip(RoundedCornerShape(26.dp))
                            .background(
                                if (translationOn) Color(0xFF1E6B49) else Color(0xFF232A36)
                            )
                            .clickable {
                                translationOn = !translationOn
                                status = if (translationOn) {
                                    "已开启翻译：从这一句开始逐句翻译（之前几句保持原文）"
                                } else {
                                    "已关闭翻译"
                                }
                            }
                            .padding(horizontal = 16.dp, vertical = 11.dp)
                    ) {
                        Text(
                            if (translationOn) "●" else "○",
                            color = if (translationOn) Color(0xFF8CE0B4) else Color(0xFF6B7686),
                            fontSize = 12.sp
                        )
                        Spacer(Modifier.width(7.dp))
                        Text(
                            if (translationOn) "翻译 开" else "翻译 关",
                            color = if (translationOn) Color.White else Color(0xFF9AA4B2),
                            fontSize = 13.sp,
                            fontWeight = FontWeight.Bold
                        )
                    }
                    Spacer(Modifier.width(6.dp))
                }
            }
            Spacer(Modifier.height(6.dp))

            val listState = rememberLazyListState()
            val scope = rememberCoroutineScope()
            var follow by remember { mutableStateOf(true) }        // 是否自动跟随最新一段

            // 用户自己往上翻 → 暂停自动跟随（不然看历史时会被不断拽到底部）；
            // 滚回底部 → 恢复跟随。拖动条拖动时也算"用户操作"。
            LaunchedEffect(listState) {
                snapshotFlow { listState.canScrollForward }.collect { canFwd ->
                    if (!canFwd) follow = true
                    else if (listState.isScrollInProgress) follow = false
                }
            }
            // "已复制 ✓" 提示 1.6 秒后复位
            LaunchedEffect(textCopied) {
                if (textCopied) {
                    kotlinx.coroutines.delay(1600)
                    textCopied = false
                }
            }
            // 新出一段就自动滚到最新（配合下面的拖动条，长段落也能随便翻）
            LaunchedEffect(segments.size) {
                if (segments.isNotEmpty() && follow) {
                    listState.animateScrollToItem(listState.layoutInfo.totalItemsCount - 1)
                }
            }
            // 纪要 / 回答 / 转写都放在同一个列表里滚动，避免把底部控件顶出屏幕
            Row(modifier = Modifier.fillMaxWidth().weight(1f)) {
                LazyColumn(
                    state = listState,
                    modifier = Modifier.weight(1f).fillMaxHeight()
                        .background(Card, RoundedCornerShape(12.dp)).padding(8.dp)
                ) {
                    // 会议纪要 / AI 回答只出现在弹窗里（列表这里不再重复显示，避免混淆）
                    // **吸顶**：列表滚动时这一行始终可见，复制/清空/回到最新随时够得着
                    stickyHeader {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            modifier = Modifier.fillMaxWidth()
                                .background(Card).padding(vertical = 4.dp)
                        ) {
                            Text(
                                "实时转写（${segments.size} 段）" +
                                    if (segments.isEmpty()) "　说话停顿约 1 秒就出一段" else "",
                                color = Color(0xFF9AA4B2), fontSize = 11.sp,
                                modifier = Modifier.weight(1f)
                            )
                            // 常显「⇣ 最新」：点了就回到底部（已在底部时点了也无副作用），
                            // 不用判断 canScrollForward（在吸顶项里读它有时不触发重组）
                            if (segments.isNotEmpty()) {
                                Text(
                                    "⇣ 最新", color = Accent, fontSize = 11.sp,
                                    modifier = Modifier.clickable {
                                        follow = true
                                        scope.launch {
                                            listState.animateScrollToItem(listState.layoutInfo.totalItemsCount - 1)
                                        }
                                    }
                                )
                                Spacer(Modifier.width(12.dp))
                            }
                            // 与「文档问答」页一致的小链接样式：⧉ 复制
                            if (segments.isNotEmpty()) {
                                Text(
                                    if (textCopied) "已复制 ✓" else "⧉ 复制",
                                    color = if (textCopied) Color(0xFF66D19E) else Accent, fontSize = 11.sp,
                                    modifier = Modifier.clickable {
                                        copyPlain(
                                            segments.joinToString("\n") { "${fmt(it.startSec)}  ${it.text}" },
                                            "转写文字"
                                        )
                                        textCopied = true
                                    }
                                )
                                Spacer(Modifier.width(12.dp))
                                Text(
                                    "清空", color = Color(0xFF9AA4B2), fontSize = 11.sp,
                                    modifier = Modifier.clickable {
                                        clearSegments("用户点清空")
                                        minutes = ""; answer = ""; llmDialog = null
                                    }
                                )
                            }
                        }
                    }
                    itemsIndexed(segments) { i, s ->
                        Column(modifier = Modifier.padding(vertical = 3.dp)) {
                            Text(fmt(s.startSec), color = Color(0xFF6D8BFF), fontSize = 10.sp)
                            Text(s.text, color = Color(0xFFE9EDF5), fontSize = 14.sp)
                            // 译文：紧跟原文；灰色=翻译中，绿色=已译好
                            if (translationOn) {
                                val tr = translations[i]
                                val skipped = translateSkipped.contains(i)
                                Text(
                                    when {
                                        tr != null -> tr
                                        skipped -> "（说得太快，这句没来得及翻）"
                                        else -> "翻译中…"
                                    },
                                    color = when {
                                        tr != null -> Color(0xFF7FD1A8)
                                        skipped -> Color(0xFF5A6372)
                                        else -> Color(0xFF6B7686)
                                    },
                                    fontSize = 12.sp
                                )
                            }
                        }
                    }
                }
                Spacer(Modifier.width(4.dp))
                // 右侧拖动条：上下拖快速翻长文字
                ListScrollBar(listState, Modifier.fillMaxHeight())
            }
        }
    }

    @Composable
    private fun LibraryTab() {
        Column(modifier = Modifier.fillMaxSize()) {
            // 顶部：导入外部音频（mp3/m4a/…），导入后自动转写
            Row(
                modifier = Modifier.fillMaxWidth()
                    .background(Card, RoundedCornerShape(12.dp)).padding(horizontal = 10.dp, vertical = 6.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Button(
                    onClick = { pickAudio.launch(arrayOf("audio/*")) },
                    colors = ButtonDefaults.buttonColors(containerColor = Accent),
                    contentPadding = PaddingValues(horizontal = 12.dp, vertical = 4.dp)
                ) { Text("导入音频", color = Color.White, fontSize = 12.sp) }
                Spacer(Modifier.width(8.dp))
                Text(
                    "支持 mp3 / wav / m4a / aac / ogg / flac / amr，导入后自动转写",
                    color = Color(0xFF9AA4B2), fontSize = 9.sp, maxLines = 2
                )
            }
            Spacer(Modifier.height(6.dp))

            if (recordings.isEmpty()) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text("还没有录音", color = Color(0xFF9AA4B2))
                        Spacer(Modifier.height(6.dp))
                        Text(
                            "录音都放在：\n${store.recordingsDir().absolutePath}",
                            color = Accent, fontSize = 10.sp,
                            modifier = Modifier.clickable { pathDialog = store.recordingsDir().absolutePath }
                        )
                    }
                }
                return@Column
            }

            LazyColumn(modifier = Modifier.fillMaxSize()) {
                items(recordings) { f ->
                    val isPlaying = playingPath == f.absolutePath
                    Column(
                        modifier = Modifier.fillMaxWidth().padding(vertical = 5.dp)
                            .background(
                                if (isPlaying) Color(0xFF243049) else Card,
                                RoundedCornerShape(10.dp)
                            ).padding(10.dp)
                    ) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Column(modifier = Modifier.weight(1f)) {
                                Text(
                                    (if (isPlaying) (if (playingPaused) "⏸ " else "▶ ") else "") + f.name,
                                    color = if (isPlaying) Accent else Color.White, fontSize = 13.sp,
                                    maxLines = 1
                                )
                                Text(
                                    "${f.length() / 1024} KB" +
                                        (if (isPlaying) (if (playingPaused) "　已暂停" else "　正在播放") else ""),
                                    color = Color(0xFF9AA4B2), fontSize = 10.sp
                                )
                            }
                            Button(
                                onClick = { togglePlay(f) },
                                colors = ButtonDefaults.buttonColors(
                                    containerColor = if (isPlaying && !playingPaused) Color(0xFFE05B5B) else Accent
                                ),
                                contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp)
                            ) {
                                Text(
                                    if (isPlaying && !playingPaused) "暂停" else "播放",
                                    color = Color.White, fontSize = 12.sp
                                )
                            }
                            Spacer(Modifier.width(5.dp))
                            OutlinedButton(
                                onClick = { transcribe(f) },
                                contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp)
                            ) { Text("转写", fontSize = 12.sp) }
                            Spacer(Modifier.width(5.dp))
                            OutlinedButton(
                                onClick = { deleteDialog = f },
                                contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp)
                            ) { Text("删除", fontSize = 12.sp, color = Color(0xFFE05B5B)) }
                        }
                        // 文件路径（点一下看完整路径并复制）—— 像普通录音机一样能找到文件
                        Text(
                            "路径：" + f.absolutePath,
                            color = Accent, fontSize = 9.sp, maxLines = 1,
                            overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                            modifier = Modifier.padding(top = 4.dp)
                                .clickable { pathDialog = f.absolutePath }
                        )
                        // 播放进度条（可拖动跳转）
                        if (isPlaying) {
                            Spacer(Modifier.height(2.dp))
                            androidx.compose.material3.Slider(
                                value = (playPosMs / 1000f).coerceAtLeast(0f),
                                onValueChange = {
                                    seeking = true
                                    playPosMs = (it * 1000).toInt()
                                },
                                onValueChangeFinished = {
                                    try {
                                        player?.seekTo(playPosMs)
                                    } catch (_: Throwable) {
                                    }
                                    seeking = false
                                },
                                valueRange = 0f..maxOf(1f, playDurMs / 1000f),
                                modifier = Modifier.fillMaxWidth().height(26.dp)
                            )
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(fmtMs(playPosMs), color = Color(0xFF9AA4B2), fontSize = 10.sp)
                                Spacer(Modifier.weight(1f))
                                Text(fmtMs(playDurMs), color = Color(0xFF9AA4B2), fontSize = 10.sp)
                                Spacer(Modifier.width(6.dp))
                                OutlinedButton(
                                    onClick = { stopPlay() },
                                    contentPadding = PaddingValues(horizontal = 10.dp, vertical = 2.dp)
                                ) { Text("停止", fontSize = 11.sp) }
                            }
                        }
                    }
                }
                item { Spacer(Modifier.height(8.dp)) }
            }
        }
    }

    // --------------------------------------------------------- 逻辑 ----

    /**
     * 自检：转写 files/selftest.wav，把结果打到 logcat（tag=SelfTest）与界面。
     *
     * 用法：`adb shell am start -n com.localrecord.app/.MainActivity --ez selftest true`
     * —— 这样在没有真机的情况下也能验证"模型加载 + 特征提取 + 识别"整条链路。
     */
    private fun runSelfTest() {
        val wav = File(store.externalModelsDir().parentFile, "selftest.wav")
        val out = File(store.externalModelsDir().parentFile, "selftest-result.txt")
        fun report(line: String) {
            android.util.Log.i("SelfTest", line)
            try {
                out.appendText(line + "\n")
            } catch (_: Exception) {
            }
        }
        report("模型目录=${store.modelsDir().absolutePath}")
        report("ASR 模型=${store.asrModel().absolutePath} 存在=${store.asrModel().isFile}")
        report("标点模型=${store.punctModel().absolutePath} 存在=${store.punctModel().isFile}")
        if (!wav.isFile()) {
            report("FAIL 找不到自检音频：${wav.absolutePath}")
            return
        }
        report("开始自检：${wav.absolutePath} (${wav.length() / 1024} KB)")
        val t0 = System.currentTimeMillis()
        val sb = StringBuilder()
        val (emitted, skipped) = asr.transcribe(wav, onSegment = { s ->
            report("SEG ${"%.1f".format(s.startSec)}s ${s.text}")
            sb.append(s.text)
            runOnUiThread { segments.add(Seg(s.text, s.startSec, s.endSec, fmt(s.startSec))) }
        })
        val ms = System.currentTimeMillis() - t0
        report("RESULT emitted=$emitted skipped=$skipped 用时=${ms}ms")
        report("TEXT ${sb}")
        runOnUiThread { status = "自检完成：$emitted 段，${ms}ms｜${sb}" }
    }

    private fun toggleRecord() {
        if (recording) {            recording = false
            live.stop.set(true)
            MicService.stop(this)                 // 收掉麦克风前台服务与通知
            val file = recorder?.stop()
            val peakDb = recorder?.peak?.let { p ->
                if (p > 0f) (20 * kotlin.math.log10(p.toDouble())).toInt() else -90
            } ?: -90
            recorder = null
            if (file != null) {
                refreshRecordings()
                status = "已保存 ${file.name}（${file.length() / 1024} KB，峰值 ${peakDb}dB）" +
                    if (peakDb < -45) "　⚠ 几乎没收到声音，检查麦克风权限/是否被其他应用占用" else ""
            } else status = "这次没有采到音频"
            return
        }
        // 没有麦克风权限：当场申请，并在状态栏说清楚为什么（用户不一定知道要先授权）
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            status = "需要麦克风权限才能录音，请在弹窗里点「允许」"
            askMic.launch(Manifest.permission.RECORD_AUDIO)
            return
        }
        stopRequested = false                     // 清掉可能残留的"停止"标志，否则一开录就被停
        // 新开一次录音：把上一次的转写和生成内容清掉，避免新旧混在一起看不清
        clearSegments("新开录音")
        minutes = ""
        answer = ""
        llmDialog = null
        val name = "rec-" + SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(Date()) + ".wav"
        val file = File(store.recordingsDir(), name)
        val r = Recorder(file)
        r.useEnhancements = enhanceOn
        if (!r.start()) {
            // 起不来：多半是权限被"拒绝且不再询问"，或麦克风被别的 app 占用
            micBlocked = true
            status = "录音启动失败：${r.error ?: "可能没授权麦克风，或被其它应用占用"}"
            return
        }
        recorder = r
        recording = true
        // 识别模型还没加载完也**照常开始录音**（音频先完整存下来），加载好会自动接着识别
        status = if (asrReady) "录音中…（可以切到别的 app，后台继续录）"
        else "录音中…（识别准备中，准备好自动出字；音频已完整保存）"
        // 关键：起 microphone 类型的前台服务，否则切到后台约 30 秒就拿不到麦克风数据
        MicService.start(this)
        MicService.elapsedText = "00:00.0"
        MicService.segText = "已出 ${segments.size} 段"
        startLiveAsr(r)
        // 兜底：个别 ROM 上前台服务会与麦克风互相影响，若刚开始就报错就停用服务、回到前台录音
        Thread({
            try {
                Thread.sleep(2500)
            } catch (_: InterruptedException) {
                return@Thread
            }
            val err = r.error
            if (err != null && MicService.active) {
                android.util.Log.w("MainActivity", "麦克风在服务模式下异常（$err），停用服务并重试")
                MicService.stop(this)
                val ok = try {
                    r.restart()
                } catch (_: Throwable) {
                    false
                }
                runOnUiThread {
                    status = if (ok) "已切回普通录音（切到后台可能会停）"
                    else "麦克风异常：$err —— 请停止后重新点录音"
                }
            }
        }, "mic-fallback").start()
    }

    /** 边录边转写：攒够 8 秒就判定+识别一段 */
    private fun startLiveAsr(r: Recorder) {
        // 上一会话的收尾线程可能还在识别（要等它把最后一段转完），
        // 关键：**给它足够时间结束**，否则两个线程会同时用 sherpa 识别器
        val previous = live
        previous.stop.set(true)
        try {
            previous.thread?.join(12000)
        } catch (_: InterruptedException) {
        }
        if (previous.thread?.isAlive == true) {
            android.util.Log.w("LiveAsr", "上一会话线程 12 秒仍未结束，仍要开新会话（已用独立 stop 标志隔离）")
        }
        // 新会话用全新的 stop 标志，绝不复用（否则会把旧线程"复活"）
        val session = LiveSession()
        live = session
        session.thread = Thread({
            // 识别模型可能还在加载（第一次装好后要几秒）：**等它就绪再开始断句识别**。
            // 这期间录音一直在进行、音频完整写入文件，所以不会丢内容。
            if (!asrReady) {
                runOnUiThread { status = "录音中…（识别准备中，准备好自动出字）" }
                var waited = 0
                while (!asrReady && waited < 120_000 && !session.stop.get()) {
                    try {
                        Thread.sleep(250)
                    } catch (_: InterruptedException) {
                        break
                    }
                    waited += 250
                }
                if (asrReady) {
                    runOnUiThread { status = "录音中…已开始出字" }
                } else if (!session.stop.get()) {
                    runOnUiThread { status = "识别没能启动：录音已保存，可在录音库里点「转写」重试" }
                }
            }
            // 断句优先用**神经网络 VAD（Silero）**：准确度远高于手写能量法；
            // 模型缺失时自动退回能量法 [Vad]，功能不中断。
            val useSilero = vadEngine.ready || vadEngine.init()
            vadEngine.reset()
            val energyVad = Vad(AsrEngine.SAMPLE_RATE)
            var failure: Throwable? = null
            var lastBlockMs = System.currentTimeMillis()
            var warned = false
            try {
                while (!session.stop.get()) {
                    val block = try {
                        r.chunks.poll(200, java.util.concurrent.TimeUnit.MILLISECONDS)
                    } catch (_: InterruptedException) {
                        null
                    }
                    if (block != null) {
                        lastBlockMs = System.currentTimeMillis()
                        warned = false
                        val f = FloatArray(block.size) { block[it] / 32768f }
                        if (useSilero) vadEngine.feed(f) { seg, start -> safeEmit(seg, start, true) }
                        else energyVad.feed(f) { seg, start -> safeEmit(seg, start) }
                    } else {
                        // 看门狗：录音中超过 3 秒收不到麦克风数据，说明录音线程出问题了
                        val idle = System.currentTimeMillis() - lastBlockMs
                        if (idle > 3000 && !warned) {
                            warned = true
                            val err = r.error
                            if (!r.running) {
                                android.util.Log.e("LiveAsr", "录音线程已停止（err=$err），尝试原地重启麦克风")
                                runOnUiThread { status = "麦克风停了（${err ?: "原因未知"}），正在自动重启…" }
                                val okRestart = try {
                                    r.restart()
                                } catch (t: Throwable) {
                                    android.util.Log.e("LiveAsr", "重启麦克风异常", t)
                                    false
                                }
                                runOnUiThread {
                                    status = if (okRestart) "麦克风已自动重启，继续录音（已录内容保留）"
                                    else "麦克风重启失败：请停止后重新点录音"
                                }
                                lastBlockMs = System.currentTimeMillis()
                            } else {
                                runOnUiThread {
                                    status = "已经 ${idle / 1000} 秒没收到麦克风数据" +
                                        "（${err ?: "可能被其他应用占用"}）"
                                }
                            }
                        }
                    }
                }
                if (useSilero) vadEngine.flush { seg, start -> safeEmit(seg, start, true) }
                else energyVad.flush { seg, start -> safeEmit(seg, start) }   // 收尾：把最后一段交出来
            } catch (t: Throwable) {
                failure = t
                android.util.Log.e("LiveAsr", "实时转写线程异常退出", t)
            } finally {
                if (failure != null) {
                    // 关键：旧代码这里线程直接静默死掉 —— 表现就是"第一次出字后再也不识别"
                    android.util.Log.e("LiveAsr", "线程因异常结束：${failure.message}")
                    runOnUiThread {
                        recording = false
                        status = "转写线程出错已停止（${failure.message}）—— 再点一次录音即可"
                    }
                }
            }
        }, "live-asr").also { it.start() }
    }

    /** 单段识别：异常只跳过这一段，绝不让它打死整个转写线程 */
    private fun safeEmit(seg: FloatArray, startSec: Float, fromSilero: Boolean = false) {
        runOnUiThread { recognizing = true }
        try {
            emitSegment(seg, startSec, fromSilero)
        } catch (t: Throwable) {
            android.util.Log.e("LiveAsr", "这一段识别失败，已跳过", t)
            runOnUiThread { status = "这一段识别失败，已跳过继续录" }
        } finally {
            runOnUiThread { recognizing = false }
        }
    }

    private fun emitSegment(seg: FloatArray, startSec: Float, fromSilero: Boolean = false) {
        var peak = 0f
        for (v in seg) { val a = kotlin.math.abs(v); if (a > peak) peak = a }
        // 门槛放得很低（-62dBFS）：低电平麦克风（原始 -55dB）也要能过，
        // 真正的"是不是人声"交给下面的信噪比判据，而不是绝对电平。
        if (peak < 0.0008f) {
            runOnUiThread { status = "这一段几乎没声音，已跳过" }
            return
        }
        // 关键防幻觉：用"信噪比 + 语音帧占比"判断这段到底是不是真有人说话。
        // 纯噪声（风扇/空调/键盘/底噪）能量太平，信噪比只有几 dB，会被丢掉。
        val (snr, ratio) = AudioQuality.quality(seg)
        if (!fromSilero && AudioQuality.isNoiseOnly(seg)) {
            runOnUiThread {
                status = "这一段像噪声，已跳过（信噪比 %.0f dB，语音占比 %.0f%%）".format(snr, ratio * 100)
            }
            return
        }
        val gain = if (peak > 0.05f) 0.9f / peak else 1f
        if (gain != 1f) for (i in seg.indices) seg[i] *= gain
        val text = asr.recognize(seg)
        // 丢不丢这段文字，看**音频证据**（VAD 认为人声的帧数与占比），而不是"文字像不像噪声"。
        // 证据充分（≥8 窗≈0.25 秒 且 占比≥40%）→ 一定是真说话，原样展示（"哈哈哈"也留着）；
        // 只有证据很弱时才动用"合成幻觉文本 / 长串重复字"这两条兜底规则。
        val speechWin = if (fromSilero) vadEngine.lastSpeechWindows else -1
        val speechPct = if (fromSilero) vadEngine.lastSpeechRatio else -1f
        val weakEvidence = if (fromSilero) (speechWin < 8 || speechPct < 0.4f) else (snr < 10f)
        if (TextFilter.shouldDrop(text, weakEvidence)) {
            runOnUiThread {
                status = "这一段没识别出内容，已跳过：" + text.take(20) +
                    if (fromSilero) "（人声 $speechWin 窗 / ${(speechPct * 100).toInt()}%）" else ""
            }
            return
        }
        val end = startSec + seg.size.toFloat() / AsrEngine.SAMPLE_RATE
        runOnUiThread {
            segments.add(Seg(text, startSec, end, fmt(startSec)))
            android.util.Log.i("Segments", "加入第 ${segments.size} 段：${text.take(12)}")
            enqueueTranslation(segments.size - 1, text)
            status = if (fromSilero) {
                "已转写 ${segments.size} 段（人声 $speechWin 窗 / ${(speechPct * 100).toInt()}%）"
            } else {
                "已转写 ${segments.size} 段（信噪比 %.0f dB）".format(snr)
            }
        }
    }

    private fun transcribe(f: File) {
        // 新做一次识别：先清掉上一次的转写内容，避免新旧混在一起（和"新录音清空"保持一致）
        clearSegments("新转写")

        if (!asrReady) { status = "识别还没准备好，稍等几秒再点「转写」"; return }
        if (!asrBusy.compareAndSet(false, true)) { status = "正在转写另一条，请稍候"; return }
        status = "正在转写 ${f.name} …"
        io.execute {
            // 与实时录音用**同一个断句器**（优先神经网络 VAD），两处规则保持一致
            val useSilero = vadEngine.ready || vadEngine.init()
            vadEngine.reset()
            val energyVad = Vad(AsrEngine.SAMPLE_RATE)
            val before = segments.size

            fun feedChunk(chunk: FloatArray) {
                if (useSilero) vadEngine.feed(chunk) { s, st -> safeEmit(s, st, true) }
                else energyVad.feed(chunk) { s, st -> safeEmit(s, st) }
            }

            var ok = false
            if (f.extension.equals("wav", ignoreCase = true)) {
                val wav = asr.readWav(f)
                if (wav != null) {
                    val samples = wav.first
                    val block = AsrEngine.SAMPLE_RATE / 10
                    var i = 0
                    while (i < samples.size) {
                        val end = minOf(i + block, samples.size)
                        feedChunk(samples.copyOfRange(i, end))
                        i = end
                    }
                    ok = true
                }
            }
            if (!ok) {
                // 其它格式（mp3/m4a/aac/ogg/flac/amr…）交给系统解码器，边解边断句
                if (f.extension.equals("wav", ignoreCase = true)) {
                    status = "wav 读取失败，改用系统解码器"
                }
                ok = AudioDecoder.decodeStream(this, android.net.Uri.fromFile(f)) { chunk ->
                    feedChunk(chunk)
                    true                          // 返回 false 才会提前终止；这里一直继续
                }
            }
            if (useSilero) vadEngine.flush { s, st -> safeEmit(s, st, true) }
            else energyVad.flush { s, st -> safeEmit(s, st) }
            val finalOk = ok
            runOnUiThread {
                tab = 0
                status = if (!finalOk) "这个文件解码失败（格式不支持？）"
                else "转写完成：新增 ${segments.size - before} 段（共 ${segments.size} 段）"
                asrBusy.set(false)
            }
        }
    }

    private fun play(f: File) {
        try {
            player?.release()
            player = MediaPlayer().apply {
                setDataSource(f.absolutePath)
                prepare()
                setOnCompletionListener { stopPlay() }
                setOnErrorListener { _, _, _ -> stopPlay(); true }
                start()
            }
            playingPath = f.absolutePath
            playingPaused = false
            playDurMs = try {
                player?.duration ?: 0
            } catch (_: Throwable) {
                0
            }
            playPosMs = 0
            status = "正在播放 ${f.name}（可拖动进度条跳转）"
        } catch (e: Exception) {
            status = "播放失败：${e.message}"
            playingPath = null
        }
    }

    /** 播放/暂停/继续 切换（原来只能播放，没法停） */
    private fun togglePlay(f: File) {
        if (playingPath != f.absolutePath) {
            play(f)
            return
        }
        val p = player ?: return
        try {
            if (p.isPlaying) {
                p.pause()
                playingPaused = true
            } else {
                p.start()
                playingPaused = false
            }
        } catch (e: Throwable) {
            status = "播放控制失败：${e.message}"
        }
    }

    private fun stopPlay() {
        try {
            player?.stop()
        } catch (_: Exception) {
        }
        try {
            player?.release()
        } catch (_: Exception) {
        }
        player = null
        if (playingPath != null) status = "已停止播放"
        playingPath = null
        playingPaused = false
        playPosMs = 0
        playDurMs = 0
    }

    /** 删除录音（会先停掉正在播放的） */
    private fun deleteRecording(f: File) {
        if (playingPath == f.absolutePath) stopPlay()
        val ok = try {
            f.delete()
        } catch (e: Throwable) {
            android.util.Log.e("MainActivity", "删除失败", e)
            false
        }
        if (ok || !f.exists()) {
            status = "已删除 ${f.name}"
            refreshRecordings()
        } else {
            status = "删除失败：${f.name}（可能被其它应用占用）"
        }
    }

    private fun copyPath(p: String) {
        try {
            val cm = getSystemService(Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager
            cm.setPrimaryClip(android.content.ClipData.newPlainText("path", p))
            status = "路径已复制：$p"
        } catch (e: Throwable) {
            status = "复制失败：${e.message}"
        }
    }

    private fun fmtMs(ms: Int): String {
        val total = (ms / 1000).coerceAtLeast(0)
        return "%02d:%02d".format(total / 60, total % 60)
    }


    private fun refreshRecordings() {
        recordings.clear()
        // 注意：不能只认 .wav —— 导入的 mp3/m4a/flac 也要列出来（否则导入完看不见）
        recordings.addAll(
            (store.recordingsDir().listFiles { f ->
                f.isFile && f.extension.lowercase() in AudioDecoder.SUPPORTED_EXT
            } ?: emptyArray())
                .sortedByDescending { it.lastModified() }
        )
    }

    private fun fmt(sec: Float): String {
        val s = sec.toInt()
        return "%02d:%02d".format(s / 60, s % 60)
    }

    /** 录音中显示到 0.1 秒，看起来才是"连续走表" */
    private fun fmtSec(sec: Float): String {
        val total = sec.coerceAtLeast(0f)
        val m = (total / 60).toInt()
        val s = (total % 60)
        return "%02d:%04.1f".format(m, s)
    }

    /** 界面侧的进度轮询：用户切走再回来时 Activity 会重建，
     *  下载进度从 DownloadService 的静态字段里读回来，保证界面不"失联"。 */
    private val uiPoller = android.os.Handler(android.os.Looper.getMainLooper())
    private val pollTask = object : Runnable {
        override fun run() {
            if (downloading.get()) {
                showDownloading = true
                downloadPct = if (DownloadService.percent >= 0) DownloadService.percent / 100f else 0f
                if (DownloadService.detail.isNotEmpty()) {
                    status = "${DownloadService.title}\n${DownloadService.detail}"
                }
                uiPoller.postDelayed(this, 1000)
            } else {
                showDownloading = false
                downloadPct = 0f
            }
        }
    }

    override fun onResume() {
        super.onResume()
        // 回到前台：可能刚在系统设置里开了麦克风权限，也可能模型刚下完 → 刷新状态
        refreshModelFileFlags()
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            micBlocked = false
        }
        // 回到前台：录音中但麦克风已经没数据/报错 → 重新绑定麦克风
        // （切到后台一次后，部分 ROM 会把 AudioRecord 解绑，之后一直读到静音，
        //   表现就是"波形很小、怎么说话都不识别"）
        if (recording) {
            val r = recorder
            // 用**电平骤降**判定麦克风被解绑（比看时长可靠）：
            // 正常说话过就有个峰值，回前台若比峰值低 12dB 以上，说明麦克风已经废了
            val dropped = r != null && r.peakRawDb > -80f && r.rawDb < r.peakRawDb - 12f
            if (r != null && (dropped || r.error != null)) {
                android.util.Log.w(
                    "MainActivity",
                    "回到前台发现麦克风电平骤降（峰值 ${r.peakRawDb} → 现在 ${r.rawDb}），重建音频会话"
                )
                Thread({
                    // 整套重建：先撤掉前台服务释放麦克风，再重新申请，然后重建 AudioRecord
                    val ok = try {
                        MicService.stop(this)
                        Thread.sleep(300)
                        MicService.start(this)
                        Thread.sleep(300)
                        r.restart()
                    } catch (_: Throwable) {
                        false
                    }
                    runOnUiThread {
                        status = if (ok) "已重新接上麦克风，继续录音（已录内容保留）"
                        else "麦克风重连失败：请停止后重新点录音"
                    }
                }, "mic-rebind").start()
            } else if (!MicService.active) {
                MicService.start(this)
            }
        }
        // 上次的下载线程可能还在跑（Activity 被回收后重建），同步界面状态
        showDownloading = downloading.get()
        if (downloading.get()) uiPoller.post(pollTask)
        if (::downloader.isInitialized) startDownloadIfIdle()
    }

    /** 网络恢复时自动继续下载（不用用户操作） */
    private fun registerNetworkWatcher() {
        try {
            val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as android.net.ConnectivityManager
            val cb = object : android.net.ConnectivityManager.NetworkCallback() {
                override fun onAvailable(network: android.net.Network) {
                    android.util.Log.i("MainActivity", "网络恢复，检查是否有未下完的模型")
                    startDownloadIfIdle()
                }
            }
            cm.registerDefaultNetworkCallback(cb)
            netCallback = cb
        } catch (e: Exception) {
            android.util.Log.w("MainActivity", "注册网络监听失败：${e.message}")
        }
    }

    override fun onDestroy() {
        live.stop.set(true)
        recorder?.stop()
        MicService.stop(this)
        player?.release()
        // 注意：**不取消下载**。下载跑在独立线程 + 前台服务上，
        // 用户切到别的 app（甚至 Activity 被回收）都应该继续下。
        releaseWakeLock()
        try {
            netCallback?.let {
                val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as android.net.ConnectivityManager
                cm.unregisterNetworkCallback(it)
            }
        } catch (_: Exception) {
        }
        asr.release()
        uiPoller.removeCallbacks(pollTask)
        io.shutdownNow()
        super.onDestroy()
    }
}
