"""2.5.1：把"预填充耗时/token 数"测出来并显示 + 多线程 + 问答单独缩短 prompt。

用户实测：7 个字用了 17.9 秒 → 0.6 token/秒，明显不是生成慢，而是预填充（prompt 太长）/
加载在吃时间。这次把三段耗时全部量出来，并做三处优化。
"""
from pathlib import Path

ROOT = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
cpp = ROOT / "android/app/src/main/cpp/llm_jni.cpp"
t = cpp.read_text(encoding="utf-8")

# ---- 1) handle 里记录分段耗时 ----
t = t.replace("""    int n_ctx = 2048;
    int n_threads = 4;
};""", """    int n_ctx = 2048;
    int n_threads = 4;
    // 上一次生成的分段耗时（给界面显示用，判断"慢"到底慢在哪一段）
    long long last_prefill_ms = 0;
    long long last_gen_ms = 0;
    int last_prompt_tokens = 0;
    int last_gen_tokens = 0;
};""")

# ---- 2) 预填充计时 ----
t = t.replace("""    // ---- 预填充 ----
    const int kBatch = 256;""", """    // ---- 预填充（prompt 越长这一段越慢；手机上往往是它吃掉大部分时间）----
    const long long t_prefill = now_ms();
    const int kBatch = 512;""")
t = t.replace("""    std::string out;
    int generated = 0;""", """    h->last_prefill_ms = now_ms() - t_prefill;
    h->last_prompt_tokens = n - start;
    LOGI("预填充：%d token / %.1f 秒（%.1f token每秒，%d 线程）",
         h->last_prompt_tokens, h->last_prefill_ms / 1000.0,
         h->last_prefill_ms > 10 ? h->last_prompt_tokens * 1000.0 / h->last_prefill_ms : 0.0,
         h->n_threads);

    std::string out;
    int generated = 0;""")

# ---- 3) 生成计时写回 handle ----
t = t.replace("""    const double sec = (double) (now_ms() - t_gen) / 1000.0;
    LOGI("生成完成：%d token / %.1f 秒 / %.1f token每秒（字符 %zu）",
         generated, sec, sec > 0.01 ? generated / sec : 0.0, out.size());""",
"""    h->last_gen_ms = now_ms() - t_gen;
    h->last_gen_tokens = generated;
    const double sec = h->last_gen_ms / 1000.0;
    LOGI("生成完成：%d token / %.1f 秒 / %.1f token每秒（字符 %zu）",
         generated, sec, sec > 0.01 ? generated / sec : 0.0, out.size());""")

# ---- 4) 新增：返回上一次耗时摘要，供界面显示 ----
t = t.replace('extern "C" JNIEXPORT jstring JNICALL\nJava_com_localrecord_app_LlmEngine_nativeGenerate(',
"""extern "C" JNIEXPORT jstring JNICALL
Java_com_localrecord_app_LlmEngine_nativeLastStats(JNIEnv *env, jobject /*thiz*/, jlong jhandle) {
    auto *h = reinterpret_cast<LlmHandle *>(jhandle);
    if (h == nullptr) return env->NewStringUTF("");
    char buf[160];
    snprintf(buf, sizeof(buf), "理解 %.1fs（%d token）/ 生成 %.1fs（%d token）",
             h->last_prefill_ms / 1000.0, h->last_prompt_tokens,
             h->last_gen_ms / 1000.0, h->last_gen_tokens);
    return env->NewStringUTF(buf);
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_localrecord_app_LlmEngine_nativeGenerate(""")

cpp.write_text(t, encoding="utf-8")
print("JNI：已加入预填充计时与 nativeLastStats ✓")

# ---- 5) Kotlin：线程数按 CPU 核数 + 暴露 lastStats ----
kt = ROOT / "android/app/src/main/java/com/localrecord/app/LlmEngine.kt"
k = kt.read_text(encoding="utf-8")
k = k.replace("fun init(threads: Int = 4): Boolean {",
              "fun init(threads: Int = defaultThreads()): Boolean {")
k = k.replace("    fun release() {",
"""    /** 线程数：按 CPU 核数来（预填充最吃多核），最多 6 个，留点核给界面 */
    private fun defaultThreads(): Int =
        Runtime.getRuntime().availableProcessors().coerceIn(2, 6)

    /** 上一次生成的分段耗时（"理解 x.xs / 生成 y.ys"），用于界面显示 */
    val lastStats: String
        get() = try {
            if (handle != 0L) nativeLastStats(handle) else ""
        } catch (_: Throwable) {
            ""
        }

    fun release() {""")
