"""麦克风采集：sounddevice 流式回调 → 音频块队列 + 实时电平。

除了给 ASR 供数据（``chunks`` 队列），这里还提供 UI 需要的三样东西：

* :attr:`Recorder.level`   —— 0~1 的实时电平（麦克风是否真的在响）；
* :attr:`Recorder.elapsed` —— 已录秒数（大计时器）；
* :meth:`Recorder.stop`    —— 返回落盘的 wav 路径，供"录音库"试听。

Windows 坑 3（点录音没反应 / 录到静音 / 不弹授权）对应处理：
- 打包时确保 sounddevice 自带的 PortAudio DLL 被收集（package_windows.sh 4d）；
- 采集启动失败（PortAudioError 等）时抛出带引导信息的 RuntimeError，
  UI 弹窗提示去系统设置：设置 → 隐私和安全性 → 麦克风 →
  「允许桌面应用访问你的麦克风」。
  （Windows 的授权弹窗在首次启动采集时出现，与 macOS 的 TCC 弹窗类似；
    若系统设置里"桌面应用"权限关闭，不会弹窗且录到静音。）
"""
from __future__ import annotations

import math
import queue
import threading
import wave
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import numpy as np

from .logger import get_logger

log = get_logger(__name__)

MIC_PRIVACY_HINT = (
    "无法打开麦克风。请检查：\n"
    "1) 系统设置 → 隐私和安全性 → 麦克风 → 打开「允许桌面应用访问你的麦克风」；\n"
    "2) 系统设置 → 系统 → 声音 → 输入设备选择是否正确；\n"
    "3) 没有其他程序（会议软件等）独占麦克风。"
)

#: 电平条只统计该频率以上的能量（人声频段）：很多笔记本麦克风有极强低频轰鸣，
#: 用它做电平会让条子一直顶满，用户看不出"我说话到底被采到没有"
LEVEL_BAND_HZ = 2000.0
#: 电平条的映射区间：该频段 RMS 的 dBFS 从 LEVEL_FLOOR_DB（=0）到 LEVEL_FULL_DB（=1）
LEVEL_FLOOR_DB = -42.0
LEVEL_FULL_DB = -18.0


def list_input_devices() -> List[str]:
    """列出可用输入设备（供设置界面/排查使用）。"""
    try:
        import sounddevice as sd
    except Exception:
        return []
    names: List[str] = []
    try:
        for idx, dev in enumerate(sd.query_devices()):
            if int(dev.get("max_input_channels", 0)) > 0:
                names.append(f"{idx}: {dev.get('name', '未知设备')}")
    except Exception:
        log.exception("枚举录音设备失败")
    return names


def _wasapi_default_input(sd) -> tuple[Optional[int], object]:
    """返回 (WASAPI 下的默认输入设备索引, 自动重采样设置)；没有 WASAPI 则 (None, None)。"""
    try:
        for api in sd.query_hostapis():
            if "WASAPI" in str(api.get("name", "")):
                dev = int(api.get("default_input_device", -1))
                if dev >= 0:
                    # auto_convert=True：允许 WASAPI 自己把 44.1k 转成我们要的 16k
                    return dev, sd.WasapiSettings(auto_convert=True)
    except Exception:  # noqa: BLE001
        log.debug("查询 WASAPI 失败", exc_info=True)
    return None, None


