"""校验打包产出的 zip 是否完整（开发辅助，不参与打包）。

用法::

    .venv\\Scripts\\python.exe scripts\\check_zip.py dist\\LocalRecord-windows-x64.zip

做两件事：
1. 读中央目录，统计条目数、顶层目录、关键文件是否都在；
2. 全量 CRC 校验（testzip）—— 如果 zip 是被中断的半成品，这一步会报出损坏条目。

> 打包第 8 步用 Windows 自带 bsdtar 压缩 3.8 GB，需要几分钟；如果中途被打断，
> zip 会缺少中央目录（Python 读它直接报 ``BadZipFile: File is not a zip file``）。
> 用本脚本可立刻判定，删掉重跑第 8 步即可（绿色版目录本身不受影响）。
"""
from __future__ import annotations

import sys
import time
import zipfile
from pathlib import Path

KEY_FILES = [
    "Local Record/Local Record.exe",
    "Local Record/config.yaml",
    "Local Record/_internal/_sounddevice_data/portaudio-binaries/libportaudio64bit.dll",
    "Local Record/storage/models/MiniCPM5-2B-Q4_K_M.gguf",
    "Local Record/storage/bin/llama-server/llama-server.exe",
    "Local Record/storage/asr/paraformer/model.int8.onnx",
    "Local Record/storage/asr/punct/model.onnx",
]


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1
                else "dist/LocalRecord-windows-x64.zip")
    if not path.is_file():
        print(f"[FAIL] 找不到 {path}")
        return 1
    size_gb = path.stat().st_size / (1024 ** 3)
    print(f"文件: {path}  ({size_gb:.2f} GB)")

    t0 = time.time()
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        print(f"条目数: {len(names)}")
        print(f"顶层目录: {sorted({n.split('/')[0] for n in names})}")
        for key in KEY_FILES:
            print(f"  {'OK  ' if key in names else 'MISS'} {key}")
        missing = [k for k in KEY_FILES if k not in names]
        print("CRC 全量校验中…")
        bad = z.testzip()
        print(f"损坏条目: {bad or '无（全部通过）'}")
    print(f"耗时 {time.time() - t0:.1f}s")
    if bad or missing:
        print("[FAIL] zip 不完整")
        return 1
    print("[PASS] zip 完整可用")
    return 0


if __name__ == "__main__":
    sys.exit(main())
