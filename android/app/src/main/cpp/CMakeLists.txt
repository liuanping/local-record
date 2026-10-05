cmake_minimum_required(VERSION 3.22.0)
project(ocrjni CXX C)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# 注意：本版本已**移除本地大模型**（会议纪要/问答），所以这里不再编译 llama.cpp/ggml。
# 保留下来的 native 只有 OCR 推理层：**不链接** onnxruntime（运行时 dlopen sherpa 已经
# 带进来的那个 .so，避免两个同名 libonnxruntime.so 冲突），所以只要头文件 + dl。
add_library(ocrjni SHARED ocr_jni.cpp)
target_include_directories(ocrjni PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(ocrjni PRIVATE android log dl)
