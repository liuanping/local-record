"""更新 README 与快照说明到 2.3.0（用 Python 写，避免 PowerShell 引号地狱）。"""
from pathlib import Path

ROOT = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")

README = ROOT / "android/README-android.md"
text = README.read_text(encoding="utf-8")
anchor = "* **2.2.0**：**导入外部音频转写**"
if "**2.3.0**" not in text:
    entry = """* **2.3.0**：**体验细节修复**（用户反馈，均已实测）：
  1. 文档问答去掉模型名介绍，只讲功能（「选一张带文字的图片…全程在手机上完成，图片和文字都不会上传」）。
  2. **修掉「明明能用却显示 OCR 未就绪」**：就绪判断原来只看内存里有没有加载过，现在改为
     「内存已加载 **或** 模型文件本来就在」，并且启动时若模型已在就自动后台加载好
     （日志实证：`OcrEngine: OCR 就绪=true 字典=18708 字符`，界面显示「可直接识别」）。
  3. **识别模型没加载完也能录音**：原来点录音会直接拒绝（「模型还没就绪」），用户不知道该怎么办。
     现在照常开始录音（音频完整保存），后台等模型就绪后自动接着识别；界面上用琥珀色文字说明。
     实测：模型不可用时录音照样生成 `rec-*.wav`（243KB / 8 秒）。
  4. **没有麦克风权限时的引导**：语音页显示红色提示「尚未获得麦克风权限…」（可点去设置）；
     点录音时当场弹系统授权；被拒绝后弹出说明弹窗，给出「去设置」和「再试一次授权」，
     并提示麦克风被其它应用占用的情况。
  5. 顺手把 `versionName` / `versionCode` 修正为 2.3.0 / 230（之前一直是 1.0.0 / 1）。

"""
    assert anchor in text, "找不到 2.2.0 锚点"
    text = text.replace(anchor, entry + anchor, 1)
    README.write_text(text, encoding="utf-8")
    print("README 已更新到 2.3.0 ✓")
else:
    print("README 已有 2.3.0，跳过")

SNAP = ROOT / "SNAPSHOT-INFO.txt"
s = SNAP.read_text(encoding="utf-8")
s = s.replace("版本：Android 2.2.0（对应 git 标签 android-v2.2.0）",
              "版本：Android 2.3.0（对应 git 标签 android-v2.3.0）")
old_head = "本版新增（相对 2.1.0）"
new_head = """本版新增（2.3.0，相对 2.2.0）
------------------------------
1. 识别模型没加载完也能录音：音频先完整保存，模型就绪后自动接着识别，界面有明确提示。
2. 麦克风权限：语音页红字提示 + 点录音弹系统授权 + 被拒后的引导弹窗（去设置 / 再试一次授权）。
3. 文档问答去掉模型名，只讲功能。
4. 修掉「明明能用却显示未就绪」的就绪判断（改为看模型文件是否已在手机上，并在启动时自动加载）。
5. versionName / versionCode 修正为 2.3.0 / 230。

上一版新增（2.2.0，相对 2.1.0）"""
if old_head in s:
    s = s.replace(old_head, new_head, 1)
SNAP.write_text(s, encoding="utf-8")
print("SNAPSHOT-INFO 已更新 ✓")
print()
print(s.splitlines()[3])
