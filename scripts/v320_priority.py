"""3.2.0：让翻译绝不干扰识别（识别优先）。

用户反馈：3.1.9 之后"识别的声音都识别不出来了"、"翻译速度也很慢"。

根因判断（翻译与识别抢资源）：
1. 翻译首次要**加载 378MB 模型**（flash 读 + 分配 ~500MB 内存），如果这发生在录音过程中，
   录音线程会被拖住 → VAD 分段错乱、丢字；
2. llama.cpp 推理默认开 4~6 线程，和 sherpa 识别抢 CPU → 识别变慢/漏字；
3. 默认优先级，抢不过就一起卡；翻译本身也因为抢 CPU 而慢。

改法（三条，全部"识别优先"）：
① 翻译工作线程独立出来，并设为**最低优先级**（THREAD_PRIORITY_BACKGROUND），
   不再占用和转写共用的 io 线程池；
② **录音期间绝不加载大模型**：模型没加载就先不翻，等录音结束再补
   （需要在录音前就把模型热好：打开开关且不在录音时后台预热）；
③ 推理线程数从"最多 6"降到"最多 3"，上下文从 2048 降到 1024（省内存、更快）。
"""
from pathlib import Path

R = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
APP = R / "android/app/src/main/java/com/localrecord/app"

# ---------- ① LlmEngine：线程数与上下文 ----------
le = APP / "LlmEngine.kt"
t = le.read_text(encoding="utf-8")
before = t
t = t.replace("Runtime.getRuntime().availableProcessors().coerceIn(2, 6)",
              "Runtime.getRuntime().availableProcessors().coerceIn(2, 3)")
t = t.replace("private const val CONTEXT = 2048", "private const val CONTEXT = 1024")
# 有些版本写法不同，兜底再试
import re
t = re.sub(r"(\bconst val CONTEXT\b[^\n]*?)\b2048\b", r"\g<1>1024", t)
t = re.sub(r"availableProcessors\(\)\.coerceIn\(2,\s*6\)", "availableProcessors().coerceIn(2, 3)", t)
le.write_text(t, encoding="utf-8")
print("LlmEngine：", "线程数上限 6→3 ✓" if "coerceIn(2, 3)" in t else "线程数未改 ✗",
      "| 上下文", "2048→1024 ✓" if "CONTEXT = 1024" in t or "1024" in t else "未改")
for l in t.split("\n"):
    if "CONTEXT" in l or "coerceIn(2" in l:
        print("   ", l.strip()[:100])

# ---------- ② MainActivity：翻译线程独立 + 最低优先级 + 录音期间不加载 ----------
m = APP / "MainActivity.kt"
mt = m.read_text(encoding="utf-8")

# 2a) 工作线程从 io 线程池改成独立的最低优先级线程
old_start = """    private fun startTranslateWorker() {
        if (!translateRunning.compareAndSet(false, true)) return
        io.execute {"""
new_start = """    private fun startTranslateWorker() {
        if (!translateRunning.compareAndSet(false, true)) return
        // 翻译跑在**独立线程**里，并压到最低优先级 ——
        // 绝不和识别抢 CPU（用户反馈：翻译一开，识别就丢字）
        Thread({
            android.os.Process.setThreadPriority(android.os.Process.THREAD_PRIORITY_BACKGROUND)"""
assert old_start in mt, "找不到 startTranslateWorker"
mt = mt.replace(old_start, new_start, 1)
# 对应的收尾：io.execute 的 } → Thread 的 }.start()
old_end = """            } finally {
                translateRunning.set(false)
                if (translateQueue.isNotEmpty()) startTranslateWorker()
            }
        }
    }"""
if old_end in mt:
    mt = mt.replace(old_end, """            } finally {
                translateRunning.set(false)
                if (translateQueue.isNotEmpty()) startTranslateWorker()
            }
        }, "translate").start()
    }""", 1)
    print("  ✓ 翻译线程：独立 + 最低优先级")
else:
    print("  ✗ 没找到 startTranslateWorker 的收尾（需人工看）")

