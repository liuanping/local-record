"""SenseVoice 实时转写（sherpa-onnx）。

方案：麦克风音频块进入队列，攒够 ``asr.chunk_seconds`` 秒后送入
``OfflineRecognizer``（SenseVoice 属于离线模型），逐段转写并带起始
时间戳，实现「边录边转写」。

工作线程 :class:`ASRWorker` 常驻：初始化模型 → 消费音频块 → 发射
``segment`` 信号（text, start_sec, end_sec）。

**段长直接影响准确率**（实测可复现：``scripts/check_asr.py --sweep``）：

    整段一次 1.9% ｜ 12 秒/段 3.3% ｜ 8 秒/段 3.3% ｜ 4 秒/段 4.8% ｜ 15 秒/段 4.3%

（字错率 CER，越低越好；同一段 60 秒中文会议语音、209 字标准答案。）
离线模型段越长上下文越足，所以默认 8 秒，再调大收益不明显。
"""
from __future__ import annotations

import queue
import re
import threading
import time
from typing import Optional

import numpy as np
from PySide6.QtCore import QThread, Signal

from .config import storage_path
from .logger import get_logger

log = get_logger(__name__)

#: 低于该峰值视为纯静音（约 -54 dBFS），不送识别，避免底噪被模型编成文字
SILENCE_PEAK = 0.002

#: 语音存在性指标（仅用于诊断/工具，**不作为丢弃依据**）
#: 实测：优质 TTS 语音的 1.5kHz 占比中位只有 7.5%，与纯噪声 3.5% 高度重叠，
#: 用它当门限会误杀正常语音（曾经踩过：一半的段被丢掉、CER 从 3.3% 涨到 60%）。
SPEECH_BAND_HZ = 1500.0

#: 只由这些语气词构成、且长度很短的段落视为"没有内容"（模型对着噪声常吐"嗯"）
FILLER_CHARS = set("嗯啊呃哦诶哎唉呀哈唔嘛誒")
FILLER_MAX_LEN = 3

#: 标点字符（判断"有没有实际内容"时忽略它们）
PUNCT_CHARS = "，。、！？；：、（）《》〈〉【】「」『』…—～·,.!?;:\"'()[]{}<>- "

#: 队列哨兵：要求工作线程立刻把当前缓冲转写掉（用户停止录音时用）
FLUSH = "__flush__"


def speech_band_ratio(samples: np.ndarray, sample_rate: int) -> float:
    """返回 1.5kHz 以上能量占总能量的比例（**仅作诊断参考，不要用来丢弃音频**）。"""
    if len(samples) < 512:
        return 0.0
    win = np.hanning(len(samples))
    power = np.abs(np.fft.rfft(samples * win)) ** 2
    freqs = np.fft.rfftfreq(len(samples), 1.0 / sample_rate)
    total = float(power.sum()) + 1e-12
    return float(power[freqs >= SPEECH_BAND_HZ].sum()) / total


def is_meaningless(text: str) -> bool:
    """判断识别结果是不是"没有实际内容"（空、纯标点、或只有语气词）。

    比"用能量比判断有没有人声"可靠：让模型先识别，再判结果 ——
    语气词/空文本丢弃，正常文字保留，不会误杀真实的轻声说话。
    """
    core = "".join(ch for ch in text if ch not in PUNCT_CHARS and not ch.isspace())
    if not core:
        return True
    return len(core) <= FILLER_MAX_LEN and all(ch in FILLER_CHARS for ch in core)


def looks_like_hallucination(text: str, run_len: int = 4) -> bool:
    """识别结果是否像"噪声幻觉"（同一个字连着重复很多次）。

    实测没人说话时模型会输出「……证证证证证证证证证证据的证的证见」这类东西，
    正常中文里连续 4 个相同字几乎不会出现。
    """
    core = "".join(ch for ch in text if ch not in PUNCT_CHARS and not ch.isspace())
    if len(core) < run_len:
        return False
    run = 1
    for prev, ch in zip(core, core[1:]):
        run = run + 1 if ch == prev else 1
        if run >= run_len:
            return True
    return False


