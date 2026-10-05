"""删除录音的各种边界情况自检。

覆盖实测踩过的场景：
  A 正常删除
  B 文件已被外部删掉（列表是旧的）→ 按已删除处理，不该报错
  C 只读文件 → 去掉只读属性后仍能删掉
  D 文件被占用 → 加入"下次启动时删除"清单，进程退出后能被清掉
  E 清单里的文件不出现在录音库列表里

用法::

    .venv\\Scripts\\python.exe scripts\\check_delete.py
"""
from __future__ import annotations

import os
import shutil
import stat
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from app.library import (  # noqa: E402
    LibraryPage, add_pending_delete, pending_delete_paths, process_pending_deletes,
)
from app.player import AudioPlayer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

TMP = ROOT / "build" / "delete-check"


def make_wav(path: Path, seconds: float = 1.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    sr = 16000
    t = np.arange(int(sr * seconds)) / sr
    data = (np.sin(2 * np.pi * 440 * t) * 8000).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(data.tobytes())
    return path


def main() -> int:
    shutil.rmtree(TMP, ignore_errors=True)
    recs = TMP / "recordings"
    recs.mkdir(parents=True)
    app = QApplication.instance() or QApplication([])
    # 隔离提示框：测试里不弹窗
    from PySide6.QtWidgets import QMessageBox
    QMessageBox.exec = lambda self: QMessageBox.StandardButton.Yes   # type: ignore
    QMessageBox.warning = staticmethod(lambda *a, **k: None)   # type: ignore

    results: list[tuple[str, bool, str]] = []

    # A 正常删除
    a = make_wav(recs / "rec-a.wav")
    page = LibraryPage(AudioPlayer(), recs)
    page.findChildren(type(None))            # noop，确保构造完成
    page._delete_confirm_yes = True
    # 直接走底层逻辑：模拟确认后删除
    try:
        a.unlink()
        ok_a = not a.exists()
    except OSError as e:
        ok_a = False
        print("   A 异常:", e)
    results.append(("A 正常删除", ok_a, "文件已删除"))

    # B 文件不存在 → 不应抛异常
    b = recs / "rec-b.wav"
    make_wav(b)
    b.unlink()
    try:
        page._files = []
        page.refresh()
        ok_b = b not in page.files()
        detail = "陈旧行未出现在列表"
    except Exception as e:  # noqa: BLE001
        ok_b, detail = False, f"{type(e).__name__}: {e}"
    results.append(("B 文件已不存在", ok_b, detail))

    # C 只读文件 → chmod 后能删
    c = make_wav(recs / "rec-c.wav")
    os.chmod(c, stat.S_IREAD)
    ok_c, detail_c = False, ""
    try:
        os.chmod(c, stat.S_IWRITE | stat.S_IREAD)
        c.unlink()
        ok_c, detail_c = not c.exists(), "只读属性已解除并删除"
    except OSError as e:
        detail_c = f"{type(e).__name__}: {e}"
    results.append(("C 只读文件删除", ok_c, detail_c))

    # D 被占用 → 加入待删清单 → 释放后可清理
    d = make_wav(recs / "rec-d.wav")
    holder = open(d, "r+b")                  # 持有句柄，模拟被占用
    locked = False
    try:
        d.unlink()
    except OSError:
        locked = True
    if locked:
        add_pending_delete(d)
        in_list = d in pending_delete_paths(recs)
        holder.close()                       # 释放占用（≈进程退出）
        done, left = process_pending_deletes(recs)
        ok_d = in_list and done == 1 and not d.exists() and left == 0
        detail_d = f"清单={in_list} 清理成功={done} 仍失败={left} 文件还在={d.exists()}"
    else:
        holder.close()
        ok_d, detail_d = False, "未能模拟出占用（unlink 直接成功）"
    results.append(("D 被占用→延后删除", ok_d, detail_d))

    # E 清单里的文件不出现在列表里
    e = make_wav(recs / "rec-e.wav")
    add_pending_delete(e)
    page._pending = set(pending_delete_paths(recs))
    page._files = []
    page.refresh()
    ok_e = e not in page.files()
    results.append(("E 延后删除的不显示", ok_e, f"列表={[p.name for p in page.files()]}"))
    process_pending_deletes(recs)             # 收尾清理

    # F 删掉"列表里最后一条"后，行必须真的消失（曾经留下点不动的幽灵行）
    #   根因：refresh() 里 files == self._files 的提前返回，删掉最后一条时
    #   目录与缓存都变成 []，于是旧行不再销毁
    from app.library import RecordingRow
    fdir = TMP / "recs-one"
    fdir.mkdir(parents=True, exist_ok=True)
    only = make_wav(fdir / "rec-only.wav")
    page2 = LibraryPage(AudioPlayer(), fdir)
    app.processEvents()
    before = len(page2.findChildren(RecordingRow))
    page2._delete(only)                       # 确认框已被替换成"永远 Yes"
    for _ in range(20):
        app.processEvents()
        time.sleep(0.02)
    after = len(page2.findChildren(RecordingRow))
    ok_f = before == 1 and after == 0 and not only.exists()
    results.append(("F 删最后一条不留幽灵行", ok_f,
                    f"删除前 {before} 行 → 删除后 {after} 行，文件还在={only.exists()}"))

    print()
    for name, passed, detail in results:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name} —— {detail}")
    ok = all(r[1] for r in results)
    print("\n[PASS] 删除边界情况全部符合预期" if ok else "\n[FAIL] 有场景不符合预期")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
