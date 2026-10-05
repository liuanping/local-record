from pathlib import Path
import re
f = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main\android\app\src\main\java\com\localrecord\app\MainActivity.kt")
lines = f.read_text(encoding="utf-8").split("\n")
for pat, tag in [(r"MAX_PENDING = 5", "MAX_PENDING 声明"),
                 (r"translateSkipped", "translateSkipped 出现处"),
                 (r"val dropped", "drop 循环"),
                 (r'"翻译 开"', "顶部小链接"),
                 (r"private fun enqueueTranslation", "enqueueTranslation")]:
    print(f"--- {tag}")
    for i, l in enumerate(lines, 1):
        if re.search(pat, l):
            print(f"{i:5d}| {l}")
print("\n--- enqueueTranslation 全文 ---")
i = next(k for k, l in enumerate(lines) if "private fun enqueueTranslation" in l)
print("\n".join(f"{k+1:5d}| {lines[k]}" for k in range(i - 12, i + 16)))