# ------------------------------------------------------------ 静音判定 ----
#: 判定"这一段到底有没有人说话"：噪声底以上帧占比低于该值就跳过识别。
#: 实测（本机样本）：有人说话 21%~63%，纯噪声/静音 0%~1%，所以 6% 有 3 倍以上余量。
SPEECH_MIN_RATIO = 0.06
SPEECH_REL_DB = 8.0        # 高出噪声底 8dB 才算"有声帧"
SPEECH_ABS_DB = -50.0      # 绝对下限，防止把极安静的环境判成有声


def speech_present(samples: np.ndarray, sample_rate: int,
                   min_ratio: float = SPEECH_MIN_RATIO,
                   rel_db: float = SPEECH_REL_DB,
                   abs_db: float = SPEECH_ABS_DB) -> tuple[bool, float, float]:
    """判断这段音频里有没有人声（自适应能量法）。

    为什么不用 Silero VAD：实测在本机 6 个样本上错 1 个（63 秒真实录音被判成无人声），
    而能量法 6/6 全对；而且它对低频轰鸣不敏感（先做了一阶差分当高通）。

    返回 ``(是否有人声, 噪声底 dB, 超过阈值的帧占比)``。
    """
    frame, hop = int(sample_rate * 0.02), int(sample_rate * 0.01)
    if len(samples) < frame * 2:
        return False, -99.0, 0.0
    # 一阶差分 ≈ 高通：压掉低频轰鸣，让"说话/没说话"的区别更明显
    src = samples.astype(np.float32)
    d = np.diff(src, prepend=src[:1])
    n = 1 + (len(d) - frame) // hop
    idx = np.arange(frame)[None, :] + hop * np.arange(n)[:, None]
    rms = np.sqrt((d[idx] ** 2).mean(axis=1) + 1e-12)
    db = 20.0 * np.log10(rms + 1e-9)
    noise = float(np.percentile(db, 10))          # 噪声底 = 最安静的 10% 帧
    thr = max(noise + rel_db, abs_db)
    ratio = float((db > thr).mean())
    return ratio >= min_ratio, noise, ratio


