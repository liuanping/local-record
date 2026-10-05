"""检查 MainActivity 是否被重复改坏（对比已提交的 3.1.1）。"""
import subprocess
from pathlib import Path

R = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
f = R / "android/app/src/main/java/com/localrecord/app/MainActivity.kt"
s = f.read_text(encoding="utf-8")

print("关键字计数（正常值）：")
for kw, ok in [("MAX_PENDING", 3), ("translateSkipped", 4), ("翻译 开", 1), ("翻译 关", 1),
               ("已开启翻译", 1), ("val dropped", 1), ("isLetterOrDigit", 1),
               ("说得太快，这句没来得及翻", 1), ("androidx.compose.material3.Switch(", 0)]:
    c = s.count(kw)
    print(f"  {kw:<28} {c}  {'✓' if c == ok else '✗ 期望 ' + str(ok)}")

d, ins = 0, False
for ch in s:
    if ch == '"':
        ins = not ins
    if not ins:
        if ch == "{":
            d += 1
        elif ch == "}":
            d -= 1
print(f"  括号平衡 = {d}（应为 0）")
print(f"  行数 = {len(s.splitlines())}")

print("\n=== 与已提交 3.1.1 的差异（只应看到我新加的胶囊按钮）===")
out = subprocess.run(["git", "diff", "--", str(f.relative_to(R))], cwd=R,
                     capture_output=True, text=True, encoding="utf-8").stdout
for line in out.splitlines():
    if line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
        print("  " + line[:120])
