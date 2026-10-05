"""Local Record 入口（Windows 版）。

开发运行: python -m app.main   （资源在项目根 storage/，可用 LOCAL_RECORD_DIR 覆盖）
打包运行: LocalRecord.exe

模块间用绝对导入（``app.*``），保证 ``python -m`` 与 PyInstaller 冻结
两种模式下都能解析包路径（spec 的 pathex 指向项目根）。

这一层负责"把零件接起来"：
录音 ↔ 播放 ↔ 转写 ↔ 大模型 ↔ 托盘/悬浮球，以及全局的运行状态心跳
（录音计时、ASR/LLM 加载进度、忙碌流动线、托盘与悬浮球状态色）。
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QTimer, Signal
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox

from app import config as config_mod
from app.asr import ASRWorker
from app.ball import FloatingBall
from app.llm import LLMClient, parse_locate_result
from app.llama_server import LlamaServer, LlamaServerError
from app.logger import get_logger, setup_logging
from app.icons import lucide_icon
from app.main_window import MainWindow
from app.ocr import OCREngine
from app.paths import logs_dir, recordings_dir, storage_dir
from app.player import AudioPlayer
from app.recorder import Recorder
from app.theme import theme
from app.tray import Tray
from app.utils import AUDIO_SUFFIXES, fmt_mmss
from app.warmup import LLMWarmupThread

log = get_logger(__name__)


# ============================================================
# 后台工作者（用 Python 线程 + Qt 排队信号，避免阻塞 UI）
# ============================================================

class LLMWorker(QObject):
    """LLM 请求在后台线程执行；完成时发 done(kind, ok, content)。"""

    done = Signal(str, bool, str)

    def __init__(self, llm: LLMClient, cfg: dict):
        super().__init__()
        self.llm = llm
        self.cfg = cfg

    def _run(self, kind: str, fn) -> None:
        def target() -> None:
            try:
                self.done.emit(kind, True, fn())
            except Exception as e:
                log.exception("LLM 请求失败: %s", kind)
                self.done.emit(kind, False, str(e))

        threading.Thread(target=target, daemon=True).start()

    def summarize(self, segments) -> None:
        self._run("summary", lambda: self.llm.summarize(
            segments, self.cfg["prompts"]["summarize"]))

    def ask(self, question: str, segments) -> None:
        self._run("answer", lambda: self.llm.ask(
            question, segments, self.cfg["prompts"]["qa"]))

    def locate(self, question: str, segments) -> None:
        self._run("locate", lambda: self.llm.locate(
            question, segments, self.cfg["prompts"]["locate"]))

    # ---- OCR 页的 LLM 请求 ----
    def summarize_ocr(self, text: str) -> None:
        self._run("ocr_summary", lambda: self.llm.summarize_ocr(
            text, self.cfg["prompts"]["ocr_summarize"]))

    def ask_ocr(self, question: str, text: str) -> None:
        self._run("ocr_answer", lambda: self.llm.ask_ocr(
            question, text, self.cfg["prompts"]["ocr_qa"]))


class OCRWorker(QObject):
    """OCR 在后台线程执行。"""

    done = Signal(str, bool, str)

    def __init__(self, engine: OCREngine, cfg: dict):
        super().__init__()
        self.engine = engine
        self.cfg = cfg

    def run(self, kind: str, path: str) -> None:
        def target() -> None:
            try:
                if kind == "pdf":
                    text = self.engine.recognize_pdf(
                        path, self.cfg["ocr"].get("pdf_dpi", 200))
                else:
                    text = self.engine.recognize_image(path)
                self.done.emit(kind, True, text)
            except Exception as e:
                log.exception("OCR 失败: %s", path)
                self.done.emit(kind, False, str(e))

        threading.Thread(target=target, daemon=True).start()


# ============================================================
# 入口
# ============================================================

def _clean_temp_recordings(max_age_hours: int = 24) -> None:
    """save_wav=false 时录音落在临时目录，这里清掉过期的文件。"""
    import tempfile
    import time as _time
    tmp = Path(tempfile.gettempdir()) / "LocalRecord"
    if not tmp.is_dir():
        return
    deadline = _time.time() - max_age_hours * 3600
    for f in tmp.glob("*.wav"):
        try:
            if f.stat().st_mtime < deadline:
                f.unlink()
        except OSError:
            pass


def main() -> int:
    # ---- 冻结环境自检模式（打包脚本调用，不启动 GUI）----
    #   LocalRecord.exe --verify         仅导入自检 + 音频设备枚举
    #   LocalRecord.exe --verify --deep  额外跑功能自检（Qt 界面/PortAudio/
    #                                    SenseVoice/OCR 真图识别/wav 回读）
    if "--verify" in sys.argv:
        sys.argv.remove("--verify")
        deep = "--deep" in sys.argv
        if deep:
            sys.argv.remove("--deep")
        from app.verify import run_verify
        code = run_verify(logs_dir() / "verify.log", deep=deep)
        return code

    cfg = config_mod.load_config()
    level = getattr(logging, str(cfg["logging"]["level"]).upper(), logging.INFO)
    setup_logging(level)

    app = QApplication(sys.argv)
    app.setApplicationName(cfg["app"]["name"])
    app.setApplicationDisplayName(cfg["app"]["name"])
    app.setQuitOnLastWindowClosed(False)      # 托盘常驻

    # ---- 主题：优先用户上次的选择，其次 config.yaml 的 ui.theme ----
    settings = QSettings("LocalRecord", "LocalRecord")
    saved_mode = settings.value("ui/theme")
    mode = str(saved_mode) if saved_mode in ("dark", "light") else \
        str(cfg.get("ui", {}).get("theme", "dark"))
    theme.apply(app, mode if mode in ("dark", "light") else "dark")

    # ---- 单实例保护：重复启动时提示并退出（避免双实例抢 8091 端口）----
    data_dir = logs_dir().parent
    data_dir.mkdir(parents=True, exist_ok=True)
    from PySide6.QtCore import QLockFile
    lock = QLockFile(str(data_dir / "app.lock"))
    if not lock.tryLock(100):
        QMessageBox.information(None, cfg["app"]["name"],
                                "Local Record 已在运行中。\n如需重启，请先退出托盘图标。")
        return 0

    log.info("=== Local Record 启动 (version=%s, python=%s, theme=%s) ===",
             cfg["app"]["version"], sys.version, theme.mode)
    logs_dir().mkdir(parents=True, exist_ok=True)

    storage = storage_dir()
    state = {"recording": False, "quitting": False}

    # ---------- 核心组件 ----------
    rec_dir = recordings_dir()
    keep_wav = bool(cfg["recorder"].get("save_wav", True))
    recorder = Recorder(
        sample_rate=int(cfg["recorder"]["sample_rate"]),
        channels=int(cfg["recorder"]["channels"]),
        dtype=cfg["recorder"]["dtype"],
        device=cfg["recorder"]["device"],
        # save_wav=false：录音仍会落盘（否则无法试听），但只落在临时目录、不入录音库
        save_dir=rec_dir if keep_wav else None,
        # 落盘前整体增益归一化：麦克风电平低时回听太小（只乘系数，不改波形）
        normalize_save=bool(cfg["recorder"].get("normalize_save", True)),
    )
    if not keep_wav:
        _clean_temp_recordings()
    player = AudioPlayer(
        device=cfg.get("player", {}).get("device"),
        volume=float(cfg.get("player", {}).get("volume", 0.8)),
    )
    llm_client = LLMClient(cfg)
    llm_worker = LLMWorker(llm_client, cfg)
    ocr_worker = OCRWorker(OCREngine(cfg), cfg)

    try:
        server = LlamaServer(cfg, storage)
    except LlamaServerError as e:
        server = None
        log.error("LLM 不可用: %s", e)

    # ---------- UI ----------
    win = MainWindow(player, rec_dir, version=str(cfg["app"]["version"]))
    autoplay = bool(cfg.get("player", {}).get("autoplay_after_stop", False))

    # ---------- 录音 / 播放 ----------
    def refresh_ball_status(text: str = "") -> None:
        ball.set_busy(not state["asr_ok"] or not state["llm_ok"])
        if text:
            ball.set_status_text(text)

    def toggle_record() -> None:
        if state["recording"]:
            wav = recorder.stop()
            state["recording"] = False
            tick_timer.stop()
            # 立刻让 ASR 把不足一段的残留音频也转写出来：
            # chunk_seconds 是 8 秒，不说满 8 秒就停会一个字都看不到（实测踩过）
            _asr = state.get("asr_worker")
            if _asr is not None:
                _asr.flush()
            ball.set_recording(False)
            ball.set_level(0.0)
            win.set_recording(False)
            if wav is not None:
                win.note_recording_saved(Path(wav), autoplay=autoplay)
                if recorder.peak < 0.01:
                    win.toast("这次录音电平很低，检查一下麦克风是否静音", "warn")
            else:
                win.toast("这次没有采集到音频", "warn")
            set_tray_state()
            log.info("录音停止%s", f"，已保存 {wav}" if wav else "")
        else:
            try:
                player.stop()          # 避免外放声音被再次录进去
                recorder.start()
            except RuntimeError as e:
                QMessageBox.warning(win, "无法录音", str(e))
                win.set_activity("录音启动失败，请检查麦克风权限")
                return
            state["recording"] = True
            ball.set_recording(True)
            win.set_recording(True)
            win.set_activity("正在录音…")
            tick_timer.start()
            open_window()
            set_tray_state()

    def tick() -> None:
        """录音期间 16 次/秒刷新计时器与电平（界面"活着"的直观体现）。"""
        if not state["recording"]:
            return
        level = recorder.level
        win.update_recording(recorder.elapsed, level)
        ball.set_level(level)
        if int(recorder.elapsed * 4) % 20 == 0:
            set_tray_state(f"已录 {fmt_mmss(recorder.elapsed)}")

    tick_timer = QTimer()
    tick_timer.setInterval(60)
    tick_timer.timeout.connect(tick)

    def toggle_playback() -> None:
        if player.is_playing:
            player.pause()
        elif player.path is not None:
            player.play()
        else:
            files = win.library_page.files()
            if files:
                player.load(files[0], autoplay=True)
            else:
                win.toast("还没有可播放的录音", "warn")

    def open_window() -> None:
        win.show()
        win.raise_()
        win.activateWindow()

    def open_library() -> None:
        open_window()
        win.show_tab(1)

    def open_data_dir() -> None:
        try:
            os.startfile(str(logs_dir().parent))
        except Exception:
            log.exception("打开数据目录失败")

    def toggle_theme() -> None:
        mode_now = theme.toggle()
        settings.setValue("ui/theme", mode_now)
        win.toast("已切换到" + ("深色" if mode_now == "dark" else "浅色") + "主题", "ok")

    def quit_app() -> None:
        if state["quitting"]:
            return
        state["quitting"] = True
        log.info("用户退出")
        if state["recording"]:
            try:
                recorder.stop()
            except Exception:
                pass
        try:
            player.stop()
        except Exception:
            pass
        asr_worker.shutdown()
        asr_worker.wait(3000)
        if warmup is not None:
            warmup.shutdown()
            warmup.wait(3000)
        if server is not None:
            try:
                server.stop()
            except Exception:
                log.exception("停止 llama-server 失败")
        tray.hide()
        app.quit()

    def menu_spec():
        return [
            ("停止录音" if state["recording"] else "开始录音",
             toggle_record, "stop" if state["recording"] else "mic"),
            ("暂停播放" if player.is_playing else "播放最近录音",
             toggle_playback, "pause" if player.is_playing else "play"),
            (None, None),
            ("打开主窗口", open_window, "activity"),
            ("录音库", open_library, "list-music"),
            ("上传文件识别（图片 / PDF）…", win.pick_ocr_file, "scan-text"),
            (None, None),
            ("切换到浅色主题" if theme.is_dark else "切换到深色主题",
             toggle_theme, "sun" if theme.is_dark else "moon"),
            ("打开数据目录（日志/录音）", open_data_dir, "folder-open"),
            (None, None),
            ("退出", quit_app, "power"),
        ]

    def make_menu() -> QMenu:
        """托盘菜单（功能齐全）。"""
        menu = QMenu()
        for text, cb, *rest in menu_spec():
            if text is None:
                menu.addSeparator()
                continue
            if cb is None:
                menu.addAction(text).setEnabled(False)
                continue
            action = menu.addAction(text, cb)
            if rest and rest[0]:
                action.setIcon(lucide_icon(rest[0], theme.hex("text"), 32, 2.0))
        return menu

    def ball_menu_spec():
        """悬浮球右键菜单：只留最常用的几项。

        用户要求悬浮球别堆一堆选项 —— 单击直接进主界面，右键只给
        开始/停止录音 与 退出，其余功能都在主界面和托盘里。
        """
        return [
            ("停止录音" if state["recording"] else "开始录音",
             toggle_record, "stop" if state["recording"] else "mic"),
            (None, None),
            ("打开主界面", open_window, "activity"),
            ("退出", quit_app, "power"),
        ]

    def make_ball_menu() -> QMenu:
        menu = QMenu()
        for text, cb, *rest in ball_menu_spec():
            if text is None:
                menu.addSeparator()
                continue
            action = menu.addAction(text, cb)
            if rest and rest[0]:
                action.setIcon(lucide_icon(rest[0], theme.hex("text"), 32, 2.0))
        return menu

    def rebuild_menus() -> None:
        tray.rebuild(menu_spec())
        ball.set_recording(state["recording"])

    def set_tray_state(detail: str = "") -> None:
        if state["recording"]:
            tray.set_state("recording", detail or f"已录 {fmt_mmss(recorder.elapsed)}")
        elif not state["asr_ok"] or not state["llm_ok"]:
            tray.set_state("busy", state.get("status_text", ""))
        else:
            tray.set_state("ok", detail or "录音 · 转写 · 问答 就绪")

    state["asr_ok"] = False
    state["llm_ok"] = server is None
    state["status_text"] = ""

    ball = FloatingBall(menu_factory=make_ball_menu)
    tray = Tray(items=menu_spec(), on_double_click=open_window)

    # ---------- 信号接线 ----------

    # ASR
    asr_worker = ASRWorker(cfg, recorder.chunks)
    state["asr_worker"] = asr_worker

    # 启动清理：上次"文件被占用、安排下次启动删除"的录音，这次开机就删掉
    try:
        # 注意：要用绝对导入。打包后本文件是以 __main__ 运行的，
        # 相对导入（from .library import ...）会抛 ImportError
        from app.library import process_pending_deletes
        n_done, n_left = process_pending_deletes(recordings_dir())
        if n_done or n_left:
            log.info("启动清理待删除录音：成功 %d，仍失败 %d", n_done, n_left)
    except Exception:
        log.exception("启动清理待删除录音失败")

    def on_asr_ready(ok: bool, message: str) -> None:
        state["asr_ok"] = ok
        state["status_text"] = message
        win.set_asr_status(ok, message)
        refresh_ball_status(message)
        set_tray_state()
        if ok:
            win.set_activity("语音识别就绪，可以开始录音")
        else:
            # ASR 不可用时持续清空音频队列，避免录音越久内存越大
            drain_timer.start()

    asr_worker.ready.connect(on_asr_ready)
    asr_worker.segment.connect(win.add_transcript)
    asr_worker.stopped.connect(lambda: log.info("ASR 线程退出"))

    def on_no_voice(count: int) -> None:
        """连续多段都识别不出内容 → 明确提示"麦克风可能没收到你的声音"。

        实测踩过：系统默认输入设备/硬件静音/强降噪导致只有低频轰鸣，
        用户说了一堆话，界面上却什么都没有，且完全不知道该查哪里。
        """
        msg = (f"已连续 {count} 段没有识别出可用内容。请检查：系统设置 → 系统 → 声音 → 输入，"
               "是否选对设备、麦克风静音键、以及关掉噪音抑制/音频增强")
        log.warning(msg)
        win.set_activity("⚠ 连续多段没有识别出内容，请检查麦克风/输入设备")
        win.toast("没识别出内容：请检查系统输入设备/静音键/音频增强", "error", 6000)

    asr_worker.noVoice.connect(on_no_voice)
    asr_worker.start()

    drain_timer = QTimer()
    drain_timer.setInterval(300)

    def drain_chunks() -> None:
        try:
            while True:
                recorder.chunks.get_nowait()
        except Exception:
            pass

    drain_timer.timeout.connect(drain_chunks)

    # LLM 预热（坑 4：超时只用于进度估算，进程活着就继续等）
    warmup = None
    if server is not None:
        warmup = LLMWarmupThread(server, cfg)
        warmup.status.connect(win.set_llm_status_text)
        warmup.status.connect(lambda t: refresh_ball_status(t))
        warmup.status.connect(lambda t: set_tray_state(t))
        warmup.progress.connect(win.set_llm_progress)
        warmup.ready.connect(lambda ok, msg: (win.set_llm_status(ok, msg),
                                              set_llm_ready_flags(ok, msg)))
        warmup.start()
    else:
        win.set_llm_status(False, "模型或 llama-server 缺失，见日志")

    def set_llm_ready_flags(ok: bool, message: str) -> None:
        state["llm_ok"] = ok
        state["status_text"] = message
        refresh_ball_status(message)
        set_tray_state()
        if ok:
            win.set_activity("本地大模型就绪，可以生成会议纪要与问答")

    # 播放器状态 → 界面/托盘
    def on_player_state(st: str) -> None:
        if st == "playing":
            win.set_activity(f"正在播放 {player.path.name if player.path else ''}")
        rebuild_menus()

    def on_player_error(message: str) -> None:
        first = message.split("\n\n")[0]
        win.toast(first, "error")
        win.set_activity(first)

    player.stateChanged.connect(on_player_state)
    player.errorOccurred.connect(on_player_error)
    player.finished.connect(lambda: win.set_activity("播放结束"))

    # LLM 请求
    RESULT_TITLES = {
        "summary": "会议纪要",
        "answer": "AI 回答",
        "locate": "时间定位",
        "ocr_summary": "OCR 总结",
        "ocr_answer": "OCR 回答",
    }

    def on_llm_done(kind: str, ok: bool, content: str) -> None:
        win.set_chat_busy(False)
        title = RESULT_TITLES.get(kind, "结果")
        if not ok:
            if kind.startswith("ocr_"):
                win.append_ocr_chat("错误", content)
            else:
                win.append_chat("错误", content)
            win.set_activity(f"{title}失败")
            win.show_llm_result(f"{title} · 出错", content, error=True)
            return
        if kind == "summary":
            win.append_chat("会议纪要", content)
        elif kind == "answer":
            win.append_chat("AI", content)
        elif kind == "locate":
            win.append_chat("定位", content)
            indices = parse_locate_result(content)
            if indices:
                win.highlight_transcript(indices)
        elif kind in ("ocr_summary", "ocr_answer"):
            win.append_ocr_chat("AI", content)
        win.set_activity(f"{title}完成")
        win.show_llm_result(title, content)

    win.ask_question.connect(lambda q: (
        win.set_chat_busy(True),
        llm_worker.ask(q, list(win.transcript_items))))
    win.request_summary.connect(lambda: (
        win.set_chat_busy(True),
        win.set_activity("大模型正在整理会议纪要…"),
        llm_worker.summarize(list(win.transcript_items))))
    win.request_locate.connect(lambda q: (
        win.set_chat_busy(True),
        llm_worker.locate(q, list(win.transcript_items))))
    win.ocr_ask_question.connect(lambda q: (
        win.set_chat_busy(True),
        llm_worker.ask_ocr(q, win.ocr_text)))
    # OCR 页已去掉「生成摘要」按钮：识别结果的主要用法是问答，不是摘要
    llm_worker.done.connect(on_llm_done)

    # OCR
    def start_ocr(kind: str, path: str) -> None:
        win.set_ocr_busy(True)
        win.set_activity(f"正在识别 {Path(path).name} …")
        ocr_worker.run(kind, path)

    def on_ocr_done(kind: str, ok: bool, content: str) -> None:
        win.set_ocr_busy(False)
        if ok:
            win.append_ocr(content)
            win.set_activity("识别完成")
            win.toast("识别完成", "ok")
        else:
            win.set_activity("识别失败")
            QMessageBox.warning(win, "OCR 失败", content)

    win.open_image_requested.connect(lambda p: start_ocr("image", p))
    win.open_pdf_requested.connect(lambda p: start_ocr("pdf", p))
    ocr_worker.done.connect(on_ocr_done)

    # 录音 / 主题 / 转写
    ball.toggle_record_requested.connect(toggle_record)
    # 单击悬浮球 → 直接进主界面（不再弹一长串菜单）
    ball.open_main_requested.connect(open_window)
    win.toggle_record_clicked.connect(toggle_record)
    win.theme_toggled.connect(toggle_theme)
    win.clear_transcript.connect(lambda: win.set_activity("已清空转写区"))

    # 拖放：音频 → 录音库；图片/PDF → OCR
    def on_files_dropped(paths: list) -> None:
        audio = [Path(p) for p in paths
                 if Path(p).suffix.lower() in AUDIO_SUFFIXES]
        docs = [p for p in paths
                if Path(p).suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp",
                                              ".webp", ".pdf")]
        if audio:
            added = win.library_page.import_files(audio)
            if added:
                win.toast(f"已导入 {added} 个音频到录音库", "ok")
                open_library()
            else:
                win.toast("只支持导入 wav 音频", "warn")
        elif docs:
            win.show_tab(2)
            start_ocr("pdf" if docs[0].lower().endswith(".pdf") else "image", docs[0])
        else:
            win.toast("支持拖入 wav / 图片 / PDF", "warn")

    win.files_dropped.connect(on_files_dropped)

    # 转写已有录音（比如用手机录好再导入）：点录音库里那条的「转写」按钮
    def start_transcribe(path) -> None:
        p = Path(path)
        if not p.is_file():
            win.toast("文件不存在", "warn")
            return
        if state.get("transcribe_worker") is not None:
            win.toast("正在转写另一条，请稍候", "warn")
            return
        from app.asr import FileTranscribeWorker
        win.show_tab(0)                       # 切到语音页看转写结果
        win.set_activity(f"正在转写 {p.name} …")
        win.toast(f"开始转写 {p.name}", "info")
        worker = FileTranscribeWorker(cfg, p)
        state["transcribe_worker"] = worker

        def on_seg(text: str, start: float, end: float) -> None:
            win.add_transcript(text, start, end)

        def on_done(ok: bool, msg: str) -> None:
            state["transcribe_worker"] = None
            win.set_activity(msg)
            win.toast(msg, "ok" if ok else "error", 5000)
            log.info("文件转写结束: %s", msg)

        worker.segment.connect(on_seg)
        worker.done.connect(on_done)
        worker.finished.connect(lambda: state.update(transcribe_worker=None))
        worker.start()
        win.transcribe_worker = worker      # 防被 GC

    win.library_page.transcribeRequested.connect(start_transcribe)

    rebuild_menus()
    set_tray_state()
    win.show()
    log.info("启动完成，等待用户操作")
    return app.exec()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # 打包版 --noconsole 没有控制台，任何未捕获异常都要进日志
        import traceback
        log.critical("启动失败:\n%s", traceback.format_exc())
        raise
