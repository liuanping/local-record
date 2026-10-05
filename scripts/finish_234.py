"""2.3.4：文档 + 版本号（自动滚动/拖动条/复制）。"""
from pathlib import Path

ROOT = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")

g = ROOT / "android/app/build.gradle.kts"
t = g.read_text(encoding="utf-8")
t = t.replace("versionCode = 233", "versionCode = 234").replace('versionName = "2.3.3"', 'versionName = "2.3.4"')
g.write_text(t, encoding="utf-8")
print("版本号 -> 2.3.4 / 234")

readme = ROOT / "android/README-android.md"
r = readme.read_text(encoding="utf-8")
if "**2.3.4**" not in r:
    anchor = "* **2.3.3**："
    entry = """* **2.3.4**：**转写文字更好用**（用户需求）：
  1. **自动滚到最新一段**：新出一段就自动滑到底部；用户往上翻看历史时**暂停自动跟随**（不会把人拽回去），
     顶部出现「↓ 最新」一点即回到最新。
  2. **右侧拖动条**：Compose 没有内置滚动条，用 Canvas 自绘了一个（长文字列表可按住上下拖快速翻页）；
     拖动条的滑块位置跟着列表走。
  3. **一键复制**：底部按钮行新增「复制文字」——放在这里是**永远够得着**（原先放列表顶部，
     滚下去就点不到了）。点一下把全部转写（`mm:ss  文字` 逐行）写进剪贴板，按钮变「已复制 ✓」，
     状态栏显示「已复制转写文字（N 字）到剪贴板」。OCR 识别结果、会议纪要、AI 回答也都能一键复制。
  * 实测：9 段转写 → 点复制 → 系统剪贴板提示显示内容正确（233 字）；拖右侧条 → 列表回到前面的段。

"""
    assert anchor in r
    readme.write_text(r.replace(anchor, entry + anchor, 1), encoding="utf-8")
    print("README 已加 2.3.4")

snap = ROOT / "SNAPSHOT-INFO.txt"
s = snap.read_text(encoding="utf-8")
s = s.replace("版本：Android 2.3.3（对应 git 标签 android-v2.3.3）",
              "版本：Android 2.3.4（对应 git 标签 android-v2.3.4）")
s = s.replace("本版新增（2.3.3，相对 2.3.2）", """本版新增（2.3.4，相对 2.3.3）
------------------------------
1. 实时转写自动滚到最新一段；用户上翻时暂停跟随，顶部「↓ 最新」一键回到底部。
2. 列表右侧自绘拖动条（Compose 无内置滚动条），可按住上下拖快速翻长文字。
3. 底部新增「复制文字」按钮（永远可见），一键把所有转写按 mm:ss 逐行复制到剪贴板；
   OCR 文字、会议纪要、AI 回答也支持一键复制。

上一版新增（2.3.3，相对 2.3.2）""", 1)
snap.write_text(s, encoding="utf-8")
print("SNAPSHOT-INFO 已更新")
