// 手机端本地大模型：llama.cpp 的最小 JNI 封装
//
// 只暴露三个方法（Kotlin 侧 LlmEngine 调用）：
//   nativeInit(modelPath, nCtx, nThreads) -> handle(0 表示失败)
//   nativeGenerate(handle, prompt, maxTokens, stopText) -> 生成文本
//   nativeFree(handle)
//
// 采样用 greedy（与电脑版一致：会议纪要/问答不需要随机性，而且要快）。
#include <jni.h>

#include <algorithm>
#include <string>
#include <chrono>
#include <vector>

#include <android/log.h>

#include "llama.h"

#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, "LlmJni", __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, "LlmJni", __VA_ARGS__)

namespace {

struct LlmHandle {
    llama_model *model = nullptr;
    llama_context *ctx = nullptr;
    const llama_vocab *vocab = nullptr;
    int n_ctx = 2048;
    int n_threads = 4;
    // 上一次生成的分段耗时（给界面显示用，判断"慢"到底慢在哪一段）
    long long last_prefill_ms = 0;
    long long last_gen_ms = 0;
    int last_prompt_tokens = 0;
    int last_gen_tokens = 0;
    // 上一次的完整 prompt token（用于前缀 KV 复用：系统提示词固定，只有最后一句在变）
    std::vector<llama_token> cached_tokens;
};

std::string jstr(JNIEnv *env, jstring s) {
    if (s == nullptr) return {};
    const char *c = env->GetStringUTFChars(s, nullptr);
    std::string out(c ? c : "");
    if (c) env->ReleaseStringUTFChars(s, c);
    return out;
}

/**
 * 用**模型自带的**对话模板拼提示词。
 *
 * 不能硬编码 Qwen 的 `<|im_start|>` —— MiniCPM5 / Qwen / Gemma 模板各不相同，
 * 用错模板模型会答非所问甚至复读。llama.cpp 能从 GGUF 元数据里读模板，
 * 拿不到时退回 ChatML。
 */
std::string build_prompt(llama_model *model, const std::string &system, const std::string &user) {
    std::vector<llama_chat_message> chat;
    if (!system.empty()) chat.push_back({"system", system.c_str()});
    chat.push_back({"user", user.c_str()});

    const char *tmpl = llama_model_chat_template(model, nullptr);   // 可能为 nullptr
    if (tmpl != nullptr) LOGI("使用模型自带对话模板（前 40 字）：%.40s", tmpl);

    int n = llama_chat_apply_template(tmpl, chat.data(), chat.size(), true, nullptr, 0);
    std::string out;
    if (n <= 0) {
        LOGE("对话模板不可用（n=%d），退回手写 ChatML", n);
        if (!system.empty()) out += "<|im_start|>system\n" + system + "<|im_end|>\n";
        out += "<|im_start|>user\n" + user + "<|im_end|>\n<|im_start|>assistant\n";
    } else {
        out.assign((size_t) n, '\0');
        const int written = llama_chat_apply_template(tmpl, chat.data(), chat.size(), true,
                                                      out.data(), (int32_t) out.size());
        if (written <= 0) return {};
        out.resize((size_t) written);
    }

    // 关闭思维链（**两次踩坑后的正确做法**）：
    //  * MiniCPM5：模板的 enable_thinking 分支因为没有模板变量而**什么都不输出**（标记 [Start thinking]
    //    是模型自己写的，模板里没有）→ 需要在 assistant 开头手工补一个空思考块。
    //  * Qwen3.5：模板是 `{%- if enable_thinking is defined and enable_thinking is true %}<think>
    //    {%- else %}<think>\n\n</think>\n\n{%- endif %}`，llama.cpp 的 C API 不传模板变量 →
    //    **走 else 分支，模板自己已经补好空思考块** → 再补就变成两层，反而污染提示词。
    // 所以：先看套用结果里最后一个 assistant 之后有没有 <think>，有就不再补。
    if (tmpl != nullptr) {
        const std::string t(tmpl);
        const size_t lastAssistant = out.rfind("assistant");
        const size_t openAt = lastAssistant == std::string::npos
                                  ? std::string::npos
                                  : out.find("<think>", lastAssistant);
        // 关键：模板可能"只开了 <think> 没闭合"（Qwen3 在 enable_thinking 未定义时就是这种），
        // 那种情况下模型会自由推理 → 必须补一个 </think> 让它变成空思考块。
        const bool hasOpen = openAt != std::string::npos;
        const bool hasClose = hasOpen && out.find("</think>", openAt) != std::string::npos;
        if (hasOpen && hasClose) {
            LOGI("模板已自带完整空思考块，不干预");
        } else if (hasOpen && !hasClose) {
            out += "\n</think>\n\n";
            LOGI("模板只开了 <think> 未闭合，已补 </think>（强制空思考）");
        } else if (t.find("[Start thinking]") != std::string::npos) {
            out += "[Start thinking]\n\n[End thinking]\n\n";
            LOGI("已关闭思维链（补空 [Start thinking] 块）");
        } else if (t.find("<think>") != std::string::npos) {
            out += "<think>\n\n</think>\n\n";
            LOGI("已关闭思维链（补空 <think> 块）");
        } else if (t.find("think") != std::string::npos) {
            LOGI("模板提到 thinking，但标记不在已知列表里，未做干预");
        }
    }
    // 决定性日志：把实际喂给模型的 prompt 末尾打出来（换行转义），
    // 末尾是 "assistant\n<think>\n\n</think>\n\n" = 思维链已关；裸 "assistant\n" = 没关。
    {
        const std::string tail = out.size() > 80 ? out.substr(out.size() - 80) : out;
        std::string esc;
        for (char c : tail) {
            if (c == '\n') esc += "\\n";
            else if (c == '\r') esc += "\\r";
            else esc += c;
        }
        LOGI("prompt 末尾 80 字：%s", esc.c_str());
    }
    return out;
}

/** 兜底：万一模型仍然输出 <think>…</think>，剥掉它 */
std::string strip_thinking(const std::string &text) {
    std::string s = text;
    // 1) MiniCPM5 系的标记：[Start thinking] … [End thinking]
    for (;;) {
        const std::string a1 = "[Start thinking]", b1 = "[End thinking]";
        const size_t a = s.find(a1);
        const size_t b = s.find(b1);
        if (a != std::string::npos && b != std::string::npos && b > a) {
            s.erase(a, b + b1.size() - a);
            continue;
        }
        if (b != std::string::npos) {          // 只有结束标记：保留后面的正文
            s.erase(0, b + b1.size());
            continue;
        }
        if (a != std::string::npos) {          // 只有开始标记（被截断）：后面全是推理，丢掉
            s.erase(a);
            continue;
        }
        break;
    }
    // 2) Qwen 系的标记：<think> … </think>
    for (;;) {
        const std::string a1 = "<think>", b1 = "</think>";
        const size_t a = s.find(a1);
        const size_t b = s.find(b1);
        if (a != std::string::npos && b != std::string::npos && b > a) {
            s.erase(a, b + b1.size() - a);
            continue;
        }
        if (b != std::string::npos) {
            s.erase(0, b + b1.size());
            continue;
        }
        if (a != std::string::npos) {
            s.erase(a);
            continue;
        }
        break;
    }
    size_t i = 0;
    while (i < s.size() && (s[i] == '\n' || s[i] == ' ' || s[i] == '\r')) ++i;
    return s.substr(i);
}

}  // namespace