k = k.replace("    private external fun nativeInit(modelPath: String, nCtx: Int, nThreads: Int): Long",
"""    private external fun nativeInit(modelPath: String, nCtx: Int, nThreads: Int): Long

    private external fun nativeLastStats(handle: Long): String""")

# ---- 6) 问答用更小的 prompt 预算（问答不需要整篇转写）----
k = k.replace("""    fun ask(transcript: String, question: String, maxTokens: Int = 300): String =
        generate(MINUTES_SYSTEM, askPrompt(fit(transcript), question), maxTokens)""",
"""    fun ask(transcript: String, question: String, maxTokens: Int = 300): String =
        // 问答只要相关片段就够，prompt 越短预填充越快（手机上这一段最费时间）
        generate(MINUTES_SYSTEM, askPrompt(fit(transcript, maxChars = 1200), question), maxTokens)""")
kt.write_text(k, encoding="utf-8")
print("LlmEngine：线程数按核数、lastStats、问答 prompt 预算 2600→1200 ✓")

# ---- 7) 状态栏显示分段耗时 ----
m = ROOT / "android/app/src/main/java/com/localrecord/app/MainActivity.kt"
mt = m.read_text(encoding="utf-8")
mt = mt.replace('status = "回答完成（${out.length} 字，用时 %.1fs）".format(sec)',
                'status = "回答完成（${out.length} 字，用时 %.1fs · ${llm.lastStats}）".format(sec)')
mt = mt.replace('status = "会议纪要完成（${out.length} 字，${(System.currentTimeMillis() - t0) / 1000}s）"',
                'status = "会议纪要完成（${out.length} 字，用时 ${(System.currentTimeMillis() - t0) / 1000}s · ${llm.lastStats}）"')
m.write_text(mt, encoding="utf-8")
print("MainActivity：状态栏显示「理解 x.xs / 生成 y.ys」✓")

# ---- 8) 版本号 + 文档 ----
g = ROOT / "android/app/build.gradle.kts"
gt = g.read_text(encoding="utf-8")
gt = gt.replace("versionCode = 250", "versionCode = 251").replace('versionName = "2.5.0"', 'versionName = "2.5.1"')
g.write_text(gt, encoding="utf-8")

readme = ROOT / "android/README-android.md"
r = readme.read_text(encoding="utf-8")
if "**2.5.1**" not in r:
    anchor = "* **2.5.0**："
    entry = """* **2.5.1**：**定位"7 个字要 17.9 秒"**（用户实测）—— 0.6 token/秒显然不是生成慢，做了三件事：
  * **把耗时拆开量**：JNI 现在分别记录并打印「预填充 N token / X.X 秒」与「生成 N token / X.X 秒」，
    界面上也显示「回答完成（7 字，用时 17.9s · 理解 12.0s（820 token）/ 生成 5.9s（12 token））」
    —— 一眼看出慢在"读 prompt"还是"写字"。
  * **线程数**从写死的 4 改为按 CPU 核数（2~6 个），预填充最吃多核。
  * **问答的 prompt 预算 2600 → 1200 字**：问答不需要整篇转写，prompt 越短预填充越快。
    会议纪要仍用 2600（需要完整转写）。

"""
    readme.write_text(r.replace(anchor, entry + anchor, 1), encoding="utf-8")
    print("README 已加 2.5.1")

snap = ROOT / "SNAPSHOT-INFO.txt"
s = snap.read_text(encoding="utf-8")
s = s.replace("版本：Android 2.5.0（对应 git 标签 android-v2.5.0）",
              "版本：Android 2.5.1（对应 git 标签 android-v2.5.1）")
s = s.replace("本版新增（2.5.0，相对 2.4.0）", """本版新增（2.5.1，相对 2.5.0）
------------------------------
1. 拆分显示耗时：预填充（理解 prompt）与生成分别计时并显示/打印。
2. 线程数按 CPU 核数（2~6），不再写死 4。
3. 问答 prompt 预算 2600 → 1200 字（会议纪要仍 2600）。

上一版新增（2.5.0，相对 2.4.0）""", 1)
snap.write_text(s, encoding="utf-8")
print("版本号 -> 2.5.1 / 251；文档已更新")
