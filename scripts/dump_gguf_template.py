"""直接解析 GGUF 元数据，把 tokenizer.chat_template 原样打印出来。

之前两次"关闭思维链"都没生效，就是因为我一直在猜标记名。这里不再猜：
GGUF 的元数据是明文键值对，直接把模板读出来看它到底用什么控制思考。
"""
import struct
from pathlib import Path

MODEL = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main\storage\models\MiniCPM5-2B-Q4_K_M.gguf")

# GGUF 值类型
UINT8, INT8, UINT16, INT16, UINT32, INT32, FLOAT32, BOOL, STRING, ARRAY, UINT64, INT64, FLOAT64 = range(13)


def read_str(f):
    n = struct.unpack("<Q", f.read(8))[0]
    return f.read(n).decode("utf-8", errors="replace")


def read_value(f, t):
    if t == STRING:
        return read_str(f)
    if t in (UINT8, INT8, BOOL):
        return struct.unpack("<B", f.read(1))[0]
    if t in (UINT16, INT16):
        return struct.unpack("<H", f.read(2))[0]
    if t in (UINT32, INT32, FLOAT32):
        return struct.unpack("<I" if t != FLOAT32 else "<f", f.read(4))[0]
    if t in (UINT64, INT64, FLOAT64):
        return struct.unpack("<Q" if t == UINT64 else ("<q" if t == INT64 else "<d"), f.read(8))[0]
    if t == ARRAY:
        et = struct.unpack("<I", f.read(4))[0]
        n = struct.unpack("<Q", f.read(8))[0]
        return [read_value(f, et) for _ in range(n)]
    raise ValueError(f"未知类型 {t}")


def main():
    with MODEL.open("rb") as f:
        magic = f.read(4)
        ver = struct.unpack("<I", f.read(4))[0]
        n_tensors = struct.unpack("<Q", f.read(8))[0]
        n_kv = struct.unpack("<Q", f.read(8))[0]
        print(f"magic={magic} 版本={ver} 张量数={n_tensors} 元数据项={n_kv}\n")

        for _ in range(n_kv):
            key = read_str(f)
            t = struct.unpack("<I", f.read(4))[0]
            val = read_value(f, t)
            if key == "tokenizer.chat_template":
                print("=" * 70)
                print("tokenizer.chat_template 原文：")
                print("=" * 70)
                print(val)
                print("=" * 70)
                print("\n【关键检查】模板里出现的思考相关字样：")
                for kw in ("think", "Think", "THINK", "reasoning", "channel", "<|", "[Start"):
                    if kw in val:
                        idx = val.find(kw)
                        print(f"  含 {kw!r}：…{val[max(0,idx-40):idx+60]!r}…".replace("\\n", " "))
            elif key in ("general.name", "general.basename", "tokenizer.ggml.model",
                         "general.architecture"):
                print(f"{key} = {val}")


if __name__ == "__main__":
    main()
