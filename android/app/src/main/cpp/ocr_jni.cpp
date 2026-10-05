// 手机端 OCR 的推理层：直接用 sherpa-onnx 已经带进来的 libonnxruntime.so
//
// 为什么这么绕：sherpa-onnx 的 AAR 里已经有一个 libonnxruntime.so（1.20.1），
// 再引入 com.microsoft.onnxruntime:onnxruntime-android（1.20.0）会**两个同名 .so 打架**
// （打包冲突 + 版本不一致可能让 sherpa 崩）。所以这里只用官方 AAR 的头文件，
// 运行时 dlopen 那个已经存在的 .so，拿 ORT 的 C API 自己开 session。
//
// 只暴露两个方法：
//   nativeInit(detPath, recPath) -> handle
//   nativeRun(handle, which, input, inDims, outDims) -> 输出张量（形状写回 outDims）
#include <jni.h>

#include <dlfcn.h>

#include <string>
#include <vector>

#include <android/log.h>

#include "ort/onnxruntime_c_api.h"

#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, "OcrJni", __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, "OcrJni", __VA_ARGS__)

namespace {

struct OcrHandle {
    const OrtApi *api = nullptr;
    OrtEnv *env = nullptr;
    OrtSessionOptions *opts = nullptr;
    OrtMemoryInfo *mem = nullptr;
    OrtSession *det = nullptr;
    OrtSession *rec = nullptr;
    std::vector<std::string> det_in, det_out, rec_in, rec_out;
};

// 缓存 session 的输入/输出名（ORT 要求用 char* 数组）
void collect_names(const OrtApi *api, OrtSession *s, std::vector<std::string> &ins,
                   std::vector<std::string> &outs) {
    size_t n = 0;
    api->SessionGetInputCount(s, &n);
    for (size_t i = 0; i < n; ++i) {
        OrtAllocator *alloc = nullptr;
        api->GetAllocatorWithDefaultOptions(&alloc);
        char *name = nullptr;
        if (api->SessionGetInputName(s, i, alloc, &name) == nullptr && name) {
            ins.emplace_back(name);
        }
    }
    api->SessionGetOutputCount(s, &n);
    for (size_t i = 0; i < n; ++i) {
        OrtAllocator *alloc = nullptr;
        api->GetAllocatorWithDefaultOptions(&alloc);
        char *name = nullptr;
        if (api->SessionGetOutputName(s, i, alloc, &name) == nullptr && name) {
            outs.emplace_back(name);
        }
    }
}

std::vector<const char *> to_cstr(const std::vector<std::string> &v) {
    std::vector<const char *> out;
    out.reserve(v.size());
    for (const auto &s : v) out.push_back(s.c_str());
    return out;
}

}  // namespace

extern "C" JNIEXPORT jlong JNICALL
Java_com_localrecord_app_OcrEngine_nativeInit(JNIEnv *env, jobject /*thiz*/,
                                              jstring jdet, jstring jrec, jint threads) {
    const char *detC = env->GetStringUTFChars(jdet, nullptr);
    const char *recC = env->GetStringUTFChars(jrec, nullptr);
    const std::string detPath(detC ? detC : ""), recPath(recC ? recC : "");
    if (detC) env->ReleaseStringUTFChars(jdet, detC);
    if (recC) env->ReleaseStringUTFChars(jrec, recC);

    // 打开已经在进程里的 onnxruntime（sherpa 带进来的）
    void *lib = dlopen("libonnxruntime.so", RTLD_NOW | RTLD_GLOBAL);
    if (lib == nullptr) {
        LOGE("dlopen libonnxruntime.so 失败：%s", dlerror());
        return 0;
    }
    auto getApiBase = reinterpret_cast<const OrtApiBase *(*)()>(dlsym(lib, "OrtGetApiBase"));
    if (getApiBase == nullptr) {
        LOGE("找不到 OrtGetApiBase");
        return 0;
    }
    const OrtApi *api = getApiBase()->GetApi(ORT_API_VERSION);
    if (api == nullptr) {
        LOGE("GetApi 返回空（运行时与头文件版本不匹配）");
        return 0;
    }
    LOGI("ORT 运行时版本：%s", getApiBase()->GetVersionString());

    auto *h = new OcrHandle();
    h->api = api;
    if (api->CreateEnv(ORT_LOGGING_LEVEL_WARNING, "localrecord", &h->env) != nullptr) {
        LOGE("CreateEnv 失败"); delete h; return 0;
    }
    if (api->CreateSessionOptions(&h->opts) != nullptr) {
        LOGE("CreateSessionOptions 失败"); delete h; return 0;
    }
    api->SetIntraOpNumThreads(h->opts, threads > 0 ? threads : 4);
    api->SetSessionGraphOptimizationLevel(h->opts, ORT_ENABLE_ALL);
    api->CreateCpuMemoryInfo(OrtArenaAllocator, OrtMemTypeDefault, &h->mem);

    OrtStatus *st = api->CreateSession(h->env, detPath.c_str(), h->opts, &h->det);
    if (st != nullptr) {
        LOGE("加载检测模型失败：%s | %s", api->GetErrorMessage(st), detPath.c_str());
        api->ReleaseStatus(st); delete h; return 0;
    }
    st = api->CreateSession(h->env, recPath.c_str(), h->opts, &h->rec);
    if (st != nullptr) {
        LOGE("加载识别模型失败：%s | %s", api->GetErrorMessage(st), recPath.c_str());
        api->ReleaseStatus(st); delete h; return 0;
    }
    collect_names(api, h->det, h->det_in, h->det_out);
    collect_names(api, h->rec, h->rec_in, h->rec_out);
    LOGI("就绪：det in=%s out=%s | rec in=%s out=%s",
         h->det_in.empty() ? "?" : h->det_in[0].c_str(),
         h->det_out.empty() ? "?" : h->det_out[0].c_str(),
         h->rec_in.empty() ? "?" : h->rec_in[0].c_str(),
         h->rec_out.empty() ? "?" : h->rec_out[0].c_str());
    return (jlong) h;
}

