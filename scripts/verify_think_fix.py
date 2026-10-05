"""验证修复：MiniCPM5 的思维链标记是 [Start thinking]，补空块能否让它直接答题。

用 --chat-template 传"直通模板"（{{ messages[0]['content'] }}），
这样 CLI 原样使用我拼好的 prompt，不会自己加东西；再对比补/不补空思考块的耗时。
"""
import re
import subprocess
import time
from pathlib import Path

LLAMA = Path(r"E:\android-dev\llama-cpu")
CLI = LLAMA / "llama-cli.exe"
MODEL = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main\storage\models\MiniCPM5-2B-Q4_K_M.gguf")
PASSTHROUGH = "{{ messages[0]['content'] }}"

OCR = """今晚 生理学或医学奖 今天 10月5日17:30 陈志坚（cGAS-STING免疫通路） 卢煜明(孕妇血里的胎儿DNA，无创产前检测) DavidHuang(OCT光学相干断层成像)
周二 物理学奖 10月6日17:45 薛其坤(董子反常霍尔效应) 叶军(光晶格原子钟)
周三 化学奖 10月7日1140 刘如谦(碱基编辑、无导编辑) 公众号·新音元"""

QUESTION = "薛其坤可能拿什么奖"
SYSTEM = "你是一个只依据给定文本回答问题的助手。"
USER = (f"下面是一次录音的转写文本：\n\n{OCR}\n\n用户问题：{QUESTION}\n\n"
        f"请只基于上面的转写内容回答；如果转写里没有相关信息，请明确说明\u201c转写中没有提到\u201d。\n"
        f"回答用纯文本（不要 Markdown 标记），条理清楚、直接给结论，别啰嗦。")


def raw_prompt(prefix: str) -> str:
    return (f"<|im_start|>system\n{SYSTEM}<|im_end|>\n"
            f"<|im_start|>user\n{USER}<|im_end|>\n"
            f"<|im_start|>assistant\n{prefix}")


def run(label: str, prefix: str):
    pf = Path(r"E:\android-dev\raw-prompt.txt")
    pf.write_text(raw_prompt(prefix), encoding="utf-8")
    cmd = [str(CLI), "-m", str(MODEL), "-f", str(pf), "-n", "300", "-c", "2048",
           "-t", "4", "--temp", "0", "-st", "--chat-template", PASSTHROUGH,
           "--no-display-prompt", "--no-warmup"]
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="ignore", cwd=str(LLAMA), timeout=1200)
    dt = time.time() - t0
    out = (r.stdout or "") + (r.stderr or "")

    def grab(pat):
        m = re.search(pat, out)
        return (float(m.group(1)) / 1000.0, m.group(2)) if m else (-1.0, "?")

    load, _ = grab(r"load time =\s*([\d.]+)\s*ms")
    peval, ptok = grab(r"prompt eval time =\s*([\d.]+)\s*ms\s*/\s*(\d+)\s*tokens")
    gen, gtok = grab(r"eval time =\s*([\d.]+)\s*ms\s*/\s*(\d+)\s*runs")
    total, _ = grab(r"total time =\s*([\d.]+)\s*ms")
    # 生成文本（去掉日志行）
    body = "\n".join(l for l in out.splitlines()
                     if l.strip() and not re.match(
                         r"^(llama_|print_info|main:|build|model|ftype|modalities|available|"
                         r"\s*\/|>|load time|prompt eval|eval time|total time|sampling|"
                         r"generate|system_info|graph|common_|init:|using|assistant|user|"
                         r"<\|)", l)).strip()
    print(f"\n=== {label} ===")
    print(f"  墙钟 {dt:.1f}s | 加载 {load:.1f}s | prompt {peval:.1f}s/{ptok}tok"
          f" | 生成 {gen:.1f}s/{gtok}tok | 合计 {total:.1f}s")
    if str(gtok).isdigit() and gen > 0:
        print(f"  速度 {float(gtok)/gen:.1f} tok/s")
    print(f"  输出（{len(body)} 字）：\n    " + body.replace("\n", "\n    ")[:500])


if __name__ == "__main__":
    run("A. 不干预（默认，会先推理）", "")
    run("B. 补空 [Start thinking] 块（本次修复）", "[Start thinking]\n\n[End thinking]\n\n")