class Recorder:
    """采集 int16 PCM 音频块（默认 16kHz 单声道），每块 100ms。

    音频块通过 :attr:`chunks` 队列交给 ASR 工作线程消费；
    PortAudio 回调线程只做 ``queue.put`` 与少量算术，不阻塞、不碰 UI。
    """

    def __init__(self, sample_rate: int = 16000, channels: int = 1,
                 dtype: str = "int16", device=None, block_ms: int = 100,
                 save_dir: Optional[Path] = None, prefer_wasapi: bool = True,
                 normalize_save: bool = True):
        self.sample_rate = sample_rate
        self.channels = channels
        self.dtype = dtype
        self.device = device
        self.block_ms = block_ms
        self.save_dir = Path(save_dir) if save_dir else None
        self.chunks: "queue.Queue[np.ndarray]" = queue.Queue()
        self.last_path: Optional[Path] = None
        self._stream = None
        self._lock = threading.Lock()
        self._wav_frames: List[np.ndarray] = []
        self._frames = 0            # 已采集帧数
        self._level = 0.0           # 平滑后的电平 0~1
        self._peak = 0.0            # 本次录音的峰值（判断是否全静音）
        self._overflows = 0
        self._win_cache: dict = {}
        #: 优先用 WASAPI 采集（重采样质量远好于 MME）；设备被显式指定时不干预
        self.prefer_wasapi = bool(prefer_wasapi)
        #: 落盘时是否做整体增益归一化（回听音量正常；波形形状不变）
        self.normalize_save = bool(normalize_save)
        self.host_api_used = "-"

    # ---------------- 状态查询 ----------------
    @property
    def is_recording(self) -> bool:
        stream = self._stream
        return stream is not None and bool(stream.active)

    @property
    def level(self) -> float:
        """实时电平（0~1），用于电平条 / 悬浮球呼吸圈。"""
        return self._level

    @property
    def peak(self) -> float:
        return self._peak

    @property
    def elapsed(self) -> float:
        """已录制秒数（按实际采集帧数计算，不会漂移）。"""
        if self.sample_rate <= 0:
            return 0.0
        return self._frames / float(self.sample_rate)

    @property
    def frames(self) -> int:
        return self._frames

    # ---------------- 生命周期 ----------------
    def start(self) -> None:
        import sounddevice as sd  # 延迟导入，避免无音频设备时拖慢启动
        with self._lock:
            if self.is_recording:
                return
            if self.save_dir:
                self.save_dir.mkdir(parents=True, exist_ok=True)
            self._wav_frames = []
            self._frames = 0
            self._level = 0.0
            self._peak = 0.0
            self._overflows = 0
            self.last_path = None
            self._drain()
            self._stream = self._open_stream(sd)
            try:
                self._stream.start()
            except Exception as e:  # PortAudioError 等
                self._stream = None
                log.exception("启动录音失败")
                raise RuntimeError(f"录音启动失败：{e}\n\n{MIC_PRIVACY_HINT}") from e
            log.info("开始录音（设备=%s, %d Hz, %d 声道, host API=%s）",
                     self.device if self.device is not None else "默认",
                     self.sample_rate, self.channels, self.host_api_used)

    def _open_stream(self, sd):
        """打开输入流：**优先 WASAPI**，失败再退回系统默认（通常是 MME）。

        实测本机麦克风原生 44.1kHz，而模型要 16kHz，这个重采样由 host API 负责：
        MME 的重采样质量差（听感发闷、失真，也会拉低识别率），WASAPI 好得多。
        WASAPI 打开失败（独占模式、老驱动）时自动退回，不影响可用性。
        """
        kwargs = dict(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype=self.dtype,
            blocksize=int(self.sample_rate * self.block_ms / 1000),
            callback=self._callback,
        )
        if self.device is None and self.prefer_wasapi:
            dev, extra = _wasapi_default_input(sd)
            if dev is not None:
                try:
                    stream = sd.InputStream(device=dev, extra_settings=extra, **kwargs)
                    self.host_api_used = "WASAPI"
                    return stream
                except Exception as e:  # noqa: BLE001
                    log.warning("WASAPI 打开失败（%s），退回系统默认 host API", e)
        self.host_api_used = "默认(MME/DirectSound)"
        return sd.InputStream(device=self.device, **kwargs)

    def _callback(self, indata, frames, time_info, status):
        # PortAudio 回调线程：只做无锁操作与少量算术
        if status:
            self._overflows += 1
            if self._overflows in (1, 50):
                log.warning("音频流状态异常: %s", status)
        self.chunks.put(indata.copy())
        self._wav_frames.append(indata.copy())
        self._frames += int(frames)
        self._level = self._compute_level(indata)

    def _compute_level(self, indata) -> float:
        """把本次回调的音频块换算成 0~1 电平（快起慢落，肉眼舒服）。

        只统计 1.5kHz 以上的人声频段：本机实测麦克风有很强的低频轰鸣
        （95% 能量在 500Hz 以下、峰值接近满量程），不滤掉的话电平条会被轰鸣
        顶满，用户根本看不出"自己说话有没有被采到"。
        """
        try:
            block = indata[:, 0] if indata.ndim > 1 else indata
            if block.dtype != np.float32:
                block = block.astype(np.float32) / 32768.0
            if block.size < 64:
                return self._level
            peak = float(np.abs(block).max())
            if peak > self._peak:
                self._peak = peak
            # 用 FFT 只取人声频段能量（1600 点 rfft 只要几十微秒，回调里够用）
            win = self._window(block.size)
            power = np.abs(np.fft.rfft(block * win)) ** 2
            freqs = np.fft.rfftfreq(block.size, 1.0 / self.sample_rate)
            band = float(power[freqs >= LEVEL_BAND_HZ].sum())
            # Parseval 反推该频段 RMS（单边谱要乘 2，并除以样点数与窗能量）
            band_rms = math.sqrt(2.0 * max(band, 0.0)) / max(
                block.size * math.sqrt(float((win ** 2).mean())), 1e-9)
            db = 20.0 * math.log10(max(band_rms, 1e-9))
            target = (db - LEVEL_FLOOR_DB) / (LEVEL_FULL_DB - LEVEL_FLOOR_DB)
            target = max(0.0, min(1.0, target))
            # 起音快、回落慢
            k = 0.55 if target > self._level else 0.10
            return self._level + (target - self._level) * k
        except Exception:                      # pragma: no cover - 回调里绝不能抛
            return self._level

    def _window(self, size: int) -> np.ndarray:
        """按块长缓存汉宁窗（回调每 100ms 调一次，别反复分配）。"""
        win = self._win_cache.get(size)
        if win is None:
            win = np.hanning(size).astype(np.float32)
            self._win_cache = {size: win}      # 块长基本固定，只留最近一个
        return win

    def stop(self) -> Optional[Path]:
        """停止录音；返回落盘的 wav 路径（无音频则返回 None）。"""
        with self._lock:
            stream, self._stream = self._stream, None
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    log.exception("关闭录音流失败")
            self._level = 0.0
            if self._wav_frames:
                try:
                    self.last_path = self._save_wav()
                except Exception:
                    log.exception("保存录音失败")
                    self.last_path = None
                return self.last_path
            return None

    # ---------------- 落盘 ----------------
    def _save_wav(self) -> Path:
        frames = np.concatenate(self._wav_frames, axis=0)
        # 落盘前做一次**整体增益归一化**：只乘一个系数，波形形状完全不变，
        # 目的是让回听音量正常。实测用户的麦克风电平只有 -25dBFS（说话帧），
        # 不处理的话保存下来的 wav 听着很小声；而识别链路本来就按段归一化，
        # 所以这一步只影响回听，不影响识别率。
        gain_db = 0.0
        if self.normalize_save:
            frames, gain_db = _normalize_peak(frames)
        path = self._wav_dir() / f"rec-{datetime.now():%Y%m%d-%H%M%S}.wav"
        data, sampwidth = _to_pcm16(frames)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(self.channels)
            w.setsampwidth(sampwidth)
            w.setframerate(self.sample_rate)
            w.writeframes(data)
        seconds = len(frames) / float(self.sample_rate or 1)
        log.info("录音已保存: %s (%.1fs, 峰值 %.3f%s)", path, seconds, self._peak,
                 f", 已整体增益 +{gain_db:.1f}dB" if gain_db > 0.1 else "")
        return path

    def _wav_dir(self) -> Path:
        if self.save_dir is not None:
            self.save_dir.mkdir(parents=True, exist_ok=True)
            return self.save_dir
        import tempfile
        tmp = Path(tempfile.gettempdir()) / "LocalRecord"
        tmp.mkdir(parents=True, exist_ok=True)
        return tmp

    def _drain(self) -> None:
        """清空队列里的残留数据（上一次录音没被消费完的块）。"""
        try:
            while True:
                self.chunks.get_nowait()
        except queue.Empty:
            pass