extern "C" JNIEXPORT jlong JNICALL
Java_com_localrecord_app_LlmEngine_nativeInit(JNIEnv *env, jobject /*thiz*/,
                                              jstring jpath, jint n_ctx, jint n_threads) {
    const std::string path = jstr(env, jpath);
    LOGI("nativeInit model=%s n_ctx=%d n_threads=%d", path.c_str(), n_ctx, n_threads);
    llama_backend_init();

    auto *h = new LlmHandle();
    llama_model_params mp = llama_model_default_params();
    mp.n_gpu_layers = 0;                       // 纯 CPU（新版默认就是 mmap 加载）
    h->model = llama_model_load_from_file(path.c_str(), mp);
    if (h->model == nullptr) {
        LOGE("加载模型失败：%s", path.c_str());
        delete h;
        return 0;
    }
    llama_context_params cp = llama_context_default_params();
    cp.n_ctx = (uint32_t) n_ctx;
    cp.n_threads = n_threads;
    cp.n_threads_batch = n_threads;
    h->ctx = llama_init_from_model(h->model, cp);
    if (h->ctx == nullptr) {
        LOGE("创建上下文失败");
        llama_model_free(h->model);
        delete h;
        return 0;
    }
    h->vocab = llama_model_get_vocab(h->model);
    h->n_ctx = (int) llama_n_ctx(h->ctx);
    h->n_threads = n_threads;
    LOGI("就绪：n_ctx=%d", h->n_ctx);
    return (jlong) h;
}

