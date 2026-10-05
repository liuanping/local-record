"""自绘控件库：让界面"看起来在工作"的关键零件。

* :class:`RootCard`      主卡片（圆角渐变 + 描边 + 顶部高光）
* :class:`IconButton`    小圆图标按钮（主题切换自动重绘图标）
* :class:`Indicator`     状态圆点 / 旋转加载环（动画）
* :class:`StatusPill`    状态胶囊：圆点 + 文案（空闲/加载中/就绪/出错/运行中）
* :class:`ProgressLine`  不确定进度条（忙碌时来回流动的细线）
* :class:`RecordButton`  大圆录音按钮（录音中呼吸光环 + 实时电平外圈）
* :class:`LevelMeter`    实时电平柱状条
* :class:`Toast`         轻量浮层提示（不打断操作）

所有颜色都从 :mod:`app.theme` 取，主题切换时自动重绘。
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import (
    QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer, Signal,
)
from PySide6.QtGui import (
    QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient,
)
from PySide6.QtWidgets import (
    QAbstractButton, QFrame, QGraphicsDropShadowEffect, QGraphicsOpacityEffect,
    QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from .icons import lucide_icon, lucide_svg, render_svg_doc
from .theme import repolish, theme


# --------------------------------------------------------------- 主卡片 ----

class ThemeAware:
    """混入类：主题变化时自动重绘。

    用**绑定方法**连接 ``theme.changed``，控件被销毁时 Qt 会连同连接一起回收，
    不会出现"主题切换回调打到已删除控件"的崩溃。
    子类可覆盖 :meth:`_theme_repaint` 做更复杂的重建（如重设图标）。
    """

    def _theme_repaint(self) -> None:
        update = getattr(self, "update", None)
        if callable(update):
            update()

    def _on_theme_changed(self, _mode: str = "") -> None:
        self._theme_repaint()


class RootCard(ThemeAware, QFrame):
    """窗口主卡片：自绘圆角渐变 + 1px 描边 + 顶部高光 + 外阴影。"""

    def __init__(self, parent: Optional[QWidget] = None, radius: int = 18):
        super().__init__(parent)
        self.setObjectName("rootCard")
        self._radius = radius
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(46)
        shadow.setOffset(0, 14)
        shadow.setColor(QColor(0, 0, 0, 170 if theme.is_dark else 60))
        self.setGraphicsEffect(shadow)
        theme.changed.connect(self._on_theme)

    def _on_theme(self, _mode: str) -> None:
        eff = self.graphicsEffect()
        if isinstance(eff, QGraphicsDropShadowEffect):
            eff.setColor(QColor(0, 0, 0, 170 if theme.is_dark else 60))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, self._radius, self._radius)

        grad = QLinearGradient(r.topLeft(), QPointF(r.left(), r.bottom()))
        grad.setColorAt(0.0, theme.color("card_a"))
        grad.setColorAt(1.0, theme.color("card_b"))
        p.fillPath(path, grad)

        # 顶部玻璃高光
        hl = QLinearGradient(r.topLeft(), QPointF(r.left(), r.top() + r.height() * 0.42))
        hl.setColorAt(0.0, theme.color("highlight", 0.10 if theme.is_dark else 0.9))
        hl.setColorAt(1.0, theme.color("highlight", 0.0))
        p.save()
        p.setClipPath(path)
        p.fillRect(r, hl)
        p.restore()

        p.setPen(QPen(theme.color("card_border"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.end()


# ----------------------------------------------------------- 图标按钮 ----

class IconButton(QPushButton):
    """小圆图标按钮；``color_token`` 为主题令牌名。"""

    def __init__(self, name: str, color_token: str = "text_dim", size: int = 17,
                 stroke: float = 2.0, tooltip: str = "", object_name: str = "iconBtn",
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._name = name
        self._token = color_token
        self._size = size
        self._stroke = stroke
        self.setObjectName(object_name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(size, size))
        if tooltip:
            self.setToolTip(tooltip)
        self._apply_icon()
        # 绑定方法连接：控件销毁时 Qt 会自动断开，避免主题切换回调打到已删除对象
        theme.changed.connect(self._on_theme_changed)

    def _on_theme_changed(self, _mode: str) -> None:
        self._apply_icon()

    def set_icon_name(self, name: str) -> None:
        self._name = name
        self._apply_icon()

    def set_color_token(self, token: str) -> None:
        self._token = token
        self._apply_icon()

    def _apply_icon(self) -> None:
        self.setIcon(lucide_icon(self._name, theme.hex(self._token),
                                 self._size * 2, self._stroke))


# ------------------------------------------------------------- 指示器 ----

class Indicator(ThemeAware, QWidget):
    """状态指示器：``dot``（可呼吸脉冲）或 ``spinner``（旋转加载环）。"""

    def __init__(self, mode: str = "dot", color_token: str = "text_faint",
                 size: int = 12, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._mode = mode
        self._token = color_token
        self._active = False
        self._phase = 0.0
        self.setFixedSize(size, size)
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)
        theme.changed.connect(self._on_theme_changed)

    def configure(self, mode: str, token: str, active: bool = True) -> None:
        self._mode = mode
        self._token = token
        self._active = active
        if active:
            self._phase = 0.0
            self._timer.start()
        else:
            self._timer.stop()
            self._phase = 0.0
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.055) % 1.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        c = theme.color(self._token)

        if self._mode == "spinner":
            track = QPen(theme.color(self._token, 0.22), 1.8)
            track.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(track)
            p.setBrush(Qt.BrushStyle.NoBrush)
            rect = QRectF(1.5, 1.5, w - 3, h - 3)
            p.drawArc(rect, 0, 360 * 16)
            arc = QPen(c, 1.8)
            arc.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(arc)
            p.drawArc(rect, int(-self._phase * 360 * 16), int(-110 * 16))
        else:
            r = min(cx, cy) - 0.6
            if self._active:  # 呼吸光环
                rad = r * (0.55 + 0.75 * self._phase)
                p.setPen(QPen(theme.color(self._token, 0.45 * (1 - self._phase)), 1.4))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(cx, cy), rad, rad)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawEllipse(QPointF(cx, cy), r * 0.62, r * 0.62)
        p.end()


class StatusPill(QFrame):
    """胶囊状态标签：``set_state(state, text, tooltip)``。

    state: idle / loading / ok / error / warn / running
    """

    _TOKENS = {
        "idle": ("text_faint", "text_dim", False, "dot"),
        "ok": ("success", "text", False, "dot"),
        "running": ("accent", "text", True, "dot"),
        "record": ("danger", "text", True, "dot"),
        "busy": ("warning", "text_dim", True, "spinner"),
        "loading": ("warning", "text_dim", True, "spinner"),
        "warn": ("warning", "text_dim", False, "dot"),
        "error": ("danger", "text_dim", False, "dot"),
    }

    def __init__(self, text: str = "", state: str = "idle",
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("statusPill")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 3, 9, 3)
        lay.setSpacing(6)
        self.indicator = Indicator(size=11)
        self.label = QLabel(text)
        self.label.setObjectName("pillText")
        lay.addWidget(self.indicator)
        lay.addWidget(self.label)
        self._state = ""
        self.set_state(state, text)

    def set_state(self, state: str, text: Optional[str] = None,
                  tooltip: str = "") -> None:
        token, _label_token, pulse, mode = self._TOKENS.get(
            state, self._TOKENS["idle"])
        self._state = state
        if text is not None:
            self.label.setText(text)
        # 颜色由 QSS 的 [state=...] 选择器决定，主题切换时会自动跟着变
        self.setProperty("state", state)
        self.indicator.configure(mode, token, pulse)
        if tooltip:
            self.setToolTip(tooltip)
        repolish(self)
        repolish(self.label)

    def set_tooltip(self, text: str) -> None:
        self.setToolTip(text)
        self.label.setToolTip(text)

    @property
    def state(self) -> str:
        return self._state


class ProgressLine(ThemeAware, QWidget):
    """不确定进度：忙碌时一条来回流动的细线（明确的"正在运行"信号）。"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedHeight(3)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._active = False
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(28)
        self._timer.timeout.connect(self._tick)
        theme.changed.connect(self._on_theme_changed)

    def set_active(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        if active:
            self._phase = 0.0
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.02) % 1.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.color("track", 0.7))
        p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
        if not self._active:
            p.end()
            return
        seg = max(60.0, w * 0.28)
        span = w + seg
        x = -seg + self._phase * span
        grad = QLinearGradient(QPointF(x, 0), QPointF(x + seg, 0))
        grad.setColorAt(0.0, theme.color("accent", 0.0))
        grad.setColorAt(0.5, theme.color("accent", 1.0))
        grad.setColorAt(1.0, theme.color("accent_2", 0.0))
        p.setBrush(grad)
        p.drawRoundedRect(QRectF(x, 0, seg, h), h / 2, h / 2)
        p.end()


