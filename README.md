# 本地录音（Local Record）

一个**完全离线**的 Android 录音转写 + 图片文字识别 App。录音、语音识别、标点、OCR **全部在手机本地完成**，不联网、不上传任何数据。

> 本项目**不含本地大模型**（3.0.0 起移除）。之前版本支持"会议纪要 / 问答"（MiniCPM5 / Qwen3.5），
> 相关代码仍在 git 历史里（`android-v2.5.2` 及更早的标签），如需可自行检出。

## 下载安装

| 渠道 | 下载 APK | 发行版页面 |
|---|---|---|
| **Gitee**（国内直连）⭐ | [LocalRecord-android-3.1.6.apk](https://gitee.com/liuanping100/local-record/releases/download/v3.1.6/LocalRecord-android-3.1.6.apk) | [v3.1.6](https://gitee.com/liuanping100/local-record/releases/tag/v3.1.6) |
| GitHub | [LocalRecord-android-3.1.6.apk](https://github.com/liuanping/local-record/releases/download/v3.1.6/LocalRecord-android-3.1.6.apk) | [v3.1.6](https://github.com/liuanping/local-record/releases/tag/v3.1.6) |

安装：下载后点击安装（首次可能提示"未知来源"，允许即可）；首次打开会自动下载模型（转写+标点+断句约 514MB，
翻译模型 397MB，建议 WiFi）。

## 功能

| 页面 | 功能 |
|---|---|
| **语音** | 录音（切后台继续录）· 实时转写（中英混说）· 自动断句（神经网络 VAD）· 自动标点 · 自动滚到最新 / 可拖动进度 · 一键复制 |
| **录音库** | 导入音频（mp3 / wav / m4a / aac / ogg / flac / amr）· 播放（可拖进度）· 删除 · 显示文件路径（可复制）· 导入后自动转写 |
| **逐句翻译** | 每识别出一句就立刻翻译（中文→英文 / 英文→中文），原文与译文并列显示，底部开关可关闭 |

其他：深色主题 · 应用图标 · 首次运行自动下载模型（ModelScope 主源，失败回退 hf-mirror）· 断点续传 · 后台下载。

翻译使用 **Qwen3-0.6B（Q4_K_M，397MB）** 在手机本地逐句翻译，不联网、不上传。

## 体积与模型

* APK：**约 41 MB**（只含 arm64-v8a；含本地翻译用的 llama.cpp）
* 需要自动下载的模型合计约 **911 MB**（转写相关 514MB + 翻译模型 397MB）：

| 用途 | 模型 | 大小 |
|---|---|---|
| 语音识别 | Paraformer zh int8（中英混说） | 227 MB |
| 标点 | CT-Transformer | 285 MB |
| 断句 | Silero VAD（神经网络） | 2.3 MB |
| 翻译（Qwen3-0.6B Q4_K_M） | 中英互译，本地逐句翻译 | 397 MB |

模型全部从 **ModelScope** 下载（失败自动回退 hf-mirror），不打包进 APK，所以安装包很小、模型可独立更新。

## 技术栈

* Kotlin + Jetpack Compose（Material 3）
* 语音识别 / 标点 / VAD：[sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)
* OCR：PP-OCRv6（ONNX Runtime）
* 音频解码：Android `MediaExtractor` + `MediaCodec`（手机能播放的格式都能转写）
* 音频处理：自研能量 + 神经网络双 VAD、谐波性 / 过零率 / 信噪比判据（都带 JVM 单元测试）

## 构建

需要 JDK 17、Android SDK（NDK + CMake）、Gradle 8.9。

```bash
# 只出 arm64（发布用，体积最小）
gradle -p android assembleRelease

# 同时出 x86_64（模拟器验证用）
gradle -p android -Pemu assembleDebug

# 单元测试（不需要设备）
gradle -p android :app:testDebugUnitTest
```

细节（工具链路径、模型放置目录、自检命令）见 [android/README-android.md](android/README-android.md) 与 [SNAPSHOT-INFO.txt](SNAPSHOT-INFO.txt)。

## 权限

| 权限 | 用途 |
|---|---|
| `RECORD_AUDIO` | 录音（必需；未授权时 App 会引导去设置里开） |
| `POST_NOTIFICATIONS` | 显示"正在录音 / 正在下载"通知 |
| `INTERNET` / `ACCESS_NETWORK_STATE` | **仅用于下载模型**，识别过程完全不联网 |
| `FOREGROUND_SERVICE`(+MICROPHONE/DATA_SYNC) | 切后台后继续录音 / 继续下载 |
| `WAKE_LOCK` | 下载时不因锁屏中断 |

## 隐私

* 录音、转写、OCR 全部在手机本地计算，**没有任何数据上传**
* 唯一的网络请求是**从 ModelScope 下载模型文件**
* 录音文件保存在 `内部存储/Android/data/com.localrecord.app/files/recordings/`，卸载即删除

## 许可证

[MIT](LICENSE)。模型各自遵循其原始许可（sherpa-onnx：Apache-2.0；PP-OCRv6：Apache-2.0；Silero VAD：MIT）。
