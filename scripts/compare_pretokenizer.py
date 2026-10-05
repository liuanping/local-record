"""对比 MiniCPM5 的预分词正则与 llama.cpp 内置正则（开发辅助）。

背景：MiniCPM5-2B 的 GGUF 声明 ``tokenizer.ggml.pre = "minicpm5"``，而
llama.cpp b9000 不认识这个名字，加载时报
``unknown pre-tokenizer type: 'minicpm5'``。

思路：llama.cpp 支持 ``--override-kv tokenizer.ggml.pre=str:<名字>``。
但如果随便换一个名字，正则不同会导致切词不同 → 静默掉效果。
所以这里：
1. 从 HuggingFace ``tokenizer.json`` 里取出模型真实的预分词正则；
2. 从 ``llama.dll`` 里把所有内置正则（含 ``\\p{L}`` 的那些字符串）提取出来；
3. 完全一致才说明可以安全覆盖成那个内置名字。

用法::

    .venv\\Scripts\\python.exe scripts\\compare_pretokenizer.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKENIZER = ROOT / "build" / "models-test" / "tokenizer.json"
LLAMA_DLL = ROOT / "storage" / "bin" / "llama-server" / "llama.dll"


def model_patterns() -> list[str]:
    data = json.loads(TOKENIZER.read_text(encoding="utf-8"))
    pats: list[str] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            if node.get("type") == "Split" and isinstance(node.get("pattern"), dict):
                p = node["pattern"]
                if p.get("Regex"):
                    pats.append(p["Regex"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data.get("pre_tokenizer"))
    return pats


def dll_regexes() -> list[str]:
    """从 llama.dll 里抽取所有"看起来像预分词正则"的字符串。"""
    raw = LLAMA_DLL.read_bytes()
    out: list[str] = []
    for m in re.finditer(rb"[\x20-\x7e]{20,600}", raw):
        s = m.group().decode("ascii")
        if "\\p{L}" in s and "\\p{N}" in s:
            out.append(s)
    # 去重保序
    seen: set[str] = set()
    uniq: list[str] = []
    for s in out:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def main() -> int:
    if not TOKENIZER.is_file():
        print(f"缺少 {TOKENIZER}（先从模型仓库下 tokenizer.json）")
        return 1
    pats = model_patterns()
    print("=== MiniCPM5-2B 的预分词正则 ===")
    for p in pats:
        print(f"  {p}")
    known = dll_regexes()
    print(f"\n=== llama.cpp(b9000) 内置正则共 {len(known)} 条 ===")
    for k in known:
        mark = ""
        if any(p == k for p in pats):
            mark = "   <<< 与模型完全一致"
        print(f"  {k[:150]}{'…' if len(k) > 150 else ''}{mark}")

    exact = [k for k in known if any(p == k for p in pats)]
    print()
    if exact:
        print("[结论] 存在完全一致的内置正则 → 可以安全用 "
              "--override-kv tokenizer.ggml.pre=str:<对应名字> 覆盖，切词行为不变。")
        print("       对应名字需按 llama.dll 里的名字表确认（见下方候选）。")
    else:
        print("[结论] 没有完全一致的内置正则 → 覆盖会改变切词，效果有风险，"
              "建议升级 llama.cpp 而不是硬凑。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
