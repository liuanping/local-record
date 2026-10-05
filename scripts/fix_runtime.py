#!/usr/bin/env python3
"""打包后运行时 DLL 修复（Windows 版坑 4a / 4b 对应）。

坑 4a 对应（cv2 / MSVC 运行库）：
  cv2.pyd 等原生扩展依赖 vcruntime140.dll / vcruntime140_1.dll /
  msvcp140.dll。把构建环境里的副本复制到 _internal/（打包有时会漏或
  版本不对）。对应 macOS 版"cv2 加载失败"的 Windows 变体。

坑 4b 对应（OpenSSL）：
  conda-forge Python 的 _ssl.pyd 动态链接 libssl-3-x64.dll /
  libcrypto-3-x64.dll。若 _internal 里被收集了别的（旧版）OpenSSL DLL，
  用构建环境 Library/bin 下的官方副本覆盖（OpenSSL 3.x ABI 兼容，
  cv2 等其它组件同样可用）。python.org 官方 Python 把 OpenSSL 静态
  链进 _ssl.pyd，找不到源文件属正常，跳过即可。

用法: python scripts/fix_runtime.py --app "dist/Local Record"
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

MSVC_DLLS = ["vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll"]
OPENSSL_DLLS = ["libssl-3-x64.dll", "libcrypto-3-x64.dll"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--app", required=True, help="打包产物目录，如 dist/Local Record")
    args = ap.parse_args()

    internal = Path(args.app) / "_internal"
    if not internal.is_dir():
        print(f"[FAIL] 找不到 _internal 目录: {internal}")
        return 1

    # 构建环境基础解释器的前缀（venv → 其基础 Python；conda env → env 根）
    base_prefix = Path(sys._base_executable).resolve().parent
    candidates = [
        base_prefix,
        base_prefix / "Library" / "bin",   # conda 布局
        base_prefix / "bin",
        base_prefix / "DLLs",              # python.org 布局
    ]

    def find(dll: str) -> Path | None:
        for c in candidates:
            p = c / dll
            if p.is_file():
                return p
        return None

    copied = 0
    for dll in MSVC_DLLS + OPENSSL_DLLS:
        src = find(dll)
        dst = internal / dll
        if src is not None:
            shutil.copy2(src, dst)
            size = dst.stat().st_size / 1024
            print(f"[fix] {dll}: {src} -> {dst} ({size:.0f} KiB)")
            copied += 1
        elif dst.is_file():
            print(f"[info] {dll}: _internal 已有副本，构建环境无源文件，保留现有副本")
        else:
            print(f"[warn] {dll}: 构建环境与 _internal 均不存在"
                  "（python.org 静态链接 OpenSSL / 系统自带 VC 运行库时属正常）")

    # 附加检查：_ssl.pyd 是否进了包（没进的话 ssl 必然用不到，构建应中止）
    ssl_pyd = internal / "_ssl.pyd"
    if ssl_pyd.is_file():
        print(f"[info] _ssl.pyd 已收集（{ssl_pyd.stat().st_size / 1024:.0f} KiB）")
    else:
        print("[warn] _internal 里没有 _ssl.pyd —— 打包配置有问题，最终自检会失败")

    print(f"[OK] 运行时修复完成（复制 {copied} 个 DLL）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
