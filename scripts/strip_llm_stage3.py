"""3.0.0 收尾（代码清理）：删掉大模型相关 Kotlin 文件与调用，删干净再出包。"""
import re
import subprocess
from pathlib import Path

ROOT = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
APP = ROOT / "android/app/src/main/java/com/localrecord/app"
TEST = ROOT / "android/app/src/test/java/com/localrecord/app"
m = APP / "MainActivity.kt"

lines = m.read_text(encoding="utf-8").split("\n")


def block_end(start):
    depth = 0
    for i in range(start, len(lines)):
        s = lines[i]
        j, in_str = 0, False
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
    return -1


# 1) 按花括号配对删掉这几个函数
for name in ("startMinutes", "startAsk", "ensureLlm", "runLlmSelfTest", "transcriptText"):
    i = next((k for k, l in enumerate(lines) if re.match(rf"\s*private fun {name}\(", l)), -1)
    if i < 0:
        print(f"  [跳过] {name}: 没找到")
        continue
    # 往上吃掉紧邻的注释行
    s = i
    while s > 0 and (lines[s - 1].strip().startswith("*") or lines[s - 1].strip().startswith("/**")
                     or lines[s - 1].strip().startswith("//")):
        s -= 1
    e = block_end(i)
    print(f"  删除 {name}：第 {s + 1}~{e + 1} 行")
    del lines[s:e + 1]

# 2) 删掉 llm 相关字段与初始化
pats = [
    r"^\s*private lateinit var llm: LlmEngine\s*$",
    r"^\s*llm = LlmEngine\(store\)\s*$",
    r"^\s*private val llmBusy = AtomicBoolean\(false\)\s*$",
    r"^\s*val llmSelfTest = intent.*$",
    r"^\s*if \(llmSelfTest\) runLlmSelfTest\(\)\s*$",
    r"^\s*private var minutes by mutableStateOf.*$",
    r"^\s*private var answer by mutableStateOf.*$",
    r"^\s*private var llmDialog by mutableStateOf.*$",
    r"^\s*private var llmReady by mutableStateOf.*$",
    r"^\s*private var llmName by mutableStateOf.*$",
    r"^\s*private var question by mutableStateOf.*$",
]
removed = 0
out = []
for l in lines:
    if any(re.match(p, l) for p in pats):
        removed += 1
        continue
    out.append(l)
lines = out
print(f"  删除 llm 相关字段/初始化 {removed} 行")

text = "\n".join(lines)
# 3) 清空链接不再提 minutes/answer
text = text.replace('minutes = ""; answer = ""; ocrText = ""; llmDialog = null', 'ocrText = ""')
text = re.sub(r"\n\s*minutes = \"\"\n\s*answer = \"\"\n", "\n", text)

# 4) 平衡自检
depth = 0
for ch in text:
    if ch == "{":
        depth += 1
    elif ch == "}":
        depth -= 1
print(f"  括号平衡：{depth}（应为 0）")
m.write_text(text, encoding="utf-8")

# 5) 删除 LLM 的独立文件
for f in (APP / "LlmEngine.kt", APP / "LlmText.kt", TEST / "LlmTextTest.kt"):
    if f.is_file():
        f.unlink()
        print(f"  已删除 {f.name}")

print("\n=== 编译检查 ===")
r = subprocess.run([r"E:\android-dev\gradle\bin\gradle.bat", "--no-daemon", "--console=plain",
                    "-p", str(ROOT / "android"), "compileDebugKotlin"],
                   capture_output=True, text=True, encoding="utf-8", errors="ignore",
                   env={**__import__("os").environ,
                        "JAVA_HOME": r"E:\android-dev\jdk",
                        "ANDROID_HOME": r"E:\android-dev\sdk",
                        "GRADLE_USER_HOME": r"E:\android-dev\gradle-home"})
errs = [l for l in (r.stdout or "").splitlines() if l.startswith("e: ")][:12]
print("编译错误：")
for e in errs:
    print("  " + e.replace(str(ROOT) + "\\", ""))
if not errs:
    print("  无 ✓")
