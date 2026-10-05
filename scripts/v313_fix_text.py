"""3.1.3 修补：按钮变宽后左侧提示被挤溢出，缩短文案 + 不再叫"圆钮"。"""
from pathlib import Path

f = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main\android\app\src\main\java\com\localrecord\app\MainActivity.kt")
t = f.read_text(encoding="utf-8")

pairs = [
    ('else "点圆钮开始录音，自动断句、自动出字"', 'else "点「录音」，自动断句出字"'),
    ('"点圆钮开始录音（标点模型还没下完，先出不带标点的文字）"', '"点「录音」开始（标点模型还没下完，先出不带标点的文字）"'),
    ('"尚未获得麦克风权限，点「录音」会弹出授权提示（没反应就点这里去设置）"',
     '"尚未获得麦克风权限，点「录音」会弹出授权提示（没反应就点这里去设置）"'),
]
for a, b in pairs:
    if a in t:
        t = t.replace(a, b)
        print(f"  ✓ {a[:26]}…")

# 提示行限制 2 行，字号 9 → 保持；但把 maxLines 收紧到 2 已有
f.write_text(t, encoding="utf-8")
print("文案已更新 ✓")

# 顺带确认界面上还有没有"圆钮"字样
left = [l.strip()[:90] for l in t.split("\n") if "圆钮" in l]
print("剩余“圆钮”字样：", left if left else "无 ✓")
