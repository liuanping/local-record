"""悬浮球：无边框、置顶、可拖动的桌面录音开关。

设计要点（"一眼看出在运行"）：

* 空闲：蓝紫渐变 + 缓慢呼吸的柔光；
* 录音中：红橙渐变 + 扩散光环 + 跟随麦克风电平的外圈弧（说话时肉眼可见）；
* 加载中：外圈旋转弧（大模型/语音模型还在准备）；
* 单击弹功能菜单，双击切换录音，右键菜单，拖动位置会被记住。
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import (
    QPoint, QPointF, QRectF, QSettings, Qt, QTimer, Signal,
)
from PySide6.QtGui import (
    QColor, QCursor, QLinearGradient, QPainter, QPen, QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from .icons import lucide_svg, render_svg_doc
from .theme import theme
from .widgets import ThemeAware


class FloatingBall(ThemeAware, QWidget):
    toggle_record_requested = Signal()
    #: 单击悬浮球 → 打开主界面（用户要求：点一下直接进主界面，不要一堆菜单）
    open_main_requested = Signal()

    def __init__(self, menu_factory: Callable[[], QMenu], size: int = 58,
                 parent: Optional[QWidget] = None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._size = size
        self.setFixedSize(size, size)
        self._menu_factory = menu_factory
        self._drag_offset: Optional[QPoint] = None
        self._moved = False
        self._recording = False
        self._busy = False
        self._level = 0.0
        self._phase = 0.0
        self._hover = False
        self._settings = QSettings("LocalRecord", "LocalRecord")

        self._restore_position()
        self.setToolTip("Local Record · 空闲（单击打开主界面，右键更多，可拖动）")
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        theme.changed.connect(self._on_theme_changed)
        self.show()  # 悬浮球必须显式 show，否则不显示

    # ---------------- 位置 ----------------
    def _restore_position(self) -> None:
        pos = self._settings.value("ball/pos")
        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else None
        if isinstance(pos, QPoint) and geo is not None and geo.contains(pos):
            self.move(pos)
            return
        if geo is not None:
            self.move(geo.right() - self._size - 74, geo.top() + 120)

    def _save_position(self) -> None:
        self._settings.setValue("ball/pos", self.pos())

    def moveEvent(self, e) -> None:  # noqa: N802
        super().moveEvent(e)
        self._save_position()

    # ---------------- 动画 ----------------
    def _tick(self) -> None:
        speed = 0.035 if self._recording else (0.05 if self._busy else 0.012)
        self._phase = (self._phase + speed) % 1.0
        self.update()

    # ---------------- 状态 ----------------
    def set_recording(self, on: bool) -> None:
        self._recording = on
        self.setToolTip("Local Record · 录音中（单击打开主界面，右键可停止）" if on
                        else "Local Record · 空闲（单击打开主界面，右键更多）")
        self.update()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.update()

    def set_level(self, level: float) -> None:
        self._level = max(0.0, min(1.0, float(level)))

    def set_status_text(self, text: str) -> None:
        state = "录音中" if self._recording else ("准备中" if self._busy else "空闲")
        self.setToolTip(f"Local Record · {state}\n{text}")

    # ---------------- 绘制 ----------------
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        cx = cy = w / 2.0
        base = w / 2.0 - 5.0

        # 外发光
        glow_r = base + 4.5 + (1.6 * self._level if self._recording else 0.0)
        glow = QRadialGradient(QPointF(cx, cy), glow_r)
        glow_color = (theme.color("record_a") if self._recording
                      else theme.color("accent"))
        glow.setColorAt(0.80, QColor(glow_color.red(), glow_color.green(),
                                     glow_color.blue(), 0))
        glow.setColorAt(0.92, QColor(glow_color.red(), glow_color.green(),
                                     glow_color.blue(), 60))
        glow.setColorAt(1.0, QColor(glow_color.red(), glow_color.green(),
                                    glow_color.blue(), 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QPointF(cx, cy), glow_r, glow_r)

        # 呼吸 / 扩散光环
        if self._recording:
            for k in (0.0, 0.5):
                ph = (self._phase + k) % 1.0
                rad = base * (0.85 + 0.35 * ph)
                p.setPen(QPen(theme.color("record_a", 0.5 * (1 - ph)), 2.0))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(cx, cy), rad, rad)
        elif self._hover:
            rad = base * (0.95 + 0.12 * self._phase)
            p.setPen(QPen(theme.color("accent", 0.5 * (1 - self._phase)), 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), rad, rad)

        # 主体
        body = QRectF(cx - base, cy - base, base * 2, base * 2)
        grad = QLinearGradient(body.topLeft(), body.bottomRight())
        if self._recording:
            grad.setColorAt(0.0, theme.color("record_a"))
            grad.setColorAt(1.0, theme.color("record_b"))
        else:
            grad.setColorAt(0.0, theme.color("accent").lighter(115))
            grad.setColorAt(1.0, theme.color("accent_2"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawEllipse(body)

        # 顶部高光
        hl = QRadialGradient(QPointF(cx, cy - base * 0.45), base * 1.15)
        hl.setColorAt(0.0, QColor(255, 255, 255, 90))
        hl.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(hl)
        p.drawEllipse(body)

        # 电平弧（录音时跟随音量）
        if self._recording and self._level > 0.01:
            ring = QRectF(cx - base - 2, cy - base - 2, (base + 2) * 2, (base + 2) * 2)
            p.setPen(QPen(QColor(255, 255, 255, 200), 2.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(ring, 90 * 16, int(-300 * self._level * 16))

        # 忙碌：外圈旋转弧
        if self._busy and not self._recording:
            ring = QRectF(cx - base - 3, cy - base - 3, (base + 3) * 2, (base + 3) * 2)
            p.setPen(QPen(theme.color("warning"), 2.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(ring, int(-self._phase * 360 * 16), int(-100 * 16))

        # 图标
        icon = lucide_svg("stop" if self._recording else "mic", "#FFFFFF", 2.2)
        pad = w * 0.30
        render_svg_doc(icon, p, QRectF(pad, pad, w - 2 * pad, w - 2 * pad))

        # 左上角小圆点：录音中的"在录制"提示
        if self._recording:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#FFFFFF"))
            p.drawEllipse(QPointF(cx + base * 0.62, cy - base * 0.62), 3.0, 3.0)
        p.end()

    # ---------------- 交互 ----------------
    def enterEvent(self, e) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (e.globalPosition().toPoint()
                                 - self.frameGeometry().topLeft())
            self._moved = False

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._drag_offset is not None:
            if (e.globalPosition().toPoint() - self._drag_offset
                    - self.frameGeometry().topLeft()).manhattanLength() > 3:
                self._moved = True
            self.move(e.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            was_drag = self._moved
            self._drag_offset = None
            if not was_drag:
                # 单击直接打开主界面（原来这里是 250ms 后弹一长串菜单，太啰嗦）
                self.open_main_requested.emit()

    def mouseDoubleClickEvent(self, e) -> None:  # noqa: N802
        # 双击与单击一致：都进主界面（避免双击时弹出两个窗口的错觉）
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = None
            self._moved = True        # 抑制随之而来的 release 再触发一次
            self.open_main_requested.emit()

    def contextMenuEvent(self, e) -> None:  # noqa: N802
        """右键才出菜单（已精简为几项）。"""
        self._menu_factory().exec(e.globalPos())
