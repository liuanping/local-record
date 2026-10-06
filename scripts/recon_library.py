from pathlib import Path
import re

R = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
t = (R / "android/app/src/main/java/com/localrecord/app/MainActivity.kt").read_text(encoding="utf-8").split("\n")
i = next(k for k, l in enumerate(t) if "private fun LibraryTab" in l)
print(f"===== LibraryTab（{i+1} 起 90 行）=====")
print("\n".join(f"{k+1:5d}|{t[k]}" for k in range(i, min(i + 90, len(t)))))

print("\n===== AndroidManifest =====")
print((R / "android/app/src/main/AndroidManifest.xml").read_text(encoding="utf-8"))

print("\n===== 依赖里的 core-ktx / activity =====")
g = (R / "android/app/build.gradle.kts").read_text(encoding="utf-8")
for l in g.split("\n"):
    if "implementation" in l or "core" in l.lower():
        print("  " + l.strip())