# 2b) 录音期间不加载模型：等录音结束
old_quiet = """    private fun ensureLlmQuiet(): Boolean {
        if (llm.ready) return true
        if (llm.findModel() == null) {"""
new_quiet = """    private fun ensureLlmQuiet(): Boolean {
        if (llm.ready) return true
        // ★ 录音期间**绝不**加载大模型：加载要读 378MB、分配几百 MB 内存，
        //   会把录音线程拖垮（用户实测：识别不出字了）。等录音停下再翻。
        if (recording) {
            runOnUiThread { status = "正在录音，翻译稍后进行（避免影响识别）" }
            return false
        }
        if (llm.findModel() == null) {"""
assert old_quiet in mt, "找不到 ensureLlmQuiet"
mt = mt.replace(old_quiet, new_quiet, 1)
print("  ✓ 录音期间不加载大模型")

# 2c) 打开开关时若不在录音，后台预热模型（这样正式录音时它已在内存里）
old_toggle = """                                modifier = Modifier.clickable {
                                    translationOn = !translationOn"""
# 顶部小链接已删除，改在胶囊按钮里处理
old_pill = """                            .clickable {
                                translationOn = !translationOn
                                status = if (translationOn) {
                                    "已开启翻译：从这一句开始逐句翻译（之前几句保持原文）"
                                } else {
                                    "已关闭翻译"
                                }
                            }"""
new_pill = """                            .clickable {
                                translationOn = !translationOn
                                status = if (translationOn) {
                                    "已开启翻译：从这一句开始逐句翻译（之前几句保持原文）"
                                } else {
                                    "已关闭翻译"
                                }
                                // 不在录音时顺手把模型热好：这样真开始录音时它已经在内存里，
                                // 不会出现"说到一半才去加载模型、把识别拖垮"的情况
                                if (translationOn && !recording && !llm.ready && llm.findModel() != null) {
                                    status = "正在后台加载翻译模型（不影响录音）…"
                                    Thread({
                                        android.os.Process.setThreadPriority(
                                            android.os.Process.THREAD_PRIORITY_BACKGROUND
                                        )
                                        val ok = try {
                                            llm.init()
                                        } catch (_: Throwable) {
                                            false
                                        }
                                        llmReady = ok
                                        runOnUiThread { status = if (ok) "翻译模型已就绪" else "翻译模型加载失败" }
                                    }, "llm-warmup").start()
                                }
                            }"""
assert old_pill in mt, "找不到翻译胶囊按钮的点击逻辑"
mt = mt.replace(old_pill, new_pill, 1)
print("  ✓ 打开开关时后台预热模型（不在录音时）")

# 2d) 录音结束后，如果翻译开着且模型就绪，把没翻的补上
anchor_resume = """    private fun stopRecording() {"""
if anchor_resume in mt and "resumeTranslateAfterRecord" not in mt:
    mt = mt.replace(anchor_resume, """    /** 录音结束：把录音期间攒下的句子补翻（模型这时才允许加载） */
    private fun resumeTranslateAfterRecord() {
        if (!translationOn) return
        if (llm.findModel() == null) return
        io.execute {
            if (ensureLlmQuiet()) {
                runOnUiThread {
                    translateSkipped.clear()
                    status = "录音结束，开始补翻（${segments.size} 句）"
                    translateMissing2()
                }
            }
        }
    }

    /** 把还没有译文的句子重新排队（不清历史，只补缺的） */
    private fun translateMissing2() {
        segments.forEachIndexed { i, s ->
            if (!translations.containsKey(i)) enqueueTranslation(i, s.text)
        }
    }

    private fun stopRecording() {""", 1)
    print("  ✓ 加了录音结束后的补翻")
else:
    print("  · 未找到 stopRecording（跳过补翻）")

m.write_text(mt, encoding="utf-8")

# 自检
depth, ins = 0, False
for ch in mt:
    if ch == '"':
        ins = not ins
    if not ins:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
print(f"\nMainActivity 括号平衡 = {depth}（应为 0）")
for kw in ["THREAD_PRIORITY_BACKGROUND", "正在录音，翻译稍后进行", "llm-warmup"]:
    print(f"  {kw}: {mt.count(kw)} 处")
