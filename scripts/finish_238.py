"""2.3.8：文档 + 版本号。"""
from pathlib import Path

ROOT = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")

g = ROOT / "android/app/build.gradle.kts"
t = g.read_text(encoding="utf-8")
t = t.replace("versionCode = 237", "versionCode = 238").replace('versionName = "2.3.7"', 'versionName = "2.3.8"')
g.write_text(t, encoding="utf-8")
print("版本号 -> 2.3.8 / 238")

readme = ROOT / "android/README-android.md"
r = readme.read_text(encoding="utf-8")
if "**2.3.8**" not in r:
    anchor = "* **2.3.7**："
    entry = """* **2.3.8**：**修好思维链关闭**（用户实测"20 多个字花了 32 秒"）：
  * 真凶：MiniCPM5 的思维链标记是 **`[Start thinking] … [End thinking]`**，不是 `<think>`。
    而 `llm_jni.cpp` 里的关闭逻辑一直判断 `<think>`，**从来没匹配过** → 模型每次都在先长篇推理，
    再给出答案。按实测速率（约 7 tok/s）算，32 秒 ≈ 220 token，正好是"推理 + 短答案"。
    **所以 32 秒不正常。**
  * 修复：JNI 现在识别 `[Start thinking]` 并补一个**空的思考块**（同时仍兼容 `<think>`）；
    `strip_thinking()` 与 Kotlin 侧 `LlmText.stripThinking()` 也都能剥离这两种标记。
  * 问答完成时状态栏显示「回答完成（N 字，用时 X.Xs）」，一眼看出是否还在推理。
  * 预期：同样的问题从约 32s 降到约 5-10s，弹窗里只有答案。

"""
    assert anchor in r
    readme.write_text(r.replace(anchor, entry + anchor, 1), encoding="utf-8")
    print("README 已加 2.3.8")

snap = ROOT / "SNAPSHOT-INFO.txt"
s = snap.read_text(encoding="utf-8")
s = s.replace("版本：Android 2.3.7（对应 git 标签 android-v2.3.7）",
              "版本：Android 2.3.8（对应 git 标签 android-v2.3.8）")
s = s.replace("本版新增（2.3.7，相对 2.3.6）", """本版新增（2.3.8，相对 2.3.7）
------------------------------
修好思维链关闭：MiniCPM5 的标记是 [Start thinking]…[End thinking]（不是 <think>），
原来的判断从没匹配过 → 模型一直在先推理（20 多字花 32 秒）。现在 JNI 补空的思考块，
两层都会剥离这两种标记；问答完成时显示用时。

上一版新增（2.3.7，相对 2.3.6）""", 1)
snap.write_text(s, encoding="utf-8")
print("SNAPSHOT-INFO 已更新")
