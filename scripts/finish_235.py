"""2.3.5：文档 + 版本号（底部按钮精简 + 吸顶小链接）。"""
from pathlib import Path

ROOT = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")

g = ROOT / "android/app/build.gradle.kts"
t = g.read_text(encoding="utf-8")
t = t.replace("versionCode = 234", "versionCode = 235").replace('versionName = "2.3.4"', 'versionName = "2.3.5"')
g.write_text(t, encoding="utf-8")
print("版本号 -> 2.3.5 / 235")

readme = ROOT / "android/README-android.md"
r = readme.read_text(encoding="utf-8")
if "**2.3.5**" not in r:
    anchor = "* **2.3.4**："
    entry = """* **2.3.5**：**界面精简**（用户要求）：
  * 删掉底部那排技术性按钮「导入模型 / 选择大模型 / 清空 / 复制文字」——模型本来就是首次运行
    自动从 ModelScope 下载，不需要用户选；手工放模型的办法仍写在本文档里。底部只保留「降噪」开关。
  * 复制改成与「文档问答」页**一致的小链接样式**（`⧉ 复制`），并把这一行做成**吸顶**：
    列表再长也一直可见，复制/清空/回到最新随时够得着（原先放底部按钮、或放列表顶部都会够不到）。
  * 「清空」也变成同一行的小链接（功能保留）；「⇣ 最新」常显，一点回到最新一段。

"""
    assert anchor in r
    readme.write_text(r.replace(anchor, entry + anchor, 1), encoding="utf-8")
    print("README 已加 2.3.5")

snap = ROOT / "SNAPSHOT-INFO.txt"
s = snap.read_text(encoding="utf-8")
s = s.replace("版本：Android 2.3.4（对应 git 标签 android-v2.3.4）",
              "版本：Android 2.3.5（对应 git 标签 android-v2.3.5）")
s = s.replace("本版新增（2.3.4，相对 2.3.3）", """本版新增（2.3.5，相对 2.3.4）
------------------------------
界面精简：删掉底部「导入模型 / 选择大模型 / 清空 / 复制文字」四个按钮（模型自动下载，只留降噪开关）；
复制改为与文档问答页一致的小链接「⧉ 复制」，整行吸顶（列表再长也够得着），清空同排放置，⇣ 最新常显。

上一版新增（2.3.4，相对 2.3.3）""", 1)
snap.write_text(s, encoding="utf-8")
print("SNAPSHOT-INFO 已更新")
