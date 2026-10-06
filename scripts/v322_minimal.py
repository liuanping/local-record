"""就做两件事：① 代码回到 v3.1.7（只改提示词，其余一律不动）。"""
import subprocess
from pathlib import Path

R = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")

# ① 全部代码回到 v3.1.7（源码、native、资源、manifest、构建脚本）
paths = [
    "android/app/src/main/java",
    "android/app/src/main/cpp",
    "android/app/src/main/res",
    "android/app/src/main/AndroidManifest.xml",
    "android/app/build.gradle.kts",
    "android/app/proguard-rules.pro",
    "android/README-android.md",
]
subprocess.run(["git", "checkout", "v3.1.7", "--", *paths], cwd=R, check=True)
print("代码已回到 v3.1.7 ✓")

# ② 只改提示词：在 v3.1.7 的两条翻译提示词后面各加一句"不许保留另一种语言"
le = R / "android/app/src/main/java/com/localrecord/app/LlmEngine.kt"
t = le.read_text(encoding="utf-8")

old_en = '''        "Output ONLY the English translation - no Chinese, no explanation, no quotes. " +
        "Example: 今天下雨了 -> It is raining today."'''
new_en = '''        "Output ONLY the English translation - no Chinese, no explanation, no quotes. " +
        "Never keep any Chinese character in your answer. " +
        "Example: 今天下雨了 -> It is raining today."'''
old_zh = '''        "Output ONLY the Chinese translation - no English, no explanation, no quotes. " +
        "Example: See you tomorrow. -> 明天见。"'''
new_zh = '''        "Output ONLY the Chinese translation - no English, no explanation, no quotes. " +
        "Never keep any English word in your answer. " +
        "Example: See you tomorrow. -> 明天见。"'''

n = 0
if old_en in t:
    t = t.replace(old_en, new_en, 1); n += 1
if old_zh in t:
    t = t.replace(old_zh, new_zh, 1); n += 1
assert n == 2, f"提示词锚点没对上（改了 {n} 处）"
le.write_text(t, encoding="utf-8")
print("提示词加固完成（只加了一句'绝不保留另一种语言'）✓")
for l in t.split("\n"):
    if "Never keep" in l or "Output ONLY" in l:
        print("   ", l.strip()[:110])

# ③ 版本号往上走一格（好覆盖安装）
g = R / "android/app/build.gradle.kts"
gt = g.read_text(encoding="utf-8")
import re
cur = re.search(r"versionCode = (\d+)", gt)
code = int(cur.group(1)) if cur else 317
gt = re.sub(r"versionCode = \d+", f"versionCode = {code + 5}", gt)
gt = re.sub(r'versionName = "[^"]*"', 'versionName = "3.2.2"', gt)
g.write_text(gt, encoding="utf-8")
for l in gt.split("\n"):
    if "versionCode" in l or "versionName" in l:
        print("   ", l.strip())
