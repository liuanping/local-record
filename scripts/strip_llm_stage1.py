"""Stage 1：砍掉大模型的 native 构建、只出 arm64、开启 R8 瘦身、下载器不再下大模型。"""
import re
from pathlib import Path

ROOT = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")

# ---------- 1) CMakeLists：只留 OCR 的 JNI ----------
cm = ROOT / "android/app/src/main/cpp/CMakeLists.txt"
cm.write_text("""cmake_minimum_required(VERSION 3.22.0)
project(ocrjni CXX C)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# 注意：本版本已**移除本地大模型**（会议纪要/问答），所以这里不再编译 llama.cpp/ggml。
# 保留下来的 native 只有 OCR 推理层：**不链接** onnxruntime（运行时 dlopen sherpa 已经
# 带进来的那个 .so，避免两个同名 libonnxruntime.so 冲突），所以只要头文件 + dl。
add_library(ocrjni SHARED ocr_jni.cpp)
target_include_directories(ocrjni PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(ocrjni PRIVATE android log dl)
""", encoding="utf-8")
print("CMakeLists：已移除 llama.cpp / llmjni ✓")

# 删掉 llm_jni.cpp（并保留一份到 third_party 之外，便于以后想恢复）
llm_cpp = ROOT / "android/app/src/main/cpp/llm_jni.cpp"
if llm_cpp.is_file():
    keep = ROOT / "android/app/src/main/cpp/removed-llm_jni.cpp.bak"
    keep.write_text(llm_cpp.read_text(encoding="utf-8"), encoding="utf-8")
    llm_cpp.unlink()
    print("llm_jni.cpp 已删除（备份为 removed-llm_jni.cpp.bak）✓")

# ---------- 2) build.gradle.kts：abiFilters + R8 ----------
g = ROOT / "android/app/build.gradle.kts"
t = g.read_text(encoding="utf-8")
t = t.replace("""        // 手机用 arm64；x86_64 留给模拟器验证
        abiFilters += listOf("arm64-v8a", "x86_64")""",
"""        // 手机用 arm64（正式包**只出 arm64**，体积最小）；
        // x86_64 只在 debug 包里保留，用于模拟器验证
        abiFilters += listOf("arm64-v8a", "x86_64")""")

old_release = re.search(r"        release \{.*?\n        \}\n", t, re.S)
assert old_release, "找不到 release 配置块"
print("原 release 配置：\n" + old_release.group(0))
new_release = """        release {
            // 正式包：只出 arm64 + 打开代码/资源瘦身，尽量压体积
            ndk {
                abiFilters.clear()
                abiFilters += listOf("arm64-v8a")
            }
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
            signingConfig = signingConfigs.getByName("debug")
        }
"""
t = t[:old_release.start()] + new_release + t[old_release.end():]
g.write_text(t, encoding="utf-8")
print("build.gradle.kts：release 只出 arm64 + R8 瘦身 ✓")

# ---------- 3) 下载器：不再下载大模型 ----------
dl = ROOT / "android/app/src/main/java/com/localrecord/app/ModelDownloader.kt"
dt = dl.read_text(encoding="utf-8")
m = re.search(r'Artifact\(\s*"llm".*?\n\s*\),\n', dt, re.S)
if m:
    dt = dt[:m.start()] + "// 说明：本版本已移除本地大模型，所以不再下载 gguf（体积/内存都省下来）\n" + dt[m.end():]
    dl.write_text(dt, encoding="utf-8")
    print("下载器：已移除大模型制品 ✓")
else:
    print("下载器：没找到大模型制品（可能已移除）")

# ---------- 4) 版本号 ----------
gt = g.read_text(encoding="utf-8")
gt = gt.replace("versionCode = 252", "versionCode = 300").replace('versionName = "2.5.2"', 'versionName = "3.0.0"')
g.write_text(gt, encoding="utf-8")
print("版本号 -> 3.0.0 / 300 ✓")
