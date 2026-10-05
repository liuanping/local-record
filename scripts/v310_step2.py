"""3.1.0 第二步：MainActivity 去 OCR + 加"边识别边翻译"。改动后自检括号平衡。"""
import re
from pathlib import Path

ROOT = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
m = ROOT / "android/app/src/main/java/com/localrecord/app/MainActivity.kt"
src = m.read_text(encoding="utf-8")
lines = src.split("\n")


def block_end(start):
    """从 start 行起按花括号配对找结束行（跳过字符串与行注释）"""
    depth = 0
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
                elif c == "}":
                    depth -= 1
            j += 1
        if depth <= 0 and i > start:
            return i
    raise RuntimeError(f"从第 {start+1} 行找不到块结尾")


def cut_function(sig_pat, label):
    """删除匹配 sig_pat 的函数（含前面的 @Composable / 注释行）"""
    global lines
    i = next((k for k, l in enumerate(lines) if re.search(sig_pat, l)), -1)
    if i < 0:
        print(f"  [跳过] {label}：没找到")
        return
    s = i
    while s > 0 and (lines[s - 1].strip().startswith("@") or lines[s - 1].strip().startswith("//")
                     or lines[s - 1].strip().startswith("*") or lines[s - 1].strip().startswith("/**")):
        s -= 1
    e = block_end(i)
    print(f"  删除 {label}：第 {s+1}~{e+1} 行")
    del lines[s:e + 1]


# ---------- 1) 删除 OCR 相关函数 ----------
cut_function(r"private fun OcrTab\(\)", "OcrTab 页面")
cut_function(r"private fun runOcrSelfTest\(\)", "OCR 自检")
cut_function(r"private val pickImage = registerForActivityResult", "选图（OCR）")
cut_function(r"private fun decodeBitmap\(", "decodeBitmap")
cut_function(r"private fun refreshModelFileFlags", "refreshModelFileFlags（含 OCR 标志，稍后重写）")

src = "\n".join(lines)

# ---------- 2) 删掉 ocr 引擎字段与初始化 / ocrtest ----------
src = src.replace("    private lateinit var ocr: OcrEngine\n", "")
src = re.sub(r"\n *ocr = OcrEngine\(store\)", "", src)
src = re.sub(r"\n *val ocrTest = intent\?\.getBooleanExtra\(\"ocrtest\", false\) == true", "", src)
src = re.sub(r"\n *if \(ocrTest\) runOcrSelfTest\(\)", "", src)
src = src.replace('        ocrFilesReady = store.ocrReady()\n', '')

# ---------- 3) 标签页：去掉"文档问答" ----------
src = src.replace("""                Tab(selected = tab == 2, onClick = { tab = 2 },
                    text = { Text("文档问答", color = Color.White) })
""", "")
src = src.replace("""                    0 -> VoiceTab()
                    1 -> LibraryTab()
                    else -> OcrTab()""", """                    0 -> VoiceTab()
                    else -> LibraryTab()""")

# ---------- 4) 清空链接不再引用 ocrText（该字段已随 OCR 移除） ----------
src = src.replace('minutes = ""; answer = ""; ocrText = ""; llmDialog = null',
                  'minutes = ""; answer = ""; llmDialog = null')

# ---------- 5) 底部：降噪 + 翻译开关，介绍文字挪到下一行 ----------
old_row = """            Row(verticalAlignment = Alignment.CenterVertically) {
                // 降噪开关：开启后重挂系统降噪/回声消除（有些手机会把声音压得很小，所以默认关）
                OutlinedButton("""
assert old_row in src, "底部行锚点没找到"
new_row = """            Row(verticalAlignment = Alignment.CenterVertically) {
                // 降噪开关：开启后重挂系统降噪/回声消除（有些手机会把声音压得很小，所以默认关）
                OutlinedButton("""
src = src.replace(old_row, new_row, 1)

old_tail = """                ) { Text(if (enhanceOn) "降噪 开" else "降噪 关", fontSize = 11.sp) }
                Spacer(Modifier.width(10.dp))
                Text(
                    "本地录音：录音转写与图片识别全部在手机本地完成，不联网、不上传任何内容。" +
                        "代码完全开源，安全放心。",
                    color = Color(0xFF6B7686), fontSize = 9.sp, maxLines = 3
                )
            }"""
assert old_tail in src, "底部行收尾锚点没找到"
new_tail = """                ) { Text(if (enhanceOn) "降噪 开" else "降噪 关", fontSize = 11.sp) }
                Spacer(Modifier.width(12.dp))
                // 逐句翻译开关：打开后每识别出一句就立刻翻译，原文与译文并排显示
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
            )"""
src = src.replace(old_tail, new_tail, 1)

