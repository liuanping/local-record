"""完成 2.3.1：去掉未使用的 ocrUsable、更新文档、打包快照。"""
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")

# 1) 去掉未使用的 ocrUsable 属性（界面已不再显示就绪状态）
kt = ROOT / "android/app/src/main/java/com/localrecord/app/MainActivity.kt"
text = kt.read_text(encoding="utf-8")
pattern = re.compile(
    r"\n    /\*\* OCR 是否可用.*?\*/\n    private val ocrUsable: Boolean get\(\) = ocrReady \|\| ocrFilesReady\n",
    re.S,
)
text2, n = pattern.subn("\n", text)
if n:
    kt.write_text(text2, encoding="utf-8")
    print(f"已移除 ocrUsable（{n} 处）")
else:
    print("ocrUsable 未匹配（可能已删或格式不同）")

# ocrFilesReady 若只剩赋值没人读，也一并去掉
uses = len(re.findall(r"ocrFilesReady", kt.read_text(encoding="utf-8")))
print(f"ocrFilesReady 出现次数：{uses}")

# 2) 更新 README
readme = ROOT / "android/README-android.md"
rtext = readme.read_text(encoding="utf-8")
if "**2.3.1**" not in rtext:
    anchor = "* **2.3.0**：**体验细节修复**"
    entry = """* **2.3.1**：**不在界面上显示"就绪/未就绪"这类内部状态**（用户反馈）。原则：能用就直接用，
  只有**真的缺模型、需要下载**时才提示下载。具体：
  * 文档问答去掉「OCR 就绪 / 未就绪」，只留一句功能说明；
  * 语音页去掉琥珀色的「识别模型正在加载 / 还没下载完」提示，换成
    「模型不完整：还需下载 N 个文件（xxx MB）」这类**可操作的下载提示**（可点，断点续传）；
  * 「生成会议纪要」的状态从「已就绪 / 待准备」改为「点这里生成（首次会先加载大模型）」；
  * 顶部状态栏从「转写模型就绪（转写 + 标点）」改为「点圆钮开始录音，自动断句、自动出字」。

"""
    assert anchor in rtext
    readme.write_text(rtext.replace(anchor, entry + anchor, 1), encoding="utf-8")
    print("README 已加 2.3.1 ✓")

# 3) 快照说明
snap = ROOT / "SNAPSHOT-INFO.txt"
s = snap.read_text(encoding="utf-8")
s = s.replace("版本：Android 2.3.0（对应 git 标签 android-v2.3.0）",
              "版本：Android 2.3.1（对应 git 标签 android-v2.3.1）")
s = s.replace("""本版新增（2.3.0，相对 2.2.0）""",
              """本版新增（2.3.1，相对 2.3.0）
------------------------------
界面不再显示「就绪 / 未就绪」这类内部状态：能用就直接用，只有真的缺模型、需要下载时才提示下载
（「模型不完整：还需下载 N 个文件」+ 进度条 + 可点的「继续下载」）。文档问答只留一句功能说明。

上一版新增（2.3.0，相对 2.2.0）""", 1)
snap.write_text(s, encoding="utf-8")
print("SNAPSHOT-INFO 已更新 ✓")
