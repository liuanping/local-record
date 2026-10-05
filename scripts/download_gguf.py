"""从 ModelScope 下载 GGUF 候选模型（开发辅助）。

用法::

    .venv\\Scripts\\python.exe scripts\\download_gguf.py                 # 下载默认候选
    .venv\\Scripts\\python.exe scripts\\download_gguf.py <repo> <文件名>   # 只下指定文件
    .venv\\Scripts\\python.exe scripts\\download_gguf.py --dest storage/models <repo> <文件名>

实现说明：ModelScope 的 ``/repo?FilePath=`` 接口对没有浏览器头的请求直接返 403，
对 ``modelscope`` 客户端某些版本又会卡在 0 字节，所以这里直接用带
User-Agent + Referer 的 HTTP 下载（会 302 到 cdn-lfs-cn-1.modelscope.cn），
实测 6~7 MB/s，支持 Range 断点续传。

默认落到 ``build/models-test/``，不塞进 ``storage/models``，避免把打包体积撑大；
选定后再拷进 ``storage/models/`` 并改 config.yaml 的 ``model.filename``。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DEST = ROOT / "build" / "models-test"

# (repo, 文件名) —— 只比"2B 档"：你点名的面壁 MiniCPM5-2B + 同门 Qwen3-1.7B 作下限参考
DEFAULT = [
    ("OpenBMB/MiniCPM5-2B-gguf", "MiniCPM5-2B-Q4_K_M.gguf"),
    ("unsloth/Qwen3-1.7B-GGUF", "Qwen3-1.7B-Q4_K_M.gguf"),
]

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Referer": "https://www.modelscope.cn/",
}


def human(n: float) -> str:
    return f"{n / 1024 ** 3:.2f} GB" if n > 1024 ** 3 else f"{n / 1024 ** 2:.0f} MB"


def url_for(repo: str, filename: str) -> str:
    return (f"https://www.modelscope.cn/api/v1/models/{repo}/repo"
            f"?Revision=master&FilePath={filename}")


def download(repo: str, filename: str, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / filename
    timeout = httpx.Timeout(30.0, read=120.0)
    with httpx.Client(follow_redirects=True, headers=HEADERS, timeout=timeout) as c:
        total = int(c.head(url_for(repo, filename)).headers.get("content-length", 0))
        if out.is_file() and total and out.stat().st_size == total:
            print(f"[skip] {filename} 已存在（{human(total)}）", flush=True)
            return out
        have = out.stat().st_size if out.is_file() else 0
        if have and total and have < total:
            print(f"[续传] {filename} 从 {human(have)} 继续", flush=True)
        else:
            have = 0
        print(f"[get ] {repo} / {filename}  {human(total)}", flush=True)
        headers = {"Range": f"bytes={have}-"} if have else {}
        t0 = time.monotonic()
        last = 0.0
        with c.stream("GET", url_for(repo, filename), headers=headers) as r:
            r.raise_for_status()
            with open(out, "ab" if have else "wb") as f:
                done = have
                for chunk in r.iter_bytes(1024 * 512):
                    f.write(chunk)
                    done += len(chunk)
                    now = time.monotonic()
                    if now - last > 5:
                        last = now
                        speed = (done - have) / max(0.01, now - t0) / 1024 ** 2
                        pct = done / total * 100 if total else 0
                        print(f"       {pct:5.1f}%  {human(done)}  {speed:.1f} MB/s",
                              flush=True)
    size = out.stat().st_size
    if total and size != total:
        raise RuntimeError(f"大小不符：{size} != {total}")
    print(f"[done] {out.name}  {human(size)}  用时 {time.monotonic() - t0:.0f}s",
          flush=True)
    return out


def main() -> int:
    args = sys.argv[1:]
    dest = DEFAULT_DEST
    if "--dest" in args:
        i = args.index("--dest")
        dest = Path(args[i + 1])
        if not dest.is_absolute():
            dest = ROOT / dest
        args = args[:i] + args[i + 2:]
    pairs = DEFAULT
    if args:
        if len(args) % 2:
            print("参数应为成对：<repo> <文件名> ...")
            return 2
        pairs = [(args[i], args[i + 1]) for i in range(0, len(args), 2)]
    ok = 0
    for repo, name in pairs:
        try:
            download(repo, name, dest)
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"[FAIL] {repo}/{name}: {type(e).__name__}: {e}", flush=True)
    print(f"\n完成 {ok}/{len(pairs)}，目录：{dest}")
    return 0 if ok == len(pairs) else 1


if __name__ == "__main__":
    sys.exit(main())
