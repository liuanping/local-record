#!/usr/bin/env python3
"""冻结环境导入自检（Windows 版）。

复刻 macOS 复现指南第 8 节的做法：用构建机 python 把 sys.path 设为

    [<_internal>, stdlib, DLLs, site-packages]

模拟冻结 app 的导入环境。注意：**不要**把 exe 同级目录加进 sys.path——
冻结版里那里只有 storage/，不可导入（对应 macOS 版"不要加 Resources"）。

逐项导入关键模块，并检查其 __file__ 落在 _internal 内（防止误加载
site-packages 造成"假通过"）。

--fix-cv2：cv2 导入失败时，把 _internal/cv2/__init__.py 替换为引导模块
（直接加载同目录 cv2.abi3.pyd / cv2.pyd / cv2.abi3.so；模块名必须叫
"cv2" 才能对上 PyInit_cv2 符号），然后重试。对应 macOS 坑 1
（cv2 loader 递归）的 Windows 变体。

坑 4d 对应：同时检查 sounddevice 的 PortAudio DLL 是否被收集
（麦克风采集在打包版里必须依赖它）。

用法: python scripts/verify_frozen.py --app "dist/Local Record" [--fix-cv2] [--allow-missing]
"""
from __future__ import annotations

import argparse
import importlib
import shutil
import sys
from pathlib import Path

# 需要逐个验证的关键模块（顺序即导入顺序）
MODULES = [
    "ssl",            # 坑 4b：_ssl / OpenSSL
    "httpx",          # 坑 4b 连带：httpx 模块级 import ssl
    "numpy",
    "cv2",            # 坑 4a：MSVC 运行库 / loader 递归
    "sounddevice",    # 坑 4d：麦克风
    "PySide6.QtCore", # UI
    "sherpa_onnx",    # ASR
    "paddleocr",      # OCR
]

# 这些模块必须解析到 _internal 内（ssl 是标准库，跳过位置检查）
LOCATION_CHECKED = {
    "httpx", "numpy", "cv2", "sounddevice", "PySide6.QtCore",
    "sherpa_onnx", "paddleocr",
}

CV2_BOOTSTRAP = '''\
# -*- coding: utf-8 -*-
# 由 scripts/verify_frozen.py --fix-cv2 生成。
# opencv 4.10+ 自带的 __init__.py loader 在 PyInstaller onedir 下可能
# 重导入自身导致递归（macOS BUNDLE 交叉链接的同款问题）。这里改为直接
# 加载同目录的原生扩展，模块名必须是 "cv2"（对上 PyInit_cv2 符号）。
# 注意：仅覆盖顶层 cv2 属性，cv2 子模块（cv2.data 等）不再可用；
# paddleocr/paddlex 只用顶层 cv2，够用。
import importlib.util
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
for _fname in ("cv2.abi3.pyd", "cv2.pyd", "cv2.abi3.so"):
    _path = os.path.join(_here, _fname)
    if os.path.exists(_path):
        _spec = importlib.util.spec_from_file_location("cv2", _path)
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        sys.modules["cv2"] = _mod
        break
else:
    raise ImportError("cv2 原生扩展缺失（目录: %s）" % _here)
'''


def try_import(name: str, internal: Path) -> tuple[bool, str]:
    try:
        mod = importlib.import_module(name)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    if name in LOCATION_CHECKED:
        f = getattr(mod, "__file__", "") or ""
        try:
            resolved = Path(f).resolve()
        except Exception:
            resolved = Path(f)
        if not str(resolved).startswith(str(internal.resolve())):
            # 纯 Python 模块会被 PyInstaller 收进 PYZ 归档（_internal/python*.zip
            # 或 *.pyz），模拟环境里看不到归档内的文件——去归档里核实
            if _module_in_pyz(internal, name):
                return True, ""
            return False, f"模块解析到构建环境而非 _internal: {f}"
    return True, ""


