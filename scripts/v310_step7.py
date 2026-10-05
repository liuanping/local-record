"""3.1.0 收尾：归档 APK、更新 README 下载入口与链接汇总、替换仓库里旧版 APK。"""
import re
import shutil
import subprocess
from pathlib import Path

R = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
GH = "https://github.com/liuanping/local-record"
GT = "https://gitee.com/liuanping100/local-record"
OLD, NEW = "v3.0.1", "v3.1.0"

# 1) 归档 APK
dst = R / "dist-android/LocalRecord-android-3.1.0.apk"
shutil.copyfile(R / "android/app/build/outputs/apk/release/app-arm64-v8a-release.apk", dst)
print(f"APK 归档：{dst.name}  {dst.stat().st_size/1e6:.2f} MB")

# 2) 仓库里只留最新一版 APK
subprocess.run(["git", "rm", "--cached", "--quiet", "dist-android/LocalRecord-android-3.0.1.apk"], cwd=R)
old = R / "dist-android/LocalRecord-android-3.0.1.apk"
if old.exists():
    old.unlink()
    print("已移除旧版 APK（仓库只保留最新一版）✓")

gi = R / ".gitignore"
g = gi.read_text(encoding="utf-8").replace(
    "!dist-android/LocalRecord-android-3.0.1.apk",
    "!dist-android/LocalRecord-android-3.1.0.apk")
gi.write_text(g, encoding="utf-8")
print(".gitignore 例外改为 3.1.0 ✓")

# 3) README：加下载安装一节（若还没有）+ 版本号替换
readme = R / "README.md"
r = readme.read_text(encoding="utf-8")
if "## 下载安装" not in r:
    block = f"""## 下载安装

| 渠道 | 下载 APK | 发行版页面 |
|---|---|---|
| **Gitee**（国内直连）⭐ | [LocalRecord-android-3.1.0.apk]({GT}/releases/download/{NEW}/LocalRecord-android-3.1.0.apk) | [{NEW}]({GT}/releases/tag/{NEW}) |
| GitHub | [LocalRecord-android-3.1.0.apk]({GH}/releases/download/{NEW}/LocalRecord-android-3.1.0.apk) | [{NEW}]({GH}/releases/tag/{NEW}) |

安装：下载后点击安装（首次可能提示"未知来源"，允许即可）；首次打开会自动下载模型（转写+标点+断句约 514MB，
翻译模型 397MB，建议 WiFi）。

"""
    r = r.replace("## 功能", block + "## 功能", 1)

# 功能表：去掉 OCR 行，改成翻译
r = r.replace("| **文档问答** | 选图片 → 离线 OCR 识别（中英数字）→ 一键复制 |",
              "| **逐句翻译** | 每识别出一句就立刻翻译（中文→英文 / 英文→中文），原文与译文并列显示，底部开关可关闭 |")
r = r.replace("其他：深色主题 · 应用图标 · 首次运行自动下载模型（ModelScope 主源，失败回退 hf-mirror）· 断点续传 · 后台下载。",
              "其他：深色主题 · 应用图标 · 首次运行自动下载模型（ModelScope 主源，失败回退 hf-mirror）· 断点续传 · 后台下载。\n\n"
              "翻译使用 **Qwen3-0.6B（Q4_K_M，397MB）** 在手机本地逐句翻译，不联网、不上传。")
r = re.sub(r"v3\.0\.1", NEW, r)
readme.write_text(r, encoding="utf-8")
print("README 已加下载安装入口并更新到 3.1.0 ✓")

# 4) 链接汇总里的版本号
lk = R / "docs/链接汇总.md"
if lk.exists():
    lk.write_text(re.sub(r"v3\.0\.1|LocalRecord-android-3\.0\.1", lambda m: NEW if m.group(0).startswith("v3") else "LocalRecord-android-3.1.0", lk.read_text(encoding="utf-8")), encoding="utf-8")
    print("docs/链接汇总.md 版本号已更新 ✓")

# 5) 体积与模型说明段落更新
r = readme.read_text(encoding="utf-8")
r = r.replace("* APK：**约 36 MB**（只含 arm64-v8a）", "* APK：**约 41 MB**（只含 arm64-v8a；含本地翻译用的 llama.cpp）")
r = r.replace("* 需要自动下载的模型合计约 **634 MB**：", "* 需要自动下载的模型合计约 **911 MB**（转写相关 514MB + 翻译模型 397MB）：")
r = r.replace("| OCR 检测 | PP-OCRv6 medium det | 59 MB |\n", "")
r = r.replace("| OCR 识别 | PP-OCRv6 medium rec | 73 MB |\n", "| 翻译（Qwen3-0.6B Q4_K_M） | 中英互译，本地逐句翻译 | 397 MB |\n")
readme.write_text(r, encoding="utf-8")
print("README 体积/模型表已更新 ✓")
print("提交前工作区：")
print(subprocess.run(["git", "status", "--porcelain"], cwd=R, capture_output=True, text=True,
                     encoding="utf-8").stdout[:1200])