class ASREngine:
    """SenseVoice 模型封装（供 ASR 工作线程使用）。"""

    def __init__(self, cfg: dict):
        self.cfg = cfg["asr"]
        self.sample_rate = int(self.cfg.get("sample_rate", 16000))
        self.chunk_len = int(self.sample_rate
                             * float(self.cfg.get("chunk_seconds", 8.0)))
        self._recognizer = None
        self._punct = None

    def init(self) -> None:
        """加载 ASR 模型；文件缺失时给出明确报错。

        支持两种引擎（``asr.backend``）：
          * ``paraformer``  中文准确率更高（实测同一段会议语音 CER 1.9% vs 3.3%），
            体积相当、速度更快，但只支持中文；
          * ``sense_voice`` 支持中英日韩粤，中文略逊，作为可切换的备选。
        """
        if self._recognizer is not None:
            return
        try:
            import sherpa_onnx
        except ImportError as e:
            raise RuntimeError("缺少 sherpa-onnx：pip install sherpa-onnx") from e

        backend = str(self.cfg.get("backend", "paraformer")).lower()
        if backend in ("sense_voice", "sensevoice", "sense-voice"):
            sc = self.cfg["sense_voice"]
            model_dir = storage_path(self.cfg, "sense_voice.model_dir")
            model_path = model_dir / sc["model_filename"]
            tokens_path = model_dir / sc["tokens_filename"]
            for p, name in ((model_path, "SenseVoice 模型"),
                            (tokens_path, "tokens 文件")):
                if not p.is_file():
                    raise FileNotFoundError(
                        f"{name}不存在: {p}\n请把模型放入 storage/ 并检查 config.yaml")
            try:
                self._recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                    model=str(model_path), tokens=str(tokens_path), num_threads=2,
                    decoding_method="greedy_search",
                    language=sc.get("language", "zh"),
                    use_itn=bool(sc.get("use_itn", True)), debug=False)
            except Exception as e:
                log.exception("SenseVoice 加载失败")
                raise RuntimeError(f"SenseVoice 模型加载失败：{e}") from e
        else:
            pc = self.cfg.get("paraformer") or {}
            model_dir = storage_path(self.cfg, "paraformer.model_dir")
            model_path = model_dir / pc.get("model_filename", "model.int8.onnx")
            tokens_path = model_dir / pc.get("tokens_filename", "tokens.txt")
            for p, name in ((model_path, "Paraformer 模型"),
                            (tokens_path, "tokens 文件")):
                if not p.is_file():
                    raise FileNotFoundError(
                        f"{name}不存在: {p}\n请把模型放入 storage/ 并检查 config.yaml")
            try:
                self._recognizer = sherpa_onnx.OfflineRecognizer.from_paraformer(
                    paraformer=str(model_path), tokens=str(tokens_path),
                    num_threads=2, sample_rate=self.sample_rate,
                    feature_dim=80, decoding_method="greedy_search", debug=False)
            except Exception as e:
                log.exception("Paraformer 加载失败")
                raise RuntimeError(f"Paraformer 模型加载失败：{e}") from e
        log.info("ASR 就绪（%s）: %s", backend, model_path)
        self._init_punctuation(sherpa_onnx)

    def _init_punctuation(self, sherpa_onnx) -> None:
        """加载标点恢复模型（CT-Transformer）。

        SenseVoice 只输出纯文字、**不带标点**，长转写看起来一坨；
        这个模型负责补上，、。？！等。模型文件缺失时静默跳过（功能降级，不算错误）。
        """
        pc = (self.cfg.get("punctuation") or {})
        if not pc.get("enabled", True):
            log.info("标点恢复已在 config.yaml 里关闭")
            return
        pdir = storage_path(self.cfg, "punctuation.model_dir")
        model = pdir / pc.get("model_filename", "model.onnx")
        tokens = pdir / pc.get("tokens_filename", "tokens.txt")
        if not (model.is_file() and tokens.is_file()):
            log.warning("未找到标点模型（%s），转写将不带标点。"
                        "可把 model.onnx / tokens.txt 放到该目录，或设 punctuation.enabled=false",
                        pdir)
            return
        try:
            cfg = sherpa_onnx.OfflinePunctuationConfig(
                model=sherpa_onnx.OfflinePunctuationModelConfig(
                    ct_transformer=str(model), num_threads=1, debug=False))
            self._punct = sherpa_onnx.OfflinePunctuation(cfg)
            log.info("标点恢复就绪: %s", model)
        except Exception:
            log.exception("标点模型加载失败（继续用不带标点的结果）")
            self._punct = None

    def _add_punctuation(self, text: str) -> str:
        if not text or self._punct is None:
            return text
        try:
            return self._punct.add_punctuation(text) or text
        except Exception:
            log.exception("标点恢复失败（本段用原文）")
            return text

    def recognize(self, samples_f32: np.ndarray) -> str:
        stream = self._recognizer.create_stream()
        stream.accept_waveform(self.sample_rate, samples_f32)
        self._recognizer.decode_stream(stream)
        return self._add_punctuation(self._clean(stream.result.text))

    @staticmethod
    def _clean(text: str) -> str:
        # 去掉 SenseVoice 可能输出的标记（<|zh|> 等）与多余空白
        text = re.sub(r"<\|[^|]*\|>", "", text)
        text = text.replace("[PAD]", "").replace("[unk]", "")
        return " ".join(text.split())