def _module_in_pyz(internal: Path, modname: str) -> bool:
    """检查模块是否被打进 PYZ 归档（纯 Python 模块的常规去处）。"""
    import zipfile
    prefix = modname.replace(".", "/")
    for z in list(internal.glob("*.pyz")) + list(internal.glob("python*.zip")):
        try:
            with zipfile.ZipFile(z) as zf:
                names = zf.namelist()
        except Exception:
            continue
        if any(n.startswith(prefix) for n in names):
            return True
    return False


def fix_cv2(internal: Path) -> None:
    cv2_dir = internal / "cv2"
    if not cv2_dir.is_dir():
        print("[fix-cv2] _internal/cv2 目录不存在（原生单文件形态，无需引导替换）")
        return
    init = cv2_dir / "__init__.py"
    if not init.is_file():
        print("[fix-cv2] 无 __init__.py，跳过")
        return
    bak = cv2_dir / "__init__.py.pyinstaller-bak"
    if not bak.exists():
        shutil.move(str(init), str(bak))
        print(f"[fix-cv2] 原 __init__.py 备份为 {bak.name}")
    init.write_text(CV2_BOOTSTRAP, encoding="utf-8")
    print("[fix-cv2] 已写入引导 __init__.py")


def find_portaudio(internal: Path) -> Path | None:
    for pat in ("libportaudio64bit.dll", "libportaudio*.dll"):
        hits = list(internal.rglob(pat))
        if hits:
            return hits[0]
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--app", required=True, help="打包产物目录，如 dist/Local Record")
    ap.add_argument("--fix-cv2", action="store_true",
                    help="cv2 导入失败时自动写入引导 __init__.py 并重试")
    ap.add_argument("--fix-cv2-only", action="store_true",
                    help="只执行 cv2 引导修复（exe --verify 检测到 cv2 失败后调用）")
    ap.add_argument("--allow-missing", action="store_true",
                    help="有失败项时仅警告，退出码仍为 0")
    args = ap.parse_args()

    app_dir = Path(args.app)
    internal = app_dir / "_internal"
    if not internal.is_dir():
        print(f"[FAIL] 找不到 _internal 目录: {internal}")
        return 1

    if args.fix_cv2_only:
        fix_cv2(internal)
        return 0

    # ---- 模拟冻结 sys.path（关键：不加 exe 同级目录）----
    import sysconfig
    sys.path = [
        str(internal),
        sysconfig.get_path("stdlib"),
        sysconfig.get_path("platstdlib"),
        sysconfig.get_path("purelib"),
    ]
    # 清理可能已加载的目标模块，保证测的是 _internal 里的版本
    for m in list(sys.modules):
        if m.split(".")[0] in {n.split(".")[0] for n in MODULES}:
            del sys.modules[m]

    failures: list[str] = []
    for name in MODULES:
        ok, msg = try_import(name, internal)
        if not ok and name == "cv2" and args.fix_cv2:
            fix_cv2(internal)
            ok, msg = try_import(name, internal)
            if ok:
                print("[FIXED] cv2（引导模块替换后导入成功）")
        if name == "ssl" and ok and not (internal / "_ssl.pyd").is_file():
            # 冻结版只从 _internal 找扩展：_ssl.pyd 没进包 = ssl 必然不可用。
            # （这里"导入成功"可能误加载了构建环境的 DLLs/_ssl.pyd，必须拦下）
            ok = False
            msg = "_internal 里没有 _ssl.pyd（PyInstaller 未收集）"
        if ok:
            print(f"[PASS] {name}")
        else:
            print(f"[FAIL] {name}: {msg}")
            failures.append(name)

    # 坑 4d：PortAudio DLL（sounddevice 运行时加载）
    pa = find_portaudio(internal)
    if pa is not None:
        print(f"[PASS] portaudio: {pa.name}")
    else:
        print("[FAIL] portaudio: 未找到 libportaudio*.dll"
              "（检查 spec 里对 sounddevice 的 collect）")
        failures.append("portaudio")

    if failures and not args.allow_missing:
        print(f"\n共 {len(failures)} 项失败: {', '.join(failures)}")
        return 1
    if failures:
        print(f"\n{len(failures)} 项失败（--allow-missing 已忽略）")
    else:
        print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
