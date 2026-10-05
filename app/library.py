"""录音库：播放器卡片 + 录音列表（试听、定位、删除、导入）。

* :class:`PlayerBar`   —— 完整播放器（波形 + 播放/暂停 + 进度 + 音量）
* :class:`MiniPlayer`  —— 语音页里的"最近一次录音"小卡片
* :class:`RecordingRow`—— 列表中的一行
* :class:`LibraryPage` —— 录音库整页（列表 + 播放器 + 导入/刷新）

所有控件共用同一个 :class:`app.player.AudioPlayer` 实例，
因此语音页的小卡片与录音库页面板永远显示同一播放状态。
"""
from __future__ import annotations

import os
import shutil
import stat
import time
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMessageBox, QScrollArea, QSlider,
    QVBoxLayout, QWidget,
)

from .logger import get_logger
from .player import AudioPlayer
from .theme import repolish
from .utils import (
    fmt_datetime, fmt_mmss, fmt_size, human_file_name, reveal_in_explorer,
    scan_audio_files, wav_duration,
)
from .waveform import MiniWave, WaveformView
from .widgets import IconButton, ProgressLine, icon_label, section_label

log = get_logger(__name__)

#: 待删除清单文件名（放在录音目录的上一级，即 %APPDATA%\LocalRecord\）
PENDING_DELETE_NAME = "pending_delete.txt"


def pending_delete_file(recordings_dir: Path) -> Path:
    return Path(recordings_dir).parent / PENDING_DELETE_NAME


def pending_delete_paths(recordings_dir: Path) -> List[Path]:
    """读取"下次启动时删除"清单。"""
    f = pending_delete_file(recordings_dir)
    if not f.is_file():
        return []
    out: List[Path] = []
    try:
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line:
                out.append(Path(line))
    except OSError:
        log.exception("读取待删除清单失败")
    return out


def add_pending_delete(path: Path) -> None:
    """把一条录音加入"下次启动时删除"清单（append，去重）。"""
    path = Path(path)
    f = pending_delete_file(path.parent)
    lines = [str(p) for p in pending_delete_paths(path.parent) if str(p) != str(path)]
    lines.append(str(path))
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("已加入待删除清单（下次启动时删除）: %s", path)


def process_pending_deletes(recordings_dir: Path) -> tuple[int, int]:
    """启动时清理待删除清单，返回 (已删除数, 仍失败数)。"""
    todo = pending_delete_paths(recordings_dir)
    if not todo:
        return 0, 0
    done, failed = 0, []
    for p in todo:
        try:
            if p.exists():
                os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
                p.unlink()
            done += 1
            log.info("启动清理：已删除上次未能删除的录音 %s", p)
        except OSError as e:
            failed.append(p)
            log.warning("启动清理：仍无法删除 %s (%s)，保留到下次", p, e)
    f = pending_delete_file(recordings_dir)
    try:
        if failed:
            f.write_text("\n".join(str(p) for p in failed) + "\n", encoding="utf-8")
        elif f.is_file():
            f.unlink()
    except OSError:
        log.exception("更新待删除清单失败")
    return done, len(failed)


class PlayButtonController(QObject):
    """把"播放按钮 ↔ 共享播放器"的联动封装成 QObject。

    用绑定方法连接信号，且控制器以按钮为父对象 —— 列表刷新删除行时，
    控制器与连接会一起被回收，不会出现回调打到已删除控件的问题。
    """

    def __init__(self, player: AudioPlayer, path_provider, btn: IconButton):
        super().__init__(btn)
        self.player = player
        self.path_provider = path_provider
        self.btn = btn
        player.stateChanged.connect(self.refresh)
        player.clipLoaded.connect(self.refresh)
        btn.clicked.connect(self.clicked)
        self.refresh()

    def refresh(self, *_args) -> None:
        path = self.path_provider()
        same = path is not None and self.player.path == path
        playing = same and self.player.is_playing
        self.btn.set_icon_name("pause" if playing else "play")
        self.btn.setEnabled(path is not None)
        self.btn.set_color_token("on_accent" if playing else "accent")
        self.btn.setProperty("active", "true" if playing else "false")
        repolish(self.btn)

    def clicked(self) -> None:
        path = self.path_provider()
        if path is None:
            return
        if self.player.path == path:
            self.player.toggle()
        else:
            self.player.load(path, autoplay=True)


