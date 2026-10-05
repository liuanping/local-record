"""音频播放：sounddevice 输出流 + 自绘波形所需的数据。

功能
----
* :class:`AudioClip`  —— 读取 wav（int8/int16/int32 PCM）为 float32 数组，
  并预计算波形峰值包络，供 :class:`app.waveform.WaveformView` 直接绘制；
* :class:`AudioPlayer` —— 播放 / 暂停 / 继续 / 停止 / 拖动定位 / 音量，
  位置由主线程定时器轮询音频游标后以信号发出（不在音频回调里碰 UI）。

播放线程只读写 ``self._cursor`` 一个整数，其余全部在 GUI 线程，
避免 PortAudio 回调里的锁竞争。
"""
from __future__ import annotations

import threading
import wave
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal

from .logger import get_logger

log = get_logger(__name__)

#: 波形包络的分桶数（足够画满整宽，越小越省内存）
PEAK_BUCKETS = 1600

PLAY_HINT = (
    "无法播放音频。请检查：\n"
    "1) 系统设置 → 系统 → 声音 → 输出设备是否正常；\n"
    "2) 扬声器/耳机是否被其他程序独占；\n"
    "3) 声卡驱动是否正常。"
)

_STATE_IDLE = "idle"
_STATE_PLAYING = "playing"
_STATE_PAUSED = "paused"


class AudioClipError(RuntimeError):
    """音频文件无法读取。"""


class AudioClip:
    """一段已解码的音频（float32，取值范围 -1~1）。"""

    __slots__ = ("path", "samples", "samplerate", "channels", "duration", "_peaks")

    def __init__(self, path: Path, samples: np.ndarray, samplerate: int):
        self.path = Path(path)
        self.samples = samples                       # (frames, channels) float32
        self.samplerate = int(samplerate)
        self.channels = 1 if samples.ndim == 1 else samples.shape[1]
        self.duration = len(samples) / float(self.samplerate or 1)
        self._peaks: Optional[List[Tuple[float, float]]] = None

    # ---- 加载 ----
    @classmethod
    def load(cls, path: str | Path) -> "AudioClip":
        p = Path(path)
        if not p.is_file():
            raise AudioClipError(f"文件不存在：{p}")
        if p.suffix.lower() != ".wav":
            raise AudioClipError(
                f"暂不支持 {p.suffix or '该'} 格式，请使用 wav 文件（录音默认保存为 wav）。")
        try:
            with wave.open(str(p), "rb") as w:
                channels = w.getnchannels()
                width = w.getsampwidth()
                rate = w.getframerate()
                raw = w.readframes(w.getnframes())
        except wave.Error as e:
            raise AudioClipError(f"无法解析 wav 文件：{e}") from e
        except OSError as e:
            raise AudioClipError(f"读取文件失败：{e}") from e

        dtype = {1: np.uint8, 2: np.int16, 4: np.int32}.get(width)
        if dtype is None:
            raise AudioClipError(f"不支持的采样位宽：{width * 8} bit")
        data = np.frombuffer(raw, dtype=dtype)
        if dtype is np.uint8:                      # 8bit wav 是无符号
            audio = (data.astype(np.float32) - 128.0) / 128.0
        elif dtype is np.int16:
            audio = data.astype(np.float32) / 32768.0
        else:
            audio = data.astype(np.float32) / 2147483648.0
        if channels > 1:
            audio = audio.reshape(-1, channels)
        return cls(p, np.ascontiguousarray(audio, dtype=np.float32),
                   rate or 16000)

    # ---- 波形包络 ----
    def peaks(self, buckets: int = PEAK_BUCKETS) -> List[Tuple[float, float]]:
        """返回 ``buckets`` 个 (最小值, 最大值) 包络，用于画波形。"""
        if self._peaks is not None and len(self._peaks) == buckets:
            return self._peaks
        mono = self.samples if self.samples.ndim == 1 else self.samples.mean(axis=1)
        n = len(mono)
        if n == 0:
            self._peaks = [(0.0, 0.0)] * buckets
            return self._peaks
        buckets = max(1, min(buckets, n))
        edges = np.linspace(0, n, buckets + 1).astype(np.int64)
        out: List[Tuple[float, float]] = []
        for i in range(buckets):
            seg = mono[edges[i]:edges[i + 1]]
            if len(seg) == 0:
                out.append((0.0, 0.0))
            else:
                out.append((float(seg.min()), float(seg.max())))
        self._peaks = out
        return out

    def rms(self) -> float:
        if len(self.samples) == 0:
            return 0.0
        return float(np.sqrt(np.mean(np.square(self.samples))))


