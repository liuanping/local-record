"""冻结环境自检（`LocalRecord.exe --verify [--deep]`）。

两级检查：

* ``--verify``      ：逐项导入关键模块（比 sys.path 模拟法可靠：PyInstaller 6
  把纯 Python 模块内嵌在 exe 里，模拟法看不到），并枚举音频设备；
* ``--verify --deep``：在真实冻结环境里**跑一遍功能**——存储解析、llama-server
  可执行、Qt 界面/图标渲染、PortAudio 输入+输出、SenseVoice 加载与识别、
  PaddleOCR 真图识别、wav 回读。用于每次打包后确认"包瘦身/升级"没有把功能删掉。

结果写入 %APPDATA%/LocalRecord/logs/verify.log（``FAIL`` 会让打包脚本中止，
``WARN`` 只提示，例如构建机没插麦克风不应该算打包失败）。
"""
from __future__ import annotations

import os
import time
from pathlib import Path

# 关键模块：ssl(坑2) / httpx(连带) / cv2(坑1) / sounddevice(坑3) / ASR / OCR / UI
MODULES = [
    "ssl", "httpx", "numpy", "cv2", "sounddevice",
    "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets", "PySide6.QtSvg",
    "sherpa_onnx", "paddleocr",
]


def run_verify(log_path: Path, deep: bool = False) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    ok_all = True

    # 必须在导入 paddleocr/paddlex 之前把 OCR 模型缓存指向 storage/ocr，
    # 否则 paddlex 会用 ~/.paddlex 并尝试联网下载（自检绝不能联网）
    try:
        from app.ocr import OFFLINE_CACHE
        lines.append(f"INFO OCR 模型缓存: {OFFLINE_CACHE or '未找到 storage/ocr（可能联网）'}")
    except Exception as e:  # noqa: BLE001
        lines.append(f"WARN 预配置 OCR 缓存失败: {type(e).__name__}: {e}")

    # ---------------- 一级：模块导入 ----------------
    for name in MODULES:
        t0 = time.time()
        try:
            mod = __import__(name)
            loc = getattr(mod, "__file__", "") or "?"
            lines.append(f"PASS {name} ({time.time() - t0:.1f}s) {loc}")
        except Exception as e:
            ok_all = False
            lines.append(f"FAIL {name}: {type(e).__name__}: {e}")

    # sounddevice 导入成功即证明 PortAudio DLL 可加载（坑 4d）
    try:
        import sounddevice as sd
        devs = sd.query_devices()
        input_devs = [d for d in devs if d["max_input_channels"] > 0]
        output_devs = [d for d in devs if d["max_output_channels"] > 0]
        lines.append(f"INFO 音频设备：输入 {len(input_devs)} 个 / 输出 {len(output_devs)} 个")
    except Exception as e:
        ok_all = False
        lines.append(f"FAIL portaudio/query_devices: {e}")

    # ---------------- 二级：功能自检 ----------------
    if deep:
        deep_lines, deep_ok = _deep_checks()
        lines += deep_lines
        ok_all = ok_all and deep_ok

    try:
        log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass
    return 0 if ok_all else 1


# --------------------------------------------------------------- 深度自检 ----

