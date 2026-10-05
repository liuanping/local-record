"""3.1.0 第二步（重做）：MainActivity 去 OCR + 加逐句翻译。

关键修复：块匹配器必须"见过至少一个 { 且 depth 回到 0"才算结尾，
否则像 registerForActivityResult( 换行写法会在第 2 行就误判结束。
"""
import re
from pathlib import Path

R = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
m = R / "android/app/src/main/java/com/localrecord/app/MainActivity.kt"
src = m.read_text(encoding="utf-8")
lines = src.split("\n")


def block_end(start):
    depth, seen = 0, False
    for i in range(start, len(lines)):
        s, j, in_str = lines[i], 0, False
        while j < len(s):
            c = s[j]
            if not in_str and c == "/" and j + 1 < len(s) and s[j + 1] == "/":
                break
            if c == '"' and (j == 0 or s[j - 1] != "\\"):
                in_str = not in_str
            if not in_str:
                if c == "{":
                    depth += 1
                    seen = True
                elif c == "}":
                    depth -= 1
            j += 1
        if seen and depth == 0:
            return i
    raise RuntimeError(f"第 {start+1} 行起找不到块尾")


def cut(sig_pat, label):
    global lines
    i = next((k for k, l in enumerate(lines) if re.search(sig_pat, l)), -1)
    if i < 0:
        print(f"  [跳过] {label}")
        return
    s = i
    while s > 0 and (lines[s - 1].strip().startswith("@") or lines[s - 1].strip().startswith("//")
                     or lines[s - 1].strip().startswith("*") or lines[s - 1].strip().startswith("/**")):
        s -= 1
    e = block_end(i)
    print(f"  删除 {label}：第 {s+1}~{e+1} 行（共 {e-s+1} 行）")
    del lines[s:e + 1]


print("--- 删除 OCR 相关 ---")
cut(r"private fun OcrTab\(\)", "OcrTab 页面")
cut(r"private fun runOcrSelfTest\(\)", "OCR 自检")
cut(r"private val pickImage = registerForActivityResult", "选图（OCR）")
cut(r"private fun decodeBitmap\(", "decodeBitmap")
cut(r"private fun refreshModelFileFlags", "refreshModelFileFlags（后面重写）")
src = "\n".join(lines)
src = src.replace("    // ------------------------------------------------------- OCR 文档问答 ----\n\n\n", "")

print("--- 去掉字段/初始化/意图 ---")
for pat in [r"\n *private lateinit var ocr: OcrEngine",
            r"\n *ocr = OcrEngine\(store\)",
            r"\n *val ocrTest = intent\?\.getBooleanExtra\(\"ocrtest\", false\) == true",
            r"\n *if \(ocrTest\) runOcrSelfTest\(\)",
            r"\n *private var ocrReady by mutableStateOf\(false\)",
            r"\n *private var ocrText by mutableStateOf\(\"\"\)",
            r"\n *private var ocrFilesReady by mutableStateOf\(false\).*",
            r"\n *private var ocrCopied by mutableStateOf\(false\).*"]:
    src, n = re.subn(pat, "", src)
    print(f"  清理 {pat[:44]}… → {n} 处")

print("--- 下载器按制品初始化：去掉 ocr 分支 ---")
src = src.replace('''                                "ocr-det", "ocr-rec" -> {
                                    refreshModelFileFlags()
                                    if (!ocr.ready) {
                                        val o = ocr.init()
                                        runOnUiThread { ocrReady = o }
                                    }
                                }
''', "", 1)

print("--- 标签页去 OCR ---")
src = src.replace("""                Tab(selected = tab == 2, onClick = { tab = 2 },
                    text = { Text("文档问答", color = Color.White) })
""", "", 1)
src = src.replace("""                    0 -> VoiceTab()
                    1 -> LibraryTab()
                    else -> OcrTab()""", """                    0 -> VoiceTab()
                    else -> LibraryTab()""", 1)
src = src.replace('minutes = ""; answer = ""; ocrText = ""; llmDialog = null',
                  'minutes = ""; answer = ""; llmDialog = null')

print("--- 底部：翻译开关 ---")
old_tail = """                ) { Text(if (enhanceOn) "降噪 开" else "降噪 关", fontSize = 11.sp) }
                Spacer(Modifier.width(10.dp))
                Text(
                    "本地录音：录音转写与图片识别全部在手机本地完成，不联网、不上传任何内容。" +
                        "代码完全开源，安全放心。",
                    color = Color(0xFF6B7686), fontSize = 9.sp, maxLines = 3
                )
            }"""
