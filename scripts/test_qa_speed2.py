"""用 llama-cpp-python 测「薛其坤可能拿什么奖」的纯生成耗时（模型只加载一次）。

对比：
  A. 不加任何东西
  B. 加空 <think></think>（Android 端 JNI 现在的做法）
每种跑两次，看是否稳定；同时把输出原样打出来看有没有推理内容。
"""
import time
from pathlib import Path

ROOT = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
MODEL = str(ROOT / "storage/models/MiniCPM5-2B-Q4_K_M.gguf")

OCR = """今晚 生理学或医学奖 今天 10月5日17:30 陈志坚（cGAS-STING免疫通路） 卢煜明(孕妇血里的胎儿DNA，无创产前检测) DavidHuang(OCT光学相干断层成像)
周二 物理学奖 10月6日17:45 薛其坤(董子反常霍尔效应) 叶军(光晶格原子钟)
周三 化学奖 10月7日1140 刘如谦(碱基编辑、无导编辑) 公众号·新音元"""

QUESTION = "薛其坤可能拿什么奖"
SYSTEM = "你是一个只依据给定文本回答问题的助手。"
USER = (f"下面是一次录音的转写文本：\n\n{OCR}\n\n用户问题：{QUESTION}\n\n"
        f"请只基于上面的转写内容回答；如果转写里没有相关信息，请明确说明\u201c转写中没有提到\u201d。\n"
        f"回答用纯文本（不要 Markdown 标记），条理清楚、直接给结论，别啰嗦。")


def main():
    from llama_cpp import Llama
    print("加载模型（只加载一次）…")
    t0 = time.time()
    llm = Llama(model_path=MODEL, n_ctx=2048, n_threads=4, verbose=False)
    print(f"  加载耗时 {time.time()-t0:.1f}s")
    tmpl = llm.metadata.get("tokenizer.chat_template", "") or ""
    print(f"  模板里是否含 <think>：{'<think>' in tmpl}")
    print(f"  模板片段：{tmpl[:160].replace(chr(10),' ')}…\n")

    def ask(label, prefix):
        prompt = (f"<|im_start|>system\n{SYSTEM}<|im_end|>\n"
                  f"<|im_start|>user\n{USER}<|im_end|>\n"
                  f"<|im_start|>assistant\n{prefix}")
        t1 = time.time()
        r = llm(prompt, max_tokens=400, temperature=0, echo=False)
        dt = time.time() - t1
        text = r["choices"][0]["text"]
        usage = r.get("usage", {})
        print(f"=== {label} ===")
        print(f"  生成耗时 {dt:.1f}s | 输出 token {usage.get('completion_tokens','?')}"
              f" | prompt token {usage.get('prompt_tokens','?')}")
        if usage.get("completion_tokens"):
            print(f"  速度 {usage['completion_tokens']/dt:.1f} tok/s")
        print(f"  输出（{len(text)} 字）：\n    " + text.strip().replace("\n", "\n    ")[:600] + "\n")

    ask("A. 不干预（默认）", "")
    ask("B. 空 think 块（Android 做法）", "<think>\n\n</think>\n\n")
    ask("B 再来一次（看是否稳定）", "<think>\n\n</think>\n\n")


if __name__ == "__main__":
    main()
