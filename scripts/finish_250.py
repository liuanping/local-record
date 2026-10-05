"""2.5.0：大模型换成 Qwen3.5-2B（Q4_K_M，1280.8MB）。"""
import re
from pathlib import Path

ROOT = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
NAME = "Qwen3.5-2B-Q4_K_M.gguf"
SIZE = 1_280_835_840

# 1) 下载器
dl = ROOT / "android/app/src/main/java/com/localrecord/app/ModelDownloader.kt"
t = dl.read_text(encoding="utf-8")
t = t.replace('ms("unsloth/Qwen3.5-4B-GGUF", "Qwen3.5-4B-Q4_K_M.gguf")',
              'ms("unsloth/Qwen3.5-2B-GGUF", "Qwen3.5-2B-Q4_K_M.gguf")')
t = t.replace('2_740_937_888L', f'{SIZE:,}L'.replace(",", "_"))
t = t.replace('https://hf-mirror.com/unsloth/Qwen3.5-4B-GGUF/resolve/main/Qwen3.5-4B-Q4_K_M.gguf',
              'https://hf-mirror.com/unsloth/Qwen3.5-2B-GGUF/resolve/main/Qwen3.5-2B-Q4_K_M.gguf')
dl.write_text(t, encoding="utf-8")
print("下载器已改为 Qwen3.5-2B（1,280,835,840 字节）")

# 2) ModelStore 常量（换名字 → 启动时会自动清掉 4B 与 MiniCPM）
ms = ROOT / "android/app/src/main/java/com/localrecord/app/ModelStore.kt"
mt = ms.read_text(encoding="utf-8")
mt = mt.replace('const val LLM_MODEL = "Qwen3.5-4B-Q4_K_M.gguf"', f'const val LLM_MODEL = "{NAME}"')
ms.write_text(mt, encoding="utf-8")
print(f"ModelStore.LLM_MODEL = {NAME}")

# 3) 版本号
g = ROOT / "android/app/build.gradle.kts"
gt = g.read_text(encoding="utf-8")
gt = gt.replace("versionCode = 240", "versionCode = 250").replace('versionName = "2.4.0"', 'versionName = "2.5.0"')
g.write_text(gt, encoding="utf-8")
print("版本号 -> 2.5.0 / 250")

# 4) 文档
readme = ROOT / "android/README-android.md"
r = readme.read_text(encoding="utf-8")
if "**2.5.0**" not in r:
    anchor = "* **2.4.0**："
    entry = """* **2.5.0**：**大模型换成 Qwen3.5-2B**（用户要求：4B 太大）：
  * `unsloth/Qwen3.5-2B-GGUF` 的 `Qwen3.5-2B-Q4_K_M.gguf` = **1,280,835,840 字节（1.28GB）**，
    比原来的 MiniCPM5-2B（1.49GB）**还小**，内存压力回到 ~2GB 可用即可。
  * 模板与前一个 4B 版本**完全一致**（已用 Range 拉取 GGUF 元数据核对）：
    `{%- if enable_thinking is defined and enable_thinking is true %}<think>{%- else %}<think>\\n\\n</think>\\n\\n{%- endif %}`，
    未定义时走 else → **官方默认关闭思维链**，且补块逻辑不会重复（JNI 已判断模板是否自带）。
  * 换名字后启动时会**自动删除** llm/ 里其它 gguf（旧的 MiniCPM5-2B / Qwen3.5-4B 都会被清掉）。

"""
    readme.write_text(r.replace(anchor, entry + anchor, 1), encoding="utf-8")
    print("README 已加 2.5.0")

snap = ROOT / "SNAPSHOT-INFO.txt"
s = snap.read_text(encoding="utf-8")
s = s.replace("版本：Android 2.4.0（对应 git 标签 android-v2.4.0）",
              "版本：Android 2.5.0（对应 git 标签 android-v2.5.0）")
s = s.replace("本版新增（2.4.0，相对 2.3.9）", """本版新增（2.5.0，相对 2.4.0）
------------------------------
大模型换成 Qwen3.5-2B-Q4_K_M（1.28GB，比 MiniCPM5-2B 还小），模板确认默认关闭思维链；
启动时自动删除 llm/ 里其它旧 gguf。

上一版新增（2.4.0，相对 2.3.9）""", 1)
snap.write_text(s, encoding="utf-8")
print("SNAPSHOT-INFO 已更新")
