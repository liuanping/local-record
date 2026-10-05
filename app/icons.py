"""图标：Lucide 官方矢量（ISC 许可） + QtSvg 渲染 + 渐变应用图标。

* :func:`lucide_svg` / :func:`lucide_icon` 用于按钮、托盘、菜单；
* :func:`make_app_icon` 生成应用图标（渐变圆角方块 + 玻璃高光 + 线条麦克风），
  支持 ``idle`` / ``recording`` / ``loading`` 三种状态配色，托盘与悬浮球
  用它直观表达"当前在做什么"。
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QColor, QIcon, QImage, QLinearGradient, QPainter, QPainterPath,
    QPixmap, QRadialGradient,
)

# ---- Lucide 官方路径（24x24 viewBox，stroke 线条风格）----
_LUCIDE_PATHS = {
    # 麦克风：竖杆 + 弧线 + 圆角矩形主体
    "mic": ('<path d="M12 19v3"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/>'
            '<rect x="9" y="2" width="6" height="13" rx="3"/>'),
    # 停止：圆角方块
    "stop": '<rect width="18" height="18" x="3" y="3" rx="2"/>',
    # 播放 / 暂停
    "play": '<polygon points="7 4 20 12 7 20 7 4"/>',
    "pause": ('<rect x="14" y="4" width="4" height="16" rx="1.2"/>'
              '<rect x="6" y="4" width="4" height="16" rx="1.2"/>'),
    # AI 星芒（摘要/总结）
    "sparkles": ('<path d="M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558'
                 'a2 2 0 0 0 1.594 1.594l5.558 1.051a1 1 0 0 1 0 1.966'
                 'l-5.558 1.051a2 2 0 0 0-1.594 1.594l-1.051 5.558a1 1 0 0 1-1.966 0'
                 'l-1.051-5.558a2 2 0 0 0-1.594-1.594l-5.558-1.051a1 1 0 0 1 0-1.966'
                 'l5.558-1.051a2 2 0 0 0 1.594-1.594z"/><path d="M20 2v4"/>'
                 '<path d="M22 4v2"/>'),
    # 时钟（时间定位）
    "clock": '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    # 扫描文本（OCR 页）
    "scan-text": ('<path d="M3 7V5a2 2 0 0 1 2-2h2"/>'
                  '<path d="M17 3h2a2 2 0 0 1 2 2v2"/>'
                  '<path d="M21 17v2a2 2 0 0 1-2 2h-2"/>'
                  '<path d="M7 21H5a2 2 0 0 1-2-2v-2"/>'
                  '<path d="M7 8h8"/><path d="M7 12h10"/><path d="M7 16h6"/>'),
    # 上传（OCR 页上传文件）
    "upload": ('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
               '<polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/>'),
    # 下载（导出）
    "download": ('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
                 '<polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>'),
    # 音量
    "volume": ('<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>'
               '<path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>'
               '<path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>'),
    "volume-off": ('<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>'
                   '<line x1="22" x2="16" y1="9" y2="15"/>'
                   '<line x1="16" x2="22" y1="9" y2="15"/>'),
    # 声波（录音库 / 运行指示）
    "audio-lines": ('<path d="M2 10v3"/><path d="M6 6v11"/><path d="M10 3v18"/>'
                    '<path d="M14 8v7"/><path d="M18 5v13"/><path d="M22 10v3"/>'),
    # 活动（运行中）
    "activity": ('<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0'
                 'L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/>'),
    # 列表 / 音乐列表
    "list-music": ('<path d="M21 15V6"/><path d="M18.5 18a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z"/>'
                   '<path d="M12 12H3"/><path d="M16 6H3"/><path d="M12 18H3"/>'),
    # 文件夹
    "folder-open": ('<path d="m6 14 1.45-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.55 6'
                    'a2 2 0 0 1-1.94 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.93a2 2 0 0 1 1.66.9'
                    'l.82 1.2a2 2 0 0 0 1.66.9H18a2 2 0 0 1 2 2v2"/>'),
    # 删除
    "trash": ('<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>'
              '<path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>'
              '<line x1="10" x2="10" y1="11" y2="17"/>'
              '<line x1="14" x2="14" y1="11" y2="17"/>'),
    # 主题
    "sun": ('<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/>'
            '<path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/>'
            '<path d="M2 12h2"/><path d="M20 12h2"/>'
            '<path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>'),
    "moon": '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
    # 窗口控制 / 关闭
    "minus": '<path d="M5 12h14"/>',
    "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "alert": ('<circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/>'
              '<line x1="12" x2="12.01" y1="16" y2="16"/>'),
    "info": ('<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/>'
             '<path d="M12 8h.01"/>'),
    "copy": ('<rect width="13" height="13" x="9" y="9" rx="2"/>'
             '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>'),
    "refresh": ('<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/>'
                '<path d="M21 3v5h-5"/>'
                '<path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/>'
                '<path d="M8 16H3v5"/>'),
    "power": ('<path d="M12 2v10"/><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/>'),
    "settings": ('<line x1="21" x2="14" y1="4" y2="4"/><line x1="10" x2="3" y1="4" y2="4"/>'
                 '<line x1="21" x2="12" y1="12" y2="12"/><line x1="8" x2="3" y1="12" y2="12"/>'
                 '<line x1="21" x2="16" y1="20" y2="20"/><line x1="12" x2="3" y1="20" y2="20"/>'
                 '<line x1="14" x2="14" y1="2" y2="6"/><line x1="8" x2="8" y1="10" y2="14"/>'
                 '<line x1="16" x2="16" y1="18" y2="22"/>'),
    "clock-rewind": ('<path d="M3 3v5h5"/><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8"/>'
                     '<path d="M12 7v5l3 2"/>'),
}


def available_icons() -> list[str]:
    return sorted(_LUCIDE_PATHS)


def lucide_svg(name: str, color: str = "#ffffff", stroke_width: float = 2) -> str:
    """Lucide 图标 → 完整 SVG 文档字符串。"""
    body = _LUCIDE_PATHS.get(name, _LUCIDE_PATHS["info"])
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="{stroke_width}" '
        f'stroke-linecap="round" stroke-linejoin="round">'
        f'{body}</svg>'
    )


def render_svg_doc(svg_doc: str, painter: QPainter, rect: QRectF) -> None:
    """把任意 SVG 文档渲染进 painter 的 rect 区域。"""
    from PySide6.QtSvg import QSvgRenderer
    QSvgRenderer(bytearray(svg_doc.encode("utf-8"))).render(painter, rect)


def lucide_icon(name: str, color: str, size: int = 64,
                stroke_width: float = 2) -> QIcon:
    """Lucide 图标 → QIcon（透明底）。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    render_svg_doc(lucide_svg(name, color, stroke_width), p,
                   QRectF(0, 0, size, size))
    p.end()
    return QIcon(pm)


