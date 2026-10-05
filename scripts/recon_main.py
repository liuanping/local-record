"""侦察 MainActivity 结构，为改动定位锚点。"""
import re
from pathlib import Path

f = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main\android\app\src\main\java\com\localrecord\app\MainActivity.kt")
lines = f.read_text(encoding="utf-8").split("\n")

pats = [
    r"data class Segment|class Segment",
    r"private fun ensureLlm",
    r"private val llm\b|private lateinit var llm\b",
    r"private var llmReady",
    r"private fun emitSegment",
    r"private fun clearSegments",
    r"fun OcrTab",
    r"private fun VoiceTab",
    r"private fun LibraryTab",
    r"val pickImage",
    r"runOcrSelfTest",
    r"decodeBitmap",
    r"private var ocrText|private var ocrReady|private var ocrCopied|private val ocr\b",
    r"ocrtest",
    r"else -> OcrTab",
    r"Text\(if \(enhanceOn\)",
    r'"实时转写"',
    r"segments\.forEach|items\(|forEachIndexed",
    r"private val io =",
    r"private var status|private var tab",
]
for p in pats:
    print(f"--- {p}")
    for i, l in enumerate(lines, 1):
        if re.search(p, l):
            print(f"  {i:5d}: {l.strip()[:110]}")

print("\n=== 行数 ===", len(lines))
