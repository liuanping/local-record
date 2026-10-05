"""系统托盘图标（QSystemTrayIcon）。

托盘图标会随状态换色（空闲=蓝紫 / 录音=红 / 准备中=橙），
悬停提示里带上当前状态与运行时长，右键菜单与悬浮球共用同一份菜单定义。
"""
from __future__ import annotations

from typing import Callable, Optional, Sequence, Tuple, Union

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .icons import lucide_icon, make_app_icon
from .theme import theme

# 菜单项：(文本, 回调) 或 (文本, 回调, 图标名)；文本为 None 时画分隔线
MenuItem = Union[Tuple[str, Callable[[], None]],
                 Tuple[str, Callable[[], None], str]]


class Tray(QSystemTrayIcon):
    def __init__(self, items: Sequence[MenuItem],
                 on_double_click: Optional[Callable[[], None]] = None,
                 parent=None):
        super().__init__(parent)
        self._icon_cache: dict[str, QIcon] = {}
        self._items: Sequence[MenuItem] = items
        self._menu = QMenu()
        self._state = "idle"
        self._detail = ""
        self.setContextMenu(self._menu)
        self.rebuild(items)
        self._refresh_icon()
        self.setToolTip("Local Record · 本地录音助手")
        self.activated.connect(self._on_activated)
        self._on_double_click = on_double_click
        theme.changed.connect(self._on_theme_changed)
        self.show()

    def _on_theme_changed(self, _mode: str = "") -> None:
        """主题切换：重建菜单图标并刷新托盘图标（绑定方法，销毁即断开）。"""
        self._icon_cache.clear()
        self.rebuild(self._items)
        self._refresh_icon()

    # ---------------- 菜单 ----------------
    def rebuild(self, items: Sequence[MenuItem]) -> None:
        """重建菜单（录音状态/主题变化时刷新文案与图标）。"""
        self._items = items
        self._menu.clear()
        for item in items:
            text, cb = item[0], item[1]
            icon_name = item[2] if len(item) > 2 else None
            if text is None:
                self._menu.addSeparator()
                continue
            if cb is None:
                action = self._menu.addAction(text)
                action.setEnabled(False)
            else:
                action = self._menu.addAction(text, cb)
            if icon_name:
                action.setIcon(self._lucide(icon_name, "text"))

    def _lucide(self, name: str, token: str) -> QIcon:
        key = f"{name}:{token}:{theme.mode}"
        if key not in self._icon_cache:
            self._icon_cache[key] = lucide_icon(name, theme.hex(token), 32, 2.0)
        return self._icon_cache[key]

    # ---------------- 状态 ----------------
    def set_state(self, state: str, detail: str = "") -> None:
        """state: idle / recording / busy / ok"""
        self._state = state
        self._detail = detail
        self._refresh_icon()
        label = {"idle": "空闲", "recording": "录音中",
                 "busy": "准备中", "ok": "就绪"}.get(state, state)
        tip = f"Local Record · {label}"
        if detail:
            tip += f"\n{detail}"
        self.setToolTip(tip)

    def _refresh_icon(self) -> None:
        state = {"recording": "recording", "busy": "loading"}.get(self._state, "idle")
        self.setIcon(make_app_icon(64, state))

    # 兼容旧调用
    def set_recording(self, on: bool) -> None:
        self.set_state("recording" if on else "idle", self._detail)

    def _on_activated(self, reason) -> None:  # noqa: ANN001
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            if self._on_double_click is not None:
                self._on_double_click()
