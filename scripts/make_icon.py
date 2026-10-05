#!/usr/bin/env python3
"""生成应用图标 installer/LocalRecord.ico（多尺寸，纯代码零外部资源）。

图标 = 系统蓝圆角方块 + 白色麦克风（FontAwesome 矢量路径，QtSvg 渲染）。

用法（venv python，需已装 PySide6 + pillow）:
  .venv/Scripts/python.exe scripts/make_icon.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QImage  # noqa: E402

from app.icons import make_app_image  # noqa: E402

ICO_PATH = ROOT / "installer" / "LocalRecord.ico"
SIZES = [16, 32, 48, 64, 128, 256]


def qimage_to_pil(img: QImage):
    from PIL import Image
    img = img.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = img.width(), img.height()
    import numpy as np
    # PySide6 6.11：constBits() 返回 memoryview，直接转 bytes（RGBA8888 无行 padding）
    arr = np.frombuffer(bytes(img.constBits()), dtype=np.uint8).reshape(h, w, 4)
    return Image.fromarray(arr, "RGBA")


def main() -> int:
    ICO_PATH.parent.mkdir(parents=True, exist_ok=True)
    imgs = [qimage_to_pil(make_app_image(s)) for s in SIZES]
    imgs[-1].save(ICO_PATH, format="ICO",
                  sizes=[(s, s) for s in SIZES])
    print(f"[OK] 已生成应用图标: {ICO_PATH}（多尺寸 {SIZES}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
