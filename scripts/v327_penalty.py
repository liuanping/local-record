"""3.2.7 第一步：JNI 采样器加重复惩罚（用户反馈偶发重复）。"""
from pathlib import Path

R = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
cpp = R / "android/app/src/main/cpp/llm_jni.cpp"
t = cpp.read_text(encoding="utf-8")

anchor = "    llama_sampler_chain_add(smpl, llama_sampler_init_greedy());"
assert anchor in t, "找不到采样器链"
new = """    // 重复抑制（用户反馈偶发重复）：
    //   penalty_last_n = 64  只回看最近 64 个 token（全词表回看会明显变慢）
    //   penalty_repeat = 1.15 轻微惩罚已出现过的 token
    //   penalty_present = 0.25 已经出现过的 token 再出现就再压一点（治"卡在一个词上反复吐"）
    // 这两项对 greedy 同样有效：先改 logits，再取最大。
    llama_sampler_chain_add(smpl, llama_sampler_init_penalties(
        (int32_t) llama_vocab_n_tokens(h->vocab), 64, 1.15f, 0.0f, 0.25f));
    LOGI("采样器：greedy + 重复惩罚（repeat=1.15, present=0.25, last_n=64）");
    llama_sampler_chain_add(smpl, llama_sampler_init_greedy());"""
cpp.write_text(t.replace(anchor, new, 1), encoding="utf-8")
print("llm_jni：采样器已加重复惩罚 ✓")

# 顺便打印当前 translate 函数，便于下一步改 maxTokens 计算
le = R / "android/app/src/main/java/com/localrecord/app/LlmEngine.kt"
lines = le.read_text(encoding="utf-8").split("\n")
i = next(k for k, l in enumerate(lines) if "fun translate(" in l)
print("\n===== 当前 translate() =====")
for k in range(i, min(i + 42, len(lines))):
    print(f"{k+1:5d}|{lines[k]}")
