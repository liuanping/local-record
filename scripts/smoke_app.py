"""整机冒烟测试（开发辅助，不参与打包）。

在**完全隔离**的目录里启动真实应用（offscreen 平台），验证：

1. 启动流程无异常、日志里没有 traceback；
2. 界面三个页面都能构建（真实录音库会被扫描到）；
3. 录音 → 落盘 → 试听 整条链路（有麦克风时）；没有麦克风则跳过；
4. 主题切换、状态胶囊、录音库刷新等不报错。

隔离方式：``LOCAL_RECORD_DIR``（config + storage）与 ``APPDATA``（日志/录音）
都指向 ``build/smoke``，不会碰用户真实数据。
为了不启动几 GB 的大模型，这里把 ``LlamaServer`` 替换成"构造即失败"的桩，
顺带覆盖"大模型不可用"这条分支。

运行::

    .venv\\Scripts\\python.exe scripts\\smoke_app.py
"""
from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SMOKE = ROOT / "build" / "smoke"
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.name == "nt" and Path(r"C:\Windows\Fonts").is_dir():
    os.environ["QT_QPA_FONTDIR"] = r"C:\Windows\Fonts"
os.environ["LOCAL_RECORD_DIR"] = str(SMOKE)
os.environ["APPDATA"] = str(SMOKE / "appdata")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import app.main as app_main  # noqa: E402
from app.llama_server import LlamaServerError  # noqa: E402
from app.main_window import MainWindow  # noqa: E402

PROBLEMS: list[str] = []
NOTES: list[str] = []


def note(text: str) -> None:
    NOTES.append(text)
    print(f"  · {text}")


def problem(text: str) -> None:
    PROBLEMS.append(text)
    print(f"  [FAIL] {text}")


def prepare() -> None:
    """准备隔离资源目录：config.yaml + 空 storage。"""
    if SMOKE.exists():
        shutil.rmtree(SMOKE, ignore_errors=True)
    (SMOKE / "storage").mkdir(parents=True, exist_ok=True)
    (SMOKE / "appdata").mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "config.yaml", SMOKE / "config.yaml")
    # 放两段真实录音进隔离数据目录，验证"录音库"页能加载与解析波形
    src = Path(os.environ["APPDATA"])  # 已被改写，下面用真实路径兜底
    user_rec = Path(os.path.expandvars(r"%USERPROFILE%\AppData\Roaming")) / "LocalRecord" / "recordings"
    dest = SMOKE / "appdata" / "LocalRecord" / "recordings"
    dest.mkdir(parents=True, exist_ok=True)
    if user_rec.is_dir():
        wavs = sorted(user_rec.glob("*.wav"))[:2]
        for w in wavs:
            shutil.copy2(w, dest / w.name)
        note(f"复制 {len(wavs)} 个真实录音用于录音库渲染测试")


def patch_everything() -> dict:
    """替换大模型服务与弹窗，避免拉起真实进程/阻塞事件循环。"""
    class NoServer:
        def __init__(self, *_a, **_k):
            raise LlamaServerError("smoke test: 跳过真实 llama-server")

    app_main.LlamaServer = NoServer

    boxes: list[str] = []

    def _box(*args, **_kwargs):
        boxes.append(str(args[1] if len(args) > 1 else args))
        print(f"  · 弹窗（已拦截）：{boxes[-1]}")

    QMessageBox.warning = staticmethod(_box)      # type: ignore[assignment]
    QMessageBox.information = staticmethod(_box)  # type: ignore[assignment]
    return {"boxes": boxes}


