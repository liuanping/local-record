"""3.2.6：回到 3.2.4（3.2.5 那两处改动全部撤销），只把"语音头回退距离"加大。

用户要求：
  ① 回退到 3.2.4（3.2.5 引入闪退，全部撤掉）；
  ② 检测到语音头之后**多回退一点**；
  ③ 唯一约束：**别跟上一段重叠**（现有的 lastEnd 限制正好就是这个，保留）。

改动：
  - android/app/src/main/java/... 整个目录 git checkout v3.2.4
  - SileroVad：PREROLL_SEC 1.0s → 1.6s（多回退 0.6 秒）；保底引导静音 0.35s → 0.5s
  - 不重叠的约束不变：from = maxOf(lastEnd, segStart - ringSize)
"""
import re
import subprocess
from pathlib import Path

R = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")

subprocess.run(["git", "checkout", "v3.2.4", "--", "android/app/src/main/java"], cwd=R, check=True)
print("已回退到 3.2.4（3.2.5 的音源与状态栏改动全部撤销）✓")

vad = R / "android/app/src/main/java/com/localrecord/app/SileroVad.kt"
t = vad.read_text(encoding="utf-8")
before = t
t = t.replace("private const val PREROLL_SEC = 1.0f", "private const val PREROLL_SEC = 1.6f")
t = t.replace("private const val MIN_LEAD_SEC = 0.35f", "private const val MIN_LEAD_SEC = 0.5f")
assert t != before, "预卷常量没找到"
vad.write_text(t, encoding="utf-8")
print("预卷 1.0s → 1.6s（多回退 0.6 秒）、保底引导静音 0.35s → 0.5s ✓")
for l in t.split("\n"):
    if "PREROLL_SEC" in l or "MIN_LEAD_SEC" in l or "val from = maxOf" in l:
        print("   ", l.strip()[:100])

# 版本
g = R / "android/app/build.gradle.kts"
gt = g.read_text(encoding="utf-8")
gt = re.sub(r"versionCode = \d+", "versionCode = 326", gt, count=1)
gt = re.sub(r'versionName = "[^"]*"', 'versionName = "3.2.6"', gt, count=1)
g.write_text(gt, encoding="utf-8")
print("版本 -> 3.2.6 / 326 ✓")
