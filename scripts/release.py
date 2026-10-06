"""建发行版 + 上传 APK + 本地备份。用法：python scripts/release.py 3.1.9

令牌只从环境变量读（$env:GH_TOKEN / $env:GT_TOKEN），绝不写进文件。
"""
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

V = sys.argv[1] if len(sys.argv) > 1 else "3.1.9"
R = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
APK = R / f"dist-android/LocalRecord-android-{V}.apk"
GH_TOKEN = os.environ.get("GH_TOKEN", "")
GT_TOKEN = os.environ.get("GT_TOKEN", "")
GT_API = "https://gitee.com/api/v5/repos/liuanping100/local-record"
GH_API = "https://api.github.com/repos/liuanping/local-record"

TITLE = f"Android {V}（修复每句都翻成同一个词）"
DESC = f"""## 本地录音 Android {V}

完全离线：录音转写（中英混说）+ 逐句翻译 + 录音库管理。

### 本版重点：修复"每句都翻成同一个词"
- **根因**：本地推理层每次生成前没有清空上下文（KV 缓存），
  第二次翻译会接在上一次的问+答后面 → 第一句答了 helmet，后面几句被带着继续 helmet
- 现在每次生成前都会清空上下文，各句完全独立
- 提示词回到简单版（单例子）；短词走专用"词典式"提示；指令只放系统提示
- 实测：头盔→helmet、整句→完整英文句子、英文句→中文，全部正确且不再互相干扰
- 顺带变快：原英文句 16 秒（反复重试）→ 现在 3.6 秒（一次就对）
- 安装包 40.77MB（arm64）

### 安装
下载附件 APK → 手机点击安装 → 首次打开自动下载模型（转写 514MB + 翻译 397MB，建议 WiFi）

识别与翻译全程在手机本地完成，不联网、不上传任何数据。MIT License"""

print(f"APK: {APK.name}  {APK.stat().st_size/1e6:.2f} MB")

print("\n=== Gitee 发行版 ===")
try:
    body = json.dumps({"access_token": GT_TOKEN, "tag_name": f"v{V}", "name": TITLE,
                       "target_commitish": "master", "body": DESC}).encode("utf-8")
    req = urllib.request.Request(f"{GT_API}/releases", data=body,
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    rid = json.loads(urllib.request.urlopen(req, timeout=60).read().decode("utf-8"))["id"]
    print(f"  已建 release id={rid}")
    out = subprocess.run(["curl.exe", "-sS", "-X", "POST", f"{GT_API}/releases/{rid}/attach_files",
                          "-F", f"access_token={GT_TOKEN}", "-F", f"file=@{APK}"],
                         capture_output=True, text=True, encoding="utf-8", errors="ignore").stdout
    j = json.loads(out)
    print("  附件 " + j["name"] + f"  {j['size']/1e6:.2f} MB")
    print("  " + j["browser_download_url"])
except Exception as e:  # noqa: BLE001
    print(f"  ✗ {type(e).__name__}: {e}")

print("\n=== GitHub 发行版 ===")
try:
    hdr = {"Authorization": f"token {GH_TOKEN}", "User-Agent": "dsh",
           "Accept": "application/vnd.github+json"}
    body = json.dumps({"tag_name": f"v{V}", "name": TITLE, "draft": False,
                       "prerelease": False, "body": DESC}).encode("utf-8")
    rel = json.loads(urllib.request.urlopen(
        urllib.request.Request(f"{GH_API}/releases", data=body, headers=hdr), timeout=60).read().decode())
    up = rel["upload_url"].split("{")[0]
    out = subprocess.run(["curl.exe", "-sS", "-w", "\nHTTP:%{http_code}", "-X", "POST",
                          "-H", f"Authorization: token {GH_TOKEN}",
                          "-H", "Content-Type: application/octet-stream",
                          "-H", "User-Agent: dsh", "--data-binary", f"@{APK}",
                          f"{up}?name={APK.name}"],
                         capture_output=True, text=True, encoding="utf-8", errors="ignore").stdout
    print("  " + ([l for l in out.splitlines() if l.startswith("HTTP:")] or ["?"])[0])
    rel2 = json.loads(urllib.request.urlopen(urllib.request.Request(
        f"{GH_API}/releases/tags/v{V}", headers=hdr), timeout=40).read().decode())
    for a in rel2.get("assets", []):
        print(f"  附件 {a['name']}  {a['size']/1e6:.2f} MB")
        print("  " + a["browser_download_url"])
except Exception as e:  # noqa: BLE001
    print(f"  ✗ {type(e).__name__}: {e}")

print("\n=== 本地备份 ===")
bk = Path(rf"E:\android-dev\LocalRecord-backup-{V}")
if bk.exists():
    shutil.rmtree(bk)
bk.mkdir(parents=True)
for f in [APK, R / "SNAPSHOT-INFO.txt", R / "android/README-android.md", R / "README.md"]:
    shutil.copyfile(f, bk / Path(f).name)
import hashlib
sha = hashlib.sha256((bk / APK.name).read_bytes()).hexdigest().upper()
(bk / "MANIFEST.txt").write_text("\n".join([
    f"本地录音 Android {V} 备份",
    f"Gitee  https://gitee.com/liuanping100/local-record/releases/download/v{V}/{APK.name}",
    f"GitHub https://github.com/liuanping/local-record/releases/download/v{V}/{APK.name}",
    "", f"APK SHA256 = {sha}"]), encoding="utf-8")
for f in sorted(bk.iterdir()):
    print(f"  {f.name:<34} {f.stat().st_size/1e6:8.2f} MB")
print(f"  SHA256 = {sha}")
