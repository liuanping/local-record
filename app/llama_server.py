"""llama-server（llama.cpp）子进程管理。

坑 4 对应实现（与 macOS 版一致）：
- ``wait_until_ready`` 的 startup_timeout_sec 只用于进度估算，
  进程还活着就继续等，硬上限 hard_timeout_sec（600s）；
- ``on_progress`` 回调上报 0.0~1.0 进度（界面显示"本地大模型加载中 X%"）；
- 健康检查异常记录详细异常，并每 30s 打一次"健康检查失败"日志
  （不再用 ``except Exception: return False`` 吞掉错误）。
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import httpx

from .logger import get_logger
from .paths import appdata_dir

log = get_logger(__name__)


class LlamaServerError(RuntimeError):
    pass


class LlamaServer:
    def __init__(self, cfg: dict, storage: Path):
        self.cfg = cfg["llama_server"]
        self.storage = storage
        self.exe = self._find_server()
        self.model = self._find_model(cfg["model"]["filename"])
        self.host = self.cfg.get("host", "127.0.0.1")
        self.port = int(self.cfg.get("port", 8091))
        self.base_url = f"http://{self.host}:{self.port}"
        self.proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._server_log = None

    # ---------------- 文件定位 ----------------

    def _find_server(self) -> Path:
        exe_name = "llama-server.exe" if os.name == "nt" else "llama-server"
        exe = self.storage / "bin" / "llama-server" / exe_name
        if not exe.is_file():
            raise LlamaServerError(
                f"找不到 llama-server 可执行文件：{exe}\n"
                f"请把 llama.cpp {self.cfg.get('release_tag', 'b9000')} 的 "
                f"win-x64 包解压内容放入 storage/bin/llama-server/")
        return exe

    def _find_model(self, filename: str) -> Path:
        model = self.storage / "models" / filename
        if not model.is_file():
            raise LlamaServerError(
                f"找不到 LLM 模型：{model}\n"
                "请把 GGUF 放入 storage/models/，并确认 config.yaml 的 "
                "model.filename 与文件名一致")
        return model

    # ---------------- 生命周期 ----------------

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> None:
        with self._lock:
            if self.is_running():
                return
            logs = appdata_dir() / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            self._server_log = open(logs / "llama-server.log", "a",
                                    encoding="utf-8", errors="replace")
            args = [
                str(self.exe),
                "-m", str(self.model),
                "--host", self.host,
                "--port", str(self.port),
                "-c", str(self.cfg.get("ctx_size", 8192)),
                "-ngl", str(self.cfg.get("gpu_layers", 0)),
            ]
            threads = int(self.cfg.get("threads", 0))
            if threads > 0:
                args += ["-t", str(threads)]
            args += [str(a) for a in self.cfg.get("extra_args", [])]

            kwargs: dict = {}
            if os.name == "nt":
                # 打包版是 --noconsole，子进程也要避免弹出控制台窗口
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            self.proc = subprocess.Popen(
                args, cwd=str(self.exe.parent),
                stdout=self._server_log, stderr=self._server_log, **kwargs)
            log.info("llama-server 已启动: %s", " ".join(args))

    def wait_until_ready(
            self,
            on_progress: Optional[Callable[[float], None]] = None,
            should_stop: Optional[Callable[[], bool]] = None) -> bool:
        """等待 /v1/models 可访问；就绪返回 True。

        进程死亡 → 抛 LlamaServerError（附日志尾部）；
        超过 hard_timeout_sec → 抛超时；
        should_stop() 返回 True（用户退出）→ 返回 False；
        其余情况一直轮询（startup_timeout_sec 仅用于进度估算）。
        """
        startup = float(self.cfg.get("startup_timeout_sec", 300))
        hard = float(self.cfg.get("hard_timeout_sec", 600))
        start = time.monotonic()
        last_err_log = 0.0
        last_err: Optional[Exception] = None

        while True:
            if should_stop is not None and should_stop():
                log.info("等待 llama-server 就绪被打断（用户退出）")
                return False
            if not self.is_running():
                code = self.proc.poll() if self.proc else -1
                raise LlamaServerError(
                    f"llama-server 进程已退出（code={code}）。日志尾部：\n"
                    f"{self._log_tail()}")
            try:
                r = httpx.get(f"{self.base_url}/v1/models", timeout=2.0)
                if r.status_code == 200:
                    log.info("llama-server 就绪（等待 %.1fs）",
                             time.monotonic() - start)
                    if on_progress:
                        on_progress(1.0)
                    return True
            except Exception as e:
                last_err = e
                now = time.monotonic()
                if now - last_err_log >= 30.0:
                    log.warning("健康检查失败（每 30s 记录一次）: %r", e)
                    last_err_log = now

            elapsed = time.monotonic() - start
            if on_progress:
                frac = min(0.85, elapsed / startup * 0.85) if startup > 0 else 0.0
                on_progress(frac)
            if elapsed > hard:
                raise LlamaServerError(
                    f"等待 llama-server 就绪超时（>{hard}s）。"
                    f"最近错误：{last_err!r}\n日志尾部：\n{self._log_tail()}")
            time.sleep(0.5)

    def stop(self) -> None:
        with self._lock:
            proc, self.proc = self.proc, None
            if proc is None:
                return
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/PID", str(proc.pid),
                                        "/T", "/F"], capture_output=True)
                    else:
                        proc.kill()
            if self._server_log is not None:
                try:
                    self._server_log.close()
                except Exception:
                    pass
            log.info("llama-server 已停止")

    def _log_tail(self, lines: int = 20) -> str:
        try:
            path = appdata_dir() / "logs" / "llama-server.log"
            all_lines = path.read_text(encoding="utf-8",
                                       errors="replace").splitlines()
            return "\n".join(all_lines[-lines:])
        except Exception:
            return "(无日志)"
