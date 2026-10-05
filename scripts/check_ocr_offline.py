"""离线 OCR 自检：确认 paddlex 只用 storage/ocr 里的模型、绝不联网下载。

用法::

    .venv\\Scripts\\python.exe scripts\\check_ocr_offline.py

原理：
1. 先把 ``PADDLE_PDX_CACHE_HOME`` 指向 ``storage/ocr``（必须在 import paddleocr 之前），
   再 import paddleocr —— 这正是 `app/ocr.py` 的离线机制；
2. 现场用 PIL 生成一张带大字的图片，跑完整识别链路，断言识别出关键词；
3. 前后快照 ``~/.paddlex/official_models``：如果多了文件，说明发生了联网下载 → 判定失败
   （缓存目录设晚了就会这样，是打包/启动顺序回归的信号）。

退出码 0 = 离线可用；1 = 失败（结果为空 / 触发了下载 / 本地模型缺失）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CACHE = ROOT / "storage" / "ocr"
DEFAULT_CACHE = Path(os.path.expanduser("~")) / ".paddlex" / "official_models"


def snapshot() -> dict[str, int]:
    """记录 ~/.paddlex/official_models 下的文件指纹，用于检测"偷偷下载"。"""
    if not DEFAULT_CACHE.is_dir():
        return {}
    return {str(p.relative_to(DEFAULT_CACHE)): p.stat().st_size
            for p in DEFAULT_CACHE.rglob("*") if p.is_file()}


def main() -> int:
    # ---- 1) 关键：必须在 import paddleocr/paddlex 之前设定缓存目录 ----
    if not CACHE.is_dir():
        print(f"[FAIL] 没有 {CACHE}")
        return 1
    os.environ["PADDLE_PDX_CACHE_HOME"] = str(CACHE)
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    print(f"[env] PADDLE_PDX_CACHE_HOME = {CACHE}")

    models = sorted(p.name for p in (CACHE / "official_models").iterdir()
                    if p.is_dir()) if (CACHE / "official_models").is_dir() else []
    print(f"[local] official_models: {models}")
    if not models:
        print("[FAIL] storage/ocr/official_models 为空")
        return 1

    before = snapshot()

    # ---- 2) 现场生成图片并识别 ----
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (800, 240), "white")
    draw = ImageDraw.Draw(img)
    font = None
    for cand in ("C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf",
                 "C:/Windows/Fonts/msyh.ttc"):
        if Path(cand).is_file():
            try:
                font = ImageFont.truetype(cand, 80)
                break
            except OSError:
                continue
    draw.text((30, 80), "LOCAL RECORD 2026", fill="black",
              font=font or ImageFont.load_default())
    sample = ROOT / "build" / "ocr-offline-sample.png"
    sample.parent.mkdir(parents=True, exist_ok=True)
    img.save(sample)
    print(f"[input] {sample}")

    from paddleocr import PaddleOCR

    ocr = PaddleOCR(
        text_detection_model_name="PP-OCRv6_medium_det",
        text_recognition_model_name="PP-OCRv6_medium_rec",
        engine="onnxruntime",
        device="cpu",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )
    texts: list[str] = []
    for page in ocr.predict(str(sample)):
        texts += [str(t) for t in page.get("rec_texts", [])]
    flat = "".join(texts).upper()
    print(f"[result] {flat}")

    # ---- 3) 判定 ----
    after = snapshot()
    new_files = sorted(set(after) - set(before))
    changed = sorted(k for k in set(after) & set(before) if after[k] != before[k])

    ok = True
    if not flat:
        print("[FAIL] 识别结果为空")
        ok = False
    if not any(k in flat for k in ("LOCAL", "RECORD", "2026", "20")):
        print(f"[FAIL] 结果不含预期关键词：{flat[:80]}")
        ok = False
    if new_files or changed:
        print(f"[FAIL] 检测到联网下载（~/.paddlex 新增 {len(new_files)} 个文件，"
              f"变动 {len(changed)} 个）：{new_files[:5]}")
        ok = False

    print("[PASS] 离线 OCR 正常（无任何下载）" if ok else "[FAIL] 离线 OCR 自检未通过")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