# ---------- 6) 列表项：原文 + 译文 ----------
old_item = """                    items(segments) { s ->
                        Column(modifier = Modifier.padding(vertical = 3.dp)) {
                            Text(fmt(s.startSec), color = Color(0xFF6D8BFF), fontSize = 10.sp)
                            Text(s.text, color = Color(0xFFE9EDF5), fontSize = 14.sp)
                        }
                    }"""
assert old_item in src, "列表项锚点没找到"
new_item = """                    itemsIndexed(segments) { i, s ->
                        Column(modifier = Modifier.padding(vertical = 3.dp)) {
                            Text(fmt(s.startSec), color = Color(0xFF6D8BFF), fontSize = 10.sp)
                            Text(s.text, color = Color(0xFFE9EDF5), fontSize = 14.sp)
                            // 译文：紧跟原文，灰色=翻译中，绿色=已译好
                            if (translationOn) {
                                val tr = translations[i]
                                Text(
                                    if (tr == null) "翻译中…" else tr,
                                    color = if (tr == null) Color(0xFF6B7686) else Color(0xFF7FD1A8),
                                    fontSize = 12.sp
                                )
                            }
                        }
                    }"""
src = src.replace(old_item, new_item, 1)

# ---------- 7) 新增翻译状态与队列 ----------
anchor = "    private val segments = mutableStateListOf<Seg>()"
assert anchor in src
addition = anchor + """

    // ---------------- 逐句翻译（边识别边翻译）----------------
    private var translationOn by mutableStateOf(true)                 // 开关：默认打开
    /** 段序号 → 译文（用 Compose 的 stateMap，写进去界面会自动刷新） */
    private val translations = androidx.compose.runtime.mutableStateMapOf<Int, String>()
    private val translateQueue = java.util.concurrent.LinkedBlockingQueue<Pair<Int, String>>()
    private val translateRunning = AtomicBoolean(false)

    /** 把一句转写排进翻译队列：串行执行，避免几个请求同时抢大模型 */
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
                if (translateQueue.isNotEmpty()) startTranslateWorker()   // 期间又来了新的
            }
        }
    }

    /** 静默加载大模型：不覆盖转写状态栏文案（首次要读 400MB，几秒钟） */
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
    }"""
src = src.replace(anchor, addition, 1)

# ---------- 8) clearSegments 时连译文一起清 ----------
src = src.replace("""        android.util.Log.i("Segments", "清空转写（$why），之前 ${segments.size} 段", Throwable("clearSegments"))
        segments.clear()""",
"""        android.util.Log.i("Segments", "清空转写（$why），之前 ${segments.size} 段", Throwable("clearSegments"))
        segments.clear()
        translations.clear()
        translateQueue.clear()""", 1)

# ---------- 9) 每出一段就排队翻译 ----------
src = src.replace("""            segments.add(Seg(text, startSec, end, fmt(startSec)))
            android.util.Log.i("Segments", "加入第 ${segments.size} 段：${text.take(12)}")""",
"""            segments.add(Seg(text, startSec, end, fmt(startSec)))
            android.util.Log.i("Segments", "加入第 ${segments.size} 段：${text.take(12)}")
            enqueueTranslation(segments.size - 1, text)""", 1)

# ---------- 10) import itemsIndexed ----------
if "import androidx.compose.foundation.lazy.itemsIndexed" not in src:
    src = src.replace("import androidx.compose.foundation.lazy.LazyColumn",
                      "import androidx.compose.foundation.lazy.LazyColumn\nimport androidx.compose.foundation.lazy.itemsIndexed", 1)

# ---------- 11) 补回 refreshModelFileFlags（去掉 OCR 标志）----------
if "private fun refreshModelFileFlags" not in src:
    src = src.replace("    private fun ensureLlm(): Boolean {",
"""    /** 记录必要模型是否已就位（只用于顶部"还没下载完"的提示） */
    private fun refreshModelFileFlags() {
        asrFilesReady = store.asrReady()
    }

    private fun ensureLlm(): Boolean {""", 1)

m.write_text(src, encoding="utf-8")

# ---------- 自检 ----------
depth = 0
in_str = False
for ch in src:
    if ch == '"':
        in_str = not in_str
    if not in_str:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
print(f"\n括号平衡 = {depth}（应为 0）")
for kw in ["OcrTab", "OcrEngine", "pickImage", "decodeBitmap", "runOcrSelfTest", "ocrTest"]:
    n = src.count(kw)
    print(f"  残留 {kw}: {n}" + ("  ✗ 需处理" if n else "  ✓"))
for kw in ["translationOn", "enqueueTranslation", "itemsIndexed", "llm.translate"]:
    print(f"  新增 {kw}: {src.count(kw)} 处")
assert depth == 0, "括号不平衡，已放弃"
print("MainActivity 改造完成 ✓")
