"""主题系统：设计令牌 + 全局样式表 + 运行时切换。

设计思路
--------
* 所有颜色/圆角/字体集中在本模块的 :data:`DARK` / :data:`LIGHT` 调色板里；
* 控件不写内联样式，只设置 ``objectName`` 与动态属性（如 ``state``、
  ``recording``），样式由 :func:`build_qss` 生成的全局 QSS 统一驱动；
* 因此切换主题只要重新 ``apply_theme()`` 一次，全部界面立即换肤，
  自绘控件（波形、悬浮球等）监听 :attr:`theme.changed` 重绘即可。

颜色一律用 ``#RRGGBB`` 表示；需要透明度时用 :func:`with_alpha` 生成
``#AARRGGBB``（Qt 样式表与 QColor 都支持该写法，比 ``rgba()`` 稳妥）。
"""
from __future__ import annotations

from string import Template
from typing import Dict

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QWidget

FONT_STACK = ('"Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI", '
              '"Microsoft YaHei", "PingFang SC", sans-serif')

# ---------------------------------------------------------------- 调色板 ----

DARK: Dict[str, str] = {
    "window": "#05070B",        # 窗口外的透明区域底色（阴影）
    "card_a": "#161D28",        # 主卡片渐变起点
    "card_b": "#0C1119",        # 主卡片渐变终点
    "card_border": "#26303F",
    "surface": "#1A2230",       # 内容卡片
    "surface_2": "#212B3B",     # 稍亮的内容卡片 / 输入框
    "surface_hover": "#27313F",
    "text": "#E9EDF5",
    "text_dim": "#94A1B6",
    "text_faint": "#5E6A7C",
    "accent": "#6D8BFF",
    "accent_2": "#A96BFF",
    "on_accent": "#FFFFFF",
    "success": "#3ED598",
    "warning": "#FFB020",
    "danger": "#FF5C6C",
    "record_a": "#FF6B6B",
    "record_b": "#D81E37",
    "track": "#26303F",
    "seg_active": "#2C3A4F",
    "scroll": "#3A4658",
    "scroll_hover": "#4E5B70",
    "select": "#2C4270",
    "shadow": "#000000",
    "highlight": "#FFFFFF",     # 顶部高光
}

LIGHT: Dict[str, str] = {
    "window": "#DDE3EC",
    "card_a": "#FFFFFF",
    "card_b": "#F4F6FB",
    "card_border": "#DCE2EC",
    "surface": "#F2F4F9",
    "surface_2": "#E9EDF5",
    "surface_hover": "#E2E8F3",
    "text": "#101725",
    "text_dim": "#5C6A80",
    "text_faint": "#93A0B2",
    "accent": "#3B6BFF",
    "accent_2": "#8B4DFF",
    "on_accent": "#FFFFFF",
    "success": "#12A150",
    "warning": "#C77700",
    "danger": "#E5484D",
    "record_a": "#FF5A5F",
    "record_b": "#D81E37",
    "track": "#DCE2EC",
    "seg_active": "#FFFFFF",
    "scroll": "#BFC8D6",
    "scroll_hover": "#A6B1C2",
    "select": "#C7D8FF",
    "shadow": "#0B1220",
    "highlight": "#FFFFFF",
}


def with_alpha(color: str, alpha: float) -> str:
    """``#RRGGBB`` + 透明度 → ``#AARRGGBB``（Qt 样式表可直接使用）。"""
    c = QColor(color)
    a = max(0, min(255, int(round(alpha * 255))))
    return f"#{a:02x}{c.red():02x}{c.green():02x}{c.blue():02x}"


# ------------------------------------------------------------------ QSS ----

