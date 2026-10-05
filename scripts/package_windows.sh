#!/usr/bin/env bash
# ============================================================
# Local Record（Windows x64）打包脚本 —— 在 Git Bash 里运行
#
# 用法:
#   ./scripts/package_windows.sh                 # 完整构建（默认）
#   ./scripts/package_windows.sh --skip-checks   # 资源缺失也继续（先出包，模型后补）
#   ./scripts/package_windows.sh --no-iss        # 不生成 Inno Setup 安装器
#
# 流程（对应 macOS 版 package_dmg.sh）:
#   1) 建/复用 .venv，装依赖 + pyinstaller
#   2) 资源检查（不下载任何东西；缺失则给出放置说明并中止，除非 --skip-checks）
#   3) 清理旧 build/dist
#   4) PyInstaller 打包（LocalRecord.spec：onedir + noconsole）
#   5) 打包后修复:
#      4a  MSVC 运行库（cv2.pyd 依赖）       → scripts/fix_runtime.py
#      4b  OpenSSL DLL（conda _ssl 依赖）    → scripts/fix_runtime.py
#      4c  冻结环境导入自检（cv2 失败自动写引导模块重试）→ scripts/verify_frozen.py
#      4d  PortAudio DLL 自检（麦克风）      → scripts/verify_frozen.py
#      4e  LLM 启动慢的超时/进度逻辑在 app 代码里
#          （app/warmup.py、app/llama_server.py），无需构建期处理
#   6) 复制 storage/ 与 config.yaml 到应用目录
#   7) 最终自检（verify_frozen.py 必须全 PASS）
#   8) 产物: dist/LocalRecord-windows-x64.zip +（可选）Inno Setup 安装器
# ============================================================
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

SKIP_CHECKS=0
NO_ISS=0
for a in "$@"; do
  case "$a" in
    --skip-checks) SKIP_CHECKS=1 ;;
    --no-iss) NO_ISS=1 ;;
    *) echo "未知参数: $a" >&2; exit 2 ;;
  esac
done

APP_NAME="Local Record"
DIST_DIR="dist/$APP_NAME"
VENV_PY=".venv/Scripts/python.exe"

say() { printf '\n==> %s\n' "$*"; }

# ---------- 1) 虚拟环境 ----------
say "[1/8] 虚拟环境与依赖"
if [ ! -x "$VENV_PY" ]; then
  PY="${PYTHON:-python}"
  "$PY" -m venv .venv
fi
"$VENV_PY" -m pip install --upgrade pip
"$VENV_PY" -m pip install -r requirements.txt pyinstaller

# ---------- 2) 资源检查（不下载） ----------
say "[2/8] 资源检查（自动建 storage/ 骨架；不下载，缺什么会列出放置说明）"
if [ "$SKIP_CHECKS" = 1 ]; then
  echo "（--skip-checks：跳过资源检查，缺模型也能出包，但运行时对应功能不可用）"
else
  "$VENV_PY" scripts/check_resources.py
fi

# ---------- 3) 清理 ----------
say "[3/8] 清理旧产物（build/ dist/）"
rm -rf build dist

# ---------- 3.5) 生成应用图标（exe / 安装器用，纯代码矢量） ----------
say "[3/8] 生成应用图标 installer/LocalRecord.ico"
"$VENV_PY" scripts/make_icon.py

# ---------- 4) PyInstaller ----------
say "[4/8] PyInstaller 打包（onedir, noconsole）"
"$VENV_PY" -m PyInstaller --noconfirm --clean LocalRecord.spec
if [ ! -f "$DIST_DIR/Local Record.exe" ]; then
  echo "[FAIL] 未生成 $DIST_DIR/Local Record.exe" >&2
  exit 1
fi

# ---------- 5) 打包后修复 ----------
say "[5/8] 4a/4b：运行时 DLL 修复（MSVC 运行库 + OpenSSL）"
"$VENV_PY" scripts/fix_runtime.py --app "$DIST_DIR"

