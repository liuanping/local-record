"""2.3.2：文档更新 + 版本号。"""
from pathlib import Path

ROOT = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")

# 版本号
g = ROOT / "android/app/build.gradle.kts"
t = g.read_text(encoding="utf-8")
t = t.replace("versionCode = 231", "versionCode = 232").replace('versionName = "2.3.1"', 'versionName = "2.3.2"')
g.write_text(t, encoding="utf-8")
print("版本号 → 2.3.2 / 232 ✓")

# README
readme = ROOT / "android/README-android.md"
r = readme.read_text(encoding="utf-8")
if "**2.3.2**" not in r:
    anchor = "* **2.3.1**："
    entry = """* **2.3.2**：修两个小问题（用户反馈）：
  1. 文案里写的「点红色按钮开始录音」不对（按钮是蓝色圆形）→ 改为「点右侧的圆形「录」按钮开始录音」。
  2. **修「漏第一个字」**：神经网络 VAD 要先确认 0.2~0.25 秒才判定成段，说话开头那一点
     （尤其轻声辅音）落在段外被丢掉了。现在每段都从环形缓冲里**补回起点前 0.35 秒**的音频
     一起送去识别（补白不超过上一段结束位置，不会重复）。同时把阈值 0.5→0.45、
     最短语音 0.25→0.2 秒，让起点发现得更早。
     实测（同一段 3 遍语音）：段起点从 `0.2s / 6.9s / 13.8s` 提前到 **`0.0s / 6.6s / 13.5s`**，
     日志可见 `分段：6.64s 起 +6.33s（补白 0.35s）`；噪声仍然 0 段、转写结果不变。

"""
    assert anchor in r
    readme.write_text(r.replace(anchor, entry + anchor, 1), encoding="utf-8")
    print("README 已加 2.3.2 ✓")

# 快照说明
snap = ROOT / "SNAPSHOT-INFO.txt"
s = snap.read_text(encoding="utf-8")
s = s.replace("版本：Android 2.3.1（对应 git 标签 android-v2.3.1）",
              "版本：Android 2.3.2（对应 git 标签 android-v2.3.2）")
s = s.replace("本版新增（2.3.1，相对 2.3.0）", """本版新增（2.3.2，相对 2.3.1）
------------------------------
1. 修「漏第一个字」：给每段补回起点前 0.35 秒音频（环形缓冲，不重复上一段），
   并把 VAD 阈值 0.5→0.45、最短语音 0.25→0.2 秒。实测段起点平均提前约 0.3 秒。
2. 修正文案「点红色按钮开始录音」→「点右侧的圆形「录」按钮开始录音」。

上一版新增（2.3.1，相对 2.3.0）""", 1)
snap.write_text(s, encoding="utf-8")
print("SNAPSHOT-INFO 已更新 ✓")
