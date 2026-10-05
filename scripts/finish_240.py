"""2.4.0：把大模型从 MiniCPM5-2B 换成 Qwen3.5-4B（并自动删掉旧模型）。"""
import re
from pathlib import Path

ROOT = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")

# ---------- 1) 下载器：换模型 ----------
dl = ROOT / "android/app/src/main/java/com/localrecord/app/ModelDownloader.kt"
t = dl.read_text(encoding="utf-8")

old_llm = re.search(r'Artifact\(\s*"llm".*?\n\s*\),\n', t, re.S)
assert old_llm, "找不到 llm 的 Artifact 定义"
print("旧的 llm 定义：\n" + old_llm.group(0))
new_llm = '''Artifact(
                "llm", "本地大模型（会议纪要 / 问答）",
                ms("unsloth/Qwen3.5-4B-GGUF", "Qwen3.5-4B-Q4_K_M.gguf"),
                File(llmDir, ModelStore.LLM_MODEL), 2_740_937_888L, required = false,
                fallbackUrl = "https://hf-mirror.com/unsloth/Qwen3.5-4B-GGUF/resolve/main/Qwen3.5-4B-Q4_K_M.gguf",
            ),
'''
t = t[:old_llm.start()] + new_llm + t[old_llm.end():]
dl.write_text(t, encoding="utf-8")
print("下载器已改为 Qwen3.5-4B-Q4_K_M（2,740,937,888 字节）✓")

# ---------- 2) 版本号 ----------
g = ROOT / "android/app/build.gradle.kts"
gt = g.read_text(encoding="utf-8")
gt = gt.replace("versionCode = 239", "versionCode = 240").replace('versionName = "2.3.9"', 'versionName = "2.4.0"')
g.write_text(gt, encoding="utf-8")
print("版本号 -> 2.4.0 / 240")

# ---------- 3) 文档 ----------
readme = ROOT / "android/README-android.md"
r = readme.read_text(encoding="utf-8")
if "**2.4.0**" not in r:
    anchor = "* **2.3.9**：" if "* **2.3.9**：" in r else "* **2.3.8**："
    entry = """* **2.4.0**：**大模型换成 Qwen3.5-4B**（用户要求：换掉面壁的 2B，试 Qwen3.5 关思维链的效果）：
  * 模型：`unsloth/Qwen3.5-4B-GGUF` 的 `Qwen3.5-4B-Q4_K_M.gguf`（ModelScope 主源，2,740,937,888 字节 ≈ 2.74GB）。
  * **思维链默认就是关的**：直接把 Qwen3.5 的对话模板挖出来看过（读 GGUF 元数据处理 Range 请求），
    里面是
    `{%- if enable_thinking is defined and enable_thinking is true %}<think>{%- else %}<think>\\n\\n</think>\\n\\n{%- endif %}`，
    而 llama.cpp 的 C API 不传模板变量 → 走 **else 分支** → 官方"不思考"写法。
  * 因此 JNI 也改了：**模板已经放了空思考块就不再补**（原来无条件补，会出现两层空 think，反而污染）。
  * **旧模型自动删除**：换模型后启动时会把 `llm/` 目录里其它 `*.gguf` 清掉（不再白占 1.5GB）。
  * 注意：4B 比 2B 每 token 慢约一倍，但思维链关掉后 token 数大幅下降，整体更快；
    内存需求约 3.5GB 可用（建议 8GB 内存的机器）。

"""
    readme.write_text(r.replace(anchor, entry + anchor, 1), encoding="utf-8")
    print("README 已加 2.4.0")

snap = ROOT / "SNAPSHOT-INFO.txt"
s = snap.read_text(encoding="utf-8")
s = s.replace("版本：Android 2.3.9（对应 git 标签 android-v2.3.9）",
              "版本：Android 2.4.0（对应 git 标签 android-v2.4.0）")
s = s.replace("本版新增（2.3.9，相对 2.3.8）", """本版新增（2.4.0，相对 2.3.9）
------------------------------
大模型换成 Qwen3.5-4B（Q4_K_M，约 2.74GB，ModelScope 主源）。它的官方模板在 enable_thinking
未定义时就走"不思考"分支，所以思维链默认关闭；JNI 也改为"模板已放空思考块就不再补"。
换模型后启动时会自动删除 llm/ 里其它旧 gguf（不再白占 1.5GB）。

上一版新增（2.3.9，相对 2.3.8）""", 1)
snap.write_text(s, encoding="utf-8")
print("SNAPSHOT-INFO 已更新")