def _deep_checks() -> tuple[list[str], bool]:
    """在冻结环境里真跑一遍关键功能；每项独立 try，绝不让自检自身崩掉。"""
    import tempfile

    out: list[str] = []
    ok = True
    tmp = Path(tempfile.mkdtemp(prefix="lr-verify-"))

    def record(name: str, fn) -> None:
        nonlocal ok
        t0 = time.time()
        try:
            detail = fn()
            out.append(f"PASS {name} ({time.time() - t0:.1f}s)"
                       + (f" {detail}" if detail else ""))
        except Exception as e:  # noqa: BLE001
            ok = False
            # 带上出错位置（文件:行），否则日志里只有一个异常类型，不好排查
            loc = ""
            try:
                import traceback
                for line in reversed(traceback.format_exc().strip().splitlines()):
                    if line.strip().startswith("File "):
                        loc = " @" + line.strip().split(", in ")[0].replace("File ", "")
                        break
            except Exception:
                pass
            out.append(f"FAIL {name}: {type(e).__name__}: {e}{loc}")

    def warn(name: str, fn) -> None:
        """设备相关检查：失败只 WARN（可能只是这台机器没麦克风/没插耳机）。"""
        t0 = time.time()
        try:
            detail = fn()
            out.append(f"PASS {name} ({time.time() - t0:.1f}s)"
                       + (f" {detail}" if detail else ""))
        except Exception as e:  # noqa: BLE001
            out.append(f"WARN {name}: {type(e).__name__}: {e}")

    # ---- 0) 配置与存储解析（冻结版应指向 exe 同级 storage/）----
    cfg: dict = {}

    def check_storage() -> str:
        from app import config as config_mod
        from app.paths import app_root, storage_dir
        cfg.update(config_mod.load_config())
        return f"root={app_root()} storage={storage_dir()}"

    record("存储/配置解析", check_storage)

    # ---- 1) llama-server 可执行 ----
    def check_llama() -> str:
        import subprocess
        from app.paths import storage_dir
        exe = storage_dir() / "bin" / "llama-server" / "llama-server.exe"
        if not exe.is_file():
            raise FileNotFoundError(f"缺少 {exe}")
        r = subprocess.run([str(exe), "--version"], capture_output=True,
                           timeout=30, text=True, errors="replace")
        lines_out = (r.stdout or r.stderr or "").strip().splitlines()
        first = lines_out[0][:60] if lines_out else "(空)"
        return f"{exe.name} 可执行，输出首行: {first}"

    record("llama-server 可执行", check_llama)

    # ---- 2) Qt 界面（offscreen）+ 图标 SVG 渲染 + 新 UI 模块 + 渲染链路 ----
    def check_ui() -> str:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        from app.icons import lucide_icon
        from app.main_window import MainWindow
        from app.player import AudioPlayer
        from app.theme import build_qss, theme
        theme.apply(app, "dark")
        assert "QFrame#rootCard" in build_qss("dark"), "深色样式表生成异常"
        theme.apply(app, "light")
        theme.apply(app, "dark")

        win = MainWindow(AudioPlayer(), tmp / "recordings", version="verify")
        assert win.stack.count() == 3, "主窗口页数异常"
        assert win.library_page.files() == [], "空目录不应有录音"

        icon = lucide_icon("mic", "#ffffff", 64)          # 走 QSvgRenderer
        assert not icon.pixmap(32, 32).isNull(), "SVG 图标渲染失败"

        # 录音态 UI + 电平条 + 计时器
        win.resize(478, 812)
        win.set_recording(True)
        win.update_recording(12.3, 0.6)
        win.set_recording(False)

        # 转写 / 问答 / OCR 三路渲染
        win.add_transcript("测试段落一二三", 1.0, 2.0)
        win.append_chat("AI", "这是回答")
        win.highlight_transcript([1])
        win.append_ocr("识别出来的文字")
        win.append_ocr_chat("AI", "OCR 回答")
        win.toast("自检浮层", "ok")
        voice_html = win.note_view.toHtml()
        ocr_html = win.ocr_view.toHtml()
        assert "测试段落一二三" in voice_html, "转写区没有渲染出段落"
        assert "这是回答" in voice_html, "问答区没有渲染出回答"
        assert "识别出来的文字" in ocr_html, "OCR 区没有渲染出文本"
        assert win.transcript_items and win.transcript_items[0]["text"] == "测试段落一二三"
        assert win.ocr_text == "识别出来的文字"

        # 真的去点三个分段按钮，断言页面确实切过去了
        # （只调 _on_seg 会漏掉"QButtonGroup 没给 id → 传负数 →
        #   setCurrentIndex 静默失效"这类 bug，正是用户点标签页没反应的原因）
        for idx, name in ((0, "语音"), (1, "录音库"), (2, "文字识别")):
            win.seg_buttons[idx].click()
            app.processEvents()
            assert win.stack.currentIndex() == idx, (
                f"点击「{name}」没有切到第 {idx} 页（当前 {win.stack.currentIndex()}）")
        win.seg_buttons[0].click()
        app.processEvents()
        assert win.stack.currentIndex() == 0, "切回语音页失败"
        app.processEvents()
        return (f"{win.stack.count()} 页 / 三个标签页点击均能切换 / "
                f"转写 {len(win.transcript_items)} 段 / OCR {len(win.ocr_text)} 字 / "
                f"深+浅色主题均可切换")

    record("Qt 界面·图标·渲染链路（含新 UI 模块）", check_ui)

    # ---- 3) PortAudio：麦克风输入 + 扬声器输出 ----
    def check_input() -> str:
        import sounddevice as sd
        with sd.InputStream(samplerate=16000, channels=1, dtype="int16",
                            blocksize=1600) as st:
            data, overflowed = st.read(1600)
        import numpy as np
        peak = int(np.abs(data).max())
        return f"读到 {len(data)} 帧，峰值 {peak}，overflow={overflowed}"

    def check_output() -> str:
        import sounddevice as sd
        import numpy as np
        buf = np.zeros((1600, 1), dtype="float32")
        with sd.OutputStream(samplerate=16000, channels=1, dtype="float32",
                             blocksize=1600) as st:
            st.write(buf)
        return "已向默认输出设备写入 100ms 静音"

    warn("麦克风采集（PortAudio 输入）", check_input)
    warn("扬声器输出（PortAudio 输出）", check_output)

    # ---- 4) ASR：加载引擎并**真的识别一段语音** ----
    def check_asr() -> str:
        """用打包进来的真实语音自检，而不是纯音调。

        旧实现喂 440Hz 正弦，识别结果为空也算通过 —— 那等于没验证
        "能不能把话转成文字"（用户反馈过"说了很多话没内容"，正是要防这个）。
        """
        import wave

        import numpy as np

        from app.asr import ASREngine
        from app.paths import storage_dir
        backend = str(cfg["asr"].get("backend", "paraformer"))
        engine = ASREngine(cfg)
        engine.init()

        sample = storage_dir() / "asr" / "selftest.wav"
        if not sample.is_file():
            # 退回旧行为（只验证模型能加载并跑通一次识别）
            sr = engine.sample_rate
            tone = (np.sin(2 * np.pi * 440 * np.arange(sr) / sr) * 0.3).astype(np.float32)
            engine.recognize(tone)
            return f"{backend} 模型已加载（未找到 selftest.wav，只做了空跑）"

        with wave.open(str(sample), "rb") as w:
            sr = w.getframerate()
            raw = w.readframes(w.getnframes())
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        text = engine.recognize(audio)
        expect = "今天的会议改到下午三点请大家准时参加"
        core = "".join(ch for ch in text if ch not in "，。、！？；： ")
        hit = sum(1 for ch in expect if ch in core)
        if hit < len(expect) * 0.6:
            raise RuntimeError(
                f"真实语音识别结果和参考文本差太多（命中 {hit}/{len(expect)} 字）：{text!r}")
        return f"{backend} 识别真实语音 {len(core)} 字，命中参考 {hit}/{len(expect)} 字：{text}"

    record("ASR 真实语音识别", check_asr)

    # ---- 4b) 幻觉防护：纯噪声不该产生文字 ----
    def check_asr_silence() -> str:
        """噪声 → 不送识别；重复字幻觉 → 丢弃。

        用户实测过"没人说话却识别出「吃葡萄不吐葡萄皮」「证证证证…」"，
        所以这一条固化进自检，防止以后改回去。
        """
        import numpy as np

        from app.asr import looks_like_hallucination, speech_present
        rng = np.random.default_rng(0)
        t = np.arange(int(16000 * 6)) / 16000.0
        noise = (0.6 * rng.normal(0, 1, len(t))
                 + 0.4 * np.sin(2 * np.pi * 120 * t)).astype(np.float32)
        noise *= 10 ** (-26.0 / 20.0) / (float(np.sqrt((noise ** 2).mean())) + 1e-9)
        has_speech, floor_db, ratio = speech_present(noise, 16000)
        if has_speech:
            raise RuntimeError(f"噪声被判成有人声（底 {floor_db:.0f}dB，"
                               f"有声帧 {ratio*100:.1f}%）→ 会再次出现幻觉文字")
        if not looks_like_hallucination("好的我的的的证证证证证证证证证证据"):
            raise RuntimeError("连续重复字的幻觉文本没有被过滤")
        return (f"噪声判为无人声（底 {floor_db:.0f}dB，有声帧 {ratio*100:.1f}%）；"
                "重复字幻觉会被丢弃")

    record("静音不产生文字（幻觉防护）", check_asr_silence)

    # ---- 4c) 落盘增益：麦克风电平低时回听不能太小声 ----
    def check_save_gain() -> str:
        """落盘归一化：只乘系数，把偏小的录音提到正常回听音量。"""
        import numpy as np

        from app.recorder import _normalize_peak
        t = np.linspace(0, 1, 16000, endpoint=False)
        # 0.1 振幅（-20dBFS）→ 需要 +19.6dB，在 +20dB 上限内，应被提到 0.95
        quiet = (0.1 * np.sin(2 * np.pi * 300 * t)).astype(np.float32).reshape(-1, 1)
        out, gain = _normalize_peak(quiet)
        peak = float(np.abs(out).max())
        if gain <= 0 or peak < 0.9:
            raise RuntimeError(f"偏小录音没有被提起来（增益 {gain:.1f}dB，峰值 {peak:.3f}）")
        # 极小声（约 -34dBFS，峰值 ≈0.02）：受 +20dB 上限保护，只提到 0.2，不该无限放大
        tiny = (0.02 * np.sin(2 * np.pi * 300 * t)).astype(np.float32).reshape(-1, 1)
        out_tiny, gain_tiny = _normalize_peak(tiny)
        if not (19.0 <= gain_tiny <= 20.1) or not (0.15 <= float(np.abs(out_tiny).max()) <= 0.25):
            raise RuntimeError(f"增益上限没生效（增益 {gain_tiny:.1f}dB，"
                               f"峰值 {float(np.abs(out_tiny).max()):.3f}）")
        # 近乎静音（峰值 0.002 < min_peak 0.005）：不折腾，避免把底噪放大成沙沙声
        silent = (0.002 * np.sin(2 * np.pi * 300 * t)).astype(np.float32).reshape(-1, 1)
        _, gain_silent = _normalize_peak(silent)
        if gain_silent != 0.0:
            raise RuntimeError(f"近乎静音的录音不该被放大（增益 {gain_silent:.1f}dB）")
        loud = (0.9 * np.sin(2 * np.pi * 300 * t)).astype(np.float32).reshape(-1, 1)
        _, gain_loud = _normalize_peak(loud)
        if gain_loud > 1.0:
            raise RuntimeError(f"本来就够响的录音不该大改（增益 {gain_loud:.1f}dB）")
        return (f"0.1 振幅 → +{gain:.1f}dB、峰值 {peak:.2f}；极小声受 +{gain_tiny:.0f}dB 上限保护；"
                f"静音不放大；已够响只 +{gain_loud:.1f}dB")

    record("录音落盘增益（回听音量）", check_save_gain)

    # ---- 5) OCR：生成一张带大字的图片，走完整识别链路（必须完全离线）----
    def check_ocr() -> str:
        from PIL import Image, ImageDraw, ImageFont
        from app.ocr import OFFLINE_CACHE, OCREngine
        # 离线前提：缓存已指向 storage/ocr，且模型目录确实在里面（否则会联网）
        if OFFLINE_CACHE is None:
            raise RuntimeError("storage/ocr 不存在，OCR 无法离线运行")
        local_models: list[str] = []
        for name in (f"{cfg['ocr'].get('det_model', '')}_onnx",
                     f"{cfg['ocr'].get('rec_model', '')}_onnx"):
            model_dir = Path(OFFLINE_CACHE) / "official_models" / name
            if not model_dir.is_dir() or not any(model_dir.iterdir()):
                raise RuntimeError(f"本地模型缺失或为空：{model_dir}")
            local_models.append(name)

        # 先自诊断：PaddleX 用 importlib.metadata.version(dep) 判断 extras 依赖是否可用，
        # 冻结包里丢了 dist-info 就会报含糊的"requires additional dependencies"。
        # 这里直接把缺失的依赖列出来，省得以后再猜。
        from paddlex.utils.deps import EXTRAS, is_dep_available
        missing = [dep for dep in EXTRAS.get("ocr-core", {})
                   if not is_dep_available(dep)]
        if missing:
            raise RuntimeError(
                f"PaddleX ocr-core 依赖在冻结环境缺失（缺 dist-info？）：{missing}")

        img = Image.new("RGB", (720, 220), "white")
        draw = ImageDraw.Draw(img)
        font = None
        for cand in ("C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf",
                     "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/msyh.ttc"):
            if Path(cand).is_file():
                try:
                    font = ImageFont.truetype(cand, 72)
                    break
                except OSError:
                    continue
        text_to_draw = "LOCAL RECORD 2026"
        draw.text((30, 70), text_to_draw, fill="black",
                  font=font or ImageFont.load_default())
        sample = tmp / "ocr-sample.png"
        img.save(sample)
        engine = OCREngine(cfg)
        text = engine.recognize_image(sample)
        flat = "".join(text.split()).upper()
        if not flat:
            raise RuntimeError("OCR 没有识别出任何文字（模型/后端可能缺失）")
        hit = "LOCAL" in flat or "RECORD" in flat or "2026" in flat
        if not hit:
            raise RuntimeError(f"OCR 结果不含预期关键词，可能识别异常：{flat[:80]}")
        return (f"离线模型 {','.join(local_models)}；识别到 {len(flat)} 字符：{flat[:60]}")

    record("OCR 真实图片识别（ONNX 后端）", check_ocr)

    # ---- 6) 录音回读：wave + numpy + 播放引擎的数据层 ----
    def check_clip() -> str:
        import wave
        import numpy as np
        from app.player import AudioClip
        sr = 16000
        data = (np.sin(2 * np.pi * 440 * np.arange(sr) / sr) * 12000).astype(np.int16)
        wav = tmp / "clip.wav"
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(data.tobytes())
        clip = AudioClip.load(wav)
        peaks = clip.peaks(120)
        assert abs(clip.duration - 1.0) < 0.05, f"时长异常 {clip.duration}"
        assert len(peaks) == 120
        return f"1.0s wav 回读正常，波形包络 {len(peaks)} 段"

    record("录音 wav 回读与波形包络", check_clip)

    # ---- 7) 点击链路：真去点按钮（教训：只调内部函数会漏掉接线类 bug）----
    def check_clicks() -> str:
        import wave
        import numpy as np
        from PySide6.QtWidgets import QApplication
        from app.library import RecordingRow
        from app.main_window import MainWindow
        from app.player import AudioPlayer

        app = QApplication.instance() or QApplication([])
        recs = tmp / "clicks"
        recs.mkdir(parents=True, exist_ok=True)
        sr = 16000
        tone = (np.sin(2 * np.pi * 440 * np.arange(sr // 2) / sr) * 12000).astype(np.int16)
        for name in ("rec-20260101-101010.wav", "rec-20260101-111111.wav",
                     "rec-20260101-121212.wav"):
            with wave.open(str(recs / name), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(sr)
                w.writeframes(tone.tobytes())

        player = AudioPlayer()
        win = MainWindow(player, recs, version="verify")
        app.processEvents()

        # 7a 三个分段标签页：点谁就该切到谁
        for idx, name in ((0, "语音"), (1, "录音库"), (2, "文字识别")):
            win.seg_buttons[idx].click()
            app.processEvents()
            assert win.stack.currentIndex() == idx, (
                f"点「{name}」没切到第 {idx} 页（当前 {win.stack.currentIndex()}）")

        # 7b 录音库列表行的 ▶
        win.show_tab(1)
        app.processEvents()
        rows = win.library_page.findChildren(RecordingRow)
        assert rows, "录音库没有生成列表行"
        rows[0].play_btn.click()
        app.processEvents()
        assert player.path == rows[0].path, "点列表行 ▶ 没有载入对应录音"
        player.stop()
        app.processEvents()

        # 7c 播放器卡片：播放 → 暂停
        bar = win.library_page.player_bar
        bar.show_clip(rows[1].path)
        app.processEvents()
        bar.play_btn.click()
        app.processEvents()
        assert player.is_playing, "点播放器 ▶ 没有开始播放"
        bar.play_btn.click()
        app.processEvents()
        assert player.is_paused, "再点一次没有暂停"
        player.stop()
        app.processEvents()

        # 7d 语音页"最近一次录音"的 ▶
        mini = win.mini_player
        mini.show_clip(rows[0].path)
        app.processEvents()
        assert mini.play_btn.isEnabled(), "最近录音的 ▶ 处于置灰状态（点不动）"
        mini.play_btn.click()
        app.processEvents()
        assert player.path == rows[0].path and player.is_playing, "点最近录音 ▶ 无效"
        player.stop()
        app.processEvents()

        # 7e 录音大按钮发出信号
        fired: list[int] = []
        win.toggle_record_clicked.connect(lambda: fired.append(1))
        win.record_btn.click()
        app.processEvents()
        assert fired, "点录音大按钮没有发出 toggle_record_clicked"

        # 7f 删除录音：正常删除 / 文件已被外部删掉（旧列表）/ 删掉最近一次录音
        from PySide6.QtWidgets import QMessageBox
        warns: list[str] = []
        orig_exec, orig_warn = QMessageBox.exec, QMessageBox.warning
        QMessageBox.exec = lambda self: QMessageBox.StandardButton.Yes  # type: ignore
        QMessageBox.warning = staticmethod(  # type: ignore
            lambda _p, title, text, *a, **k: warns.append(f"{title}: {text}"))

        def _row_for(target: Path):
            """按路径找当前列表里的行（refresh 会重建行控件，
            不能缓存 findChildren 的旧结果——旧行要等 deleteLater 才销毁）。"""
            for r in win.library_page.findChildren(RecordingRow):
                if r.path == target:
                    return r
            return None

        def _click_delete(target: Path) -> None:
            row = _row_for(target)
            assert row is not None, f"列表里找不到 {target.name} 的行"
            row.del_btn.click()
            app.processEvents()

        try:
            files = win.library_page.files()
            assert len(files) >= 3, f"自检需要至少 3 条测试录音，实际 {len(files)}"

            # 正常删除
            victim = files[0]
            _click_delete(victim)
            assert not victim.exists(), "正常删除没有真的删掉文件"
            assert not warns, f"正常删除不该报错：{warns}"

            # 文件已被外部删除（列表还是旧的）→ 不该再弹"删除失败"
            stale = win.library_page.files()[0]
            stale.unlink()
            warns.clear()
            _click_delete(stale)
            assert not warns, f"文件已不存在时不该报错误框：{warns}"

            # 删掉"最近一次录音"→ 迷你条必须清引用、按钮置灰
            last = win.library_page.files()[0]
            win.note_recording_saved(last)
            app.processEvents()
            assert win.mini_player.current_path() == last, "迷你条没有指向刚保存的录音"
            _click_delete(last)
            assert win.mini_player.current_path() is None, "删除后迷你条仍指向已删文件"
            assert not win.mini_player.play_btn.isEnabled(), "删除后迷你条 ▶ 仍可点"
        finally:
            QMessageBox.exec, QMessageBox.warning = orig_exec, orig_warn

        return ("标签页 / 列表播放 / 播放器播放暂停 / 最近录音 / 录音按钮 / "
                "删除（正常·文件已丢失·删最近录音）点击链路均正常")

    record("点击链路（真点按钮）", check_clicks)

    return out, ok
