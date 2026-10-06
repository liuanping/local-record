"""建 3.1.8 发行版（两个平台）+ 上传 APK + 本地备份。

令牌只从环境变量读（$env:GH_TOKEN / $env:GT_TOKEN），绝不写进文件。
"""
import json
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path

R = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
V = "3.1.8"
APK = R / f"dist-android/LocalRecord-android-{V}.apk"
GH_TOKEN = os.environ.get("GH_TOKEN", "")
GT_TOKEN = os.environ.get("GT_TOKEN", "")
GT_API = "https://gitee.com/api/v5/repos/liuanping100/local-record"
GH_API = "https://api.github.com/repos/liuanping/local-record"

DESC = f"""## 本地录音 Android {V}

完全离线：录音转写（中英混说）+ 逐句翻译 + 录音库管理。

### 本版内容
- **修复翻译中英串扰**：简单词曾出现"半翻半留"（「头盔」被翻成「head 盔」），现在正确译成 helmet
- 提示词加入 few-shot 例子，并明确要求译文里**不允许保留另一种语言**
- 代码侧最多试三种问法（few-shot → 直译式 → "这个词的英文是什么"），每步都做语言检测
- 实测：头盔 → helmet ✓、会议纪要 → meeting minutes ✓、中英整句互译 ✓
- 安装包 40.77MB（arm64）

### 安装
下载附件 APK → 手机点击安装 → 首次打开自动下载模型（转写 514MB + 翻译 397MB，建议 WiFi）

识别与翻译全程在手机本地完成，不联网、不上传任何数据。MIT License"""

print(f"APK: {APK.name}  {APK.stat().st_size/1e6:.2f} MB")

# ---------- Gitee ----------
print("\n=== Gitee 发行版 ===")
try:
    body = json.dumps({"access_token": GT_TOKEN, "tag_name": f"v{V}",
                       "name": f"Android {V}（修翻译中英串扰）",
                       "target_commitish": "master", "body": DESC}).encode("utf-8")
    req = urllib.request.Request(f"{GT_API}/releases", data=body,
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    rel = json.loads(urllib.request.urlopen(req, timeout=60).read().decode("utf-8"))
    rid = rel["id"]
    print(f"  已建 release id={rid}")
    out = subprocess.run(["curl.exe", "-sS", "-X", "POST",
                          f"{GT_API}/releases/{rid}/attach_files",
                          "-F", f"access_token={GT_TOKEN}", "-F", f"file=@{APK}"],
                         capture_output=True, text=True, encoding="utf-8", errors="ignore").stdout
    j = json.loads(out)
    print("  附件 " + j["name"] + f"  {j['size']/1e6:.2f} MB")
    print("  " + j["browser_download_url"])
except Exception as e:  # noqa: BLE001
    print(f"  ✗ {type(e).__name__}: {e}")

# ---------- GitHub ----------
print("\n=== GitHub 发行版 ===")
try:
    hdr = {"Authorization": f"token {GH_TOKEN}", "User-Agent": "dsh",
           "Accept": "application/vnd.github+json"}
    body = json.dumps({"tag_name": f"v{V}", "name": f"Android {V}（修翻译中英串扰）",
                       "draft": False, "prerelease": False, "body": DESC}).encode("utf-8")
    req = urllib.request.Request(f"{GH_API}/releases", data=body, headers=hdr)
    rel = json.loads(urllib.request.urlopen(req, timeout=60).read().decode("utf-8"))
    up = rel["upload_url"].split("{")[0]
    out = subprocess.run(["curl.exe", "-sS", "-w", "\nHTTP:%{http_code}", "-X", "POST",
                          "-H", f"Authorization: token {GH_TOKEN}",
                          "-H", "Content-Type: application/octet-stream",
                          "-H", "User-Agent: dsh", "--data-binary", f"@{APK}",
                          f"{up}?name=LocalRecord-android-{V}.apk"],
                         capture_output=True, text=True, encoding="utf-8", errors="ignore").stdout
    code = [l for l in out.splitlines() if l.startswith("HTTP:")]
    print("  " + (code[0] if code else "?"))
    rel2 = json.loads(urllib.request.urlopen(
        urllib.request.Request(f"{GH_API}/releases/tags/v{V}", headers=hdr), timeout=40).read().decode())
    for a in rel2.get("assets", []):
        print(f"  附件 {a['name']}  {a['size']/1e6:.2f} MB")
        print("  " + a["browser_download_url"])
except Exception as e:  # noqa: BLE001
    print(f"  ✗ {type(e).__name__}: {e}")

# ---------- 本地备份 ----------
print("\n=== 本地备份 ===")
bk = Path(rf"E:\android-dev\LocalRecord-backup-{V}")
if bk.exists():
    shutil.rmtree(bk)
bk.mkdir(parents=True)
for f in [APK, R / "SNAPSHOT-INFO.txt", R / "android/README-android.md", R / "README.md"]:
    shutil.copyfile(f, bk / Path(f).name)
lines = [f"本地录音 Android {V} 备份",
         f"Gitee  https://gitee.com/liuanping100/local-record/releases/download/v{V}/LocalRecord-android-{V}.apk",
         f"GitHub https://github.com/liuanping/local-record/releases/download/v{V}/LocalRecord-android-{V}.apk",
         ""]
sha = subprocess.run(["certutil", "-hashfile", str(bk / APK.name), "SHA256"],
                     capture_output=True, text=True, encoding="utf-8").stdout
lines.append("APK SHA256 = " + ("".join(sha.splitlines()[1:2]).replace(" ", "")))
(bk / "MANIFEST.txt").write_text("\n".join(lines), encoding="utf-8")
for f in sorted(bk.iterdir()):
    print(f"  {f.name:<32} {f.stat().st_size/1e6:8.2f} MB")
