"""复现「薛其坤可能拿什么奖」的耗时，判断 32 秒是否正常。

对比：
  A. 默认（模型自带模板，不干预）—— 看它会不会先长篇推理
  B. 空的 <think></think>（Android 端 JNI 现在的做法）
  C. 模板参数 enable_thinking=false（llama.cpp CLI 支持，看是否更干净）
记录：加载耗时 / prompt 处理 / 生成 token 与耗时 / 输出内容。
"""
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
LLAMA = Path(r"E:\android-dev\llama-cpu")
CLI = LLAMA / "llama-cli.exe"
MODEL = ROOT / "storage/models/MiniCPM5-2B-Q4_K_M.gguf"
TMP = Path(r"E:\android-dev\qa-prompt.txt")

OCR = """今晚
生理学或医学奖
今天
10月5日17:30
陈志坚（cGAS-STING免疫通路）
卢煜明(孕妇血里的胎儿DNA，无创产前检测)
DavidHuang(OCT光学相干断层成像)
周二
物理学奖
10月6日17:45
薛其坤(董子反常霍尔效应)
叶军(光晶格原子钟)
周三
化学奖
10月7日1140
刘如谦(碱基编辑、无导编辑)
公众号·新音元"""

QUESTION = "薛其坤可能拿什么奖"
SYSTEM = "你是一个只依据给定文本回答问题的助手。"

USER = (f"下面是一次录音的转写文本：\n\n{OCR}\n\n用户问题：{QUESTION}\n\n"
        f"请只基于上面的转写内容回答；如果转写里没有相关信息，请明确说明\u201c转写中没有提到\u201d。\n"
        f"回答用纯文本（不要 Markdown 标记），条理清楚、直接给结论，别啰嗦。\n"
        f"<think>\n\n</think>\n\n")


def run(label, extra_args, user_text):
    TMP.write_text(user_text, encoding="utf-8")
    cmd = [str(CLI), "-m", str(MODEL), "-sys", SYSTEM, "-f", str(TMP),
           "-n", "400", "-c", "2048", "-t", "4", "--temp", "0", "-st"] + extra_args
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="ignore", cwd=str(LLAMA), timeout=1200)
    dt = time.time() - t0
    out = (r.stdout or "") + (r.stderr or "")

    def ms(pat):
        m = re.search(pat, out)
        return (float(m.group(1)) / 1000.0, m.group(2)) if m else (-1.0, "?")

    load, _ = ms(r"load time =\s*([\d.]+)\s*ms")
    peval, ptok = ms(r"prompt eval time =\s*([\d.]+)\s*ms\s*/\s*(\d+)\s*tokens")
    gen, gtok = ms(r"eval time =\s*([\d.]+)\s*ms\s*/\s*(\d+)\s*runs")
    total, _ = ms(r"total time =\s*([\d.]+)\s*ms")

    # 取生成文本（去掉日志行）
    lines = [l for l in out.splitlines()
             if l.strip() and not re.match(r"^(llama_|print_info|main:|build|model|ftype|"
                                           r"llama_model|llama_context|load|sampler|generate|"
                                           r"prompt eval|eval time|total time|system_info|"
                                           r"sampling|graph|common_|init:|warming|using|"
                                           r"assistant|user|<\|)", l)]
    body = "\n".join(lines).strip()
    print(f"\n=== {label} ===")
    print(f"  墙钟 {dt:.1f}s | 加载 {load:.1f}s | prompt {peval:.1f}s/{ptok}tok"
          f" | 生成 {gen:.1f}s/{gtok}tok | 合计 {total:.1f}s")
    if gtok.isdigit() and float(gtok) > 0 and gen > 0:
        print(f"  速度 {float(gtok)/gen:.1f} tok/s")
    print(f"  输出（{len(body)} 字）：\n    " + body.replace("\n", "\n    ")[:600])
    return body


if __name__ == "__main__":
    print("llama-cli:", CLI, "存在:", CLI.is_file())
    print("模型:", MODEL, "存在:", MODEL.is_file())
    run("A. 默认（不干预模板）", [], USER)
    run("B. 空 think 块（Android 端做法）", [], USER)
    run("C. enable_thinking=false", ["--chat-template-kwargs", '{"enable_thinking":false}'],
        USER.replace("<think>\n\n</think>\n\n", ""))