_QSS = Template("""
/* ---------- 基础 ---------- */
QWidget {
    background: transparent;
    color: $text;
    font-family: $font;
    font-size: 12px;
}
QToolTip {
    background: $surface;
    color: $text;
    border: 1px solid $card_border;
    border-radius: 6px;
    padding: 5px 8px;
}
QMainWindow, QDialog { background: transparent; }

/* ---------- 主卡片 ---------- */
QFrame#rootCard { background: transparent; }

/* ---------- 标题区 ---------- */
QLabel#brandTitle { font-size: 13.5px; font-weight: 600; color: $text; }
QLabel#brandSub { font-size: 10px; color: $text_faint; }
QLabel#sectionLabel {
    font-size: 10px; font-weight: 600; color: $text_dim;
    letter-spacing: 0.5px;
}
QLabel#hintLabel { font-size: 10px; color: $text_faint; }
QLabel#bigTimer {
    font-size: 21px; font-weight: 600; color: $text;
    font-family: "Consolas", "Cascadia Mono", monospace;
}
QLabel#recStateText { font-size: 12px; font-weight: 600; color: $text; }
QLabel#metaText { font-size: 10px; color: $text_dim; }

/* ---------- 状态胶囊 ---------- */
QFrame#statusPill {
    background: $surface; border: 1px solid $card_border; border-radius: 13px;
}
QLabel#pillText { font-size: 10px; font-weight: 600; color: $text_dim; }
QFrame#statusPill[state="ok"] QLabel#pillText { color: $text; }
QFrame#statusPill[state="running"] QLabel#pillText { color: $text; }
QFrame#statusPill[state="record"] QLabel#pillText { color: $danger; }
QFrame#statusPill[state="busy"] QLabel#pillText { color: $warning; }
QFrame#statusPill[state="loading"] QLabel#pillText { color: $warning; }
QFrame#statusPill[state="error"] QLabel#pillText { color: $danger; }

/* ---------- 卡片内标题 / 列表标题 ---------- */
QLabel#cardTitle { font-size: 12px; font-weight: 600; color: $text; }
QLabel#rowTitle { font-size: 11.5px; font-weight: 600; color: $text; }

/* ---------- OCR 上传区 ---------- */
QFrame#dropZone {
    background: $surface_2; border: 2px dashed $card_border; border-radius: 14px;
}
QFrame#dropZone:hover { border: 2px dashed $accent; background: $surface_hover; }
QLabel#dropTitle { font-size: 12px; font-weight: 600; color: $text; }
QLabel#dropHint { font-size: 10px; color: $text_faint; }

/* ---------- 小圆按钮（最小化/关闭/主题） ---------- */
QPushButton#iconBtn {
    background: transparent; border: none; border-radius: 9px;
    padding: 5px 7px;
}
QPushButton#iconBtn:hover { background: $surface_hover; }
QPushButton#iconBtn:pressed { background: $surface_2; }
QPushButton#iconBtn[danger="true"]:hover { background: $danger; }

/* ---------- 分段切换（语音 / 录音库 / 文字识别） ---------- */
QFrame#segBar {
    background: $surface; border: 1px solid $card_border; border-radius: 12px;
}
QPushButton#segBtn {
    background: transparent; border: none; border-radius: 9px;
    color: $text_dim; font-size: 12px; font-weight: 600; padding: 5px 4px;
}
QPushButton#segBtn:hover:!checked { color: $text; }
QPushButton#segBtn:checked {
    background: $seg_active; color: $accent;
    border: 1px solid $card_border;
}

/* ---------- 内容卡片 ---------- */
QFrame#card {
    background: $surface; border: 1px solid $card_border; border-radius: 14px;
}
QFrame#card[emphasis="true"] {
    background: $surface; border: 1px solid $accent;
}
QFrame#rowCard {
    background: $surface; border: 1px solid $card_border; border-radius: 10px;
}
QFrame#rowCard:hover { background: $surface_hover; }

/* ---------- 文本区 ---------- */
QTextBrowser {
    background: $surface_2; border: 1px solid $card_border;
    border-radius: 10px; padding: 6px 8px;
    selection-background-color: $select; selection-color: $text;
}
QTextEdit {
    background: $surface_2; border: 1px solid $card_border;
    border-radius: 11px; padding: 8px 10px;
    selection-background-color: $select; selection-color: $text;
}
QPlainTextEdit {
    background: $surface_2; border: 1px solid $card_border;
    border-radius: 11px; padding: 8px 10px;
}

/* ---------- 输入框 ---------- */
QLineEdit {
    background: $surface_2; border: 1px solid $card_border;
    border-radius: 9px; padding: 4px 9px; font-size: 12px;
    selection-background-color: $select; selection-color: $text;
}
QLineEdit:focus { border: 1px solid $accent; }
QLineEdit:disabled { color: $text_faint; }
QComboBox {
    background: $surface_2; border: 1px solid $card_border; border-radius: 9px;
    padding: 5px 10px; color: $text;
}
QComboBox:hover { border: 1px solid $accent; }
QComboBox QAbstractItemView {
    background: $surface; border: 1px solid $card_border;
    selection-background-color: $accent; selection-color: $on_accent;
    outline: none; padding: 4px;
}

/* ---------- 通用按钮 ---------- */
QPushButton {
    background: $surface_2; color: $text; border: 1px solid $card_border;
    border-radius: 10px; padding: 7px 15px; font-size: 13px;
}
QPushButton:hover { background: $surface_hover; }
QPushButton:pressed { background: $surface; }
QPushButton:disabled { color: $text_faint; background: $surface; }

/* 主按钮：强调色 */
QPushButton#primaryBtn {
    background: $accent; color: $on_accent; border: none;
    border-radius: 9px; padding: 5px 18px; font-weight: 600;
}
QPushButton#primaryBtn:hover { background: $accent_hover; }
QPushButton#primaryBtn:pressed { background: $accent_press; }
QPushButton#primaryBtn:disabled { background: $accent_disabled; color: $text_faint; }

/* 次按钮：白底描边 */
QPushButton#softBtn {
    background: $surface_2; color: $text; border: 1px solid $card_border;
    border-radius: 9px; padding: 6px 12px; font-weight: 600;
}
QPushButton#softBtn:hover { background: $surface_hover; border: 1px solid $accent; }
QPushButton#softBtn:disabled { color: $text_faint; border: 1px solid $card_border; }

/* 幽灵按钮：纯文字 */
QPushButton#ghostBtn {
    background: transparent; border: none; color: $text_dim;
    padding: 4px 8px; font-size: 12px;
}
QPushButton#ghostBtn:hover { color: $accent; }

/* 危险按钮 */
QPushButton#dangerBtn {
    background: transparent; border: 1px solid $card_border; color: $danger;
    border-radius: 10px; padding: 8px 14px; font-weight: 600;
}
QPushButton#dangerBtn:hover { background: $record_b; color: #ffffff; border-color: $record_b; }

/* 上传区（OCR） */
QPushButton#dropZone {
    background: $surface_2; border: 2px dashed $card_border; border-radius: 14px;
    color: $text_dim; padding: 18px 10px; font-size: 13px;
}
QPushButton#dropZone:hover { border: 2px dashed $accent; color: $text; }

/* ---------- 播放控制 ---------- */
QPushButton#playBtn {
    background: $accent; border: none; border-radius: 21px;
}
QPushButton#playBtn:hover { background: $accent_hover; }
QPushButton#playBtn:pressed { background: $accent_press; }
QPushButton#playBtn:disabled { background: $surface_2; }

QPushButton#roundBtn {
    background: $surface_2; border: 1px solid $card_border; border-radius: 16px;
}
QPushButton#roundBtn:hover { background: $surface_hover; border: 1px solid $accent; }
QPushButton#roundBtn:disabled { background: $surface; }

/* 录音库行内播放按钮 */
QPushButton#rowPlayBtn {
    background: $surface_2; border: 1px solid $card_border; border-radius: 15px;
}
QPushButton#rowPlayBtn:hover { background: $surface_hover; border: 1px solid $accent; }
QPushButton#rowPlayBtn[active="true"] {
    background: $accent; border: 1px solid $accent;
}
QPushButton#rowPlayBtn:disabled { background: $surface; border: 1px solid $card_border; }

/* ---------- 滑块 ---------- */
QSlider { min-height: 18px; }
QSlider::groove:horizontal {
    height: 4px; background: $track; border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: $accent; border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 12px; margin: -5px 0; border-radius: 6px;
    background: $on_accent; border: 1px solid $card_border;
}
QSlider::handle:horizontal:hover { background: #ffffff; }
QSlider::handle:horizontal:disabled { background: $text_faint; }
QSlider::sub-page:horizontal:disabled { background: $track; }

/* ---------- 列表 / 滚动区 ---------- */
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical {
    background: $scroll; border-radius: 4px; min-height: 28px;
}
QScrollBar::handle:vertical:hover { background: $scroll_hover; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 2px; }
QScrollBar::handle:horizontal {
    background: $scroll; border-radius: 4px; min-width: 28px;
}
QScrollBar::handle:horizontal:hover { background: $scroll_hover; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }

/* ---------- 菜单 ---------- */
QMenu {
    background: $card_a; border: 1px solid $card_border;
    border-radius: 10px; padding: 6px;
}
QMenu::item {
    padding: 7px 22px 7px 14px; border-radius: 7px; color: $text;
}
QMenu::item:selected { background: $accent; color: $on_accent; }
QMenu::item:disabled { color: $text_faint; }
QMenu::separator { height: 1px; background: $card_border; margin: 5px 8px; }
QMenu::icon { padding-left: 8px; }

/* ---------- 进度条 ---------- */
QProgressBar {
    background: $track; border: none; border-radius: 3px;
    height: 6px; text-align: center; color: transparent;
}
QProgressBar::chunk { background: $accent; border-radius: 3px; }
""")