def _normalize_peak(frames: np.ndarray, target: float = 0.95,
                    max_gain: float = 10.0, min_peak: float = 0.005
                    ) -> "tuple[np.ndarray, float]":
    """整体增益归一化：返回 (处理后的音频, 施加的增益 dB)。

    * 只乘一个系数 → 波形形状与动态完全不变，不会压缩/失真；
    * ``max_gain`` 限制最大放大倍数（默认 +20dB），避免把近乎静音的录音
      连底噪一起放大成沙沙声；
    * 峰值低于 ``min_peak`` 视为静音，不做处理。
    """
    if frames.size == 0:
        return frames, 0.0
    peak = float(np.abs(frames.astype(np.float32)).max())
    if peak < min_peak or peak >= target:
        return frames, 0.0
    gain = min(target / peak, max_gain)
    if gain <= 1.02:                      # 提升不到 0.2dB 就不折腾
        return frames, 0.0
    out = np.clip(frames.astype(np.float32) * gain, -1.0, 1.0)
    return out, 20.0 * float(np.log10(gain))


def _to_pcm16(frames: np.ndarray) -> tuple[bytes, int]:
    """把采集到的 numpy 数组转成 wav 需要的 int16 字节流。"""
    if frames.dtype == np.int16:
        return frames.tobytes(), 2
    if frames.dtype == np.int32:
        return (frames >> 16).astype(np.int16).tobytes(), 2
    if frames.dtype == np.float32 or frames.dtype == np.float64:
        clipped = np.clip(frames, -1.0, 1.0)
        return (clipped * 32767.0).astype(np.int16).tobytes(), 2
    return frames.astype(np.int16).tobytes(), 2