def main() -> int:
    prepare()
    hooks = patch_everything()

    result: dict = {"window": None, "wav": None, "played": False, "code": None}

    def find_window() -> None:
        for w in QApplication.topLevelWidgets():
            if isinstance(w, MainWindow):
                result["window"] = w
                return

    def start_record() -> None:
        find_window()
        win = result["window"]
        if win is None:
            problem("找不到主窗口")
            return
        note(f"主窗口已构建：{win.stack.count()} 页 / {len(win.library_page.files())} 条录音")
        try:
            import sounddevice as sd
            has_mic = any(d["max_input_channels"] > 0 for d in sd.query_devices())
        except Exception as e:
            has_mic = False
            note(f"查询录音设备失败：{e}")
        if not has_mic:
            note("没有麦克风，跳过真实录音环节")
            return
        win.toggle_record_clicked.emit()
        note("已发出开始录音信号")

    def stop_record() -> None:
        win = result["window"]
        if win is None or not win._recording:
            return
        win.toggle_record_clicked.emit()
        note("已发出停止录音信号")
        rec_dir = SMOKE / "appdata" / "LocalRecord" / "recordings"
        fresh = sorted(rec_dir.glob("rec-*.wav"), key=lambda p: p.stat().st_mtime)
        if fresh:
            result["wav"] = fresh[-1]
            note(f"新录音：{fresh[-1].name} ({fresh[-1].stat().st_size} 字节)")

    def test_playback() -> None:
        win = result["window"]
        if win is None:
            return
        files = win.library_page.files()
        if not files:
            problem("录音库为空（应至少包含复制进来的真实录音）")
            return
        # 挑最长的一条，避免刚录的极短片段还没采样就已经播完
        target = max(files, key=lambda p: p.stat().st_size)
        player = win.player
        if not player.load(target):
            problem("播放引擎无法载入录音库里的 wav")
            return
        note(f"已载入 {target.name}，时长 {player.duration:.2f}s")
        player.play()
        max_pos = 0.0
        deadline = time.time() + 0.8
        while time.time() < deadline:
            QApplication.processEvents()
            max_pos = max(max_pos, player.position)
            time.sleep(0.02)
        result["played"] = max_pos > 0.05
        if result["played"]:
            note(f"播放位置推进到 {max_pos:.2f}s")
        else:
            problem("播放位置没有推进")
        player.stop()

        if result["wav"] is not None:
            if player.load(result["wav"]):
                note("刚录的 wav 可以立即回放")
            else:
                problem("刚录的 wav 无法回放")

    def switch_theme() -> None:
        win = result["window"]
        if win is None:
            return
        win.theme_toggled.emit()
        QApplication.processEvents()
        win.theme_toggled.emit()
        QApplication.processEvents()
        note("主题切换两次无异常")

    def finish() -> None:
        """通过悬浮球菜单里的「退出」走真实退出流程（停止 ASR/播放/子进程）。"""
        from app.ball import FloatingBall
        for w in QApplication.topLevelWidgets():
            if isinstance(w, FloatingBall):
                menu = w._menu_factory()
                for act in menu.actions():
                    if act.text() == "退出":
                        act.trigger()
                        note("已通过菜单「退出」触发优雅退出")
                        return
        problem("悬浮球菜单里找不到「退出」项")
        app = QApplication.instance()
        if app is not None:
            app.quit()

    original_exec = QApplication.exec

    def fake_exec(self) -> int:
        QTimer.singleShot(300, find_window)
        QTimer.singleShot(600, start_record)
        QTimer.singleShot(2400, stop_record)
        QTimer.singleShot(2800, test_playback)
        QTimer.singleShot(3400, switch_theme)
        QTimer.singleShot(3900, finish)
        code = original_exec()
        result["code"] = code
        return code

    QApplication.exec = fake_exec  # type: ignore[assignment]
    try:
        code = app_main.main()
    except Exception:
        import traceback
        traceback.print_exc()
        problem("main() 抛异常")
        return 1
    finally:
        QApplication.exec = original_exec  # type: ignore[assignment]

    # ---- 日志检查 ----
    log_file = SMOKE / "appdata" / "LocalRecord" / "logs" / "app.log"
    if not log_file.is_file():
        problem("没有生成日志文件")
    else:
        text = log_file.read_text(encoding="utf-8", errors="replace")
        # 隔离环境里故意不放 ASR 模型，"模型不存在"的堆栈属于预期分支
        unexpected = [
            block for block in text.split("Traceback (most recent call last):")[1:]
            if "SenseVoice 模型不存在" not in block
        ]
        if unexpected:
            problem("日志里出现非预期异常：\n" + unexpected[0][:500])
        if "启动失败" in text:
            problem("日志里出现「启动失败」")
        for key in ("=== Local Record 启动", "启动完成，等待用户操作", "用户退出"):
            if key not in text:
                problem(f"日志缺少关键行：{key}")
        note(f"日志大小 {log_file.stat().st_size} 字节")

    print("\n================ 结果 ================")
    if PROBLEMS:
        print(f"失败 {len(PROBLEMS)} 项：")
        for p in PROBLEMS:
            print(f"  - {p}")
        return 1
    print(f"冒烟测试通过（{len(NOTES)} 项观察，退出码 {code}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