/** 毫秒计时（用于日志里报速度） */
long long now_ms() {
    using namespace std::chrono;
    return duration_cast<milliseconds>(steady_clock::now().time_since_epoch()).count();
}

/** 生成核心（两个 JNI 入口共用） */
std::string generate_impl(LlmHandle *h, const std::string &prompt, int max_tokens,
                          const std::string &stop) {
    const long long t_gen = now_ms();      // 只统计"生成"耗时（预填充算在 prompt 里）
    // ---- 分词 ----
    int n_max = (int) prompt.size() + 64;
    std::vector<llama_token> tokens(n_max);
    int n = llama_tokenize(h->vocab, prompt.c_str(), (int) prompt.size(),
                           tokens.data(), n_max, true, true);
    if (n < 0) {                                  // 缓冲不够，按返回的负数扩容重来
        tokens.resize(-n);
        n_max = -n;
        n = llama_tokenize(h->vocab, prompt.c_str(), (int) prompt.size(),
                           tokens.data(), n_max, true, true);
    }
    if (n <= 0) {
        LOGE("分词失败 n=%d", n);
        return {};
    }
    // 上下文预算：给输出留位置；超了就丢最前面（Kotlin 侧已按预算裁过转写文本）
    int budget = h->n_ctx - max_tokens - 8;
    if (budget < 64) budget = 64;
    int start = 0;
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

    // ---- 采样器：greedy ----
    llama_sampler *smpl = llama_sampler_chain_init(llama_sampler_chain_default_params());
    // 重复抑制（用户反馈偶发重复）：
    //   penalty_last_n = 64  只回看最近 64 个 token（全词表回看会明显变慢）
    //   penalty_repeat = 1.05 轻微惩罚已出现过的 token
    //   penalty_present = 0.1 已经出现过的 token 再出现就再压一点（治"卡在一个词上反复吐"）
    // 这两项对 greedy 同样有效：先改 logits，再取最大。
    llama_sampler_chain_add(smpl, llama_sampler_init_penalties(
        (int32_t) llama_vocab_n_tokens(h->vocab), 64, 1.05f, 0.0f, 0.1f));
    LOGI("采样器：greedy + 重复惩罚（repeat=1.05, present=0.1, last_n=64）");
    llama_sampler_chain_add(smpl, llama_sampler_init_greedy());

    // ---- 预填充（prompt 越长这一段越慢；手机上往往是它吃掉大部分时间）----
    const long long t_prefill = now_ms();
    const int kBatch = 512;
    bool ok = true;
    for (int i = start; i < n; i += kBatch) {
        const int cnt = std::min(kBatch, n - i);
        llama_batch batch = llama_batch_get_one(tokens.data() + i, cnt);
        if (llama_decode(h->ctx, batch) != 0) {
            LOGE("预填充 llama_decode 失败（i=%d）", i);
            ok = false;
            break;
        }
    }

    h->last_prefill_ms = now_ms() - t_prefill;
    h->last_prompt_tokens = n - start;
    LOGI("预填充：%d token / %.1f 秒（%.1f token每秒，%d 线程）",
         h->last_prompt_tokens, h->last_prefill_ms / 1000.0,
         h->last_prefill_ms > 10 ? h->last_prompt_tokens * 1000.0 / h->last_prefill_ms : 0.0,
         h->n_threads);

    std::string out;
    int generated = 0;
    if (ok) {
        const llama_token eos = llama_vocab_eos(h->vocab);
        const llama_token eot = llama_vocab_eot(h->vocab);   // 有些模型（含 MiniCPM）用 eot 结束
        for (int i = 0; i < max_tokens; ++i) {
            const llama_token id = llama_sampler_sample(smpl, h->ctx, -1);
            if (id == eos || id == eot) break;
            char buf[512];
            const int len = llama_token_to_piece(h->vocab, id, buf, sizeof(buf), 0, true);
            if (len > 0) {
                out.append(buf, len);
                generated++;
                if (!stop.empty() && out.find(stop) != std::string::npos) break;
            }
            llama_sampler_accept(smpl, id);
            llama_token next = id;
            llama_batch batch = llama_batch_get_one(&next, 1);
            if (llama_decode(h->ctx, batch) != 0) {
                LOGE("生成 llama_decode 失败（第 %d 个 token）", i);
                break;
            }
        }
    }
    llama_sampler_free(smpl);

    if (!stop.empty()) {
        const auto pos = out.find(stop);
        if (pos != std::string::npos) out = out.substr(0, pos);
    }
    // 把"生成多少 token、花了多久、多快"打出来 —— 判断"慢"到底是推理太多还是机器本身慢，
    // 看这行就够：token 数 ≈ 30 却要 30 秒 = 机器慢；token 数 150+ = 模型在推理。
    // 记录本次 prompt 的 token，下次找公共前缀用
    h->cached_tokens.assign(tokens.begin(), tokens.end());

    h->last_gen_ms = now_ms() - t_gen;
    h->last_gen_tokens = generated;
    const double sec = h->last_gen_ms / 1000.0;
    LOGI("生成完成：%d token / %.1f 秒 / %.1f token每秒（字符 %zu）",
         generated, sec, sec > 0.01 ? generated / sec : 0.0, out.size());
    return out;
}

