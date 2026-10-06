"""核对 Gitee / GitHub 上的代码是不是最新。

**本脚本不需要任何令牌**：仓库是公开的，匿名 API 只读即可；
master 的 sha 直接用 `git ls-remote` 取（同样不需要认证）。

用法：python scripts/verify_remote.py
"""
import base64
import json
import subprocess
import urllib.request

GH = "https://api.github.com/repos/liuanping/local-record"
GT = "https://gitee.com/api/v5/repos/liuanping100/local-record"
GH_GIT = "git@github.com:liuanping/local-record.git"
GT_GIT = "https://gitee.com/liuanping100/local-record.git"
UA = {"User-Agent": "dsh"}


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
        return json.loads(r.read().decode("utf-8"))


def ls_remote(url):
    out = subprocess.run(["git", "ls-remote", url, "master"], capture_output=True,
                         text=True, encoding="utf-8", errors="ignore").stdout.strip()
    return out.split("\t")[0][:7] if out else "?"


def remote_file(api, path):
    d = get(f"{api}/contents/{path}?ref=master")
    return base64.b64decode(d["content"]).decode("utf-8", "ignore")


local = subprocess.run(["git", "rev-parse", "--short", "master"], capture_output=True,
                       text=True, encoding="utf-8").stdout.strip()
print("=== master 提交对比 ===")
print(f"  本地    : {local}")
for name, url in [("Gitee ", GT_GIT), ("GitHub", GH_GIT)]:
    sha = ls_remote(url)
    print(f"  {name}  : {sha}  {'✓ 一致' if sha == local else '✗ 不一致'}")

print("\n=== 关键文件是否含最新特征 ===")
checks = [
    ("android/app/build.gradle.kts", 'versionName = "3.1.6"', "版本号 3.1.6"),
    ("android/app/src/main/java/com/localrecord/app/MainActivity.kt", "去时间戳复制", "去时间戳复制按钮"),
    ("android/app/src/main/java/com/localrecord/app/MainActivity.kt", "enqueueTranslation", "逐句翻译队列"),
    ("android/app/src/main/java/com/localrecord/app/LlmEngine.kt", "TRANSLATE_TO_EN", "翻译提示词"),
    ("android/app/src/main/java/com/localrecord/app/ModelDownloader.kt", "Qwen3-0.6B", "Qwen3-0.6B 下载"),
    ("android/app/src/main/cpp/CMakeLists.txt", "llama", "llama.cpp 编译"),
    (".gitignore", "LocalRecord-android-3.1.6.apk", "APK 白名单"),
]
for path, needle, label in checks:
    row = f"  {label:<18}"
    for name, api in [("Gitee", GT), ("GitHub", GH)]:
        try:
            row += f"  {name} {'✓' if needle in remote_file(api, path) else '✗'}"
        except Exception as e:  # noqa: BLE001
            row += f"  {name} ?({type(e).__name__})"
    print(row)

print("\n=== 标签 ===")
for name, api in [("Gitee ", GT), ("GitHub", GH)]:
    try:
        tags = [t["name"] for t in get(f"{api}/tags")]
        print(f"  {name}: " + ", ".join(sorted(tags)))
    except Exception as e:  # noqa: BLE001
        print(f"  {name}: 查询失败 {type(e).__name__}")

st = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True,
                    encoding="utf-8").stdout.strip()
print("\n=== 本地工作区 ===")
print("  " + (st if st else "干净，无未提交改动 ✓"))
