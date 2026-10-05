"""启动编排线程：启动 llama-server 并等待就绪，按比例上报进度。

流程（对应 macOS 版 warmup.py + llm.py）：
- start() 后立刻报 0%；
- wait_until_ready 的 on_progress 把 0.0~0.85 映射为 0~85%；
- 就绪后报 100%（界面"本地大模型加载中 X%"→"大模型就绪"）。
启动失败时把完整 traceback 写入 logs/llm-startup-error.log。
"""
from __future__ import annotations

import traceback

from PySide6.QtCore import QThread, Signal

from .llama_server import LlamaServer
from .logger import get_logger
from .paths import appdata_dir

log = get_logger(__name__)


class LLMWarmupThread(QThread):
    status = Signal(str)          # 状态栏文字
    progress = Signal(int)        # 0-100
    ready = Signal(bool, str)     # (ok, message)

    def __init__(self, server: LlamaServer, cfg: dict, parent=None):
        super().__init__(parent)
        self.server = server
        self.cfg = cfg
        self._want_stop = False

    def run(self) -> None:
        startup = float(self.cfg["llama_server"].get("startup_timeout_sec", 300))
        try:
            self.server.start()
            self.status.emit(f"本地大模型加载中（预计 {int(startup)}s 内就绪）")

            def _on_progress(f: float) -> None:
                if self._want_stop:
                    return
                pct = int(f * 100)
                self.progress.emit(pct)
                self.status.emit(f"本地大模型加载中 {pct}%")

            ok = self.server.wait_until_ready(
                on_progress=_on_progress,
                should_stop=lambda: self._want_stop)
            if not ok or self._want_stop:
                return
            self.status.emit("大模型就绪")
            self.progress.emit(100)
            self.ready.emit(True, "大模型就绪")
        except Exception as e:
            log.exception("LLM 启动失败")
            try:
                (appdata_dir() / "logs" / "llm-startup-error.log").write_text(
                    traceback.format_exc(), encoding="utf-8")
            except Exception:
                pass
            self.status.emit("大模型启动失败")
            self.ready.emit(False, str(e))

    def shutdown(self) -> None:
        self._want_stop = True
