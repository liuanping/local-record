from pathlib import Path
R = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
for rel, a, b, tag in [
    ("android/app/src/main/java/com/localrecord/app/LlmEngine.kt", 20, 40, "LlmEngine const 区域"),
    ("android/app/src/main/java/com/localrecord/app/MainActivity.kt", 434, 450, "ocr 引用 442"),
    ("android/app/src/main/java/com/localrecord/app/MainActivity.kt", 718, 830, "pickImage 残留"),
]:
    lines = (R / rel).read_text(encoding="utf-8").split("\n")
    print(f"\n===== {tag}（{rel.split('/')[-1]} {a}~{b}）=====")
    for i in range(a - 1, min(b, len(lines))):
        print(f"{i+1:5d}| {lines[i]}")
