#!/usr/bin/env python3
"""打包前资源检查：确认本地文件齐全（不下载任何内容）。

用法:
  python scripts/check_resources.py [--allow-missing]

缺什么打印什么并退出码 1（--allow-missing 时仅警告）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
STORAGE = ROOT / "storage"

# 需要自动创建的目录骨架（每次运行都会确保存在）
STORAGE_SKELETON = [
    STORAGE / "models",
    STORAGE / "bin" / "llama-server",
    STORAGE / "asr" / "paraformer",
    STORAGE / "asr" / "sense-voice",
    STORAGE / "asr" / "punct",
    STORAGE / "ocr",
]

STORAGE_README = """\
# storage/ —— 模型资源目录（不进版本库）

把下列文件放进对应目录，然后运行打包脚本：
（目录已由 scripts/check_resources.py 自动创建，直接放入即可）

| 目录 | 内容 |
|---|---|
| models/ | LLM 模型 GGUF，文件名必须与 config.yaml 的 model.filename 完全一致 |
| bin/llama-server/ | llama.cpp win-cpu-x64 包解压内容（llama-server.exe + ggml*.dll） |
| asr/paraformer/ | （默认引擎）Paraformer zh 模型（model.int8.onnx + tokens.txt，中文最准） |
| asr/sense-voice/ | （备选）SenseVoice 模型（model.int8.onnx + tokens.txt，中英日韩粤） |
| asr/punct/ | 标点恢复模型（model.onnx + tokens.json） |
| ocr/official_models/ | PaddleOCR 模型目录（PP-OCRv6_medium_det(_onnx) / PP-OCRv6_medium_rec(_onnx)） |

模型也可以放别的盘：设置环境变量 LOCAL_RECORD_DIR 指向含 storage/ 的目录。
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--allow-missing", action="store_true",
                    help="缺失时仅警告，不退出")
    args = ap.parse_args()

    # 先自动建目录骨架（幂等），避免手动 mkdir
    for d in STORAGE_SKELETON:
        d.mkdir(parents=True, exist_ok=True)
    readme = STORAGE / "README.md"
    if not readme.exists():
        readme.write_text(STORAGE_README, encoding="utf-8")
    print(f"[init] storage/ 目录骨架已就绪（见 {readme.relative_to(ROOT)}）")

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    # (名称, 路径, 修复提示, 是否要求"非空目录")
    checks: list[tuple[str, Path, str, bool]] = []

    # LLM 模型（config.model.filename 必须与 storage/models/ 一致）
    model_name = cfg["model"]["filename"]
    checks.append((
        "LLM 模型 (GGUF)",
        STORAGE / "models" / model_name,
        f"把 GGUF 放入 storage/models/{model_name}（文件名须与 config.yaml 的 model.filename 完全一致）",
        False,
    ))

    # llama-server
    server_dir = STORAGE / "bin" / "llama-server"
    checks.append((
        "llama-server 可执行文件",
        server_dir / "llama-server.exe",
        f"解压 llama.cpp {cfg['llama_server'].get('release_tag', 'b9000')} 的 "
        "win-x64 包（llama-server.exe + ggml*.dll）到 storage/bin/llama-server/",
        False,
    ))

    # ASR 模型：当前 backend 的模型是必需项；另一个引擎属可选（缺了只提示）
    backend = str(cfg["asr"].get("backend", "paraformer")).lower()
    engines = [("paraformer", "asr/paraformer", "Paraformer"),
               ("sense_voice", "asr/sense-voice", "SenseVoice")]
    for key, rel, label in engines:
        section = cfg["asr"].get(key) or {}
        d = STORAGE / rel
        is_active = key == backend
        suffix = "" if is_active else "（备选引擎，可缺）"
        for what, fname in (("模型 (onnx)", section.get("model_filename", "model.int8.onnx")),
                            ("tokens", section.get("tokens_filename", "tokens.txt"))):
            checks.append((
                f"{label} {what}{suffix}",
                d / fname,
                f"把 {fname} 放入 {d.relative_to(ROOT)}/",
                False,              # 检查的是文件存在，不是目录非空
                not is_active,      # 备选引擎缺失不算失败
            ))
    # 标点模型（可选：缺了转写只是没标点）
    pc = cfg["asr"].get("punctuation") or {}
    pd = STORAGE / "asr" / "punct"
    for what, fname in (("模型 (onnx)", pc.get("model_filename", "model.onnx")),
                        ("tokens", pc.get("tokens_filename", "tokens.json"))):
        checks.append((f"标点 {what}（可缺）", pd / fname,
                       f"把 {fname} 放入 {pd.relative_to(ROOT)}/", False, True))

    # OCR 模型目录（PP-OCRv6 模型，要求非空）
    checks.append((
        "OCR 模型目录",
        STORAGE / "ocr",
        "把 PP-OCRv6_medium_det(_onnx) / PP-OCRv6_medium_rec(_onnx) 等模型目录"
        "放入 storage/ocr/official_models/（文件名须与 config.yaml 的 ocr.det_model/rec_model 一致）",
        True,
    ))

    missing: list[tuple[str, Path, str]] = []
    optional_missing: list[str] = []
    for item in checks:
        name, p, hint, require_nonempty = item[0], item[1], item[2], item[3]
        optional = bool(item[4]) if len(item) > 4 else False
        ok = (p.is_dir() and any(p.iterdir())) if require_nonempty else p.is_file()
        if ok:
            continue
        (optional_missing if optional else missing).append(
            name if optional else (name, p, hint))

    if optional_missing:
        for name in optional_missing:
            print(f"[提示] 可选资源缺失（不影响运行）: {name}")

    if not missing:
        print("[OK] 资源齐全")
        return 0

    print(f"[{'WARN' if args.allow_missing else 'FAIL'}] 缺失 {len(missing)} 项资源：")
    for name, p, hint in missing:
        print(f"  - {name}: {p.relative_to(ROOT)}")
        print(f"    修复: {hint}")
    return 0 if args.allow_missing else 1


if __name__ == "__main__":
    sys.exit(main())