def _play_button(player: AudioPlayer, path_provider, object_name: str,
                 size: int, icon_size: int) -> IconButton:
    """圆形播放/暂停按钮。

    ``path_provider`` 返回该按钮负责的音频路径（``None`` 表示暂无可播放内容）；
    点击时按需把该音频载入共享播放器，因此同一时刻只有一个音频在播放。
    """
    btn = IconButton("play", "accent", icon_size, 2.4, "播放", object_name)
    btn.setFixedSize(size, size)
    btn.controller = PlayButtonController(player, path_provider, btn)  # type: ignore[attr-defined]
    return btn


class PlayerBar(QFrame):
    """完整播放器卡片（录音库页顶部）。"""

    def __init__(self, player: AudioPlayer, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("card")
        self.player = player
        self._path: Optional[Path] = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(icon_label("audio-lines", "accent", 15))
        self.title = QLabel("未选择录音")
        self.title.setObjectName("cardTitle")
        self.meta = QLabel("")
        self.meta.setObjectName("metaText")
        head.addWidget(self.title)
        head.addStretch(1)
        head.addWidget(self.meta)
        self.reveal_btn = IconButton("folder-open", "text_dim", 16, 2.0, "在文件夹中显示")
        self.reveal_btn.clicked.connect(self._reveal)
        head.addWidget(self.reveal_btn)
        lay.addLayout(head)

        self.wave = WaveformView(64)
        self.wave.seekRequested.connect(self.player.seek_ratio)
        lay.addWidget(self.wave)

        ctrl = QHBoxLayout()
        ctrl.setSpacing(10)
        self.play_btn = _play_button(player, lambda: self._path, "playBtn", 34, 15)
        ctrl.addWidget(self.play_btn)
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setObjectName("metaText")
        ctrl.addWidget(self.time_label)
        ctrl.addStretch(1)
        ctrl.addWidget(icon_label("volume", "text_dim", 15))
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setFixedWidth(76)
        self.volume.setValue(int(player.volume * 100))
        self.volume.valueChanged.connect(lambda v: player.set_volume(v / 100.0))
        ctrl.addWidget(self.volume)
        lay.addLayout(ctrl)

        player.clipLoaded.connect(self._on_loaded)
        player.positionChanged.connect(self._on_position)
        player.durationChanged.connect(lambda _d: self._sync_time())
        self.clear()

    # ---- 数据 ----
    def current_path(self) -> Optional[Path]:
        return getattr(self, "_path", None)

    def show_clip(self, path: Optional[Path]) -> None:
        """外部（如停止录音后）把某条录音装进播放器。"""
        if path is None:
            return
        clip_path = Path(path)
        if self.player.path != clip_path:
            self.player.load(clip_path)
            self._on_loaded(str(clip_path), self.player.duration)
        # 显式刷新 ▶ 状态：按钮的可用性由 controller 决定，
        # 不刷新的话会一直停在"没内容→置灰"，点了没反应
        self.play_btn.controller.refresh()

    def clear(self) -> None:
        self._path: Optional[Path] = None
        self.title.setText("未选择录音")
        self.meta.setText("")
        self.wave.clear()
        self.time_label.setText("00:00 / 00:00")
        self.play_btn.set_icon_name("play")
        self.play_btn.set_color_token("accent")
        self.play_btn.setProperty("active", "false")
        repolish(self.play_btn)

    def _on_loaded(self, path: str, duration: float) -> None:
        p = Path(path)
        self._path = p
        clip = self.player.clip
        if clip is not None:
            self.wave.set_peaks(clip.peaks(), clip.duration)
        self.title.setText(p.name)
        self.title.setToolTip(str(p))
        dur = duration or (wav_duration(p) or 0.0)
        extra = []
        try:
            stat = p.stat()
            extra.append(fmt_size(stat.st_size))
            extra.append(fmt_datetime(stat.st_mtime))
        except OSError:
            pass
        self.meta.setText(" · ".join([fmt_mmss(dur)] + extra))
        self._sync_time()

    def _on_position(self, _pos: float) -> None:
        d = self.player.duration
        self.wave.set_progress(self.player.progress)
        self.wave.set_playing(self.player.is_playing)
        self._sync_time()

    def _sync_time(self) -> None:
        d = self.player.duration
        pos = min(self.player.position, d) if d else 0.0
        self.time_label.setText(f"{fmt_mmss(pos)} / {fmt_mmss(d)}")

    def _reveal(self) -> None:
        if self._path is not None:
            reveal_in_explorer(self._path)


class MiniPlayer(QFrame):
    """语音页里的"最近一次录音"卡片：一键试听刚录的内容。"""

    def __init__(self, player: AudioPlayer, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("rowCard")
        self.player = player
        self._path: Optional[Path] = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(9, 6, 10, 6)
        lay.setSpacing(8)

        self.play_btn = _play_button(player, lambda: self._path, "rowPlayBtn", 28, 13)
        lay.addWidget(self.play_btn)

        texts = QVBoxLayout()
        texts.setSpacing(1)
        self.name = QLabel("暂无录音")
        self.name.setObjectName("rowTitle")
        self.sub = QLabel("录音停止后可在这里立即回放")
        self.sub.setObjectName("metaText")
        texts.addWidget(self.name)
        texts.addWidget(self.sub)
        lay.addLayout(texts, 1)

        self.wave = MiniWave(22)
        self.wave.setMinimumWidth(70)
        lay.addWidget(self.wave, 1)

        player.clipLoaded.connect(self._on_loaded)
        player.positionChanged.connect(self._on_position)

    def show_clip(self, path: Optional[Path]) -> None:
        if path is None:
            return
        p = Path(path)
        try:
            stat = p.stat()
        except OSError:
            return
        dur = wav_duration(p) or 0.0
        self._path = p
        self.name.setText(human_file_name(p))
        self.name.setToolTip(str(p))
        self.sub.setText(f"{fmt_mmss(dur)} · {fmt_datetime(stat.st_mtime)}")
        self.play_btn.setToolTip("试听这次录音")
        # 同上：立刻让 ▶ 可用（否则要等一次播放器加载才点亮，用户会以为坏了）
        self.play_btn.controller.refresh()
        self._sync_peaks()

    def current_path(self) -> Optional[Path]:
        """当前这张卡片指向的录音（没有则为 None）。"""
        return self._path

    def forget(self, path: Path) -> None:
        """这条录音被删掉了：清掉引用，别让 ▶ 指向不存在的文件。"""
        if self._path is not None and Path(path) == self._path:
            self.clear()

    def clear(self) -> None:
        """回到"暂无录音"状态（按钮置灰，不再指向任何文件）。"""
        self._path = None
        self.name.setText("暂无录音")
        self.name.setToolTip("")
        self.sub.setText("录音停止后可在这里立即回放")
        self.wave.clear()
        self.play_btn.setToolTip("暂无录音")
        self.play_btn.controller.refresh()

    def _sync_peaks(self) -> None:
        """按当前播放器内容刷新小波形。

        不能只依赖 ``clipLoaded`` 信号：如果这条录音**已经**载入播放器
        （例如刚在录音库里点开过），就不会再发信号，波形得直接取。
        """
        clip = self.player.clip
        if self._path is not None and clip is not None and clip.path == self._path:
            self.wave.set_peaks(clip.peaks(600))
        else:
            self.wave.clear()

    def _on_loaded(self, _path: str, _duration: float) -> None:
        self._sync_peaks()

    def _on_position(self, _pos: float) -> None:
        if self._path is not None and self.player.path == self._path:
            self.wave.set_progress(self.player.progress)
        else:
            self.wave.set_progress(0.0)


class RecordingRow(QFrame):
    """录音列表中的一行。"""

    playRequested = Signal(Path)
    deleteRequested = Signal(Path)
    #: 请求转写这条录音（已有音频 → 文字）
    transcribeRequested = Signal(Path)

    def __init__(self, path: Path, player: AudioPlayer,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("rowCard")
        self.path = path
        self.player = player

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.setSpacing(8)

        self.play_btn = _play_button(player, lambda: path, "rowPlayBtn", 26, 12)
        lay.addWidget(self.play_btn)

        texts = QVBoxLayout()
        texts.setSpacing(1)
        self.name = QLabel(human_file_name(path))
        self.name.setObjectName("rowTitle")
        dur = wav_duration(path) or 0.0
        try:
            stat = path.stat()
            meta = f"{fmt_mmss(dur)} · {fmt_datetime(stat.st_mtime)} · {fmt_size(stat.st_size)}"
        except OSError:
            meta = fmt_mmss(dur)
        self.meta = QLabel(meta)
        self.meta.setObjectName("metaText")
        texts.addWidget(self.name)
        texts.addWidget(self.meta)
        lay.addLayout(texts, 1)

        self.reveal_btn = IconButton("folder-open", "text_faint", 15, 2.0, "在文件夹中显示")
        self.reveal_btn.clicked.connect(lambda: reveal_in_explorer(self.path))
        lay.addWidget(self.reveal_btn)

        # 转写这条录音：用于"用手机等更好的麦克风录好后导入再转写"的场景
        self.transcribe_btn = IconButton("file-audio", "text_faint", 15, 2.0,
                                         "转写这条录音（把已有音频变成文字）")
        self.transcribe_btn.clicked.connect(lambda: self.transcribeRequested.emit(self.path))
        lay.addWidget(self.transcribe_btn)

        self.del_btn = IconButton("trash", "text_faint", 15, 2.0, "删除这条录音")
        self.del_btn.clicked.connect(lambda: self.deleteRequested.emit(self.path))
        lay.addWidget(self.del_btn)

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(str(path))

    def mouseDoubleClickEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self.playRequested.emit(self.path)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        # 单击整行即可试听（行内的小按钮会自行消费点击事件）
        if e.button() == Qt.MouseButton.LeftButton:
            self.player.load(self.path, autoplay=True)


class LibraryPage(QWidget):
    """录音库整页：列表 + 播放器 + 导入/刷新/打开目录。"""

    imported = Signal(int)          # 成功导入的文件数
    recordingDeleted = Signal(Path)  # 删除了一条录音（外部据此清理引用）
    #: 文件被占用 → 已安排"下次启动时删除"（外部也会清理引用，界面立即去掉该行）
    recordingDeleteDeferred = Signal(Path)
    #: 请求转写某条已有录音（音频 → 文字）
    transcribeRequested = Signal(Path)

    def __init__(self, player: AudioPlayer, directory: Path,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.player = player
        self.directory = Path(directory)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(section_label("录音库"))
        self.count_label = QLabel("0 条")
        self.count_label.setObjectName("metaText")
        head.addWidget(self.count_label)
        head.addStretch(1)
        self.import_btn = IconButton("upload", "text_dim", 16, 2.0, "导入 wav 文件")
        self.import_btn.clicked.connect(self.pick_files)
        head.addWidget(self.import_btn)
        self.refresh_btn = IconButton("refresh", "text_dim", 16, 2.0, "刷新列表")
        self.refresh_btn.clicked.connect(self.refresh)
        head.addWidget(self.refresh_btn)
        self.folder_btn = IconButton("folder-open", "text_dim", 16, 2.0, "打开录音目录")
        self.folder_btn.clicked.connect(lambda: self._open_dir())
        head.addWidget(self.folder_btn)
        lay.addLayout(head)

        self.player_bar = PlayerBar(player)
        lay.addWidget(self.player_bar)
        self.progress = ProgressLine()
        lay.addWidget(self.progress)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        holder = QWidget()
        self.rows_lay = QVBoxLayout(holder)
        self.rows_lay.setContentsMargins(0, 0, 4, 0)
        self.rows_lay.setSpacing(5)
        self.rows_lay.addStretch(1)
        self.scroll.setWidget(holder)
        lay.addWidget(self.scroll, 1)

        self.empty_label = QLabel("还没有录音。点「语音」页开始录音，或点上方 ↑ 导入 wav。")
        self.empty_label.setObjectName("hintLabel")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        lay.addWidget(self.empty_label)

        self._files: List[Path] = []
        # 已安排"下次启动时删除"的文件：列表里不再显示（文件会在下次启动时清掉）
        self._pending: set = set(pending_delete_paths(self.directory))
        self.refresh()

    # ---------------- 列表 ----------------
    def files(self) -> List[Path]:
        """当前列表里的音频文件（最新在前）。"""
        return list(self._files)

    def refresh(self, force: bool = False) -> None:
        """重建列表。

        ``force=True`` 必须用于"刚删掉文件"等场景：``self._files`` 被清空成 ``[]`` 时，
        若目录也变空，``files == self._files`` 会让这里**提前返回、旧行不销毁**，
        界面上就留下一条点不动的幽灵行（用户实测："最后一条录音删不掉"）。
        """
        files = [p for p in scan_audio_files(self.directory)
                 if p not in self._pending]
        if not force and files == self._files:
            return
        self._files = files
        while self.rows_lay.count() > 1:
            item = self.rows_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                # 先 setParent(None) 立即从界面上摘掉，再 deleteLater 回收。
                # 只调 deleteLater 的话，销毁要等事件循环处理 DeferredDelete，
                # 行会在界面上"赖着不走"（实测：删掉最后一条后仍显示一条幽灵行）
                w.setParent(None)
                w.deleteLater()
        for path in files:
            row = RecordingRow(path, self.player)
            row.deleteRequested.connect(self._delete)
            row.transcribeRequested.connect(self.transcribeRequested.emit)
            row.playRequested.connect(lambda p: self.player.load(p, autoplay=True))
            self.rows_lay.insertWidget(self.rows_lay.count() - 1, row)
        self.count_label.setText(f"{len(files)} 条")
        self.empty_label.setVisible(not files)
        self.scroll.setVisible(bool(files))

    def note_saved(self, path: Path, autoplay: bool = False) -> None:
        """录音结束后调用：刷新列表、载入播放器（可选自动播放）。"""
        self.refresh()
        self.player_bar.show_clip(path)
        if autoplay:
            self.player.play()

    # ---------------- 导入 / 删除 ----------------
    def pick_files(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        paths, _ = QFileDialog.getOpenFileNames(
            self, "导入音频", "", "音频文件 (*.wav)")
        if paths:
            self.import_files([Path(p) for p in paths])

    def import_files(self, paths: List[Path]) -> int:
        self.directory.mkdir(parents=True, exist_ok=True)
        count = 0
        for src in paths:
            src = Path(src)
            if not src.is_file() or src.suffix.lower() != ".wav":
                continue
            dst = self.directory / src.name
            n = 1
            while dst.exists() and dst.resolve() != src.resolve():
                dst = self.directory / f"{src.stem}-{n}{src.suffix}"
                n += 1
            if dst.resolve() == src.resolve():
                count += 1
                continue
            try:
                shutil.copy2(src, dst)
                count += 1
            except OSError:
                continue
        self._files = []            # 强制重建
        self.refresh()
        if count:
            self.imported.emit(count)
        return count

    def _delete(self, path: Path) -> None:
        """删除一条录音。

        用户报过"无法删除文件 / 系统找不到有效文件"，真实情况有三类，都要处理：
        1. 文件其实**已经不在了**（资源管理器里删过、列表是旧的、点了两次）——
           按"已删除"处理并刷新列表，不要弹"删除失败"吓人；
        2. 文件**被别的进程占用**（杀软/索引器/正在播放）——先释放自己的引用，
           再重试几次；仍失败才提示，并给出可操作建议；
        3. 它是播放器/最近录音条**当前指向**的文件——先停播清空，否则占用不释放。
        """
        box = QMessageBox(self)
        box.setWindowTitle("删除录音")
        box.setText(f"确定删除这条录音吗？\n\n{path.name}")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return

        # 3) 先释放自己这边的引用
        if self.player.path == path:
            self.player.stop()
            self.player_bar.clear()

        # 1) 已经不在了 → 当作删除成功
        if not path.exists():
            log.info("删除录音：文件已不存在，按已删除处理 %s", path)
            self._finish_delete(path, already_gone=True)
            return

        # 2) 删除 + 针对占用重试（Windows 上杀软扫描新录音时很常见）
        err: Optional[OSError] = None
        for attempt in range(6):
            try:
                path.unlink()
                err = None
                break
            except FileNotFoundError:
                err = None          # 竞态：刚好被外部删掉，也算成功
                break
            except OSError as e:
                err = e
                winerr = getattr(e, "winerror", None)
                # 只读属性/权限不足：先去掉只读再试一次（WinError 5 / EACCES）
                if winerr == 5 or e.errno == 13:
                    try:
                        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
                    except OSError:
                        pass
                if winerr in (5, 32) or e.errno in (11, 13, 32):
                    time.sleep(0.3 * (attempt + 1))
                    continue
                break

        if err is not None:
            # 仍然删不掉（多半被别的进程长时间占着）：问用户是否安排"下次启动时删除"，
            # 这样界面上这一行立刻消失，文件也会在下次启动时被清掉，不必一直卡着。
            log.warning("删除录音失败: %s (%s)，询问是否延后删除", path, err)
            box = QMessageBox(self)
            box.setWindowTitle("删除失败")
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText(f"这条录音仍被占用，无法立即删除：\n{path.name}")
            box.setInformativeText(
                f"原因：{err}\n\n"
                "常见原因是杀毒软件正在扫描、资源管理器在生成缩略图，或别的程序正打开它。\n"
                "点「下次启动时删除」会先把这条从列表里去掉，下次打开本程序时自动清除文件。")
            again = box.addButton("再试一次", QMessageBox.ButtonRole.AcceptRole)
            later = box.addButton("下次启动时删除", QMessageBox.ButtonRole.DestructiveRole)
            box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            clicked = box.clickedButton()
            if clicked is later:
                try:
                    add_pending_delete(path)
                except OSError:
                    log.exception("写入待删除清单失败")
                log.info("已安排下次启动时删除: %s", path)
                self._pending.add(path)
                self._finish_delete(path, already_gone=True)
                self.recordingDeleteDeferred.emit(path)
            elif clicked is again:
                self._delete(path)          # 递归重试一次（用户自己判断时机）
            return

        log.info("已删除录音: %s", path)
        self._finish_delete(path)

    def _finish_delete(self, path: Path, already_gone: bool = False) -> None:
        """删除成功（或文件本就不存在）后的收尾：刷新列表、通知外部清引用。"""
        self._files = []            # 强制重建
        self.refresh(force=True)     # 必须强制重建，否则删掉最后一条会留幽灵行
        self.recordingDeleted.emit(path)

    def _open_dir(self) -> None:
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            import os
            os.startfile(str(self.directory))     # type: ignore[attr-defined]
        except Exception:
            pass

    # ---------------- 忙碌状态 ----------------
    def set_busy(self, busy: bool) -> None:
        self.progress.set_active(busy)
