"""3.1.0 第一步：装回大模型 native 层；下载器去掉 OCR、加入 Qwen3-0.6B；
LlmEngine 加 translate()；删掉 OCR 的 native 与引擎文件。

先备份，失败可回退。所有改动后做括号/存在性自检。
"""
import re
import shutil
import urllib.request
import json
from pathlib import Path

ROOT = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
APP = ROOT / "android/app/src/main/java/com/localrecord/app"
CPP = ROOT / "android/app/src/main/cpp"

# ---------- 0) 先拿到 Qwen3-0.6B-Q4_K_M.gguf 的精确字节数 ----------
UA = {"User-Agent": "Mozilla/5.0"}
url = "https://www.modelscope.cn/api/v1/models/unsloth/Qwen3-0.6B-GGUF/repo/files?Revision=master&Recursive=true"
with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
    data = json.loads(r.read().decode("utf-8"))
target = "Qwen3-0.6B-Q4_K_M.gguf"
size = next((f["Size"] for f in (data.get("Data") or {}).get("Files", []) if f.get("Path") == target), 0)
assert size > 0, "没取到 Qwen3-0.6B-Q4_K_M.gguf 的大小"
print(f"Qwen3-0.6B-Q4_K_M.gguf = {size} 字节（{size/1e6:.1f} MB）")

# ---------- 1) CMakeLists：只编大模型（不再有 OCR）----------
(CPP / "CMakeLists.txt").write_text("""cmake_minimum_required(VERSION 3.22.0)
project(llmjni CXX C)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# 只编译需要的部分，并静态链接进 libllmjni.so
set(LLAMA_BUILD_TESTS     OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_EXAMPLES  OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_SERVER    OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_TOOLS     OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_COMMON    OFF CACHE BOOL "" FORCE)
set(LLAMA_CURL            OFF CACHE BOOL "" FORCE)
set(GGML_OPENMP           OFF CACHE BOOL "" FORCE)
set(GGML_CCACHE           OFF CACHE BOOL "" FORCE)
set(GGML_LLAMAFILE        OFF CACHE BOOL "" FORCE)
set(BUILD_SHARED_LIBS     OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)

# 第三方源码（llama-cpp-python 源码包里 vendored 的 llama.cpp）
add_subdirectory(
    ${CMAKE_CURRENT_SOURCE_DIR}/../../../../third_party/llama.cpp
    ${CMAKE_CURRENT_BINARY_DIR}/llama-build
    EXCLUDE_FROM_ALL)

add_library(llmjni SHARED llm_jni.cpp)
target_link_libraries(llmjni PRIVATE llama ggml android log)

# 说明：3.1.0 起移除了 OCR，所以这里不再有 ocrjni。
""", encoding="utf-8")
print("CMakeLists：只编大模型 ✓")

# ---------- 2) 装回 llm_jni.cpp ----------
bak = CPP / "removed-llm_jni.cpp.bak"
assert bak.is_file(), "找不到 llm_jni.cpp 备份"
shutil.copyfile(bak, CPP / "llm_jni.cpp")
print(f"llm_jni.cpp 已装回（{bak.stat().st_size} 字节）✓")

# ---------- 3) 删掉 OCR 的 native 与引擎 ----------
for f in [CPP / "ocr_jni.cpp"]:
    if f.is_file():
        f.unlink()
        print(f"已删除 {f.name} ✓")
ort = CPP / "ort"
if ort.is_dir():
    shutil.rmtree(ort)
    print("已删除 cpp/ort（ONNX Runtime 头文件，只有 OCR 用）✓")
for f in [APP / "OcrEngine.kt", ROOT / "android/app/src/main/assets/ocr_rec_dict.txt"]:
    if f.is_file():
        f.unlink()
        print(f"已删除 {f.relative_to(ROOT)} ✓")

