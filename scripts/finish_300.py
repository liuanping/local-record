"""3.0.0 收尾：ABI 切分只出 arm64（-Pemu 时才带上 x86_64 供模拟器验证）。"""
import re
from pathlib import Path

ROOT = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
g = ROOT / "android/app/build.gradle.kts"
t = g.read_text(encoding="utf-8")

# 在 android { } 里加 splits（放在 defaultConfig 之后）
if "splits {" not in t:
    anchor = "    buildTypes {"
    assert anchor in t
    t = t.replace(anchor, """    // 正式包只出 arm64（手机的 onnxruntime 就有 26MB，x86_64 那份 31MB 只给模拟器用，
    // 全部切掉后包体能少一半）。需要模拟器验证时：gradlew -Pemu assembleDebug
    splits {
        abi {
            isEnable = !project.hasProperty("emu")
            reset()
            include("arm64-v8a")
            isUniversalApk = false
        }
    }

""" + anchor, 1)
    g.write_text(t, encoding="utf-8")
    print("已加入 ABI 切分（-Pemu 可关闭）✓")

# 版本号已经是 3.0.0 / 300（stage1 改过）
for line in t.splitlines():
    if "versionCode" in line or "versionName" in line:
        print("  " + line.strip())

# README
readme = ROOT / "android/README-android.md"
r = readme.read_text(encoding="utf-8")
if "**3.0.0**" not in r:
    anchor = "* **2.5.2**："
    entry = """* **3.0.0**：**移除本地大模型，只做语音识别 + OCR，并大幅压缩包体**（用户要求）：
  * 删掉的功能：生成会议纪要 / 对转写或文档提问 / 大模型结果弹窗，以及下载 gguf 的制品。
    界面只剩三件事：录音转写（含复制）、录音库（播放/删除/导入音频）、文档问答→改为**纯 OCR 识别**。
  * **native 只留 OCR 推理层**：CMake 不再编译 llama.cpp/ggml（`llm_jni.cpp` 已删，备份为
    `removed-llm_jni.cpp.bak`），APK 里也就没有了 libllmjni/libggml。
  * **ABI 切分**：正式包只出 `arm64-v8a`。x86_64 的 `libonnxruntime.so` 有 **31MB**，只对模拟器有用
    → 切掉后包体从 **96.2MB 降到约 34MB**。需要模拟器时用 `gradlew -Pemu assembleDebug`。
  * **R8 代码/资源瘦身**：`isMinifyEnabled` / `isShrinkResources` 打开，并加 `proguard-rules.pro`
    保留 sherpa-onnx 与 native 方法（见文件内注释）。
  * 用户"一次下载完成"：自动下载的模型只剩 ASR(2) + 标点(2) + OCR(2) + VAD(1) ≈ **634MB**，
    不再有 1.28GB 的大模型。

"""
    readme.write_text(r.replace(anchor, entry + anchor, 1), encoding="utf-8")
    print("README 已加 3.0.0")

snap = ROOT / "SNAPSHOT-INFO.txt"
s = snap.read_text(encoding="utf-8")
s = s.replace("版本：Android 2.5.2（对应 git 标签 android-v2.5.2）",
              "版本：Android 3.0.0（对应 git 标签 android-v3.0.0）")
s = s.replace("本版新增（2.5.2，相对 2.5.1）", """本版新增（3.0.0，相对 2.5.2）
------------------------------
移除本地大模型（会议纪要/问答），只保留语音识别 + OCR；native 不再编译 llama.cpp；
正式包 ABI 切分只出 arm64（去掉 31MB 的 x86_64 onnxruntime）；R8 代码与资源瘦身。
包体 96.2MB → 约 34MB；需自动下载的模型只剩约 634MB（无大模型）。

上一版新增（2.5.2，相对 2.5.1）""", 1)
snap.write_text(s, encoding="utf-8")
print("SNAPSHOT-INFO 已更新")
