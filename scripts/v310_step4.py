"""3.1.0 第四步：加翻译自检钩子 + 版本号 + 文档。"""
import re
from pathlib import Path

R = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
APP = R / "android/app/src/main/java/com/localrecord/app"
m = APP / "MainActivity.kt"
src = m.read_text(encoding="utf-8")

# 找到现有自检写文件的写法（复用同一套路径 API）
mm = re.search(r"[^\n]*-result\.txt[^\n]*", src)
print("现有自检写文件的写法：", mm.group(0).strip() if mm else "（没找到）")
m2 = re.search(r"fun (\w+)\(\)[^\n]*= *File\(([^)]*)\)", src)
print("路径 API 线索：", m2.group(0).strip() if m2 else "（没找到）")
mm3 = re.findall(r"File\((store\.\w+\(\)|\w+)[^)]*\)", src)
print("File(...) 调用样例：", sorted(set(mm3))[:6])

hook = '''            if (liveTest) runLiveSelfTest()'''
if hook not in src:
    # 换一个钩子位置：紧跟其它自检调用
    m3 = re.search(r"\n( *)if \((\w+)\) run\w+SelfTest\(\)", src)
    print("备用钩子：", m3.group(0).strip() if m3 else "（没找到）")

print("\n--- 版本号 ---")
g = R / "android/app/build.gradle.kts"
gt = g.read_text(encoding="utf-8")
gt = gt.replace("versionCode = 310", "versionCode = 311").replace("versionCode = 301", "versionCode = 311")
gt = gt.replace('versionName = "3.0.1"', 'versionName = "3.1.0"')
g.write_text(gt, encoding="utf-8")
for l in gt.split("\n"):
    if "version" in l.lower() and ("Code" in l or "Name" in l):
        print("  " + l.strip())