# ---------- 4) ModelDownloader：去掉 OCR、加入 Qwen3-0.6B ----------
dl = APP / "ModelDownloader.kt"
dt = dl.read_text(encoding="utf-8")
# 删掉两个 OCR 制品（Artifact("ocr"... ) 两段）
before = dt
dt = re.sub(r'Artifact\(\s*"ocr"[^)]*?\),\n', '', dt, flags=re.S)
print(f"下载器：删除 OCR 制品 {len(before) - len(dt)} 字符 ✓")
# 加入 gguf
if "Qwen3-0.6B-Q4_K_M.gguf" not in dt:
    m = re.search(r'( *)(// 说明：本版本已移除本地大模型.*|Artifact\(\s*"llm")', dt)
    llm_block = (
        '        Artifact(\n'
        '            "llm",\n'
        f'            ms("unsloth/Qwen3-0.6B-GGUF", "{target}"),\n'
        f'            File(llmDir, ModelStore.LLM_MODEL), {size}L, required = false,\n'
        f'            fallbackUrl = "https://hf-mirror.com/unsloth/Qwen3-0.6B-GGUF/resolve/main/{target}",\n'
        '        ),\n'
    )
    if m:
        dt = dt[:m.start()] + llm_block + dt[m.end():]
    else:
        # 退而求其次：插在 artifacts 列表开头
        dt = dt.replace("    private val artifacts = listOf(\n", "    private val artifacts = listOf(\n" + llm_block, 1)
    print("下载器：加入 Qwen3-0.6B-Q4_K_M.gguf ✓")
dl.write_text(dt, encoding="utf-8")

# ---------- 5) ModelStore：模型名换成 Qwen3-0.6B ----------
ms = APP / "ModelStore.kt"
mt = ms.read_text(encoding="utf-8")
mt = re.sub(r'const val LLM_MODEL = "[^"]*"', 'const val LLM_MODEL = "Qwen3-0.6B-Q4_K_M.gguf"', mt)
ms.write_text(mt, encoding="utf-8")
print("ModelStore.LLM_MODEL = Qwen3-0.6B-Q4_K_M.gguf ✓")

# ---------- 6) LlmEngine：加 translate() ----------
le = APP / "LlmEngine.kt"
lt = le.read_text(encoding="utf-8")
if "fun translate(" not in lt:
    anchor = "    fun ask(transcript: String, question: String, maxTokens: Int = 300): String ="
    assert anchor in lt, "找不到 ask() 作为插入锚点"
    lt = lt.replace(anchor, """    /**
     * 逐句翻译：中文→英文、英文→中文（自动判断方向）。
     * 输入只放**这一句**，prompt 很短 → 手机上预填充快，能做到"边识别边翻译"。
     * 末尾的 /no_think 是 Qwen3 的软开关（关闭思维链）；JNI 还会补空 <think> 块，
     * 输出侧再兜底剥一次，三重保证不出现思考过程。
     */
    fun translate(text: String, maxTokens: Int = 200): String =
        generate(TRANSLATE_SYSTEM, text.trim() + "\\n/no_think", maxTokens)

""" + anchor, 1)
    # 加系统提示词
    m = re.search(r'val MINUTES_SYSTEM = """.*?"""', lt, re.S)
    assert m, "找不到 MINUTES_SYSTEM"
    add = '''

/** 翻译用的系统提示词：只要译文，不要解释 */
private const val TRANSLATE_SYSTEM =
    "你是专业翻译。规则：内容是中文就翻译成英文，是英文就翻译成中文；" +
        "只输出译文本身，不要解释、不要拼音、不要引号、不要重复原文、不要任何思考过程。"
'''
    lt = lt[:m.end()] + add + lt[m.end():]
    le.write_text(lt, encoding="utf-8")
    print("LlmEngine：已加 translate() 与 TRANSLATE_SYSTEM ✓")
else:
    print("LlmEngine 已有 translate()，跳过")

# ---------- 7) proguard：去掉 OCR 的 keep ----------
pg = ROOT / "android/app/proguard-rules.pro"
if pg.is_file():
    p = pg.read_text(encoding="utf-8")
    p = re.sub(r'-keep class com\.localrecord\.app\.OcrEngine \{ \* \}\n', '', p)
    pg.write_text(p, encoding="utf-8")
    print("proguard：去掉 OcrEngine keep ✓")
print("\n第一步完成")