class AudioPlayer(QObject):
    """基于 sounddevice 的音频播放器（一次播放一段音频）。"""

    stateChanged = Signal(str)          # idle / playing / paused
    positionChanged = Signal(float)     # 秒
    durationChanged = Signal(float)     # 秒
    clipLoaded = Signal(str, float)     # (路径, 时长)
    finished = Signal()
    errorOccurred = Signal(str)

    def __init__(self, device=None, volume: float = 0.8, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._device = device
        self._volume = max(0.0, min(1.0, float(volume)))
        self._clip: Optional[AudioClip] = None
        self._stream = None
        self._cursor = 0            # 已播放帧数
        self._eof = False
        self._state = _STATE_IDLE
        self._lock = threading.Lock()
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._poll)

    # ---------------- 只读属性 ----------------
    @property
    def state(self) -> str:
        return self._state

    @property
    def is_playing(self) -> bool:
        return self._state == _STATE_PLAYING

    @property
    def is_paused(self) -> bool:
        return self._state == _STATE_PAUSED

    @property
    def path(self) -> Optional[Path]:
        return self._clip.path if self._clip else None

    @property
    def duration(self) -> float:
        return self._clip.duration if self._clip else 0.0

    @property
    def position(self) -> float:
        if self._clip is None:
            return 0.0
        return min(self._cursor / float(self._clip.samplerate), self._clip.duration)

    @property
    def progress(self) -> float:
        d = self.duration
        return (self.position / d) if d > 0 else 0.0

    @property
    def volume(self) -> float:
        return self._volume

    @property
    def clip(self) -> Optional[AudioClip]:
        return self._clip

    # ---------------- 加载 ----------------
    def load(self, path: str | Path, autoplay: bool = False) -> bool:
        self.stop()
        try:
            clip = AudioClip.load(path)
        except AudioClipError as e:
            log.warning("加载音频失败: %s", e)
            self.errorOccurred.emit(str(e))
            return False
        self._clip = clip
        self._cursor = 0
        self._eof = False
        self.durationChanged.emit(clip.duration)
        self.positionChanged.emit(0.0)
        self.clipLoaded.emit(str(clip.path), clip.duration)
        log.info("已载入音频: %s (%.1fs)", clip.path.name, clip.duration)
        if autoplay:
            self.play()
        return True

    # ---------------- 传输控制 ----------------
    def play(self) -> None:
        if self._clip is None:
            self.errorOccurred.emit("没有已载入的音频。")
            return
        if self._state == _STATE_PAUSED and self._stream is not None:
            try:
                self._stream.start()
            except Exception as e:                      # pragma: no cover
                self._fail(e)
                return
            self._set_state(_STATE_PLAYING)
            self._timer.start()
            return
        if self._state == _STATE_PLAYING:
            return
        if not self._open_stream():
            return
        self._set_state(_STATE_PLAYING)
        self._timer.start()

    def pause(self) -> None:
        if self._state != _STATE_PLAYING:
            return
        if self._stream is not None:
            try:
                self._stream.stop()
            except Exception:                            # pragma: no cover
                log.exception("暂停失败")
        self._set_state(_STATE_PAUSED)
        self._timer.stop()
        self.positionChanged.emit(self.position)

    def toggle(self) -> None:
        if self._state == _STATE_PLAYING:
            self.pause()
        else:
            self.play()

    def stop(self) -> None:
        self._close_stream()
        self._timer.stop()
        self._cursor = 0
        self._eof = False
        if self._clip is not None:
            self.positionChanged.emit(0.0)
        self._set_state(_STATE_IDLE)

    def seek(self, seconds: float) -> None:
        if self._clip is None:
            return
        seconds = max(0.0, min(float(seconds), self._clip.duration))
        with self._lock:
            self._cursor = int(seconds * self._clip.samplerate)
            self._eof = False
        self.positionChanged.emit(seconds)

    def seek_ratio(self, ratio: float) -> None:
        self.seek(max(0.0, min(1.0, ratio)) * self.duration)

    def nudge(self, seconds: float) -> None:
        self.seek(self.position + seconds)

    def set_volume(self, volume: float) -> None:
        self._volume = max(0.0, min(1.0, float(volume)))

    # ---------------- 输出流 ----------------
    def _open_stream(self) -> bool:
        if self._clip is None:
            return False
        try:
            import sounddevice as sd
        except Exception as e:                           # pragma: no cover
            self._fail(e)
            return False
        if self._cursor >= len(self._clip.samples):
            self._cursor = 0
        self._eof = False
        channels = min(2, self._clip.channels)
        try:
            self._stream = sd.OutputStream(
                samplerate=self._clip.samplerate,
                channels=channels,
                dtype="float32",
                device=self._device,
                blocksize=1024,
                callback=self._callback,
            )
            self._stream.start()
        except Exception as e:
            self._stream = None
            self._fail(e)
            return False
        return True

    def _close_stream(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:                            # pragma: no cover
                log.exception("关闭输出流失败")

    def _callback(self, outdata, frames, time_info, status) -> None:  # noqa: ANN001
        """PortAudio 回调：只做数组拷贝与整数自增。"""
        clip = self._clip
        if clip is None or self._stream is None:
            outdata.fill(0)
            return
        with self._lock:
            start = self._cursor
            remaining = len(clip.samples) - start
            n = int(min(frames, max(0, remaining)))
            if n > 0:
                self._cursor = start + n
            else:
                self._eof = True
        if n <= 0:
            outdata.fill(0)
            return
        chunk = clip.samples[start:start + n] * self._volume
        if chunk.ndim == 1:
            outdata[:n, 0] = chunk
            if outdata.shape[1] > 1:
                outdata[:n, 1] = chunk
        else:
            outdata[:n, :chunk.shape[1]] = chunk
            if outdata.shape[1] > chunk.shape[1]:
                outdata[:n, chunk.shape[1]:] = outdata[:n, :1]
        if n < frames:
            outdata[n:] = 0
            self._eof = True

    def _poll(self) -> None:
        if self._clip is None:
            return
        self.positionChanged.emit(self.position)
        if self._eof or self.position >= self._clip.duration - 1e-3:
            self._close_stream()
            self._timer.stop()
            self._cursor = 0
            self._eof = False
            self._set_state(_STATE_IDLE)
            self.positionChanged.emit(self._clip.duration)
            self.finished.emit()

    def _set_state(self, state: str) -> None:
        if state == self._state:
            return
        self._state = state
        self.stateChanged.emit(state)

    def _fail(self, exc: Exception) -> None:
        log.exception("播放失败")
        self._stream = None
        self._timer.stop()
        self._set_state(_STATE_IDLE)
        self.errorOccurred.emit(f"播放失败：{exc}\n\n{PLAY_HINT}")