say "[5/8] 4c/4d：冻结环境自检（真实 exe --verify；cv2 失败自动引导修复）"
APP_EXE="$DIST_DIR/Local Record.exe"
"$APP_EXE" --verify
VERIFY_LOG="$APPDATA/LocalRecord/logs/verify.log"
if [ ! -f "$VERIFY_LOG" ]; then
  # APPDATA 变量在 Git Bash 下可能为空，兜底用 python 定位
  VERIFY_LOG=$("$VENV_PY" -c "import os;print(os.path.join(os.environ.get('APPDATA',''),'LocalRecord','logs','verify.log'))")
fi
if grep -q "FAIL cv2" "$VERIFY_LOG" 2>/dev/null; then
  echo "[fix-cv2] cv2 导入失败，写入引导模块后重试"
  "$VENV_PY" scripts/verify_frozen.py --app "$DIST_DIR" --fix-cv2-only
  "$APP_EXE" --verify
fi
if grep -q "FAIL" "$VERIFY_LOG" 2>/dev/null; then
  echo "[FAIL] 冻结环境自检未通过："
  grep "FAIL" "$VERIFY_LOG"
  exit 1
fi
echo "[PASS] 冻结环境自检通过"

# ---------- 6) 复制资源 ----------
say "[6/8] 复制资源到应用目录（storage/ + config.yaml）"
rm -rf "$DIST_DIR/storage"
cp -r storage "$DIST_DIR/storage"
cp config.yaml "$DIST_DIR/config.yaml"

# ---------- 7) 最终自检 ----------
say "[7/8] 最终自检（真实 exe --verify --deep：跑功能而不是只导入）"
"$DIST_DIR/Local Record.exe" --verify --deep
if grep -q "FAIL" "$VERIFY_LOG" 2>/dev/null; then
  echo "[FAIL] 最终自检未通过：" >&2
  grep -E "FAIL|WARN" "$VERIFY_LOG" >&2
  exit 1
fi
echo "[PASS] 最终自检通过（verify.log: $VERIFY_LOG）"
grep -E "WARN" "$VERIFY_LOG" 2>/dev/null && echo "（以上 WARN 属环境相关，例如构建机没有麦克风）" || true

MODEL_NAME=$("$VENV_PY" -c "import yaml;print(yaml.safe_load(open('config.yaml',encoding='utf-8'))['model']['filename'])")
if [ -f "$DIST_DIR/storage/models/$MODEL_NAME" ]; then
  echo "[PASS] 模型: storage/models/$MODEL_NAME"
else
  echo "[warn] storage/models/$MODEL_NAME 缺失（--skip-checks 构建时属正常，运行时会提示）"
fi
if [ -f "$DIST_DIR/storage/bin/llama-server/llama-server.exe" ]; then
  echo "[PASS] llama-server: storage/bin/llama-server/llama-server.exe"
else
  echo "[warn] llama-server.exe 缺失"
fi
if [ -s "$DIST_DIR/storage/asr/paraformer/model.int8.onnx" ]; then
  echo "[PASS] ASR 模型(默认): storage/asr/paraformer/model.int8.onnx"
else
  echo "[warn] Paraformer 模型缺失（默认引擎）"
fi
if [ -s "$DIST_DIR/storage/asr/sense-voice/model.int8.onnx" ]; then
  echo "[PASS] ASR 备选模型也已打包: storage/asr/sense-voice/model.int8.onnx"
else
  echo "[i] 未打包 SenseVoice 备选引擎（按需精简，省 226MB）"
fi
if [ -s "$DIST_DIR/storage/asr/punct/model.onnx" ]; then
  echo "[PASS] 标点模型: storage/asr/punct/model.onnx"
else
  echo "[warn] 标点模型缺失（转写将不带标点）"