def build_qss(mode: str = "dark") -> str:
    """生成全局样式表。"""
    p = dict(DARK if mode == "dark" else LIGHT)
    p["font"] = FONT_STACK
    # 由基色派生的半透明 / 状态色（QSS 里不能直接算，先算好再代入）
    p["accent_hover"] = _shift(p["accent"], 0.10)
    p["accent_press"] = _shift(p["accent"], -0.12)
    p["accent_disabled"] = with_alpha(p["accent"], 0.22)
    p["accent_soft"] = with_alpha(p["accent"], 0.16)
    p["surface_soft"] = with_alpha(p["surface_2"], 0.75)
    return _QSS.substitute(p)


def _shift(color: str, amount: float) -> str:
    """把颜色整体变亮(正)/变暗(负)，amount 为 0~1 的比例。"""
    c = QColor(color)
    if amount >= 0:
        return c.lighter(int(100 + amount * 100)).name()
    return c.darker(int(100 - amount * 100)).name()


# ------------------------------------------------------------ 主题管理 ----

class ThemeManager(QObject):
    """全局主题：``theme.mode`` 为 ``dark`` / ``light``。"""

    changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._mode = "dark"
        self._app: QApplication | None = None
        self._palette: Dict[str, str] = DARK

    # ---- 属性 ----
    @property
    def mode(self) -> str:
        return self._mode

    @property
    def is_dark(self) -> bool:
        return self._mode == "dark"

    @property
    def palette(self) -> Dict[str, str]:
        return self._palette

    def color(self, token: str, alpha: float | None = None) -> QColor:
        """取颜色（供自绘控件使用），``alpha`` 为 0~1。"""
        c = QColor(self._palette.get(token, "#000000"))
        if alpha is not None:
            c.setAlphaF(max(0.0, min(1.0, alpha)))
        return c

    def hex(self, token: str, alpha: float | None = None) -> str:
        c = QColor(self._palette.get(token, "#000000"))
        if alpha is not None:
            return with_alpha(c.name(), alpha)
        return c.name()

    # ---- 应用 ----
    def apply(self, app: QApplication, mode: str | None = None) -> None:
        if mode in ("dark", "light"):
            self._mode = mode
        self._app = app
        self._palette = DARK if self._mode == "dark" else LIGHT
        app.setStyleSheet(build_qss(self._mode))
        self.changed.emit(self._mode)

    def toggle(self) -> str:
        self.set_mode("light" if self._mode == "dark" else "dark")
        return self._mode

    def set_mode(self, mode: str) -> None:
        if mode not in ("dark", "light") or mode == self._mode:
            return
        if self._app is None:
            self._mode = mode
            self._palette = DARK if mode == "dark" else LIGHT
            return
        self.apply(self._app, mode)


# 全局单例
theme = ThemeManager()


def repolish(widget: QWidget) -> None:
    """动态属性（如 state/recording）变化后刷新样式。"""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
