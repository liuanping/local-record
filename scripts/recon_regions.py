"""打印 MainActivity 需要改动的几段，附行号。"""
from pathlib import Path

f = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main\android\app\src\main\java\com\localrecord\app\MainActivity.kt")
lines = f.read_text(encoding="utf-8").split("\n")

for a, b, tag in [(94, 146, "字段/状态/clearSegments"),
                  (475, 495, "ensureLlm"),
                  (1100, 1150, "TabRow 与底部行"),
                  (1468, 1492, "items(segments) 列表项"),
                  (1845, 1885, "emitSegment"),
                  (750, 800, "pickImage 头部")]:
    print(f"\n========== {tag}（{a}~{b}）==========")
    for i in range(a - 1, min(b, len(lines))):
        print(f"{i+1:5d}| {lines[i]}")