fi
if [ -d "$DIST_DIR/storage/ocr" ] && [ -n "$(ls -A "$DIST_DIR/storage/ocr" 2>/dev/null)" ]; then
  echo "[PASS] OCR 模型目录非空"
else
  echo "[warn] OCR 模型目录为空"
fi

# ---------- 8) 产物 ----------
say "[8/8] 生成 zip"
DIST_WIN=$(cygpath -w "$(pwd)/dist")
ZIP_WIN="$DIST_WIN\\LocalRecord-windows-x64.zip"
rm -f "$DIST_DIR/../LocalRecord-windows-x64.zip" 2>/dev/null || true
# 优先用 Windows 自带 bsdtar（快，且不占 C 盘临时空间；Compress-Archive 会把
# 临时文件放 %TEMP%，C 盘紧张时会报"磁盘空间不足"）
if [ -x "/c/Windows/System32/tar.exe" ]; then
  ( cd dist && /c/Windows/System32/tar.exe -a -c -f "LocalRecord-windows-x64.zip" "$APP_NAME" )
  echo "已生成: $ZIP_WIN"
elif command -v powershell >/dev/null 2>&1; then
  mkdir -p /e/tmpzip
  TMP="E:\\tmpzip" TEMP="E:\\tmpzip" powershell -NoProfile -Command \
    "Compress-Archive -Path '$DIST_WIN\\$APP_NAME' -DestinationPath '$ZIP_WIN' -Force"
  echo "已生成: $ZIP_WIN"
else
  echo "[warn] 未找到 zip 工具，跳过（可手动压缩 dist/$APP_NAME）"
fi

if [ "$NO_ISS" = 1 ]; then
  exit 0
fi

# 找 iscc：先 PATH，再常见安装位置（含 /CURRENTUSER 装到用户目录的情况）
ISCC_BIN="$(command -v iscc 2>/dev/null || true)"
if [ -z "$ISCC_BIN" ]; then
  for cand in \
    "${LOCALAPPDATA:-$HOME/AppData/Local}/Programs/InnoSetup6/ISCC.exe" \
    "${LOCALAPPDATA:-$HOME/AppData/Local}/Programs/Inno Setup 6/ISCC.exe" \
    "/c/Program Files (x86)/Inno Setup 6/ISCC.exe" \
    "/c/Program Files/Inno Setup 6/ISCC.exe" \
    "/d/Program Files (x86)/Inno Setup 6/ISCC.exe"; do
    if [ -x "$cand" ]; then ISCC_BIN="$cand"; break; fi
  done
fi

if [ -n "$ISCC_BIN" ]; then
  say "生成 Inno Setup 安装器（$ISCC_BIN）"
  # 简体中文语言包不在 Inno Setup 默认安装里，缺了会自动退回英文（见 .iss 的 ISPP 判断）
  if [ ! -f "$(dirname "$ISCC_BIN")/Languages/ChineseSimplified.isl" ]; then
    echo "[提示] 未找到 Languages/ChineseSimplified.isl，安装器界面将为英文。"
    echo "       需要中文界面可下载后放进 $(dirname "$ISCC_BIN")/Languages/："
    echo "       https://jrsoftware.org/files/istrans/ChineseSimplified.isl"
  fi
  "$ISCC_BIN" "/DAppSource=$(cygpath -w "$(pwd)/$DIST_DIR")" installer/LocalRecord.iss
else
  echo "（未找到 iscc，跳过安装器；装 Inno Setup 6 后重跑即可："
  echo "   https://jrsoftware.org/isdl.php ，或 winget install JRSoftware.InnoSetup ）"
  echo "   手动编译： iscc /DAppSource=\"$(cygpath -w "$(pwd)/$DIST_DIR")\" installer/LocalRecord.iss"
fi

say "完成。产物:"
echo "  dist/$APP_NAME/          # 绿色版（自包含，拷走即用）"
echo "  dist/LocalRecord-windows-x64.zip"