/** 直接给完整提示词（调试用） */
extern "C" JNIEXPORT jstring JNICALL
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
Java_com_localrecord_app_LlmEngine_nativeGenerate(JNIEnv *env, jobject /*thiz*/, jlong jhandle,
                                                  jstring jprompt, jint max_tokens,
                                                  jstring jstop) {
    auto *h = reinterpret_cast<LlmHandle *>(jhandle);
    if (h == nullptr || h->ctx == nullptr) return env->NewStringUTF("");
    const std::string out = generate_impl(h, jstr(env, jprompt), max_tokens, jstr(env, jstop));
    return env->NewStringUTF(out.c_str());
}

/**
 * 给系统提示 + 用户输入，**用模型自带的对话模板**拼提示词后生成。
 * 这样 MiniCPM5 / Qwen / Gemma 都能用同一个接口。
 */
extern "C" JNIEXPORT jstring JNICALL
Java_com_localrecord_app_LlmEngine_nativeGenerateChat(JNIEnv *env, jobject /*thiz*/, jlong jhandle,
                                                      jstring jsystem, jstring juser,
                                                      jint max_tokens, jstring jstop) {
    auto *h = reinterpret_cast<LlmHandle *>(jhandle);
    if (h == nullptr || h->ctx == nullptr) return env->NewStringUTF("");
    const std::string prompt = build_prompt(h->model, jstr(env, jsystem), jstr(env, juser));
    if (prompt.empty()) {
        LOGE("提示词拼装失败");
        return env->NewStringUTF("");
    }
    const std::string out = generate_impl(h, prompt, max_tokens, jstr(env, jstop));
    const std::string clean = strip_thinking(out);
    return env->NewStringUTF(clean.c_str());
}

extern "C" JNIEXPORT void JNICALL
Java_com_localrecord_app_LlmEngine_nativeFree(JNIEnv * /*env*/, jobject /*thiz*/, jlong jhandle) {
    auto *h = reinterpret_cast<LlmHandle *>(jhandle);
    if (h == nullptr) return;
    if (h->ctx != nullptr) llama_free(h->ctx);
    if (h->model != nullptr) llama_model_free(h->model);
    delete h;
}