assert old_tail in src, "底部行锚点变了"
src = src.replace(old_tail, """                ) { Text(if (enhanceOn) "降噪 开" else "降噪 关", fontSize = 11.sp) }
                Spacer(Modifier.width(12.dp))
                // 逐句翻译开关：打开后每识别出一句立刻翻译，原文与译文并排显示
                Text(
                    "边识别边翻译",
                    color = if (translationOn) Accent else Color(0xFF6B7686),
                    fontSize = 11.sp
                )
                androidx.compose.material3.Switch(
                    checked = translationOn,
                    onCheckedChange = { on ->
                        translationOn = on
                        if (on) {
                            translateMissing()
                            if (segments.isNotEmpty()) status = "正在翻译已有 ${segments.size} 句…"
                        } else {
                            status = "已关闭翻译"
                        }
                    }
                )
            }
            Text(
                "本地录音：录音转写与逐句翻译全部在手机本地完成，不联网、不上传任何内容。代码完全开源，安全放心。",
                color = Color(0xFF6B7686), fontSize = 9.sp, maxLines = 3
            )""", 1)

print("--- 列表项：原文 + 译文 ---")
old_item = """                    items(segments) { s ->
                        Column(modifier = Modifier.padding(vertical = 3.dp)) {
                            Text(fmt(s.startSec), color = Color(0xFF6D8BFF), fontSize = 10.sp)
                            Text(s.text, color = Color(0xFFE9EDF5), fontSize = 14.sp)
                        }
                    }"""
assert old_item in src, "列表项锚点变了"
src = src.replace(old_item, """                    itemsIndexed(segments) { i, s ->
                        Column(modifier = Modifier.padding(vertical = 3.dp)) {
                            Text(fmt(s.startSec), color = Color(0xFF6D8BFF), fontSize = 10.sp)
                            Text(s.text, color = Color(0xFFE9EDF5), fontSize = 14.sp)
                            // 译文：紧跟原文；灰色=翻译中，绿色=已译好
                            if (translationOn) {
                                val tr = translations[i]
                                Text(
                                    if (tr == null) "翻译中…" else tr,
                                    color = if (tr == null) Color(0xFF6B7686) else Color(0xFF7FD1A8),
                                    fontSize = 12.sp
                                )
                            }
                        }
                    }""", 1)

print("--- 新增翻译状态与队列 ---")
anchor = "    private val segments = mutableStateListOf<Seg>()"
assert anchor in src
src = src.replace(anchor, anchor + """

    // ---------------- 逐句翻译（边识别边翻译）----------------
    private var translationOn by mutableStateOf(true)                 // 开关：默认打开
    /** 段序号 → 译文（Compose 的 stateMap，写进去界面自动刷新） */
    private val translations = androidx.compose.runtime.mutableStateMapOf<Int, String>()
    private val translateQueue = java.util.concurrent.LinkedBlockingQueue<Pair<Int, String>>()
    private val translateRunning = AtomicBoolean(false)

    /** 把一句转写排进翻译队列：串行执行，避免多个请求同时抢大模型 */
    private fun enqueueTranslation(idx: Int, text: String) {
        if (!translationOn || text.isBlank() || translations.containsKey(idx)) return
        translateQueue.offer(idx to text)
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

    /** 开关重新打开时，把还没翻译的句子补上 */
    private fun translateMissing() {
        segments.forEachIndexed { i, s -> if (!translations.containsKey(i)) enqueueTranslation(i, s.text) }
    }""", 1)

print("--- clearSegments 连译文一起清 ---")
src = src.replace("""        segments.clear()""", """        segments.clear()
        translations.clear()
        translateQueue.clear()""", 1)

print("--- 每出一段就排队翻译 ---")
src = src.replace("""            android.util.Log.i("Segments", "加入第 ${segments.size} 段：${text.take(12)}")""",
"""            android.util.Log.i("Segments", "加入第 ${segments.size} 段：${text.take(12)}")
            enqueueTranslation(segments.size - 1, text)""", 1)

print("--- import + refreshModelFileFlags 重写 ---")
if "import androidx.compose.foundation.lazy.itemsIndexed" not in src:
    src = src.replace("import androidx.compose.foundation.lazy.LazyColumn",
                      "import androidx.compose.foundation.lazy.LazyColumn\nimport androidx.compose.foundation.lazy.itemsIndexed", 1)
if "private fun refreshModelFileFlags" not in src:
    src = src.replace("    private fun ensureLlm(): Boolean {",
"""    /** 必要模型是否已就位（只用于顶部"还没下载完"的提示） */
    private fun refreshModelFileFlags() {
        asrFilesReady = store.asrReady()
    }

    private fun ensureLlm(): Boolean {""", 1)

m.write_text(src, encoding="utf-8")

depth, in_str = 0, False
for ch in src:
    if ch == '"':
        in_str = not in_str
    if not in_str:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
print(f"\n括号平衡 = {depth}（应为 0）")
for kw in ["OcrEngine", "decodeBitmap", "pickImage", "ocrReady", "ocrText", "OcrTab", "runOcrSelfTest"]:
    c = src.count(kw)
    print(f"  残留 {kw}: {c}" + ("  ✗" if c else "  ✓"))
for kw in ["translationOn", "enqueueTranslation", "itemsIndexed", "llm.translate", "translateMissing"]:
    print(f"  新增 {kw}: {src.count(kw)} 处")
assert depth == 0
print("完成 ✓")
