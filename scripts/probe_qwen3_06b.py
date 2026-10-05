"""探测 ModelScope 上 Qwen3-0.6B GGUF 的文件与大小（匿名 API，不需要令牌）。"""
import json
import urllib.request

UA = {"User-Agent": "Mozilla/5.0"}
CANDIDATES = [
    "Qwen/Qwen3-0.6B-GGUF",
    "unsloth/Qwen3-0.6B-GGUF",
    "QuantFactory/Qwen3-0.6B-GGUF",
    "modelscope/Qwen3-0.6B-GGUF",
]


def list_files(repo):
    url = f"https://www.modelscope.cn/api/v1/models/{repo}/repo/files?Revision=master&Recursive=true"
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=40) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"
    files = (data.get("Data") or {}).get("Files") or []
    return [(f.get("Path"), f.get("Size", 0)) for f in files], None


for repo in CANDIDATES:
    files, err = list_files(repo)
    print(f"\n=== {repo} ===")
    if err:
        print(f"  ✗ {err}")
        continue
    gguf = [(p, s) for p, s in files if p.lower().endswith(".gguf")]
    if not gguf:
        print(f"  仓库存在但没有 gguf（共 {len(files)} 个文件）")
        for p, s in files[:5]:
            print(f"    {p}  {s/1e6:.1f} MB")
        continue
    for p, s in sorted(gguf, key=lambda x: x[1]):
        print(f"  {p:<44} {s/1e6:8.1f} MB")
