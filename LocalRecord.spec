# -*- mode: python ; coding: utf-8 -*-
# Local Record (Windows x64) PyInstaller 配置 —— 精简版
# 用法: python -m PyInstaller --noconfirm --clean LocalRecord.spec
#
# 关键点：
# - onedir（不用 onefile）：总产物体积大，onefile 启动要解压且易被杀软拦截；
# - console=False（--noconsole）：无控制台窗口；
# - 模型等大资源不进包，由 package_windows.sh 在构建后复制到 exe 同级 storage/。
#
# 瘦身原则（每一条都由打包后的 `Local Record.exe --verify --deep` 真跑功能验证）：
#   1. 不再 collect_all("PySide6")：本项目只用 QtCore/QtGui/QtWidgets/QtSvg，
#      PyInstaller 自带的 PySide6 hook 会按实际 import 收集 DLL 与插件；
#      collect_all 会把 Qt3D/QtWebEngine/QtQuick/QtMultimedia… 全塞进来（实测 634MB）。
#   2. 不再 collect_all("numpy") / ("onnxruntime")：改用它们自带/contrib 的 hook，
#      避免把 numpy 测试套件、onnxruntime.tools/transformers 打进包；
#      onnxruntime 是被 paddlex 动态 import 的，这里显式写进 hiddenimports。
#   3. excludes 再兜一层：没用到的 Qt 子模块 + tkinter（pandas 的可选依赖）。
#   4. sounddevice 的 PortAudio DLL 由 hook-sounddevice 收集，这里再显式钉一遍，
#      保证麦克风采集与录音回放（都走 PortAudio）在任何 PyInstaller 版本下都不丢。
from pathlib import Path
import importlib.util

from PyInstaller.utils.hooks import collect_all, copy_metadata, get_module_file_attribute

# ---- collect-all 清单（包未安装时自动跳过）----
# 说明：paddleocr/paddlex 会动态加载 pipeline 与配置，sherpa_onnx/cv2 带原生库，
# 这四个必须 collect_all；其余交给标准 hook，避免把体积吹起来。
COLLECT_ALL = [
    "paddleocr",
    "paddlex",
    "sherpa_onnx",
    "cv2",
]
if importlib.util.find_spec("paddle"):
    # OCR 走 paddle 后端时需要；纯 ONNX 后端可省略（会减小体积）
    COLLECT_ALL.append("paddle")

# 动态 import 的模块：paddlex 在运行时才决定用哪个推理后端
HIDDEN = [
    "onnxruntime",
    "onnxruntime.capi._pybind_state",
    "onnxruntime.capi.onnxruntime_pybind11_state",
    "onnxruntime.capi.onnxruntime_inference_collection",
    "onnxruntime.capi.onnxruntime_validation",
]

# 明确排除：本项目完全不用的 Qt 家族与 tkinter（避免被其它库连带引入）
EXCLUDES = [
    "tkinter", "_tkinter",
    "PySide6.Qt3DAnimation", "PySide6.Qt3DCore", "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DRender",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets", "PySide6.QtWebView",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2", "PySide6.QtQuickWidgets", "PySide6.QtQuickTest",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtSpatialAudio",
    "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtGraphs", "PySide6.QtGraphsWidgets",
    "PySide6.QtDesigner", "PySide6.QtUiTools", "PySide6.QtHelp",
    "PySide6.QtTest", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtSql", "PySide6.QtNetworkAuth", "PySide6.QtNfc",
    "PySide6.QtBluetooth", "PySide6.QtSerialPort", "PySide6.QtSerialBus",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSensors",
    "PySide6.QtStateMachine", "PySide6.QtTextToSpeech", "PySide6.QtWebSockets",
    "PySide6.QtWebChannel", "PySide6.QtHttpServer", "PySide6.QtLocation",
    "PySide6.QtPositioning", "PySide6.QtDBus", "PySide6.QtAxContainer",
    "PySide6.QtCanvasPainter", "PySide6.scripts",
    "onnxruntime.tools", "onnxruntime.transformers",
]

METADATA = [
    "paddleocr", "paddlex", "paddle", "onnxruntime",
    "sherpa_onnx", "sounddevice", "cv2", "PySide6",
]

# extras 的元数据必须单独收：copy_metadata(recursive=True) 只递归 METADATA 里
# **不带 extra 标记**的依赖，而 PaddleX 用 ``is_extra_available("ocr-core")`` +
# ``importlib.metadata.version(dep)`` 判断 extras 是否可用 —— 冻结包里缺了这些
# dist-info，OCR pipeline 会以 "requires additional dependencies" 失败，而
# 纯 import 自检完全看不出来（所以才有 --verify --deep）。
EXTRA_METADATA = [
    # paddlex[ocr-core]（PP-OCR det/rec 必需）
    "imagesize", "opencv-contrib-python", "pyclipper", "pypdfium2",
    "python-bidi", "shapely",
    # 基础依赖里也常被 require_deps() 询问的
    "numpy", "pillow", "pandas", "packaging", "typing-extensions",
]

datas, binaries, hiddenimports = [], [], []

for pkg in COLLECT_ALL:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:  # noqa: BLE001
        print(f"[spec] 跳过 collect_all({pkg}): {e}")

hiddenimports += HIDDEN

# ---- PortAudio：显式兜底（hook-sounddevice 已在，这里不依赖它的行为）----
try:
    sd_dir = Path(get_module_file_attribute("sounddevice")).parent \
        / "_sounddevice_data" / "portaudio-binaries"
    if sd_dir.is_dir():
        dest = "_sounddevice_data/portaudio-binaries"
        for lib in list(sd_dir.glob("libportaudio*.dll")) + list(sd_dir.glob("libportaudio*.dylib")):
            binaries.append((str(lib), dest))
        print(f"[spec] 显式收集 PortAudio: {[p.name for p in sd_dir.glob('libportaudio*.*')]}")
    else:
        print(f"[spec] 警告：未找到 PortAudio 目录 {sd_dir}")
except Exception as e:  # noqa: BLE001
    print(f"[spec] 收集 PortAudio 失败: {e}")

# ---- 元数据：去重后统一收集 ----
# copy_metadata 对未安装的包会抛异常（例如没装 paddlepaddle），逐个 try 即可跳过
_meta_seen: set = set()
for pkg in METADATA + EXTRA_METADATA:
    try:
        entries = copy_metadata(pkg, recursive=pkg in ("paddleocr", "paddlex"))
        for item in entries:
            if item not in _meta_seen:
                _meta_seen.add(item)
                datas.append(item)
    except Exception as e:  # noqa: BLE001
        print(f"[spec] 跳过 copy_metadata({pkg}): {e}")

print(f"[spec] 共收集 {len(_meta_seen)} 份包元数据（PaddleX 依赖检查需要）")

a = Analysis(
    ["app/main.py"],
    pathex=[str(Path(SPECPATH))],  # 项目根目录：让 `import app.*` 可解析
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Local Record",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,  # 崩溃时弹错误框，便于用户反馈
    icon="installer/LocalRecord.ico",  # scripts/make_icon.py 生成
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Local Record",
    contents_directory="_internal",
)
