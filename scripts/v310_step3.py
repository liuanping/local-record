"""3.1.0 第三步：修掉上一步的残留（trimIndent 错位、下载器 ocr 分支、pickImage 残体）。"""
import re
from pathlib import Path

R = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
APP = R / "android/app/src/main/java/com/localrecord/app"

# ---------- 1) LlmEngine：把 .trimIndent() 挪回 MINUTES_SYSTEM ----------
le = APP / "LlmEngine.kt"
t = le.read_text(encoding="utf-8")
t = t.replace('''重要：直接输出结果，不要输出任何思考过程、推理步骤或内心独白。"""

/** 翻译用的系统提示词：只要译文，不要解释 */
private const val TRANSLATE_SYSTEM =
    "你是专业翻译。规则：内容是中文就翻译成英文，是英文就翻译成中文；" +
        "只输出译文本身，不要解释、不要拼音、不要引号、不要重复原文、不要任何思考过程。"
.trimIndent()''', '''重要：直接输出结果，不要输出任何思考过程、推理步骤或内心独白。""".trimIndent()

/** 翻译用的系统提示词：只要译文，不要解释 */
private const val TRANSLATE_SYSTEM =
    "你是专业翻译。规则：内容是中文就翻译成英文，是英文就翻译成中文；只输出译文本身，" +
        "不要解释、不要拼音、不要引号、不要重复原文、不要任何思考过程。"''')
le.write_text(t, encoding="utf-8")
print("LlmEngine：trimIndent 归位 ✓")

# ---------- 2) MainActivity ----------
m = APP / "MainActivity.kt"
lines = m.read_text(encoding="utf-8").split("\n")


def block_end(start):
    depth = 0
    for i in range(start, len(lines)):
        s, j, in_str = lines[i], 0, False
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
    raise RuntimeError(f"{start+1} 起找不到块尾")


# 2a) 删掉 pickImage 的残留 lambda 体（以 ") { uri ->" 起头那一段）
i = next((k for k, l in enumerate(lines) if l.strip() == ") { uri ->"), -1)
assert i >= 0, "找不到 pickImage 残留"
e = block_end(i)
print(f"  删除 pickImage 残体：第 {i+1}~{e+1} 行")
del lines[i:e + 1]

# 2b) 删掉顶部 OCR 注释残迹
lines = [l for l in lines if l.strip() != "// ------------------------------------------------------- OCR 文档问答 ----"]

src = "\n".join(lines)

# 2c) 下载器按制品初始化的 switch 里去掉 ocr 分支
src = src.replace('''                                "ocr-det", "ocr-rec" -> {
                                    refreshModelFileFlags()
                                    if (!ocr.ready) {
                                        val o = ocr.init()
                                        runOnUiThread { ocrReady = o }
                                    }
                                }
''', '''                                "llm" -> {
                                    // 不自动加载（占内存），等有句子要翻译时再按需加载
                                }
''', 1)
# 若替换后出现重复的 "llm" 分支，清掉旧的
src = src.replace('''                                "llm" -> {
                                    // 不自动加载（占内存），等有句子要翻译时再按需加载
                                }
                                "llm" -> {
                                    // 不自动加载（占内存），等用户点「生成会议纪要」时再加载
                                }
''', '''                                "llm" -> {
                                    // 不自动加载（占内存），等有句子要翻译时再按需加载
                                }
''', 1)

# 2d) 清理 OCR 相关残留状态（不再使用）
for pat in [r"\n *private var ocrReady by mutableStateOf\(false\)",
            r"\n *private var ocrText by mutableStateOf\(\"\"\)",
            r"\n *private var ocrFilesReady by mutableStateOf\(false\).*",
            r"\n *private var ocrCopied by mutableStateOf\(false\).*"]:
    src = re.sub(pat, "", src)

m.write_text(src, encoding="utf-8")

depth = 0
in_str = False
for ch in src:
    if ch == '"':
        in_str = not in_str
    if not in_str:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
print(f"括号平衡 = {depth}（应为 0）")
for kw in ["OcrEngine", "decodeBitmap", "pickImage", "ocr.", "ocrReady", "ocrText"]:
    print(f"  残留 {kw}: {src.count(kw)}")
assert depth == 0
print("残留清理完成 ✓")
