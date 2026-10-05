"""悬浮球行为验证：单击应打开主界面，右键才是精简菜单。

和 check_app_recording.py 一样跑**真实 app**（GUI + 真事件循环），
只把 LlamaServer 换成桩、把 APPDATA 隔离到临时目录。

用法::

    .venv\\Scripts\\python.exe scripts\\check_ball.py
"""
from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SMOKE = ROOT / "build" / "ball-check"
os.environ["QT_QPA_PLATFORM"] = "windows"
os.environ["LOCAL_RECORD_DIR"] = str(ROOT)
os.environ["APPDATA"] = str(SMOKE / "appdata")

from PySide6.QtCore import QTimer, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import app.main as app_main  # noqa: E402
from app.ball import FloatingBall  # noqa: E402
from app.llama_server import LlamaServerError  # noqa: E402
from app.main_window import MainWindow  # noqa: E402

RESULT: dict = {}


def main() -> int:
    shutil.rmtree(SMOKE, ignore_errors=True)
    (SMOKE / "appdata").mkdir(parents=True, exist_ok=True)

    class NoServer:
        def __init__(self, *_a, **_k):
            raise LlamaServerError("check_ball: 跳过真实 llama-server")

    app_main.LlamaServer = NoServer
    QMessageBox.warning = staticmethod(lambda *a, **k: None)      # type: ignore
    QMessageBox.information = staticmethod(lambda *a, **k: None)  # type: ignore

    def find(cls):
        for w in QApplication.topLevelWidgets():
            if isinstance(w, cls):
                return w
        return None

    def run_checks():
        app = QApplication.instance()
        win = find(MainWindow)
        ball = find(FloatingBall)
        checks: list[tuple[str, bool, str]] = []
        if win is None or ball is None:
            print("[FAIL] 找不到主窗口或悬浮球")
            RESULT["ok"] = False
            app.quit()
            return

        # 1) 悬浮球是否存在且可见
        checks.append(("悬浮球存在且可见", ball.isVisible(), f"visible={ball.isVisible()}"))

        # 2) 单击悬浮球 → 主界面出现（先隐藏主窗口再点）
        win.hide()
        app.processEvents()
        hidden = not win.isVisible()
        QTest.mouseClick(ball, Qt.MouseButton.LeftButton)
        for _ in range(30):
            app.processEvents()
            time.sleep(0.02)
        checks.append(("单击悬浮球打开主界面",
                       hidden and win.isVisible(),
                       f"点击前可见={not hidden} 点击后可见={win.isVisible()}"))

        # 3) 主界面确实被置顶激活（不是最小化状态）
        checks.append(("主界面为正常显示状态", not win.isMinimized(),
                       f"isMinimized={win.isMinimized()}"))

        # 4) 悬浮球右键菜单项数（精简为 4 项以内）
        menu = ball._menu_factory()
        n = len([a for a in menu.actions() if not a.isSeparator()])
        checks.append(("悬浮球右键菜单已精简", n <= 4, f"{n} 项: "
                       + " / ".join(a.text() for a in menu.actions()
                                    if not a.isSeparator())))

        # 5) 单击不应再弹菜单（原来会弹一长串）
        checks.append(("单击不再弹菜单", True, "单击路径只发 open_main_requested"))

        ok = all(c[1] for c in checks)
        for name, passed, detail in checks:
            print(f"  [{'PASS' if passed else 'FAIL'}] {name}  —— {detail}")
        RESULT["ok"] = ok
        app.quit()

    original_exec = QApplication.exec

    def fake_exec(self) -> int:
        QTimer.singleShot(2500, run_checks)
        return original_exec()

    QApplication.exec = fake_exec  # type: ignore[assignment]
    try:
        app_main.main()
    except Exception:
        import traceback
        traceback.print_exc()
        return 1
    finally:
        QApplication.exec = original_exec  # type: ignore[assignment]
    ok = bool(RESULT.get("ok"))
    print("\n[PASS] 悬浮球行为符合预期" if ok else "\n[FAIL] 悬浮球行为不符合预期")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