def lucide_pixmap(name: str, color: str, size: int = 64,
                  stroke_width: float = 2) -> QPixmap:
    return lucide_icon(name, color, size, stroke_width).pixmap(size, size)


# ------------------------------------------------------- 应用图标（渐变） ----

# 状态 → (渐变起色, 渐变止色)
_STATE_COLORS = {
    "idle": ("#7C9CFF", "#5B6BFF"),
    "recording": ("#FF7A7A", "#D81E37"),
    "loading": ("#FFC46B", "#F08A00"),
}


def _paint_app_icon(p: QPainter, size: float, state: str = "idle") -> None:
    """渐变底 + 顶部玻璃高光 + 白色线条麦克风。"""
    top, bottom = _STATE_COLORS.get(state, _STATE_COLORS["idle"])
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    clip = QPainterPath()
    radius = size * 0.225
    clip.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    p.setClipPath(clip)

    grad = QLinearGradient(0, 0, size * 0.35, size)
    grad.setColorAt(0.0, QColor(top))
    grad.setColorAt(1.0, QColor(bottom))
    p.fillRect(QRectF(0, 0, size, size), grad)

    hl = QRadialGradient(size * 0.5, size * 0.1, size * 0.95)
    hl.setColorAt(0.0, QColor(255, 255, 255, 120))
    hl.setColorAt(0.45, QColor(255, 255, 255, 26))
    hl.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.fillRect(QRectF(0, 0, size, size), hl)

    pad = size * 0.24
    icon = "stop" if state == "recording" else "mic"
    render_svg_doc(lucide_svg(icon, "#ffffff", 2.2), p,
                   QRectF(pad, pad, size - 2 * pad, size - 2 * pad))
    p.setClipping(False)


def make_app_icon(size: int = 64, state: str = "idle") -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    _paint_app_icon(p, size, state)
    p.end()
    return QIcon(pm)


def make_app_image(size: int = 256, state: str = "idle") -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    _paint_app_icon(p, size, state)
    p.end()
    return img
