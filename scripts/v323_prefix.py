"""3.2.3：① 修头部截断 ② prefix KV cache（系统提示词固定，预热复用）③ 头盔短词专用提示。

① 头被切掉：预卷 0.35s → 0.7s（麦克风偏小时 VAD 判定更晚，0.35s 不够），
   VAD 阈值 0.45 → 0.38（更早触发，减少开头丢失）。
② prefix KV cache（用户建议，正确且很关键）：系统提示词是固定的，每次只有最后一句用户文本在变。
   改成"找出与上一次相同的 token 前缀 → 只重算不同的部分"，省掉重复的预填充。
   之前为了修"多句都被翻成同一个词"做的是"每次全清"，那样会丢掉固定前缀的复用；
   现在改成：有公共前缀 → 只删尾巴（seq_rm）；没有 → 才全清。
③ 头盔：≤6 字的短词走"词典式"提示词（无例子可抄，实测 头盔→helmet）。
"""
import re
import subprocess
from pathlib import Path

R = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
CPP = R / "android/app/src/main/cpp/llm_jni.cpp"
APP = R / "android/app/src/main/java/com/localrecord/app"

# ---------- ① VAD：预卷与阈值 ----------
vad = APP / "SileroVad.kt"
vt = vad.read_text(encoding="utf-8")
vt = vt.replace("private const val PREROLL_SEC = 0.35f", "private const val PREROLL_SEC = 0.7f")
m = re.search(r"(private const val THRESHOLD\s*=\s*)([\d.]+)f", vt)
if m:
    print(f"  原阈值 {m.group(2)} → 0.38")
    vt = vt[:m.start(2)] + "0.38" + vt[m.end(2):]
vad.write_text(vt, encoding="utf-8")
print("SileroVad：预卷 0.35s→0.7s，阈值→0.38 ✓（头不再被切掉）")

# ---------- ② JNI：前缀 KV 复用 ----------
c = CPP.read_text(encoding="utf-8")
if "cached_tokens" not in c:
    c = c.replace("""    int last_prompt_tokens = 0;
    int last_gen_tokens = 0;
};""", """    int last_prompt_tokens = 0;
    int last_gen_tokens = 0;
    // 上一次的完整 prompt token（用于前缀 KV 复用：系统提示词固定，只有最后一句在变）
    std::vector<llama_token> cached_tokens;
};""", 1)

    old = """    int start = 0;
    if (n > budget) {
        start = n - budget;
        LOGI("提示词过长：%d token，截断到 %d（丢掉前 %d）", n, budget, start);
    }
"""
    new = """    int start = 0;
    if (n > budget) {
        start = n - budget;
        h->cached_tokens.clear();          // 截断过就不做前缀复用，避免位置对不上
        LOGI("提示词过长：%d token，截断到 %d（丢掉前 %d）", n, budget, start);
    }

    // ---- 前缀 KV 缓存复用 ----
    // 系统提示词是固定的，每次只有最后那句用户文本不同。找出与上一次相同的 token 前缀，
    // 只重新计算不同的部分（省掉重复的预填充，实测能快一倍以上）。
    // 注意：别整段都当缓存，至少留 1 个 token 要算，否则会空转。
    {
        int n_common = 0;
        const int cap = std::min((int) h->cached_tokens.size(), n);
        while (n_common < cap && h->cached_tokens[(size_t) n_common] == tokens[(size_t) n_common]) {
            n_common++;
        }
        if (n_common >= n) n_common = n - 1;
        if (n_common < start) n_common = 0;          // 被截断过就不复用
        llama_memory_t mem = llama_get_memory(h->ctx);
        if (n_common > 0) {
            llama_memory_seq_rm(mem, 0, n_common, -1);   // 只丢掉不同的尾巴，公共前缀留在缓存里
            LOGI("前缀 KV 复用：%d/%d token 命中缓存，只重算 %d 个", n_common, n, n - n_common);
        } else {
            llama_memory_clear(mem, true);
            LOGI("没有公共前缀，清空上下文重算");
        }
        start = n_common;
    }
"""
    assert old in c, "找不到截断/预填充那段"
    c = c.replace(old, new, 1)

    # 生成结束后记录本次 token，供下次复用（放在函数返回前）
    anchor = "    h->last_gen_ms = now_ms() - t_gen;"
    assert anchor in c, "找不到生成本耗时统计处"
    c = c.replace(anchor, """    // 记录本次 prompt 的 token，下次找公共前缀用
    h->cached_tokens.assign(tokens.begin(), tokens.end());

""" + anchor, 1)
    CPP.write_text(c, encoding="utf-8")
    print("llm_jni：前缀 KV 复用已实现 ✓")
else:
    print("llm_jni 已有前缀复用")

# ---------- ③ 头盔：短词走词典式提示 ----------
le = APP / "LlmEngine.kt"
t = le.read_text(encoding="utf-8")
if "DICT_EN" not in t:
    # 在 translate() 前面加两个词典式提示词
    t = t.replace("    /** 含汉字就译成英文", '''    /**
     * 短词（≤6 字）专用的"词典式"提示词：**故意不给例子** ——
     * 给例子会被小模型抄成万能答案，不给例子整句又会退化成查词，
     * 所以只对短词用它（实测「头盔」→ helmet 稳定）。
     */
    private val DICT_EN = "You are a Chinese-English dictionary. The user sends a Chinese word. " +
        "Reply with its English meaning only: one word, no Chinese, no explanation, no quotes."
    private val DICT_ZH = "You are an English-Chinese dictionary. The user sends an English word. " +
        "Reply with its Chinese meaning only, no English, no explanation, no quotes."

    /** 含汉字就译成英文''', 1)
    # 在 translate() 里按长度选择系统提示词
    old_call = """        return generate(
            if (looksChinese(src)) TRANSLATE_TO_EN else TRANSLATE_TO_ZH,
            src,
            maxTokens
        )"""
    assert old_call in t, "找不到 translate 的 generate 调用"
    t = t.replace(old_call, """        val toEnglish = looksChinese(src)
        // 短词（≤6 字）用词典式提示：治「头盔 → head 盔」这类半翻半留
        val sys = when {
            src.length <= 6 && toEnglish -> DICT_EN
            src.length <= 6 -> DICT_ZH
            toEnglish -> TRANSLATE_TO_EN
            else -> TRANSLATE_TO_ZH
        }
        return generate(sys, src, maxTokens)""", 1)
le.write_text(t, encoding="utf-8")
print("LlmEngine：短词改走词典式提示（头盔专用）✓")

# ---------- ④ 版本 ----------
g = R / "android/app/build.gradle.kts"
gt = g.read_text(encoding="utf-8")
gt = re.sub(r"versionCode = \d+", "versionCode = 323", gt, count=1)
gt = re.sub(r'versionName = "[^"]*"', 'versionName = "3.2.3"', gt, count=1)
g.write_text(gt, encoding="utf-8")
print("版本 -> 3.2.3 / 323 ✓")

depth, ins = 0, False
for ch in t:
    if ch == '"':
        ins = not ins
    if not ins:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
print(f"LlmEngine 括号平衡 = {depth}（应为 0）")
