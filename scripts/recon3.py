from pathlib import Path
R = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
APP = R / "android/app/src/main/java/com/localrecord/app"
for rel, a, b, tag in [
    ("ModelDownloader.kt", 40, 58, "Artifact 构造参数顺序"),
    ("ModelDownloader.kt", 92, 104, "llm 制品"),
    ("MainActivity.kt", 565, 578, "ocrText 引用 572"),
    ("MainActivity.kt", 815, 850, "ocr 残留 823"),
]:
    lines = (APP / rel).read_text(encoding="utf-8").split("\n")
    print(f"\n===== {tag} =====")
    for i in range(a - 1, min(b, len(lines))):
        print(f"{i+1:5d}| {lines[i]}")
