"""PaddleOCR（PP-OCRv6）图片 / PDF 识别。

Windows 版要点（已实测 paddleocr 3.7.0 + paddlex 3.7.2）：
- **离线模型**：paddlex 的模型缓存根目录由环境变量 ``PADDLE_PDX_CACHE_HOME``
  决定（默认 ~/.paddlex），模型放在 ``<cache>/official_models/<模型名>/`` 下。
  这里在 import paddlex 之前把它指向 app 的 ``storage/ocr``，打包版零下载。
- **引擎**：paddleocr 3.7 的 ``PaddleOCR()`` 不再有 ``enable_onnxruntime``
  参数，改为 ``engine`` 透传（paddlex 3.7 引擎名：onnxruntime / paddle_static）。
  Windows 上默认不装 paddlepaddle，OCR 走 ONNX Runtime。
- **API**：识别用 ``predict()``（``ocr(img, cls=...)`` 是 2.x 老 API，3.7 已移除）；
  返回 ``list[dict]``，文本在 ``page['rec_texts']``。

config.yaml 的 ocr.backend：auto | onnx | paddle
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Union

from .logger import get_logger
from .paths import storage_dir

log = get_logger(__name__)


def configure_offline_cache() -> Path | None:
    """把 paddlex 的模型缓存根指向 ``storage/ocr``（**必须在 import paddlex 之前**）。

    paddlex 在 ``import`` 时就把缓存目录定下来了，之后再设环境变量无效 ——
    那时它会退回 ``~/.paddlex``，本地找不到模型就联网下载。所以：

    * 本模块**导入时**就调用一次（``app.main`` 启动即 import 本模块，
      早于任何 OCR 动作，也早于任何 paddlex 导入）；
    * :meth:`OCREngine.init` 里再调一次兜底。

    同时关掉 PaddleX 的"模型源连通性检查"（离线包不需要，能省掉几秒网络探测）。
    """
    ocr_cache = storage_dir() / "ocr"
    if not ocr_cache.is_dir():
        return None
    os.environ["PADDLE_PDX_CACHE_HOME"] = str(ocr_cache)
    # 模型都在本地：跳过联网探测；真缺模型时直接报错，而不是静默下载
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    return ocr_cache


# 导入即配置（晚于本模块才 import paddlex 的代码也能拿到正确的缓存目录）
OFFLINE_CACHE = configure_offline_cache()


class OCREngine:
    def __init__(self, cfg: dict):
        self.cfg = cfg["ocr"]
        self._ocr = None

    def init(self) -> None:
        """加载 PaddleOCR（在 OCR 工作线程里调用）。"""
        if self._ocr is not None:
            return
        # 兜底再设一次（正常情况下模块导入时已设好）
        cache = configure_offline_cache()
        if cache is not None:
            log.info("OCR 离线模型目录: %s（不联网）", cache)
        else:
            log.warning("storage/ocr 不存在，OCR 模型可能尝试联网下载")

        try:
            from paddleocr import PaddleOCR
        except ImportError as e:
            raise RuntimeError("缺少 paddleocr：pip install paddleocr paddlex") from e

        backend = self.cfg.get("backend", "auto")
        if backend == "paddle":
            engine = "paddle_static"  # 需要额外安装 paddlepaddle
        else:
            engine = "onnxruntime"

        kwargs = dict(
            text_detection_model_name=self.cfg.get("det_model", "PP-OCRv6_medium_det"),
            text_recognition_model_name=self.cfg.get("rec_model", "PP-OCRv6_medium_rec"),
            use_doc_orientation_classify=self.cfg.get("use_doc_orientation_classify", False),
            use_doc_unwarping=False,
            use_textline_orientation=self.cfg.get("use_textline_orientation", False),
            device=self.cfg.get("device", "cpu"),
            engine=engine,
        )
        try:
            self._ocr = PaddleOCR(**kwargs)
        except Exception as e:
            log.exception("PaddleOCR 初始化失败")
            raise RuntimeError(
                f"PaddleOCR 初始化失败：{e}\n"
                "Windows 版默认走 ONNX Runtime（onnxruntime 已随依赖安装）；"
                "如确认 storage/ocr 里模型齐全仍失败，把 config.yaml 的 "
                "ocr.backend 改为 onnx 并查看日志") from e
        log.info("OCR 引擎就绪（engine=%s, det=%s, rec=%s）",
                 engine, kwargs["text_detection_model_name"],
                 kwargs["text_recognition_model_name"])

    # ---------------- 识别 ----------------

    def recognize_image(self, path: Union[str, Path]) -> str:
        self.init()
        res = self._ocr.predict(str(path))
        return "\n".join(self._extract(res))

    def recognize_pdf(self, path: Union[str, Path], dpi: int = 200) -> str:
        self.init()
        try:
            import pypdfium2 as pdfium
        except ImportError as e:
            raise RuntimeError("缺少 pypdfium2：pip install pypdfium2") from e

        pdf = pdfium.PdfDocument(str(path))
        out: List[str] = []
        scale = dpi / 72.0
        for i, page in enumerate(pdf):
            pil = page.render(scale=scale).to_pil()
            arr = pil.convert("RGB")  # paddlex 读取器可处理 PIL/np 输入
            res = self._ocr.predict(arr)
            text = "\n".join(self._extract(res))
            out.append(f"---- 第 {i + 1} 页 ----\n{text}")
        return "\n".join(out)

    @staticmethod
    def _extract(res) -> List[str]:
        """paddleocr 3.x 返回 list[dict]，文本在 page['rec_texts']。"""
        lines: List[str] = []
        for page in res or []:
            for text in (page.get("rec_texts") or []):
                text = str(text).strip()
                if text:
                    lines.append(text)
        return lines