class ASRWorker(QThread):
    """常驻工作线程：初始化模型 → 消费音频块 → 发射分段信号。"""

    ready = Signal(bool, str)            # (ok, message)
    segment = Signal(str, float, float)  # (text, start_sec, end_sec)
    noVoice = Signal(int)                # (连续多少段没识别出内容) —— 疑似麦克风没收到人声
    stopped = Signal()

    def __init__(self, cfg: dict, chunks: "queue.Queue[np.ndarray]", parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.chunks = chunks
        self._engine: Optional[ASREngine] = None
        self._stop = threading.Event()
        self._buf = np.zeros(0, dtype=np.float32)
        self._seg_start = 0.0
        self._empty = 0            # 连续"没有可用内容"的段数（用于提示用户）
        #: 静音判定阈值：可在 config.yaml 的 asr.speech_min_ratio 调整
        self._min_ratio = float(self.cfg.get("speech_min_ratio", SPEECH_MIN_RATIO))

    def run(self) -> None:
        try:
            self._engine = ASREngine(self.cfg)
            self._engine.init()
        except Exception as e:
            log.exception("ASR 初始化失败")
            self.ready.emit(False, f"ASR 加载失败：{e}")
            return
        self.ready.emit(True, "ASR 就绪")
        sr = self._engine.sample_rate

        while not self._stop.is_set():
            try:
                block = self.chunks.get(timeout=0.2)
            except queue.Empty:
                continue
            if block is None:  # 关闭信号
                break
            if isinstance(block, str) and block == FLUSH:
                # 用户停止录音：立刻把不足一段的缓冲也转写出来，
                # 否则"说不到 chunk_seconds 秒"的录音一个字都不会出（用户实测踩过）
                self._guard(self._flush_buffer)
                continue
            self._guard(self._feed, block)

        # 收尾：用户点了「停止录音」，但队列里已经采集到的音频不能丢——
        # 旧实现在这里直接 break，残留块被整段丢弃，最后一段就再也不会被转写。
        deadline = time.monotonic() + 120.0
        while time.monotonic() < deadline:
            try:
                block = self.chunks.get_nowait()
            except queue.Empty:
                break
            if block is None or (isinstance(block, str) and block == FLUSH):
                continue
            self._guard(self._feed, block)
        self._guard(self._flush_buffer)
        self.stopped.emit()

    @staticmethod
    def _guard(fn, *args) -> None:
        """执行一步并吞掉异常。

        这个线程在 --noconsole 打包版里崩掉是**完全静默**的（异常只打到不存在
        的控制台），用户只会看到"转写一直没反应"。所以任何单步失败都必须
        记日志后继续，绝不能让整条线程死掉。
        """
        try:
            fn(*args)
        except Exception:
            log.exception("ASR 线程单步失败（已跳过，线程继续）")

    def _flush_buffer(self) -> None:
        """把当前缓冲（可能不足一段）立刻转写并发出去。"""
        if len(self._buf) > self._engine.sample_rate * 0.3:
            self._emit()
            self._seg_start += len(self._buf) / self._engine.sample_rate
        self._buf = np.zeros(0, dtype=np.float32)

    def flush(self) -> None:
        """外部调用（录音停止时）：让工作线程把残留缓冲马上转写出来。"""
        self.chunks.put(FLUSH)

    def _feed(self, block: np.ndarray) -> None:
        """把一块麦克风音频并入缓冲；够长就转写一段。"""
        # 麦克风块是 (frames, channels) 二维，取第一通道转一维，
        # 否则与累积缓冲（一维）拼接会抛维度错误并杀死线程
        mono = block[:, 0] if block.ndim > 1 else block
        self._buf = np.concatenate(
            [self._buf, mono.astype(np.float32) / 32768.0])
        if len(self._buf) >= self._engine.chunk_len:
            self._emit()
            self._seg_start += len(self._buf) / self._engine.sample_rate
            self._buf = np.zeros(0, dtype=np.float32)

    def _emit(self) -> None:
        # 单段识别失败不能杀死整个工作线程（记日志后跳过本段）
        try:
            chunk = self._buf
            sr = self._engine.sample_rate
            peak = float(np.abs(chunk).max()) if len(chunk) else 0.0
            # 近乎纯静音（约 -54 dBFS 以下）直接跳过：这是绝对判据，不会误杀语音
            if peak < SILENCE_PEAK:
                log.debug("本段近乎静音（峰值 %.5f），跳过识别", peak)
                return
            # 本段到底有没有人声：没有就**不送模型**。
            # 这是解决"没人说话却识别出文字"的关键 —— 模型对着底噪会硬凑出
            # 「吃葡萄不吐葡萄皮」「证证证证…」这类幻觉文字。
            has_speech, noise_db, ratio = speech_present(chunk, sr, self._min_ratio)
            if not has_speech:
                self._empty += 1
                if self._empty <= 3 or self._empty % 20 == 0:
                    log.info("本段没人声（噪声底 %.0f dB，有声帧 %.1f%% < %.0f%%），跳过识别"
                             "（已跳过 %d 段）", noise_db, ratio * 100,
                             self._min_ratio * 100, self._empty)
                # 连续多段没人声 → 提示用户检查麦克风（可能是选错设备/静音）
                if self._empty in (3, 10) or self._empty % 50 == 0:
                    self.noVoice.emit(self._empty)
                return
            # 低电平录音（麦克风增益低/离得远）归一化到 0.9 峰值，提升识别率
            if peak > 0.05:
                chunk = chunk * (0.9 / peak)
            text = self._engine.recognize(chunk)
        except Exception:
            log.exception("本段识别失败（已跳过）")
            return

        if text and not is_meaningless(text) and not looks_like_hallucination(text):
            self._empty = 0
            start = self._seg_start
            end = start + len(self._buf) / self._engine.sample_rate
            self.segment.emit(text, start, end)
            return

        # 识别为空、只有语气词、或明显的重复字幻觉：不发给界面
        self._empty += 1
        log.info("丢弃本段结果（峰值 %.3f，噪声底 %.0f dB，有声帧 %.1f%%，结果 %r），已连续 %d 段",
                 peak, noise_db, ratio * 100, text[:24], self._empty)
        if self._empty in (3, 10) or self._empty % 50 == 0:
            self.noVoice.emit(self._empty)

    def shutdown(self) -> None:
        self._stop.set()
        self.chunks.put(None)


class FileTranscribeWorker(QThread):
    """转写**已有音频文件**（不是实时录音）。

    用途：用手机等更好的麦克风录好音，传进电脑后导入录音库，再点「转写」。
    走与实时链路完全相同的判定：静音段跳过、语气词/重复字幻觉丢弃，
    所以不会出现"没人说话却出文字"。
    """

    segment = Signal(str, float, float)     # (text, start_sec, end_sec)
    progress = Signal(int, int)             # (已完成段数, 总段数)
    done = Signal(bool, str)                # (ok, message)

    def __init__(self, cfg: dict, path, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.path = str(path)
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:  # noqa: D102
        try:
            import wave

            with wave.open(self.path, "rb") as w:
                sr = w.getframerate()
                channels = w.getnchannels()
                width = w.getsampwidth()
                raw = w.readframes(w.getnframes())
        except Exception as e:  # noqa: BLE001
            self.done.emit(False, f"读不出音频：{e}")
            return
        try:
            dtype = {1: np.uint8, 2: np.int16, 4: np.int32}.get(width, np.int16)
            data = np.frombuffer(raw, dtype=dtype).astype(np.float32)
            if dtype is np.int16:
                data /= 32768.0
            elif dtype is np.int32:
                data /= 2147483648.0
            elif dtype is np.uint8:
                data = (data - 128.0) / 128.0
            if channels > 1:
                data = data.reshape(-1, channels).mean(axis=1)
            if sr != 16000:                      # 简单线性重采样到 16k
                idx = (np.arange(int(len(data) * 16000 / sr)) * sr / 16000.0).astype(int)
                data = data[np.clip(idx, 0, len(data) - 1)]

            engine = ASREngine(self.cfg)
            engine.init()
            chunk = int(16000 * float(self.cfg["asr"].get("chunk_seconds", 8.0)))
            min_ratio = float(self.cfg["asr"].get("speech_min_ratio", SPEECH_MIN_RATIO))
            starts = list(range(0, len(data), chunk))
            emitted = skipped = 0
            for n, i in enumerate(starts, 1):
                if self._stop.is_set():
                    self.done.emit(False, "已取消")
                    return
                seg = data[i:i + chunk]
                if len(seg) < 16000 * 0.4:
                    continue
                sec = i / 16000.0
                peak = float(np.abs(seg).max())
                if peak < SILENCE_PEAK:
                    skipped += 1
                else:
                    ok, _floor, _ratio = speech_present(seg, 16000, min_ratio)
                    if not ok:
                        skipped += 1
                    else:
                        text = engine.recognize(seg * (0.9 / peak) if peak > 0.05 else seg)
                        if text and not is_meaningless(text) and not looks_like_hallucination(text):
                            self.segment.emit(text, sec, sec + len(seg) / 16000.0)
                            emitted += 1
                        else:
                            skipped += 1
                self.progress.emit(n, len(starts))
            self.done.emit(True, f"转写完成：{emitted} 段有内容，{skipped} 段是静音/无效已跳过")
        except Exception as e:  # noqa: BLE001
            log.exception("文件转写失败")
            self.done.emit(False, f"转写失败：{e}")
