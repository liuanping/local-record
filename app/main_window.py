"""主窗口：深色玻璃拟态 + "随时看得出在运行"的三段式界面。

布局::

    ┌──────────────────────────────────────────────┐
    │ [图标] Local Record              ☀  −  ✕      │ ← 品牌 + 窗口按钮
    │ ● 运行中   ● ASR 就绪   ◌ 大模型 45%   00:12  │ ← 运行状态一目了然
    │ [  语音  ][  录音库  ][  文字识别  ]          │ ← 三段切换
    │ ┌──────────────────────────────────────────┐ │
    │ │ (◉)  正在录音 00:12.4                    │ │ ← 录音卡（呼吸光环+计时）
    │ │ ▁▃▅▇▅▃▁▂▄▆▇▆▄▂ 实时电平                   │ │
    │ └──────────────────────────────────────────┘ │
    │ ┌ 实时转写  12 段        [复制][清空] ─────┐ │
    │ └──────────────────────────────────────────┘ │
    │ [ 📋 生成会议纪要 ]                          │
    │ [ 在这里输入问题…                  ][⏱][发送] │
    │ ─── 流动进度线（忙碌时）───────────────────  │
    │ ● 已保存 rec-xxx.wav                  ⌟      │ ← 活动行 + 缩放角
    └──────────────────────────────────────────────┘

文字识别页（无「摘要」按钮，识别结果主要用于提问）：
    │ [ 上传图片 / PDF 开始识别 ]                  │
    │ ┌ 识别文本 ─────────────────────[复制][清空]┐ │
    │ ① 文档问答                                    │
    │   在下面输入你想问的问题，AI 只依据识别出的文字│
    │ [ 在这里输入问题…                 ][提问]     │

对外信号：toggle_record_clicked / ask_question / request_summary /
request_locate / clear_transcript / open_image_requested /
open_pdf_requested / ocr_ask_question / theme_toggled
对外槽：add_transcript / append_chat / append_ocr / append_ocr_chat /
set_asr_status / set_llm_status / set_llm_status_text / set_llm_progress /
set_chat_busy / set_ocr_busy / set_recording / update_recording /
set_run_state / set_activity / set_busy / toast / show_llm_result /
highlight_transcript / clear_transcript_view
"""
from __future__ import annotations

import html
import time
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QPoint, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QPushButton, QSizeGrip, QStackedWidget, QTextBrowser,
    QTextEdit, QVBoxLayout, QWidget,
)

from .icons import lucide_icon, make_app_image
from .library import LibraryPage, MiniPlayer
from .logger import get_logger
from .md import to_html
from .player import AudioPlayer
from .theme import theme
from .utils import fmt_mmss, fmt_time, fmt_timer
from .widgets import (
    DropZone, IconButton, LevelMeter, ProgressLine, RecordButton, RootCard,
    StatusPill, Toast, icon_label, section_label,
)

log = get_logger(__name__)

TAB_VOICE, TAB_LIBRARY, TAB_OCR = 0, 1, 2


