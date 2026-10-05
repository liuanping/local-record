"""读取 GGUF 头部元数据（架构 / 上下文 / 对话模板），换模型前先自检。

用法::

    .venv\\Scripts\\python.exe scripts\\gguf_meta.py <模型.gguf> [更多.gguf ...]

为什么需要它：llama.cpp 只认识它编译进去的架构名。下载一个更新的模型后，
如果 ``general.architecture`` 不在支持列表里，``llama-server`` 会在加载时
直接报 ``unknown architecture``——先看一眼能省掉一次几 GB 的无用下载。
同时打印是否自带 Jinja 对话模板（决定要不要 ``--jinja``）。
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

# GGUF KV 值类型
_T_U8, _T_I8, _T_U16, _T_I16, _T_U32, _T_I32, _T_F32, _T_BOOL = range(8)
_T_STRING, _T_ARRAY, _T_U64, _T_I64, _T_F64 = 8, 9, 10, 11, 12
_SCALAR = {
    _T_U8: ("<B", 1), _T_I8: ("<b", 1), _T_U16: ("<H", 2), _T_I16: ("<h", 2),
    _T_U32: ("<I", 4), _T_I32: ("<i", 4), _T_F32: ("<f", 4), _T_BOOL: ("<?", 1),
    _T_U64: ("<Q", 8), _T_I64: ("<q", 8), _T_F64: ("<d", 8),
}
WANT = (
    "general.architecture", "general.name", "general.size_label",
    "general.file_type", "general.quantization_version",
    "tokenizer.ggml.model", "tokenizer.chat_template",
)


def read_gguf_meta(path: Path) -> dict:
    """解析 GGUF 头部；只保留 WANT 里的键，其余（含巨大的 token 词表）跳过。"""
    meta: dict = {}
    with open(path, "rb") as f:
        magic = f.read(4)
        if magic != b"GGUF":
            raise ValueError(f"{path.name} 不是 GGUF 文件（magic={magic!r}）")
        version = struct.unpack("<I", f.read(4))[0]
        _tensors = struct.unpack("<Q", f.read(8))[0]
        n_kv = struct.unpack("<Q", f.read(8))[0]
        meta["_gguf_version"] = version

        def read_string() -> str:
            (n,) = struct.unpack("<Q", f.read(8))
            raw = f.read(n)
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                return raw.decode("utf-8", "replace")

        for _ in range(n_kv):
            key = read_string()
            (vtype,) = struct.unpack("<I", f.read(4))
            keep = key in WANT or key.endswith(".context_length") \
                or key.endswith(".block_count") or key.endswith(".embedding_length") \
                or key.endswith(".attention.head_count_kv")
            if vtype == _T_STRING:
                val = read_string()
                if keep:
                    meta[key] = (val[:400] + "…") if len(val) > 400 else val
            elif vtype == _T_ARRAY:
                (etype,) = struct.unpack("<I", f.read(4))
                (count,) = struct.unpack("<Q", f.read(8))
                if etype == _T_STRING:
                    for _i in range(count):
                        n = struct.unpack("<Q", f.read(8))[0]
                        f.seek(n, 1)          # 跳过（token 词表可能有十几万条）
                    if keep:
                        meta[key] = f"<{count} 个字符串>"
                else:
                    fmt, size = _SCALAR[etype]
                    if keep and count <= 16:
                        meta[key] = [struct.unpack(fmt, f.read(size))[0]
                                     for _i in range(count)]
                    else:
                        f.seek(size * count, 1)
                        if keep:
                            meta[key] = f"<{count} 个数值>"
            else:
                fmt, size = _SCALAR[vtype]
                val = struct.unpack(fmt, f.read(size))[0]
                if keep:
                    meta[key] = val
    return meta


def describe(path: Path) -> dict:
    m = read_gguf_meta(path)
    arch = m.get("general.architecture", "?")
    return {
        "file": path.name,
        "size_gb": path.stat().st_size / 1024 ** 3,
        "architecture": arch,
        "name": m.get("general.name", ""),
        "ctx_length": m.get(f"{arch}.context_length", m.get("llama.context_length")),
        "block_count": m.get(f"{arch}.block_count"),
        "kv_heads": m.get(f"{arch}.attention.head_count_kv"),
        "quant": m.get("general.file_type"),
        "has_chat_template": "tokenizer.chat_template" in m,
        "chat_template_head": (m.get("tokenizer.chat_template") or "")[:90].replace("\n", " "),
        "gguf_version": m.get("_gguf_version"),
    }


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    for arg in sys.argv[1:]:
        p = Path(arg)
        print(f"\n=== {p.name} ===")
        try:
            info = describe(p)
        except Exception as e:  # noqa: BLE001
            print(f"  [FAIL] {type(e).__name__}: {e}")
            continue
        for k, v in info.items():
            if k != "file":
                print(f"  {k:20} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
