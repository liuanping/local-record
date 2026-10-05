from pathlib import Path

f = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main\android\app\src\main\java\com\localrecord\app\MainActivity.kt")
t = f.read_text(encoding="utf-8")

print("已有 clip import:", "import androidx.compose.ui.draw.clip" in t)
print("compose.ui 相关 import:")
for l in t.split("\n")[:90]:
    if "compose.ui" in l:
        print("  " + l.strip())

# 1) 加 import
if "import androidx.compose.ui.draw.clip" not in t:
    t = t.replace("import androidx.compose.ui.Modifier",
                  "import androidx.compose.ui.Modifier\nimport androidx.compose.ui.draw.clip", 1)
    print("已加 import androidx.compose.ui.draw.clip ✓")

# 2) 链式调用改回短名
t = t.replace(".androidx.compose.ui.draw.clip(RoundedCornerShape(20.dp))",
              ".clip(RoundedCornerShape(20.dp))")
print("链式调用已改为 .clip(...) ✓")
f.write_text(t, encoding="utf-8")

# 3) 版本号
g = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main\android\app\build.gradle.kts")
gt = g.read_text(encoding="utf-8")
gt = gt.replace("versionCode = 311", "versionCode = 312")
gt = gt.replace('versionName = "3.1.1"', 'versionName = "3.1.2"')
g.write_text(gt, encoding="utf-8")
for l in gt.split("\n"):
    if "versionCode" in l or "versionName" in l:
        print("  " + l.strip())