class MainWindow(QMainWindow):
    # ---- 语音页 ----
    toggle_record_clicked = Signal()
    ask_question = Signal(str)
    request_summary = Signal()
    request_locate = Signal(str)
    clear_transcript = Signal()
    # ---- OCR 页 ----
    open_image_requested = Signal(str)
    open_pdf_requested = Signal(str)
    ocr_ask_question = Signal(str)
    request_ocr_summary = Signal()
    # ---- 其它 ----
    theme_toggled = Signal()
    files_dropped = Signal(list)          # 拖入的文件路径列表

    def __init__(self, player: AudioPlayer, library_dir: Path, version: str = "",
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Local Record")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(478, 812)
        self.setMinimumSize(380, 480)
        self._fit_to_screen()
        self.setAcceptDrops(True)

        self.player = player
        self.library_dir = Path(library_dir)
        self.version = version
        self._drag_pos: Optional[QPoint] = None
        self._busy = False
        self._llm_ready = False
        self._ocr_busy = False
        self._recording = False

        # LLM 上下文（按时间顺序的分段）
        self._voice_blocks: List[dict] = []
        self._ocr_blocks: List[dict] = []
        self._seg_count = 0
        self._started_at = time.time()

        self._build_ui()
        self._on_theme(theme.mode)
        self._restore_geometry()
        theme.changed.connect(self._on_theme)
        self._uptime_timer = QTimer(self)
        self._uptime_timer.setInterval(1000)
        self._uptime_timer.timeout.connect(self._tick_uptime)
        self._uptime_timer.start()

    # ==================================================== UI 构建 ====

    def _fit_to_screen(self) -> None:
        """默认尺寸按屏幕可用区收敛。

        1280x720 @150% 这类小屏（可用高度只有 ~680 逻辑像素）上，
        固定 812 高的窗口会超出屏幕 → 底部被裁、内容区被挤小。
        """
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        w = max(380, min(478, area.width() - 40))
        h = max(480, min(812, area.height() - 36))
        self.resize(w, h)

    def _build_ui(self) -> None:
        outer = QWidget()
        outer_lay = QVBoxLayout(outer)
        outer_lay.setContentsMargins(14, 14, 14, 14)
        outer_lay.setSpacing(0)
        self.card = RootCard(radius=20)
        outer_lay.addWidget(self.card)
        self.setCentralWidget(outer)
        self.toaster = Toast(self)

        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(8)

        # ---- 行 1：品牌 + 窗口按钮 ----
        self.brand_icon = QLabel()
        self.brand_icon.setFixedSize(26, 26)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        self.brand_title = QLabel("Local Record")
        self.brand_title.setObjectName("brandTitle")
        self.brand_sub = QLabel("本地录音 · 实时转写 · 智能问答")
        self.brand_sub.setObjectName("brandSub")
        brand_text.addWidget(self.brand_title)
        brand_text.addWidget(self.brand_sub)

        self.theme_btn = IconButton("sun", "text_dim", 17, 2.0, "切换深色/浅色主题")
        self.theme_btn.clicked.connect(self.theme_toggled.emit)
        self.btn_min = IconButton("minus", "text_dim", 17, 2.2, "最小化")
        self.btn_min.clicked.connect(self.showMinimized)
        self.btn_close = IconButton("x", "text_dim", 17, 2.2,
                                   "隐藏到托盘（托盘菜单可退出）")
        self.btn_close.clicked.connect(self.hide)

        head = QHBoxLayout()
        head.setSpacing(9)
        head.addWidget(self.brand_icon)
        head.addLayout(brand_text)
        head.addStretch(1)
        head.addWidget(self.theme_btn)
        head.addWidget(self.btn_min)
        head.addWidget(self.btn_close)
        lay.addLayout(head)

        # ---- 行 2：运行状态 ----
        self.run_pill = StatusPill("运行中", "running")
        self.asr_pill = StatusPill("ASR 加载中", "loading")
        self.asr_pill.setToolTip("语音识别模型状态")
        self.llm_pill = StatusPill("大模型等待中", "idle")
        self.llm_pill.setToolTip("本地大模型状态")
        self.uptime_label = QLabel("00:00")
        self.uptime_label.setObjectName("metaText")
        self.uptime_label.setToolTip("本程序已运行时长")

        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        status_row.addWidget(self.run_pill)
        status_row.addWidget(self.asr_pill)
        status_row.addWidget(self.llm_pill)
        status_row.addStretch(1)
        status_row.addWidget(icon_label("activity", "text_faint", 12))
        status_row.addWidget(self.uptime_label)
        lay.addLayout(status_row)

        # ---- 行 3：分段切换 ----
        seg_bar = QFrame()
        seg_bar.setObjectName("segBar")
        seg_lay = QHBoxLayout(seg_bar)
        seg_lay.setContentsMargins(3, 3, 3, 3)
        seg_lay.setSpacing(3)
        self.seg_group = QButtonGroup(self)
        self.seg_group.setExclusive(True)
        seg_defs = (("语音", TAB_VOICE), ("录音库", TAB_LIBRARY), ("文字识别", TAB_OCR))
        self.seg_buttons: List[QPushButton] = []
        for text, idx in seg_defs:
            btn = QPushButton(text)
            btn.setObjectName("segBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(29)
            # 必须显式给 id（=页号）：不给的话 QButtonGroup 会自动分配负数 id，
            # 而 stack.setCurrentIndex(负数) 不做任何事 → 点标签页没反应。
            self.seg_group.addButton(btn, idx)
            seg_lay.addWidget(btn, 1)
            self.seg_buttons.append(btn)
        self.seg_buttons[TAB_VOICE].setChecked(True)
        self.seg_group.idClicked.connect(self._on_seg)
        lay.addWidget(seg_bar)

        # ---- 页面堆叠 ----
        self.stack = QStackedWidget()
        self.voice_page = self._build_voice_page()
        self.library_page = LibraryPage(self.player, self.library_dir)
        # 录音被删除时，语音页的"最近一次录音"条也要清掉引用，
        # 否则 ▶ 还指向已删除的文件，点了必然失败
        self.library_page.recordingDeleted.connect(self._on_recording_deleted)
        self.ocr_page = self._build_ocr_page()
        self.stack.addWidget(self.voice_page)
        self.stack.addWidget(self.library_page)
        self.stack.addWidget(self.ocr_page)
        lay.addWidget(self.stack, 1)

        # ---- 底部：流动进度线 + 活动行 ----
        self.progress = ProgressLine()
        lay.addWidget(self.progress)
        self.activity_label = QLabel("已就绪，等待操作")
        self.activity_label.setObjectName("metaText")
        foot = QHBoxLayout()
        foot.setSpacing(7)
        foot.addWidget(self.activity_label)
        foot.addStretch(1)
        grip = QSizeGrip(self.card)
        grip.setFixedSize(12, 12)
        foot.addWidget(grip, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        lay.addLayout(foot)

        self.set_recording(False)
        self.set_chat_busy(False)

    # ---------------------------------------------- 语音页 ----

    def _build_voice_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        # 录音卡
        rec_card = QFrame()
        rec_card.setObjectName("card")
        rec_lay = QVBoxLayout(rec_card)
        rec_lay.setContentsMargins(12, 9, 12, 9)
        rec_lay.setSpacing(7)

        top = QHBoxLayout()
        top.setSpacing(14)
        self.record_btn = RecordButton(64)
        self.record_btn.clicked.connect(self.toggle_record_clicked.emit)
        top.addWidget(self.record_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        info = QVBoxLayout()
        info.setSpacing(2)
        self.rec_state_label = QLabel("准备就绪")
        self.rec_state_label.setObjectName("recStateText")
        self.timer_label = QLabel("00:00.0")
        self.timer_label.setObjectName("bigTimer")
        self.rec_hint_label = QLabel("点击圆形按钮开始录音 · 双击悬浮球同样可以")
        self.rec_hint_label.setObjectName("hintLabel")
        self.rec_hint_label.setWordWrap(True)
        info.addWidget(self.rec_state_label)
        info.addWidget(self.timer_label)
        info.addWidget(self.rec_hint_label)
        top.addLayout(info, 1)
        rec_lay.addLayout(top)

        self.level_meter = LevelMeter(30)
        self.level_meter.setFixedHeight(32)
        rec_lay.addWidget(self.level_meter)
        lay.addWidget(rec_card)

        # 最近一次录音（试听）
        self.mini_player = MiniPlayer(self.player)
        self.mini_player.setVisible(False)
        lay.addWidget(self.mini_player)

        # 转写卡
        note_card = QFrame()
        note_card.setObjectName("card")
        note_lay = QVBoxLayout(note_card)
        note_lay.setContentsMargins(10, 8, 10, 8)
        note_lay.setSpacing(6)

        note_head = QHBoxLayout()
        note_head.setSpacing(7)
        note_head.addWidget(icon_label("audio-lines", "accent", 13))
        note_head.addWidget(section_label("实时转写"))
        self.seg_count_label = QLabel("0 段")
        self.seg_count_label.setObjectName("metaText")
        note_head.addWidget(self.seg_count_label)
        note_head.addStretch(1)
        self.copy_btn = IconButton("copy", "text_dim", 15, 2.0, "复制全部转写")
        self.copy_btn.clicked.connect(self._copy_transcript)
        note_head.addWidget(self.copy_btn)
        self.clear_btn = IconButton("trash", "text_dim", 15, 2.0, "清空转写与对话")
        self.clear_btn.clicked.connect(self._clear_transcript)
        note_head.addWidget(self.clear_btn)
        note_lay.addLayout(note_head)

        self.note_view = QTextBrowser()
        self.note_view.setOpenExternalLinks(False)
        self.note_view.setPlaceholderText(
            "点上面的圆形按钮开始录音，说话后文字会实时出现在这里。")
        self.note_view.document().setDocumentMargin(4)
        note_lay.addWidget(self.note_view, 1)
        lay.addWidget(note_card, 1)

        # 会议纪要 + 问答
        self.summary_btn = QPushButton("  生成会议纪要")
        self.summary_btn.setObjectName("softBtn")
        self.summary_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.summary_btn.setIcon(lucide_icon("clipboard-list", theme.hex("accent"), 34, 2.0))
        self.summary_btn.setIconSize(QSize(17, 17))
        self.summary_btn.setToolTip("按会议纪要格式整理：重点内容 / 待办事项 / 风险 / 决议")
        self.summary_btn.clicked.connect(self.request_summary.emit)
        lay.addWidget(self.summary_btn)

        self.question_edit = QLineEdit()
        self.question_edit.setPlaceholderText("在这里输入问题，问这次转写的内容…")
        self.question_edit.setFixedHeight(33)
        self.question_edit.returnPressed.connect(self._on_ask)
        self.locate_btn = IconButton("clock", "text_dim", 16, 2.1,
                                    "按输入的问题定位到转写时间点", "roundBtn")
        self.locate_btn.setFixedSize(33, 33)
        self.locate_btn.clicked.connect(self._on_locate)
        self.ask_btn = QPushButton("发送")
        self.ask_btn.setObjectName("primaryBtn")
        self.ask_btn.setFixedHeight(33)
        self.ask_btn.clicked.connect(self._on_ask)
        ask_row = QHBoxLayout()
        ask_row.setSpacing(8)
        ask_row.addWidget(self.question_edit, 1)
        ask_row.addWidget(self.locate_btn)
        ask_row.addWidget(self.ask_btn)
        lay.addLayout(ask_row)
        return page

    # ---------------------------------------------- OCR 页 ----

    def _build_ocr_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self.upload_btn = DropZone("scan-text", "上传图片 / PDF 开始识别",
                                   "也可以把文件直接拖进窗口")
        self.upload_btn.clicked.connect(self._on_upload)
        lay.addWidget(self.upload_btn)

        ocr_card = QFrame()
        ocr_card.setObjectName("card")
        ocr_lay = QVBoxLayout(ocr_card)
        ocr_lay.setContentsMargins(10, 8, 10, 8)
        ocr_lay.setSpacing(6)
        ocr_head = QHBoxLayout()
        ocr_head.setSpacing(7)
        ocr_head.addWidget(icon_label("scan-text", "accent", 13))
        ocr_head.addWidget(section_label("识别文本"))
        ocr_head.addStretch(1)
        self.ocr_copy_btn = IconButton("copy", "text_dim", 15, 2.0, "复制识别文本")
        self.ocr_copy_btn.clicked.connect(self._copy_ocr)
        ocr_head.addWidget(self.ocr_copy_btn)
        self.ocr_clear_btn = IconButton("trash", "text_dim", 15, 2.0, "清空识别文本")
        self.ocr_clear_btn.clicked.connect(self._clear_ocr)
        ocr_head.addWidget(self.ocr_clear_btn)
        ocr_lay.addLayout(ocr_head)

        self.ocr_view = QTextBrowser()
        self.ocr_view.setPlaceholderText("识别结果会显示在这里（支持图片与多页 PDF）。")
        self.ocr_view.document().setDocumentMargin(4)
        ocr_lay.addWidget(self.ocr_view, 1)
        lay.addWidget(ocr_card, 1)

        # 文档问答：识别结果主要用途是"提问"，不做摘要，所以这里不放摘要按钮，
        # 而是把"在哪儿输入问题"写得明明白白（用户反馈过不知道能提问）
        ask_title = QLabel("文档问答")
        ask_title.setObjectName("cardTitle")
        ask_hint = QLabel("在下面输入你想问的问题，AI 只依据上面识别出的文字回答"
                          "（不用先做摘要）")
        ask_hint.setObjectName("hintLabel")
        ask_hint.setWordWrap(True)
        ask_head = QHBoxLayout()
        ask_head.setSpacing(8)
        ask_head.addWidget(icon_label("message-circle-question", "accent", 13))
        ask_head.addWidget(ask_title)
        ask_head.addStretch(1)
        lay.addLayout(ask_head)
        lay.addWidget(ask_hint)

        self.ocr_question_edit = QLineEdit()
        self.ocr_question_edit.setPlaceholderText(
            "在这里输入问题，例如：这份合同的付款方式和期限是什么？")
        self.ocr_question_edit.setFixedHeight(33)
        self.ocr_question_edit.returnPressed.connect(self._on_ocr_ask)
        self.ocr_ask_btn = QPushButton("提问")
        self.ocr_ask_btn.setObjectName("primaryBtn")
        self.ocr_ask_btn.setFixedHeight(33)
        self.ocr_ask_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ocr_ask_btn.clicked.connect(self._on_ocr_ask)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.ocr_question_edit, 1)
        row.addWidget(self.ocr_ask_btn)
        lay.addLayout(row)
        return page

    # ==================================================== 内部槽 ====

    def _on_seg(self, idx: int) -> None:
        # 双保险：即使拿到非法 id（例如某个按钮漏设 id）也不要静默失效
        if not (0 <= idx < self.stack.count()):
            log.warning("分段按钮传来非法 id=%s，已忽略", idx)
            return
        self.stack.setCurrentIndex(idx)
        if idx == TAB_LIBRARY:
            self.library_page.refresh()

    def _on_theme(self, _mode: str) -> None:
        self.brand_icon.setPixmap(
            QPixmap.fromImage(make_app_image(64)).scaled(
                26, 26, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        self.theme_btn.set_icon_name("moon" if theme.is_dark else "sun")
        self.summary_btn.setIcon(lucide_icon("clipboard-list", theme.hex("accent"), 34, 2.0))
        self._render_voice()
        self._render_ocr()

    def _tick_uptime(self) -> None:
        self.uptime_label.setText(fmt_mmss(time.time() - self._started_at))

    def _on_ask(self) -> None:
        text = self.question_edit.text().strip()
        if not text:
            self.toast("先输入一个问题", "warn")
            return
        self.question_edit.clear()
        self.append_chat("你", text)
        self.ask_question.emit(text)

    def _on_locate(self) -> None:
        text = self.question_edit.text().strip()
        if not text:
            self.toast("在输入框写下要定位的问题，再点定位", "warn")
            return
        self.append_chat("定位请求", text)
        self.request_locate.emit(text)

    def _on_ocr_ask(self) -> None:
        text = self.ocr_question_edit.text().strip()
        if not text:
            self.toast("先输入一个问题", "warn")
            return
        self.ocr_question_edit.clear()
        self.append_ocr_chat("你", text)
        self.ocr_ask_question.emit(text)

    def _on_recording_deleted(self, path) -> None:
        """录音库删掉一条录音后：清掉语音页"最近一次录音"条的引用。"""
        self.mini_player.forget(path)
        if self.mini_player.current_path() is None:
            self.mini_player.setVisible(False)

    def show_tab(self, index: int) -> None:
        """切换到指定页（语音 0 / 录音库 1 / 文字识别 2）。"""
        if 0 <= index < self.stack.count():
            self.seg_buttons[index].setChecked(True)
            self._on_seg(index)

    def pick_ocr_file(self) -> None:
        """打开文件选择框（供托盘/悬浮球菜单调用）。"""
        self.show_tab(TAB_OCR)
        self._on_upload()

    def _on_upload(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择文件", "",
            "图片或 PDF (*.png *.jpg *.jpeg *.bmp *.webp *.pdf)")
        if not path:
            return
        if path.lower().endswith(".pdf"):
            self.open_pdf_requested.emit(path)
        else:
            self.open_image_requested.emit(path)

    def _copy_transcript(self) -> None:
        text = "\n".join(
            f"[{b['no']}] {fmt_time(b['start'])} {b['text']}"
            for b in self._voice_blocks if b["kind"] == "seg")
        if not text:
            self.toast("还没有可复制的转写", "warn")
            return
        QGuiApplication.clipboard().setText(text)
        self.toast("转写已复制到剪贴板", "ok")

    def _copy_ocr(self) -> None:
        text = "\n\n".join(b["text"] for b in self._ocr_blocks if b["kind"] == "ocr")
        if not text:
            self.toast("还没有可复制的识别文本", "warn")
            return
        QGuiApplication.clipboard().setText(text)
        self.toast("识别文本已复制", "ok")

    def _clear_transcript(self) -> None:
        if not self._voice_blocks:
            return
        self._voice_blocks.clear()
        self._seg_count = 0
        self.seg_count_label.setText("0 段")
        self._render_voice()
        self.clear_transcript.emit()
        self.toast("已清空转写区", "ok")

    def _clear_ocr(self) -> None:
        if not self._ocr_blocks:
            return
        self._ocr_blocks.clear()
        self._render_ocr()
        self.toast("已清空识别区", "ok")

    # ==================================================== 加载界面 ====

    def _run_pill_state(self) -> None:
        """按当前状态刷新"运行中"胶囊（录音 > 忙碌 > 就绪）。"""
        if self._recording:
            self.run_pill.set_state("record", "录音中")
        elif self._busy or self._ocr_busy:
            self.run_pill.set_state("busy", "处理中")
        else:
            self.run_pill.set_state("running", "运行中")

    # ==================================================== 录音状态 ====

    def set_recording(self, recording: bool) -> None:
        self._recording = recording
        self.record_btn.set_active(recording)
        self.level_meter.set_active(recording)
        if recording:
            self.rec_state_label.setText("正在录音")
            self.rec_hint_label.setText("再次点击即可停止，音频会自动保存到录音库")
        else:
            self.rec_state_label.setText("准备就绪")
            self.timer_label.setText("00:00.0")
            self.rec_hint_label.setText("点击圆形按钮开始录音 · 双击悬浮球同样可以")
        self._run_pill_state()

    def update_recording(self, elapsed: float, level: float) -> None:
        """主线程定时器调用：刷新计时器与电平条（"在运行"的直观证据）。"""
        self.timer_label.setText(fmt_timer(elapsed))
        self.level_meter.push(level)
        self.record_btn.set_level(level)

    def set_run_state(self, state: str, text: Optional[str] = None) -> None:
        self.run_pill.set_state(state, text)

    def note_recording_saved(self, path: Path, autoplay: bool = False) -> None:
        """录音结束后：语音页出现"最近一次录音"卡片，并在录音库中选中它。"""
        self.mini_player.show_clip(path)
        self.mini_player.setVisible(True)
        self.library_page.note_saved(path, autoplay=autoplay)
        self.toast(f"已保存 {path.name}，点 ▶ 可立即回放", "ok")
        self.set_activity(f"已保存 {path.name}")

    def set_activity(self, text: str) -> None:
        self.activity_label.setText(text)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.progress.set_active(busy or self._ocr_busy)
        self._run_pill_state()

    def toast(self, text: str, kind: str = "info", ms: int = 2600) -> None:
        """轻量浮层提示（不打断操作）。"""
        self.toaster.pop(text, kind, ms)

    # ==================================================== 转写/对话 ====

    @property
    def transcript_items(self) -> List[dict]:
        return [{"text": b["text"], "start": b["start"], "end": b["end"]}
                for b in self._voice_blocks if b["kind"] == "seg"]

    def add_transcript(self, text: str, start: float, end: float) -> None:
        self._seg_count += 1
        self._voice_blocks.append({
            "kind": "seg", "text": text, "start": start, "end": end,
            "no": self._seg_count, "highlight": False,
        })
        self.seg_count_label.setText(f"{self._seg_count} 段")
        self._render_voice(stick_bottom=True)

    def append_chat(self, role: str, text: str) -> None:
        self._voice_blocks.append({
            "kind": "chat", "role": role, "text": text,
            "variant": "error" if role in ("错误",) else "normal",
            "highlight": False,
        })
        self._render_voice(stick_bottom=True)

    def append_ocr(self, text: str) -> None:
        self._ocr_blocks.append({"kind": "ocr", "text": text})
        self._render_ocr(stick_bottom=True)

    def append_ocr_chat(self, role: str, text: str) -> None:
        self._ocr_blocks.append({
            "kind": "chat", "role": role, "text": text,
            "variant": "error" if role == "错误" else "normal",
        })
        self._render_ocr(stick_bottom=True)

    def highlight_transcript(self, indices: List[int]) -> None:
        """把时间定位命中的段落高亮并滚动过去。"""
        wanted = {int(i) for i in indices}
        first = None
        for block in self._voice_blocks:
            if block["kind"] != "seg":
                continue
            hit = block["no"] in wanted
            block["highlight"] = hit
            if hit and first is None:
                first = block["no"]
        self._render_voice(stick_bottom=False)
        if first is not None:
            self.note_view.scrollToAnchor(f"seg{first}")
            self.toast(f"已高亮 {len(wanted)} 处相关段落", "ok")

    def clear_transcript_view(self) -> None:
        self._clear_transcript()

    # ==================================================== 渲染 HTML ====

    def _render_voice(self, stick_bottom: bool = True) -> None:
        p = theme.palette
        parts = ['<div style="font-size:12px;">']
        for b in self._voice_blocks:
            if b["kind"] == "seg":
                ts = fmt_time(b["start"])
                bg = (f'background:{theme.hex("accent", 0.18)};'
                      f'border-left:3px solid {p["accent"]};padding:2px 6px;'
                      'border-radius:6px;') if b.get("highlight") else ""
                parts.append(
                    f'<div style="{bg}margin:0 0 6px 0;line-height:1.6;">'
                    f'<a name="seg{b["no"]}"></a>'
                    f'<span style="color:{p["text_faint"]};font-size:10px;'
                    f'font-family:Consolas,monospace;">{ts}</span>'
                    f'<span style="color:{p["text_dim"]};font-size:9px;'
                    f'background:{p["surface_2"]};border-radius:4px;'
                    f'padding:1px 5px;margin-left:6px;">#{b["no"]}</span>'
                    f'<span style="color:{p["text"]};margin-left:7px;">'
                    f'{html.escape(b["text"])}</span></div>')
            else:
                err = b.get("variant") == "error"
                accent = p["danger"] if err else p["accent"]
                # 大模型输出是 Markdown（会议纪要有标题/加粗/表格），
                # 用轻量渲染器转成 HTML，否则用户会看到一堆 ## 和 |
                body = to_html(b["text"], p)
                parts.append(
                    f'<div style="background:{p["surface_2"]};'
                    f'border:1px solid {p["card_border"]};border-radius:11px;'
                    'padding:7px 9px;margin:7px 0;line-height:1.6;">'
                    f'<span style="color:{accent};font-weight:700;font-size:10px;">'
                    f'{html.escape(b["role"])}</span><br/>'
                    f'<span style="color:{p["text"]};">{body}</span></div>')
        parts.append("</div>")
        self._set_html(self.note_view, "".join(parts), stick_bottom)

    def _render_ocr(self, stick_bottom: bool = True) -> None:
        p = theme.palette
        parts = ['<div style="font-size:13px;">']
        for b in self._ocr_blocks:
            if b["kind"] == "ocr":
                body = html.escape(b["text"]).replace("\n", "<br/>")
                parts.append(
                    f'<div style="color:{p["text"]};line-height:1.65;margin:0 0 6px 0;">'
                    f'{body}</div>'
                    f'<div style="height:1px;background:{p["card_border"]};'
                    'margin:8px 0;"></div>')
            else:
                err = b.get("variant") == "error"
                accent = p["danger"] if err else p["accent"]
                body = to_html(b["text"], p)
                parts.append(
                    f'<div style="background:{p["surface_2"]};'
                    f'border:1px solid {p["card_border"]};border-radius:11px;'
                    'padding:8px 11px;margin:9px 0;line-height:1.7;">'
                    f'<span style="color:{accent};font-weight:700;font-size:11px;">'
                    f'{html.escape(b["role"])}</span><br/>'
                    f'<span style="color:{p["text"]};">{body}</span></div>')
        parts.append("</div>")
        self._set_html(self.ocr_view, "".join(parts), stick_bottom)

    @staticmethod
    def _set_html(view: QTextBrowser, body: str, stick_bottom: bool) -> None:
        if not body or body == '<div style="font-size:13px;"></div>':
            view.clear()
            return
        bar = view.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 28
        view.setHtml(body)
        if stick_bottom or at_bottom:
            bar.setValue(bar.maximum())

    @property
    def ocr_text(self) -> str:
        return "\n\n".join(b["text"] for b in self._ocr_blocks if b["kind"] == "ocr")

    # ==================================================== 状态指示 ====

    def set_asr_status(self, ok: bool, message: str) -> None:
        if ok:
            self.asr_pill.set_state("ok", "ASR 就绪", message)
        else:
            self.asr_pill.set_state("error", "ASR 不可用", message)
            self.toaster.pop("语音识别模型未就绪，详见日志", "error")

    def set_llm_status(self, ok: bool, message: str) -> None:
        self._llm_ready = ok
        if ok:
            self.llm_pill.set_state("ok", "大模型就绪", message)
            self.progress.set_active(self._busy or self._ocr_busy)
        else:
            self.llm_pill.set_state("error", "大模型不可用", message)
        self._set_llm_enabled()

    def set_llm_status_text(self, text: str) -> None:
        # 加载过程中的文案（如 "大模型 45%"）用加载胶囊 + 流动进度线表达
        short = (text.replace("本地大模型加载中", "大模型")
                     .replace("正在启动", "")
                     .replace("（预计", "（"))
        loading = "%" in short or "加载" in short or "启动" in short
        self.llm_pill.set_state("loading" if loading else "idle", short)
        if loading:
            self.progress.set_active(True)
        self.set_activity(short)

    def set_llm_progress(self, pct: int) -> None:
        self.llm_pill.set_tooltip(f"大模型加载进度 {pct}%")

    def _set_llm_enabled(self) -> None:
        ok = self._llm_ready and not self._busy
        for w in (self.ask_btn, self.summary_btn, self.question_edit,
                  self.locate_btn, self.ocr_ask_btn,
                  self.ocr_question_edit):
            w.setEnabled(ok)

    def set_chat_busy(self, busy: bool) -> None:
        self._busy = busy
        self._set_llm_enabled()
        self.progress.set_active(busy or self._ocr_busy)
        self.ask_btn.setText("思考中…" if busy else "发送")
        self.ocr_ask_btn.setText("思考中…" if busy else "提问")
        self._run_pill_state()
        if busy:
            self.set_activity("大模型正在生成回答…")

    def set_ocr_busy(self, busy: bool) -> None:
        self._ocr_busy = busy
        self.upload_btn.setEnabled(not busy)
        self.upload_btn.set_text(
            "正在识别，请稍候…" if busy else "上传图片 / PDF 开始识别",
            "大图 / 多页 PDF 需要一点时间" if busy else "也可以把文件直接拖进窗口")
        self.progress.set_active(busy or self._busy)
        self._run_pill_state()

    # ==================================================== 结果弹窗 ====

    def show_llm_result(self, title: str, text: str, error: bool = False) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setModal(True)
        dlg.resize(500, 420)
        dlg.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(icon_label("alert" if error else "sparkles",
                                  "danger" if error else "accent", 17))
        head.addWidget(section_label(title.upper() if not error else "出错"))
        head.addStretch(1)

        view = QTextEdit()
        view.setReadOnly(True)
        view.setPlainText(text)

        copy_btn = QPushButton("  复制")
        copy_btn.setObjectName("softBtn")
        copy_btn.setIcon(lucide_icon("copy", theme.hex("text"), 30, 2.0))
        copy_btn.setIconSize(QSize(15, 15))
        ok_btn = QPushButton("关闭" if error else "好")
        ok_btn.setObjectName("dangerBtn" if error else "primaryBtn")

        def _copy() -> None:
            QGuiApplication.clipboard().setText(text)
            copy_btn.setText("  已复制")
            copy_btn.setIcon(lucide_icon("check", theme.hex("success"), 30, 2.2))

        copy_btn.clicked.connect(_copy)
        ok_btn.clicked.connect(dlg.accept)
        ok_btn.setFixedHeight(34)
        copy_btn.setFixedHeight(34)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(copy_btn)
        row.addStretch(1)
        row.addWidget(ok_btn)

        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)
        lay.addLayout(head)
        lay.addWidget(view, 1)
        lay.addLayout(row)
        dlg.exec()

    # ==================================================== 窗口拖动 ====

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and e.position().y() < 58:
            self._drag_pos = (e.globalPosition().toPoint()
                              - self.frameGeometry().topLeft())

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._drag_pos is not None and (e.buttons() & Qt.MouseButton.LeftButton):
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        self._drag_pos = None

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        if self.toaster.isVisible():
            self.toaster.reposition()

    # ---------------- 窗口几何记忆 ----------------

    def _restore_geometry(self) -> None:
        """恢复上次的窗口位置/大小；首次启动时居中显示。"""
        settings = QSettings("LocalRecord", "LocalRecord")
        geo = settings.value("win/geometry")
        if geo is not None:
            try:
                if self.restoreGeometry(geo):
                    return
            except (TypeError, RuntimeError):
                pass
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.move(area.center() - self.rect().center())

    def _save_geometry(self) -> None:
        QSettings("LocalRecord", "LocalRecord").setValue(
            "win/geometry", self.saveGeometry())

    def hideEvent(self, e) -> None:  # noqa: N802
        self._save_geometry()
        super().hideEvent(e)

    def closeEvent(self, e) -> None:  # noqa: N802
        self._save_geometry()
        super().closeEvent(e)

    # ==================================================== 拖放 ====

    def dragEnterEvent(self, e) -> None:  # noqa: N802
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:  # noqa: N802
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths)
            e.acceptProposedAction()
