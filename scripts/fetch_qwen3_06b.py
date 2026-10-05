"""带断点续传 + 重试的模型下载（ModelScope 主源，hf-mirror 兜底），下完校验字节数。"""
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

OUT = Path(r"E:\android-dev\models\Qwen3-0.6B-Q4_K_M.gguf")
EXPECT = 396_705_472
URLS = [
    "https://www.modelscope.cn/models/unsloth/Qwen3-0.6B-GGUF/resolve/master/Qwen3-0.6B-Q4_K_M.gguf",
    "https://hf-mirror.com/unsloth/Qwen3-0.6B-GGUF/resolve/main/Qwen3-0.6B-Q4_K_M.gguf",
]
UA = {"User-Agent": "Mozilla/5.0"}

OUT.parent.mkdir(parents=True, exist_ok=True)
for attempt in range(1, 41):
    have = OUT.stat().st_size if OUT.exists() else 0
    if have >= EXPECT:
        break
    url = URLS[(attempt - 1) // 8 % len(URLS)]        # 每 8 次换一个源
    headers = dict(UA)
    if have:
        headers["Range"] = f"bytes={have}-"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=90) as r:
            mode = "ab" if have and r.status == 206 else "wb"
            if mode == "wb":
                have = 0
            t0 = time.time()
            with open(OUT, mode) as f:
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    f.write(b)
                    have += len(b)
            sp = have / max(time.time() - t0, 0.1) / 1e6
            print(f"[{attempt}] {url.split('/')[2]} 追加到 {have/1e6:.1f}/{EXPECT/1e6:.1f} MB（{sp:.1f} MB/s）", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[{attempt}] 出错：{type(e).__name__}: {e}（已有 {have/1e6:.1f} MB，继续续传）", flush=True)
        time.sleep(2)

size = OUT.stat().st_size if OUT.exists() else 0
print(f"最终大小 {size} 字节（期望 {EXPECT}）→ {'OK ✓' if size == EXPECT else '不完整 ✗'}")
sys.exit(0 if size == EXPECT else 1)
