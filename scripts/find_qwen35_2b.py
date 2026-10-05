"""找 Qwen3.5-2B 的 GGUF（ModelScope）+ 确认它的模板默认关闭思维链。"""
import json
import re
import struct
import urllib.error
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 Chrome/120"}
REPOS = [
    "unsloth/Qwen3.5-2B-GGUF",
    "Qwen/Qwen3.5-2B-GGUF",
    "Qwen/Qwen3.5-2B",
    "unsloth/Qwen3.5-1.7B-GGUF",
    "Qwen/Qwen3.5-1.7B-GGUF",
]


def list_files(repo):
    url = f"https://www.modelscope.cn/api/v1/models/{repo}/repo/files?Revision=master"
    try:
        raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25).read()
        return [(f["Path"], f["Size"]) for f in json.loads(raw)["Data"]["Files"] if f["Type"] == "blob"]
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return type(e).__name__


def fetch_range(url, nbytes):
    hdr = dict(UA)
    hdr["Range"] = f"bytes=0-{nbytes - 1}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=180) as r:
        return r.read()


def parse_template(buf):
    if buf[:4] != b"GGUF":
        return None, "不是 GGUF"
    pos = 4
    struct.unpack_from("<I", buf, pos)[0]; pos += 4
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
        raise ValueError(f"类型 {t}")

    for _ in range(n_kv):
        try:
            key, pos = rd_str(pos)
            t = struct.unpack_from("<I", buf, pos)[0]; pos += 4
            val, pos = rd_val(pos, t)
        except Exception as e:  # noqa: BLE001
            return None, f"解析中断@{pos}: {e}"
        if key == "tokenizer.chat_template":
            return val, f"张量={n_tensors} 元数据={n_kv}"
    return None, "没找到 chat_template"


def main():
    best = None
    for repo in REPOS:
        r = list_files(repo)
        if isinstance(r, str):
            print(f"  [--] {repo}: {r}")
            continue
        gguf = [(p, s) for p, s in r if p.lower().endswith(".gguf")]
        print(f"  [OK] {repo}: gguf {len(gguf)} 个")
        for p, s in gguf[:6]:
            print(f"        {p:<44} {s / 1e6:8.1f} MB")
        q4 = [x for x in gguf if "Q4_K_M" in x[0]]
        if q4 and best is None:
            best = (repo, q4[0][0], q4[0][1])

    if not best:
        print("没有找到 Q4_K_M")
        return
    repo, name, size = best
    url = f"https://www.modelscope.cn/models/{repo}/resolve/master/{name}"
    print(f"\n选用：{repo} / {name} = {size} 字节（{size / 1e6:.1f} MB）")
    print(f"地址：{url}\n")

    for mb in (8, 24, 64):
        buf = fetch_range(url, mb * 1024 * 1024)
        tmpl, info = parse_template(buf)
        print(f"前 {mb} MB：{info}")
        if tmpl:
            i = tmpl.find("add_generation_prompt")
            print("\n=== 生成部分 ===")
            print(tmpl[i - 20:i + 320].replace("\n", " "))
            print("\n=== enable_thinking 出现处 ===")
            for m in re.finditer("enable_thinking", tmpl):
                seg = tmpl[max(0, m.start() - 100):m.start() + 120].replace("\n", " ")
                print("  …" + seg + "…")
            return


if __name__ == "__main__":
    main()
