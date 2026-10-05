"""精确统计：系统提示词 / 提示词模板 / 用户内容各占多少字，估算 token。

直接从 LlmEngine.kt 抠出真实字符串（不改代码，只读源码），避免我凭印象回答。
"""
import re
from pathlib import Path

ROOT = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
kt = (ROOT / "android/app/src/main/java/com/localrecord/app/LlmEngine.kt").read_text(encoding="utf-8")


def grab_triple_after(marker: str) -> str:
    i = kt.find(marker)
    assert i != -1, marker
    a = kt.find('"""', i) + 3
    b = kt.find('"""', a)
    return kt[a:b]


sys_prompt = grab_triple_after("val MINUTES_SYSTEM =").strip()
minutes_tpl = grab_triple_after("fun minutesPrompt(transcript: String): String =")
ask_tpl = grab_triple_after("fun askPrompt(transcript: String, question: String): String =")


def count(name: str, text: str):
    chars = len(text)
    # 中文按约 0.7 token/字估（Qwen BPE）；准确的数字由 JNI 现在打印的 token 数为准
    print(f"  {name:<28} {chars:>5} 字   ≈{chars * 0.7:>6.0f} token")
    return chars


print("=== 固定部分（每次都要喂给模型）===")
s1 = count("系统提示词 MINUTES_SYSTEM", sys_prompt)
print()
print("=== 会议纪要模板（$transcript 是变量）===")
m_fixed = minutes_tpl.replace("$transcript", "")
m1 = count("模板固定文字", m_fixed)
print()
print("=== 问答模板（$transcript / $question 是变量）===")
a_fixed = ask_tpl.replace("$transcript", "").replace("$question", "")
a1 = count("模板固定文字", a_fixed)

print("\n=== 用户内容（可变）===")
ocr = ("今晚 生理学或医学奖 今天 10月5日17:30 陈志坚（cGAS-STING免疫通路） "
       "卢煜明(孕妇血里的胎儿DNA，无创产前检测) DavidHuang(OCT光学相干断层成像) "
       "周二 物理学奖 10月6日17:45 薛其坤(董子反常霍尔效应) 叶军(光晶格原子钟) "
       "周三 化学奖 10月7日1140 刘如谦(碱基编辑、无导编辑) 公众号·新音元")
c1 = count("你的那张图 OCR 文字", ocr)
seg = "今天的会议改到下午三点请大家准时参加"
transcript9 = "\n".join(f"[{i+1}] 00:{i*7:02d} {seg}" for i in range(9))
c2 = count("9 段转写（示例）", transcript9)

print("\n=== 实际发出去的完整 prompt（估算）===")
ask_full = s1 + a1 + len(ocr) + len("薛其坤可能拿什么奖")
print(f"  问答（用你这张图）      ≈{ask_full} 字  ≈{ask_full * 0.7:.0f} token")
print(f"    其中系统提示词        {s1} 字（{s1 / ask_full * 100:.0f}%）")
min_full = s1 + m1 + len(transcript9)
print(f"  会议纪要（9 段转写）    ≈{min_full} 字  ≈{min_full * 0.7:.0f} token")
print(f"  会议纪要（满预算 2600） ≈{s1 + m1 + 2600} 字  ≈{(s1 + m1 + 2600) * 0.7:.0f} token")

print("\n=== 系统提示词原文（%d 字）===" % s1)
print(sys_prompt)
