"""更新 docs/链接汇总.md（用实测过的链接）+ 给 README 加"下载安装"一节。"""
from pathlib import Path

ROOT = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
GH = "https://github.com/liuanping/local-record"
GT = "https://gitee.com/liuanping100/local-record"
VER = "v3.0.1"

doc = f"""# 项目链接汇总

> 全部链接都已实测（Gitee / 模型 / hf-mirror 返回 200 ✓；
> GitHub 因本机网络被墙无法直接请求，但已通过 GitHub API 确认仓库、分支、发行版与附件都存在 ✓）。

## 一、给用户下载（最重要）

| 渠道 | 下载 APK | 发行版页面 |
|---|---|---|
| **Gitee**（国内直连，不用翻墙）⭐ | [{VER}/LocalRecord-android-3.0.1.apk]({GT}/releases/download/{VER}/LocalRecord-android-3.0.1.apk) · 35.92 MiB ✓ | [{VER}]({GT}/releases/tag/{VER}) |
| GitHub | [LocalRecord-android-3.0.1.apk]({GH}/releases/download/{VER}/LocalRecord-android-3.0.1.apk) · 35.92 MiB | [{VER}]({GH}/releases/tag/{VER}) |

## 二、源码仓库

| 用途 | Gitee | GitHub |
|---|---|---|
| 仓库主页 | <{GT}> | <{GH}> |
| README | [README.md]({GT}/blob/master/README.md) | [README.md]({GH}/blob/master/README.md) |
| 克隆（HTTPS） | `{GT}.git` | `{GH}.git` |
| 克隆（SSH） | `git@gitee.com:liuanping100/local-record.git` | `git@github.com:liuanping/local-record.git` |
| 源码包（tar/zip） | [repository/archive/{VER}.zip]({GT}/repository/archive/{VER}.zip) ✓ | [archive/{VER}.zip]({GH}/archive/refs/tags/{VER}.zip) |
| 全部版本 | — | [{VER} 标签]({GH}/tags) |

## 三、App 自动下载的模型（ModelScope 主源，全部实测 200 ✓）

| 用途 | 地址 |
|---|---|
| 语音识别（Paraformer 中英混说）227MB | <https://www.modelscope.cn/models/pengzhendong/sherpa-onnx-paraformer-zh/resolve/master/model.int8.onnx> |
| 语音词表 | <https://www.modelscope.cn/models/pengzhendong/sherpa-onnx-paraformer-zh/resolve/master/tokens.txt> |
| 标点（CT-Transformer）285MB | <https://www.modelscope.cn/models/csukuangfj/sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12/resolve/master/model.onnx> |
| 标点词表 | <https://www.modelscope.cn/models/csukuangfj/sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12/resolve/master/tokens.json> |
| OCR 检测（PP-OCRv6 det）59MB | <https://www.modelscope.cn/models/PaddlePaddle/PP-OCRv6_medium_det_onnx/resolve/master/inference.onnx> |
| OCR 识别（PP-OCRv6 rec）73MB | <https://www.modelscope.cn/models/PaddlePaddle/PP-OCRv6_medium_rec_onnx/resolve/master/inference.onnx> |
| 断句（Silero VAD）2.3MB ✓ | <https://hf-mirror.com/deepghs/silero-vad-onnx/resolve/main/silero_vad.onnx> |

## 四、仓库内的文档

| 文件 | 说明 |
|---|---|
| [README.md](../README.md) | 项目介绍、功能、构建、权限、隐私 |
| [LICENSE](../LICENSE) | MIT 许可 |
| [SNAPSHOT-INFO.txt](../SNAPSHOT-INFO.txt) | 自包含源码快照说明（含重新编译步骤） |
| [android/README-android.md](../android/README-android.md) | Android 版详细说明 + 完整版本记录（1.2.0 → 3.0.1） |
| [docs/发布到Gitee.md](发布到Gitee.md) | Gitee 发布步骤 |
| [docs/发布到GitHub.md](发布到GitHub.md) | GitHub 发布步骤（含被墙时的 SSH over 443 方案） |
| [docs/仓库描述.md](仓库描述.md) | 可直接复制的简介 / 详细描述 / Topics / 发行版说明 |

## 五、日常更新一条命令推两边

```bash
git add -A && git commit -m "fix: 改了什么"
git push                      # Gitee + GitHub 同时更新
git tag v3.0.2 && git push origin v3.0.2    # 标签也两边一起
```
"""
(ROOT / "docs/链接汇总.md").write_text(doc, encoding="utf-8")
print("已写入 docs/链接汇总.md ✓")

# README 加"下载安装"
readme = ROOT / "README.md"
r = readme.read_text(encoding="utf-8")
if "## 下载安装" not in r:
    block = f"""## 下载安装

| 渠道 | 下载 APK | 说明 |
|---|---|---|
| **Gitee**（国内直连）⭐ | [LocalRecord-android-3.0.1.apk]({GT}/releases/download/{VER}/LocalRecord-android-3.0.1.apk) | [发行版页面]({GT}/releases/tag/{VER}) |
| GitHub | [LocalRecord-android-3.0.1.apk]({GH}/releases/download/{VER}/LocalRecord-android-3.0.1.apk) | [发行版页面]({GH}/releases/tag/{VER}) |

安装：下载后点击安装（首次可能提示"未知来源"，允许即可）；首次打开会自动下载识别模型（约 634MB，建议 WiFi）。

源码仓库：[Gitee]({GT}) · [GitHub]({GH})　|　完整链接清单见 [docs/链接汇总.md](docs/链接汇总.md)

"""
    anchor = "## 功能"
    assert anchor in r
    r = r.replace(anchor, block + anchor, 1)
    readme.write_text(r, encoding="utf-8")
    print("README 已加入「下载安装」一节 ✓")
else:
    print("README 已有下载安装一节，跳过")
