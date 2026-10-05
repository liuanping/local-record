"""3.0.0 收尾（补漏）：删掉最后几处大模型残留引用。"""
import re
import subprocess
import os
from pathlib import Path

ROOT = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
m = ROOT / "android/app/src/main/java/com/localrecord/app/MainActivity.kt"
lines = m.read_text(encoding="utf-8").split("\n")

drop_preds = [
    lambda l: l.strip() == "answer = \"\"",
    lambda l: l.strip() == "llmDialog = null",
    lambda l: l.strip() == "if (llmDemo) {",
    lambda l: "LlmText.toPlainText(demo)" in l,
    lambda l: "故意用带 Markdown 的样例" in l,
    lambda l: 'val demo = "## 会议纪要' in l,
    # pickGguf 的整个回调（选大模型）——大模型没了，这个入口一起删
    lambda l: l.strip() == "private val pickGguf = registerForActivityResult(",
]

out = []
i = 0
while i < len(lines):
    l = lines[i]
    if any(p(l) for p in drop_preds):
        # 跳过这一行；若是 pickGguf 声明，则整块删掉（按圆括号+花括号配对）
        if l.strip().startswith("private val pickGguf"):
            depth = 0
            j = i
            while j < len(lines):
                depth += lines[j].count("(") - lines[j].count(")")
                depth += lines[j].count("{") - lines[j].count("}")
                if depth <= 0 and j > i:
                    break
                j += 1
            i = j + 1
            continue
        i += 1
        continue
    out.append(l)
    i += 1

lines = out
# llmDemo 的声明也去掉
lines = [l for l in lines if "val llmDemo = intent" not in l and "--ez llmdemo" not in l]

text = "\n".join(lines)
depth = 0
for ch in text:
    if ch == "{":
        depth += 1
    elif ch == "}":
        depth -= 1
print(f"括号平衡：{depth}（应为 0）")
m.write_text(text, encoding="utf-8")

env = {**os.environ, "JAVA_HOME": r"E:\android-dev\jdk", "ANDROID_HOME": r"E:\android-dev\sdk",
       "GRADLE_USER_HOME": r"E:\android-dev\gradle-home"}
r = subprocess.run([r"E:\android-dev\gradle\bin\gradle.bat", "--no-daemon", "--console=plain",
                    "-p", str(ROOT / "android"), "compileDebugKotlin"],
                   capture_output=True, text=True, encoding="utf-8", errors="ignore", env=env)
errs = [l for l in (r.stdout or "").splitlines() if l.startswith("e: ")]
print(f"编译错误 {len(errs)} 条：")
for e in errs[:10]:
    print("  " + e.replace(str(ROOT) + os.sep, "").replace("/", os.sep)[:150])
