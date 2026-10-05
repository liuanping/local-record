"""取 Qwen3.5-4B Q4_K_M 的精确大小，并用 Range 只下载开头几 MB 读它的对话模板。

目的：确认它的模板是否支持 enable_thinking（决定"关思维链"能不能靠补空 think 块实现）。
"""
import struct
import urllib.request
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 Chrome/120"}
REPO = "unsloth/Qwen3.5-4B-GGUF"
FILE = "Qwen3.5-4B-Q4_K_M.gguf"
URL = f"https://www.modelscope.cn/models/{REPO}/resolve/master/{FILE}"


def head_size():
    req = urllib.request.Request(URL, headers=UA, method="HEAD")
    with urllib.request.urlopen(req, timeout=60) as r:
        return int(r.headers.get("Content-Length", 0)), r.headers.get("Accept-Ranges")


def fetch_range(nbytes):
    hdr = dict(UA)
    hdr["Range"] = f"bytes=0-{nbytes - 1}"
    req = urllib.request.Request(URL, headers=hdr)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def parse_template(buf):
    """在内存里解析 GGUF 元数据，找 tokenizer.chat_template"""
    if buf[:4] != b"GGUF":
        return None, "不是 GGUF"
    pos = 4
    ver = struct.unpack_from("<I", buf, pos)[0]; pos += 4
    n_tensors = struct.unpack_from("<Q", buf, pos)[0]; pos += 8
    n_kv = struct.unpack_from("<Q", buf, pos)[0]; pos += 8

    def rd_str(p):
        n = struct.unpack_from("<Q", buf, p)[0]; p += 8
        return buf[p:p + n].decode("utf-8", "replace"), p + n

    def rd_val(p, t):
        if t == 8:
            return rd_str(p)
        if t in (0, 1, 7):
            return buf[p], p + 1
        if t in (2, 3):
            return struct.unpack_from("<H", buf, p)[0], p + 2
        if t in (4, 5, 6):
            return struct.unpack_from("<I" if t != 6 else "<f", buf, p)[0], p + 4
        if t in (10, 11, 12):
            return struct.unpack_from("<Q" if t == 10 else ("<q" if t == 11 else "<d"), buf, p)[0], p + 8
        if t == 9:
            et = struct.unpack_from("<I", buf, p)[0]; n = struct.unpack_from("<Q", buf, p + 4)[0]
            p += 12
            for _ in range(n):
                _, p = rd_val(p, et)
            return None, p
        raise ValueError(f"未知类型 {t}")

    for _ in range(n_kv):
        try:
            key, pos = rd_str(pos)
            t = struct.unpack_from("<I", buf, pos)[0]; pos += 4
            val, pos = rd_val(pos, t)
        except Exception as e:  # noqa: BLE001
            return None, f"解析中断（读到 {pos} 字节）：{e}"
        if key == "tokenizer.chat_template":
            return val, f"版本={ver} 张量={n_tensors} 元数据={n_kv}"
        if key == "general.name":
            print(f"  general.name = {val}")
    return None, "前几 MB 里没有 chat_template（元数据更长）"


def main():
    size, ranges = head_size()
    print(f"文件：{FILE}")
    print(f"  精确大小 {size} 字节 = {size / 1e6:.1f} MB  支持 Range={ranges}")
    for mb in (2, 8, 24):
        buf = fetch_range(mb * 1024 * 1024)
        tmpl, info = parse_template(buf)
        print(f"\n  取前 {mb} MB：{info}")
        if tmpl:
            print("=" * 70)
            print(tmpl)
            print("=" * 70)
            print("【思考控制相关】")
            for kw in ("enable_thinking", "think", "/no_think", "reasoning"):
                if kw in tmpl:
                    i = tmpl.find(kw)
                    print(f"  含 {kw!r}: …{tmpl[max(0, i - 60):i + 80]!r}…")
            return


if __name__ == "__main__":
    main()
