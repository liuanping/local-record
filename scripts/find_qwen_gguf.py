"""查 ModelScope 上 Qwen3 / Qwen3.5 的 GGUF 文件与大小，用于替换当前的 MiniCPM5-2B。"""
import json
import urllib.error
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 Chrome/120"}

REPOS = [
    "Qwen/Qwen3.5-4B-GGUF",
    "Qwen/Qwen3.5-4B",
    "Qwen/Qwen3-4B-GGUF",
    "Qwen/Qwen3-4B-Instruct-2507-GGUF",
    "Qwen/Qwen3-4B-Thinking-2507-GGUF",
    "unsloth/Qwen3.5-4B-GGUF",
    "lmstudio-community/Qwen3-4B-GGUF",
]


def list_files(repo):
    url = f"https://www.modelscope.cn/api/v1/models/{repo}/repo/files?Revision=master"
    try:
        raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25).read()
        data = json.loads(raw)
        return [(f["Path"], f["Size"]) for f in data["Data"]["Files"] if f["Type"] == "blob"]
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}"


def main():
    for repo in REPOS:
        r = list_files(repo)
        if isinstance(r, str):
            print(f"  [--] {repo}: {r}")
            continue
        gguf = [(p, s) for p, s in r if p.lower().endswith(".gguf")]
        print(f"  [OK] {repo}: 共 {len(r)} 文件；gguf {len(gguf)} 个")
        for p, s in gguf[:10]:
            print(f"        {p:<46} {s / 1e6:8.1f} MB")


if __name__ == "__main__":
    main()
