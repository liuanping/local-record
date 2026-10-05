"""离屏渲染界面截图（开发辅助，不参与打包）。

用法::

    .venv\\Scripts\\python.exe scripts\\preview_ui.py [输出目录]

在没有显示器的环境里用 Qt 的 offscreen 平台把主窗口画出来存成 PNG，
方便快速检查排版/配色；同时用真实录音目录填充"录音库"页。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# offscreen 平台默认找不到字体（文本会变成方框），指向系统字体目录
if os.name == "nt" and Path(r"C:\Windows\Fonts").is_dir():
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.logger import setup_logging  # noqa: E402
from app.main_window import MainWindow  # noqa: E402
from app.paths import recordings_dir  # noqa: E402
from app.player import AudioPlayer  # noqa: E402
from app.theme import theme  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "preview"
# 第二个参数可指定渲染尺寸，例如 478x644（1280x720 @150% 小屏下的真实尺寸）
SIZE = (478, 812)
if len(sys.argv) > 2 and "x" in sys.argv[2]:
    _w, _h = sys.argv[2].split("x")
    SIZE = (int(_w), int(_h))

SEGMENTS = [
    (3.2, "大家好，今天我们过一下这个季度的交付情况。"),
    (18.6, "第一个模块已经完成了联调，测试用例覆盖了百分之八十五。"),
    (35.1, "第二个模块遇到一点阻塞，主要卡在第三方的接口联调上。"),
    (52.4, "我们计划把风险同步给采购，下周三之前给出替代方案。"),
    (71.8, "第三个模块按原计划下周上线，需要运维配合灰度发布。"),
]


def pump(app: QApplication, ms: int) -> None:
    """驱动事件循环 ms 毫秒（让动画/布局真正跑起来）。"""
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def populate(win: MainWindow, app: QApplication) -> None:
    for start, text in SEGMENTS:
        win.add_transcript(text, start, start + 6.0)
    win.append_chat("你", "这周的交付风险有哪些？")
    win.append_chat(
        "AI",
        "1) 第二个模块的第三方接口联调尚未完成，属于主要风险；\n"
        "2) 替代方案需在下周三前给出；\n"
        "3) 第三个模块上线需要运维配合灰度发布，建议提前锁定窗口。")
    win.append_ocr("会议纪要（识别结果）\n本季度交付三个模块，前两个已完成联调，"
                   "第三个计划下周上线。风险集中在第三方接口联调。")
    win.append_ocr_chat("AI", "已识别出 3 条关键信息，其中 1 条为风险项。")
    win.set_asr_status(True, "ASR 就绪")
    win.set_llm_status(True, "大模型就绪")
    win.set_activity("已保存 rec-20260920-002711.wav")


def shoot(widget, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    widget.grab().save(str(path))
    print("已保存", path)


def main() -> int:
    setup_logging(30)
    app = QApplication(sys.argv)
    theme.apply(app, "dark")

    player = AudioPlayer()
    win = MainWindow(player, recordings_dir(), version="1.0.0")
    win.resize(*SIZE)
    win.show()
    populate(win, app)
    pump(app, 250)

    # --- 深色：语音页（空闲）---
    win.show_tab(0)
    pump(app, 200)
    shoot(win, "01-voice-dark.png")

    # --- 深色：语音页（录音中，电平跳动）---
    win.set_recording(True)
    levels = [0.18, 0.42, 0.66, 0.88, 0.55, 0.31, 0.72, 0.94, 0.47, 0.26,
              0.61, 0.83, 0.38, 0.19, 0.52, 0.77, 0.91, 0.44, 0.23, 0.58]
    t = 0.0
    for i in range(120):
        t += 0.06
        win.update_recording(t, levels[i % len(levels)])
        pump(app, 12)
    shoot(win, "02-voice-recording-dark.png")

    # --- 深色：定位高亮 ---
    win.set_recording(False)
    win.highlight_transcript([2, 4])
    pump(app, 200)
    shoot(win, "03-voice-highlight-dark.png")

    # --- 深色：录音库 ---
    win.show_tab(1)
    files = win.library_page.files()
    if files:
        win.library_page.note_saved(files[0])
    pump(app, 350)
    shoot(win, "04-library-dark.png")

    # --- 深色：停录后的"最近一次录音"试听条 ---
    if files:
        win.show_tab(0)
        win.note_recording_saved(files[0])
        pump(app, 300)
        shoot(win, "11-voice-miniplayer-dark.png")
        win.player.play()
        pump(app, 700)
        shoot(win, "12-voice-miniplayer-playing-dark.png")
        win.player.stop()

    # --- 深色：文字识别 ---
    win.show_tab(2)
    pump(app, 200)
    shoot(win, "05-ocr-dark.png")

    # --- 浅色主题 ---
    theme.set_mode("light")
    pump(app, 250)
    shoot(win, "06-library-light.png")
    win.show_tab(0)
    win.set_recording(True)
    for i in range(60):
        t += 0.06
        win.update_recording(t, levels[i % len(levels)])
        pump(app, 12)
    shoot(win, "07-voice-recording-light.png")
    win.set_recording(False)
    win.show_tab(2)
    pump(app, 150)
    shoot(win, "08-ocr-light.png")

    # --- 悬浮球（深色录音中 / 浅色空闲）---
    from app.ball import FloatingBall
    from PySide6.QtWidgets import QMenu
    theme.set_mode("dark")
    ball = FloatingBall(lambda: QMenu(), size=58)
    ball.set_recording(True)
    ball.set_level(0.72)
    pump(app, 300)
    shoot(ball, "09-ball-recording-dark.png")
    ball.set_recording(False)
    ball.set_busy(True)
    pump(app, 200)
    shoot(ball, "10-ball-busy-dark.png")
    ball.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
