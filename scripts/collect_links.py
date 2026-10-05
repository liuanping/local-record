"""汇总项目相关的全部链接，并逐个验证可用性。

⚠️ 令牌一律从环境变量读取，绝不能写死在文件里（曾经犯过这个错，被 GitHub 密钥扫描拦下）：
    $env:GH_TOKEN = "..."   # GitHub personal access token
    $env:GT_TOKEN = "..."   # Gitee personal access token
    python scripts/collect_links.py
"""
import datetime
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GH_TOKEN = os.environ.get("GH_TOKEN", "")
GT_TOKEN = os.environ.get("GT_TOKEN", "")
UA = {"User-Agent": "Mozilla/5.0"}


def check(url, headers=None, timeout=40):
    """返回 (状态码 或 异常名, 大小MB 或 None)；只做 HEAD，不下载内容"""
    try:
        req = urllib.request.Request(url, headers={**UA, **(headers or {})}, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            n = r.headers.get("Content-Length")
            return r.status, (float(n) / 1e6 if n and n.isdigit() else None)
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:  # noqa: BLE001
        return type(e).__name__, None


links = []


def add(group, name, url, headers=None, verify=True):
    st, size = check(url, headers) if verify else ("(未测)", None)
    links.append((group, name, url, st, size))
    extra = f"  ({size:.2f} MB)" if size else ""
    print(f"  [{st}] {name}\n        {url}{extra}")


print("=== Gitee ===")
add("Gitee", "仓库主页", "https://gitee.com/liuanping100/local-record")
add("Gitee", "发行版页面", "https://gitee.com/liuanping100/local-record/releases/tag/v3.0.1")
add("Gitee", "APK 下载直链",
    "https://gitee.com/liuanping100/local-record/releases/download/v3.0.1/LocalRecord-android-3.0.1.apk")
add("Gitee", "源码包 zip", "https://gitee.com/liuanping100/local-record/repository/archive/v3.0.1.zip")
add("Gitee", "README", "https://gitee.com/liuanping100/local-record/blob/master/README.md")
add("Gitee", "克隆 HTTPS", "https://gitee.com/liuanping100/local-record.git", verify=False)
add("Gitee", "克隆 SSH", "git@gitee.com:liuanping100/local-record.git", verify=False)

print("\n=== GitHub（本机被墙，改用 API 验证）===")
if GH_TOKEN:
    h = {"Authorization": f"token {GH_TOKEN}", "User-Agent": "dsh",
         "Accept": "application/vnd.github+json"}
    add("GitHub", "仓库 API", "https://api.github.com/repos/liuanping/local-record", h)
    add("GitHub", "发行版 API", "https://api.github.com/repos/liuanping/local-record/releases/tags/v3.0.1", h)
else:
    print("  （未设置 GH_TOKEN，跳过 GitHub 验证）")
add("GitHub", "仓库主页", "https://github.com/liuanping/local-record", verify=False)
add("GitHub", "发行版页面", "https://github.com/liuanping/local-record/releases/tag/v3.0.1", verify=False)
add("GitHub", "APK 下载直链",
    "https://github.com/liuanping/local-record/releases/download/v3.0.1/LocalRecord-android-3.0.1.apk",
    verify=False)
add("GitHub", "源码包 zip",
    "https://github.com/liuanping/local-record/archive/refs/tags/v3.0.1.zip", verify=False)

print("\n=== App 自动下载的模型 ===")
dl = (ROOT / "android/app/src/main/java/com/localrecord/app/ModelDownloader.kt").read_text(encoding="utf-8")
for m in re.finditer(r'ms\("([^"]+)",\s*"([^"]+)"\)', dl):
    repo, fn = m.group(1), m.group(2)
    add("模型", fn, f"https://www.modelscope.cn/models/{repo}/resolve/master/{fn}")
add("模型", "silero_vad.onnx",
    "https://hf-mirror.com/deepghs/silero-vad-onnx/resolve/main/silero_vad.onnx")

out = ["# 项目链接汇总", "",
       f"生成时间：{datetime.datetime.now():%Y-%m-%d %H:%M}（脚本：`scripts/collect_links.py`）", ""]
for g in ("Gitee", "GitHub", "模型"):
    rows = [x for x in links if x[0] == g]
    if not rows:
        continue
    out += [f"## {g}", "", "| 用途 | 链接 | 实测 |", "|---|---|---|"]
    for _, name, url, st, size in rows:
        mark = f"✓ {size:.1f} MB" if st == 200 and size else ("✓" if st == 200 else str(st))
        out.append(f"| {name} | <{url}> | {mark} |")
    out.append("")
(ROOT / "docs/链接汇总.md").write_text("\n".join(out), encoding="utf-8")
print(f"\n已写入 docs/链接汇总.md，共 {len(links)} 条")