# --------------------------------------------------------- 录音大按钮 ----

class RecordButton(ThemeAware, QAbstractButton):
    """圆形录音按钮：录音中呼吸光环 + 实时电平外圈，空闲时渐变麦克风。"""

    def __init__(self, diameter: int = 88, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._d = diameter
        self.setFixedSize(diameter, diameter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("开始录音")
        self._active = False
        self._level = 0.0
        self._hover = False
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        theme.changed.connect(self._on_theme_changed)

    # ---- 状态 ----
    def set_active(self, active: bool) -> None:
        self._active = active
        self.setToolTip("停止录音" if active else "开始录音")
        self.update()

    def is_active(self) -> bool:
        return self._active

    def set_level(self, level: float) -> None:
        self._level = max(0.0, min(1.0, float(level)))

    def _tick(self) -> None:
        self._phase = (self._phase + (0.022 if self._active else 0.012)) % 1.0
        self.update()

    # ---- 交互 ----
    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()

    # ---- 绘制 ----
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        cx = cy = w / 2.0
        outer = cx - 1.5

        # 呼吸光环（录音中 / 加载幻觉感）
        if self._active:
            for k in (0.0, 0.5):
                ph = (self._phase + k) % 1.0
                rad = outer * (0.72 + 0.28 * ph)
                p.setPen(QPen(theme.color("record_a", 0.42 * (1 - ph)), 2.0))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(cx, cy), rad, rad)

        # 外圈：实时电平弧（录音中）否则浅色描边
        ring_w = 3.0
        if self._active:
            p.setPen(QPen(theme.color("record_a", 0.85), ring_w))
            p.setBrush(Qt.BrushStyle.NoBrush)
            span = 360.0 * max(0.04, self._level)
            p.drawArc(QRectF(1.5, 1.5, w - 3, w - 3), 90 * 16, int(-span * 16))
        else:
            p.setPen(QPen(theme.color("card_border"), ring_w))
            p.setBrush(Qt.BrushStyle.NoBrush)
            r = QRectF(1.5, 1.5, w - 3, w - 3)
            p.drawArc(r, 0, 360 * 16)

        # 主体圆
        inner = QRectF(9, 9, w - 18, w - 18)
        grad = QRadialGradient(QPointF(cx * 0.78, cy * 0.62), w * 0.9)
        if self._active:
            grad.setColorAt(0.0, theme.color("record_a"))
            grad.setColorAt(1.0, theme.color("record_b"))
        else:
            grad.setColorAt(0.0, theme.color("accent").lighter(118))
            grad.setColorAt(1.0, theme.color("accent_2"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawEllipse(inner)

        if self._hover and not self._active:
            p.setPen(QPen(theme.color("highlight", 0.35), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(inner.adjusted(1, 1, -1, -1))

        # 图标
        name = "stop" if self._active else "mic"
        pad = w * 0.32
        render_svg_doc(lucide_svg(name, "#FFFFFF", 2.2), p,
                       QRectF(pad, pad, w - 2 * pad, w - 2 * pad))
        p.end()


# ------------------------------------------------------------- 电平条 ----

class LevelMeter(ThemeAware, QWidget):
    """实时电平柱状条：录音时随声音跳动，空闲时静止基线。"""

    def __init__(self, bars: int = 44, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._n = bars
        self._levels: List[float] = [0.0] * bars
        self._targets: List[float] = [0.0] * bars
        self._active = False
        self.setMinimumHeight(46)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        theme.changed.connect(self._on_theme_changed)

    def set_active(self, active: bool) -> None:
        self._active = active
        if not active:
            self._targets = [0.0] * self._n
        self.update()

    def push(self, level: float) -> None:
        """推入一帧电平（0~1）。"""
        level = max(0.0, min(1.0, float(level)))
        self._targets = self._targets[1:] + [level]

    def _tick(self) -> None:
        changed = False
        for i in range(self._n):
            cur, tgt = self._levels[i], self._targets[i]
            nxt = cur + (tgt - cur) * 0.35
            if abs(nxt - cur) > 1e-4:
                changed = True
            self._levels[i] = nxt
        if changed or self._active:
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        gap = 2.0
        bw = max(1.5, (w - gap * (self._n - 1)) / self._n)
        mid = h / 2.0
        base = theme.color("accent")
        top = theme.color("accent_2")
        p.setPen(Qt.PenStyle.NoPen)
        for i, lv in enumerate(self._levels):
            x = i * (bw + gap)
            # 基线：空闲时保留一根细线，表明"随时可录"
            bar_h = max(2.0, lv * (h - 4))
            rect = QRectF(x, mid - bar_h / 2, bw, bar_h)
            grad = QLinearGradient(QPointF(x, mid - bar_h / 2), QPointF(x, mid + bar_h / 2))
            grad.setColorAt(0.0, top if lv > 0.02 else theme.color("track"))
            grad.setColorAt(1.0, base if lv > 0.02 else theme.color("track"))
            p.setBrush(grad)
            p.drawRoundedRect(rect, bw / 2, bw / 2)
        p.end()


# --------------------------------------------------------------- 提示 ----

class Toast(ThemeAware, QFrame):
    """轻量浮层提示：显示在父窗口底部中央，自动淡出。"""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(11, 6, 12, 6)
        lay.setSpacing(8)
        self.indicator = Indicator(size=12)
        self.label = QLabel("")
        self.label.setObjectName("toastText")
        lay.addWidget(self.indicator)
        lay.addWidget(self.label)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self._eff = QGraphicsOpacityEffect(self)
        self._eff.setOpacity(1.0)
        self.setGraphicsEffect(self._eff)
        self._fade = QPropertyAnimation(self._eff, b"opacity", self)
        self._fade.setDuration(320)
        self._fade.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fade.finished.connect(self.hide)
        theme.changed.connect(self._on_theme_changed)

    def pop(self, text: str, kind: str = "info", ms: int = 2600) -> None:
        token = {"info": "accent", "ok": "success",
                 "warn": "warning", "error": "danger"}.get(kind, "accent")
        self.indicator.configure("dot", token, False)
        self.label.setText(text)
        self._restyle()
        self.adjustSize()
        self.reposition()
        self._eff.setOpacity(1.0)
        self.show()
        self.raise_()
        self._timer.start(ms)

    def _theme_repaint(self) -> None:
        self._restyle()
        self.update()

    def _restyle(self) -> None:
        self.setStyleSheet(
            "QFrame#toast {"
            f" background: {theme.hex('surface')};"
            f" border: 1px solid {theme.hex('card_border')};"
            " border-radius: 12px; }"
            "QLabel#toastText {"
            f" color: {theme.hex('text')}; font-size: 12px; font-weight: 600; }}")
        self.label.setStyleSheet(
            f"color: {theme.hex('text')}; font-size: 12px; font-weight: 600;")

    def reposition(self) -> None:
        """把浮层摆到父窗口底部中央（父窗口尺寸变化时调用）。"""
        parent = self.parentWidget()
        if parent is None:
            return
        x = (parent.width() - self.width()) // 2
        y = parent.height() - self.height() - 38
        self.move(max(8, x), max(8, y))

    def _fade_out(self) -> None:
        self._fade.stop()
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.start()


class DropZone(QFrame):
    """上传区：虚线描边 + 居中图标/标题/提示，整块可点击。"""

    clicked = Signal()

    def __init__(self, icon_name: str, title: str, hint: str,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(70)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 9, 14, 9)
        lay.setSpacing(3)
        self.icon = icon_label(icon_name, "accent", 22)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title = QLabel(title)
        self.title.setObjectName("dropTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint = QLabel(hint)
        self.hint.setObjectName("dropHint")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addStretch(1)
        lay.addWidget(self.icon)
        lay.addWidget(self.title)
        lay.addWidget(self.hint)
        lay.addStretch(1)

    def set_text(self, title: str, hint: str) -> None:
        self.title.setText(title)
        self.hint.setText(hint)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(
                e.position().toPoint()):
            self.clicked.emit()


def section_label(text: str) -> QLabel:
    """分区小标题。"""
    lab = QLabel(text)
    lab.setObjectName("sectionLabel")
    return lab


class IconLabel(ThemeAware, QLabel):
    """纯图标 QLabel（卡片标题左侧的小图标），主题切换自动换色。"""

    def __init__(self, name: str, token: str = "text_dim", size: int = 16,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._name = name
        self._token = token
        self._size = size
        self._refresh()

    def _theme_repaint(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        self.setPixmap(lucide_icon(self._name, theme.hex(self._token),
                                   self._size * 2).pixmap(self._size, self._size))


def icon_label(name: str, token: str = "text_dim", size: int = 16) -> IconLabel:
    """构造一个随主题换色的图标标签。"""
    return IconLabel(name, token, size)