extern "C" JNIEXPORT jfloatArray JNICALL
Java_com_localrecord_app_OcrEngine_nativeRun(JNIEnv *env, jobject /*thiz*/, jlong jhandle,
                                             jboolean useDet, jfloatArray jinput,
                                             jlongArray jindims, jlongArray joutdims) {
    auto *h = reinterpret_cast<OcrHandle *>(jhandle);
    if (h == nullptr) return nullptr;
    const OrtApi *api = h->api;
    OrtSession *session = useDet ? h->det : h->rec;
    const auto &ins = useDet ? h->det_in : h->rec_in;
    const auto &outs = useDet ? h->det_out : h->rec_out;
    if (session == nullptr || ins.empty() || outs.empty()) return nullptr;

    const jsize inLen = env->GetArrayLength(jinput);
    jlong *inDims = env->GetLongArrayElements(jindims, nullptr);
    const int64_t rank = (int64_t) env->GetArrayLength(jindims);
    std::vector<int64_t> shape(inDims, inDims + rank);
    env->ReleaseLongArrayElements(jindims, inDims, JNI_ABORT);

    jfloat *inData = env->GetFloatArrayElements(jinput, nullptr);
    OrtValue *inputTensor = nullptr;
    OrtStatus *st = api->CreateTensorWithDataAsOrtValue(
        h->mem, inData, (size_t) inLen * sizeof(float), shape.data(), (size_t) rank,
        ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT, &inputTensor);
    if (st != nullptr) {
        LOGE("建输入张量失败：%s", api->GetErrorMessage(st));
        api->ReleaseStatus(st);
        env->ReleaseFloatArrayElements(jinput, inData, JNI_ABORT);
        return nullptr;
    }
    const char *inNames[1] = {ins[0].c_str()};
    const char *outNames[1] = {outs[0].c_str()};
    OrtValue *outputTensor = nullptr;
    st = api->Run(session, nullptr, inNames, (const OrtValue *const *) &inputTensor, 1,
                  outNames, 1, &outputTensor);
    if (st != nullptr) {
        LOGE("推理失败：%s", api->GetErrorMessage(st));
        api->ReleaseStatus(st);
        api->ReleaseValue(inputTensor);
        env->ReleaseFloatArrayElements(jinput, inData, JNI_ABORT);
        return nullptr;
    }

    // 输出形状
    OrtTensorTypeAndShapeInfo *info = nullptr;
    api->GetTensorTypeAndShape(outputTensor, &info);
    size_t outRank = 0;
    api->GetDimensionsCount(info, &outRank);
    std::vector<int64_t> outShape(outRank);
    api->GetDimensions(info, outShape.data(), outRank);
    size_t total = 1;
    for (auto d : outShape) total *= (size_t) (d > 0 ? d : 0);
    jlong *outDims = env->GetLongArrayElements(joutdims, nullptr);
    const jsize outDimsLen = env->GetArrayLength(joutdims);
    for (jsize i = 0; i < outDimsLen; ++i) {
        outDims[i] = (i < (jsize) outRank) ? (jlong) outShape[i] : 0;
    }
    env->ReleaseLongArrayElements(joutdims, outDims, 0);

    float *outData = nullptr;
    api->GetTensorMutableData(outputTensor, (void **) &outData);
    jfloatArray result = env->NewFloatArray((jsize) total);
    if (result != nullptr && outData != nullptr) {
        env->SetFloatArrayRegion(result, 0, (jsize) total, outData);
    }
    api->ReleaseTensorTypeAndShapeInfo(info);
    api->ReleaseValue(outputTensor);
    api->ReleaseValue(inputTensor);
    env->ReleaseFloatArrayElements(jinput, inData, JNI_ABORT);
    return result;
}

extern "C" JNIEXPORT void JNICALL
Java_com_localrecord_app_OcrEngine_nativeFree(JNIEnv * /*env*/, jobject /*thiz*/, jlong jhandle) {
    auto *h = reinterpret_cast<OcrHandle *>(jhandle);
    if (h == nullptr) return;
    const OrtApi *api = h->api;
    if (h->det) api->ReleaseSession(h->det);
    if (h->rec) api->ReleaseSession(h->rec);
    if (h->mem) api->ReleaseMemoryInfo(h->mem);
    if (h->opts) api->ReleaseSessionOptions(h->opts);
    if (h->env) api->ReleaseEnv(h->env);
    delete h;
}
