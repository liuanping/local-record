cmake_minimum_required(VERSION 3.22.0)
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
