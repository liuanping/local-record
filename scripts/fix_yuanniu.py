"""3.1.4 修补：清掉所有残留的"圆钮"字样（按钮已改成胶囊）。"""
from pathlib import Path

APP = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main\android\app\src\main\java\com\localrecord\app")
total = 0
for f in sorted(APP.glob("*.kt")):
    t = f.read_text(encoding="utf-8")
    if "圆钮" not in t:
        continue
    print(f"--- {f.name}")
    for i, l in enumerate(t.split("\n"), 1):
        if "圆钮" in l:
            print(f"  {i:5d}| {l.strip()[:120]}")
    # 常见替换：圆钮 -> 「录音」按钮
    t2 = (t.replace("点圆钮开始录音", "点「录音」开始")
            .replace("圆钮", "「录音」按钮"))
    f.write_text(t2, encoding="utf-8")
    total += 1
print(f"\n已处理 {total} 个文件")
# 复查
rest = []
for f in sorted(APP.glob("*.kt")):
    if "圆钮" in f.read_text(encoding="utf-8"):
        rest.append(f.name)
print("仍含“圆钮”的文件：", rest if rest else "无 ✓")
