"""读 GGUF 里的 chat_template，看清思维链是怎么控制的。"""
import struct
from pathlib import Path

p = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main\storage\models\MiniCPM5-2B-Q4_K_M.gguf")
f = open(p, "rb")
magic, ver, n_tensors, n_kv = struct.unpack("<IIQQ", f.read(24))
print(f"GGUF v{ver}, {n_tensors} tensors, {n_kv} kv")


def rd_str():
    n = struct.unpack("<Q", f.read(8))[0]
    return f.read(n).decode("utf-8", "replace")


T = {0: "u8", 1: "i8", 2: "u16", 3: "i16", 4: "u32", 5: "i32", 6: "f32", 7: "bool",
     8: "str", 9: "arr", 10: "u64", 11: "i64", 12: "f64"}
FMT = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}


def skip_val(t):
    if t == 8:
        rd_str()
    elif t == 9:
        et = struct.unpack("<I", f.read(4))[0]
        n = struct.unpack("<Q", f.read(8))[0]
        for _ in range(n):
            skip_val(et)
    else:
        f.read(struct.calcsize(FMT[t]))


for _ in range(n_kv):
    k = rd_str()
    t = struct.unpack("<I", f.read(4))[0]
    if t == 8 and "chat_template" in k:
        v = rd_str()
        print(f"=== {k}（{len(v)} 字符）===")
        print(v)
        print("=== 结束 ===")
    elif t == 8 and ("eos" in k or "bos" in k or "pre" in k or "arch" in k or "thinking" in k or "reason" in k):
        print(f"{k} = {rd_str()[:200]}")
    else:
        skip_val(t)
f.close()
