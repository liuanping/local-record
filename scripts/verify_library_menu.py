"""在模拟器上验证录音库的「⋯」菜单：重命名 / 分享 / 另存为 / 删除。"""
import re
import subprocess
import sys
import time
from pathlib import Path

ADB = r"E:\android-dev\sdk\platform-tools\adb.exe"
DEV = "/sdcard/Android/data/com.localrecord.app/files"
ROOT = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")


def sh(*args, timeout=120):
    return subprocess.run([ADB, *args], capture_output=True, text=True,
                          encoding="utf-8", errors="ignore", timeout=timeout).stdout


def dump():
    sh("shell", "uiautomator", "dump", "/sdcard/v.xml")
    subprocess.run([ADB, "pull", "/sdcard/v.xml", r"E:\android-dev\v.xml"],
                   capture_output=True, text=True)
    return Path(r"E:\android-dev\v.xml").read_text(encoding="utf-8", errors="ignore")


def tap_text(xml, text, exact=True):
    pat = rf'text="{re.escape(text)}"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
    for m in re.finditer(pat, xml):
        if exact and m.group(0).split('text="')[1].split('"')[0] != text:
            continue
        x1, y1, x2, y2 = map(int, m.groups())
        sh("shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2))
        return True
    return False


def texts(xml):
    return [t for t in re.findall(r'text="([^"]+)"', xml) if t.strip()]


print("=== 放一个录音文件进去 ===")
sh("shell", "mkdir", "-p", f"{DEV}/recordings")
local_wav = ROOT / "android/app/src/test/resources/selftest.wav"
if not local_wav.exists():
    local_wav = Path(r"E:\android-dev\models\selftest.wav")
sh("push", str(local_wav), f"{DEV}/recordings/我的测试录音.wav")
print(sh("shell", "ls", "-l", f"{DEV}/recordings/").strip()[:300])

print("\n=== 启动 app 并切到「录音库」 ===")
sh("shell", "pm", "grant", "com.localrecord.app", "android.permission.RECORD_AUDIO")
sh("shell", "am", "force-stop", "com.localrecord.app")
sh("shell", "am", "start", "-n", "com.localrecord.app/.MainActivity", "--ez", "nodownload", "true")
time.sleep(18)
xml = dump()
if not tap_text(xml, "录音库"):
    print("✗ 没找到「录音库」标签页")
    sys.exit(0)
time.sleep(4)
xml = dump()
print("  录音库界面:", " | ".join(texts(xml))[:260])

print("\n=== 点「⋯」菜单 ===")
if not tap_text(xml, "⋯"):
    print("✗ 没找到「⋯」按钮")
    sys.exit(0)
time.sleep(3)
xml = dump()
t = texts(xml)
print("  菜单项:", " | ".join(t)[:200])
for item in ["重命名", "分享", "另存为", "删除"]:
    print(f"    {item}: {'✓ 有' if item in t else '✗ 缺'}")

print("\n=== 点「重命名」看对话框 ===")
if tap_text(xml, "重命名"):
    time.sleep(3)
    xml = dump()
    t2 = texts(xml)
    print("  对话框:", " | ".join(t2)[:200])
    print("    有输入框:", "✓" if any("文件名" in x for x in t2) else "✗")
    sh("shell", "screencap", "-p", "/sdcard/m1.png")
    subprocess.run([ADB, "pull", "/sdcard/m1.png", r"E:\android-dev\m1.png"],
                   capture_output=True, text=True)
    # 取消，避免真的改名
    if tap_text(xml, "取消"):
        time.sleep(2)
        print("    已取消 ✓")
sh("shell", "screencap", "-p", "/sdcard/m0.png")
subprocess.run([ADB, "pull", "/sdcard/m0.png", r"E:\android-dev\m0.png"],
               capture_output=True, text=True)
print("\n截图：m1.png（重命名对话框）")
