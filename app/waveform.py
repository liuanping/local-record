"""波形控件：播放进度波形 + 迷你进度条。

* :class:`WaveformView` —— 完整波形，支持点击/拖动定位、悬停时间提示；
* :class:`MiniWave`     —— 卡片里的小波形（不可交互，仅示意 + 进度）。

数据来自 :class:`app.player.AudioClip` 的峰值包络 ``[(min,max), ...]``。
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from .theme import theme
from .utils import fmt_mmss
from .widgets import ThemeAware

Peaks = Sequence[Tuple[float, float]]


def _auto_gain(peaks: Peaks, max_gain: float = 12.0,
               floor: float = 0.004) -> float:
    """自动增益：让音量偏低的录音也能看清波形轮廓。

    峰值太低（近似静音）时不放大，避免把底噪画成"有声"。
    """
    if not peaks:
        return 1.0
    top = max(max(abs(lo), abs(hi)) for lo, hi in peaks)
    if top <= floor:
        return 1.0
    return min(max_gain, 0.96 / top)


class WaveformView(ThemeAware, QWidget):
    """可点击定位的波形视图。"""

    seekRequested = Signal(float)     # 0~1 的比例
    hoverRatio = Signal(float)        # 悬停位置（-1 表示离开）

    def __init__(self, height: int = 88, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._peaks: List[Tuple[float, float]] = []
        self._progress = 0.0
        self._duration = 0.0
        self._playing = False
        self._hover_x: Optional[float] = None
        self._dragging = False
        self._gain = 1.0
        self.setMinimumHeight(height)
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        theme.changed.connect(self._on_theme_changed)

    # ---------------- 数据 ----------------
    def set_peaks(self, peaks: Peaks, duration: float = 0.0) -> None:
        self._peaks = list(peaks)
        self._duration = duration
        self._gain = _auto_gain(self._peaks)
        self.update()

    def set_progress(self, ratio: float) -> None:
        ratio = max(0.0, min(1.0, float(ratio)))
        if abs(ratio - self._progress) < 0.0004:
            return
        self._progress = ratio
        self.update()

    def set_playing(self, playing: bool) -> None:
        if playing != self._playing:
            self._playing = playing
            self.update()

    def clear(self) -> None:
        self._peaks = []
        self._progress = 0.0
        self._duration = 0.0
        self.update()

    # ---------------- 交互 ----------------
    def _ratio_at(self, x: float) -> float:
        w = max(1, self.width())
        return max(0.0, min(1.0, x / w))

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self._peaks:
            self._dragging = True
            self.seekRequested.emit(self._ratio_at(e.position().x()))

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        x = e.position().x()
        self._hover_x = x
        if self._dragging:
            self.seekRequested.emit(self._ratio_at(x))
        self.update()
        self.hoverRatio.emit(self._ratio_at(x) if self._peaks else -1.0)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        self._dragging = False

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover_x = None
        self.update()
        self.hoverRatio.emit(-1.0)

    # ---------------- 绘制 ----------------
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        radius = 12.0

        bg = QPainterPath()
        bg.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), radius, radius)
        p.fillPath(bg, theme.color("surface_2"))
        p.setPen(QPen(theme.color("card_border"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(bg)

        mid = h / 2.0
        if not self._peaks:
            p.setPen(QPen(theme.color("text_faint"), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(14, mid), QPointF(w - 14, mid))
            p.setPen(QPen(theme.color("text_faint"), 1))
            f = p.font()
            f.setPointSizeF(9.5)
            p.setFont(f)
            p.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter,
                       "选择一条录音即可试听")
            p.end()
            return

        p.save()
        p.setClipPath(bg)

        n = len(self._peaks)
        bar_w = 2.0
        gap = 1.0
        step = bar_w + gap
        cols = max(1, int((w - 12) / step))
        x0 = (w - cols * step) / 2.0
        played_x = self._progress * w

        unplayed = theme.color("accent", 0.38)
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, theme.color("accent_2"))
        grad.setColorAt(1.0, theme.color("accent"))

        for i in range(cols):
            x = x0 + i * step
            b0 = int(i / cols * n)
            b1 = max(b0 + 1, int((i + 1) / cols * n))
            seg = self._peaks[b0:b1]
            if not seg:
                continue
            lo = min(s[0] for s in seg)
            hi = max(s[1] for s in seg)
            # 自动增益 + 感知压缩（gamma 0.6）：音量偏低的录音也能看清轮廓
            pos = min(1.0, max(0.0, hi * self._gain)) ** 0.6
            neg = min(1.0, max(0.0, -lo * self._gain)) ** 0.6
            top = mid - max(pos, 0.03) * (h / 2 - 6)
            bottom = mid + max(neg, 0.03) * (h / 2 - 6)
            if bottom - top < 2.0:
                top, bottom = mid - 1.0, mid + 1.0
            rect = QRectF(x, top, bar_w, bottom - top)
            if x + bar_w <= played_x:
                p.setBrush(grad)
            elif x < played_x:
                p.setBrush(grad)
            else:
                p.setBrush(unplayed)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(rect, bar_w / 2, bar_w / 2)

        # 播放游标
        if self._progress > 0.0:
            p.setPen(QPen(theme.color("accent", 0.9), 1.6))
            p.drawLine(QPointF(played_x, 4), QPointF(played_x, h - 4))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.color("accent"))
            p.drawEllipse(QPointF(played_x, 5), 2.6, 2.6)

        # 悬停提示线
        if self._hover_x is not None and not self._dragging:
            p.setPen(QPen(theme.color("text", 0.35), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(self._hover_x, 2), QPointF(self._hover_x, h - 2))

        p.restore()

        # 悬停时间气泡
        if self._hover_x is not None and self._duration > 0:
            ratio = self._ratio_at(self._hover_x)
            text = fmt_mmss(ratio * self._duration)
            f = p.font()
            f.setPointSizeF(8.5)
            p.setFont(f)
            tw = p.fontMetrics().horizontalAdvance(text) + 12
            tx = min(max(4.0, self._hover_x - tw / 2), w - tw - 4)
            bubble = QRectF(tx, 4, tw, 17)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.color("card_a", 0.94))
            p.drawRoundedRect(bubble, 6, 6)
            p.setPen(QPen(theme.color("text"), 1))
            p.drawText(bubble, Qt.AlignmentFlag.AlignCenter, text)
        p.end()


class MiniWave(ThemeAware, QWidget):
    """极小波形（语音页"最近录音"用）：仅显示 + 进度。"""

    def __init__(self, height: int = 26, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._peaks: List[Tuple[float, float]] = []
        self._progress = 0.0
        self.setFixedHeight(height)
        self.setMinimumWidth(60)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        theme.changed.connect(self._on_theme_changed)

    def set_peaks(self, peaks: Peaks) -> None:
        self._peaks = list(peaks)
        self._gain = _auto_gain(self._peaks, max_gain=8.0)
        self.update()

    def set_progress(self, ratio: float) -> None:
        self._progress = max(0.0, min(1.0, float(ratio)))
        self.update()

    def clear(self) -> None:
        self._peaks = []
        self._progress = 0.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        mid = h / 2.0
        if not self._peaks:
            p.setPen(QPen(theme.color("text_faint", 0.6), 1))
            p.drawLine(QPointF(2, mid), QPointF(w - 2, mid))
            p.end()
            return
        n = len(self._peaks)
        step = 3.0
        cols = max(1, int(w / step))
        played_x = self._progress * w
        for i in range(cols):
            x = i * step
            b0 = int(i / cols * n)
            b1 = max(b0 + 1, int((i + 1) / cols * n))
            seg = self._peaks[b0:b1]
            if not seg:
                continue
            hi = max(max(abs(s[0]), abs(s[1])) for s in seg) * self._gain
            amp = min(1.0, max(0.0, hi)) ** 0.6
            bh = max(2.0, amp * (h - 2))
            color = (theme.color("accent") if x + 1.6 <= played_x
                     else theme.color("accent", 0.5))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawRoundedRect(QRectF(x, mid - bh / 2, 1.8, bh), 0.9, 0.9)
        p.end()
