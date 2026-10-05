"""Stage 2（可靠版）：用括号配对删除大模型界面，删完先自检括号平衡。"""
import subprocess
from pathlib import Path

ROOT = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
m = ROOT / "android/app/src/main/java/com/localrecord/app/MainActivity.kt"

# 先恢复（去掉上一次切坏的结果）
subprocess.run(["git", "checkout", "--", str(m.relative_to(ROOT))], cwd=ROOT, check=True)
print("已恢复 MainActivity.kt 到 2.5.2 ✓")

lines = m.read_text(encoding="utf-8").split("\n")


def block_end(start: int) -> int:
    """从 start 行开始，按花括号配对找到该块结束行（含）"""
    depth = 0
    for i in range(start, len(lines)):
        s = lines[i]
        j, in_str = 0, False
        while j < len(s):
            c = s[j]
            if not in_str and c == "/" and j + 1 < len(s) and s[j + 1] == "/":
                break
            if c == '"' and (j == 0 or s[j - 1] != "\\"):
                in_str = not in_str
            if not in_str:
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
            j += 1
        if depth == 0 and i > start:
            return i
        if depth < 0:
            return i
    raise RuntimeError(f"从第 {start + 1} 行起找不到块结尾")


def cut(marker_pred, label):
    global lines
    i = next((k for k, l in enumerate(lines) if marker_pred(l)), -1)
    if i < 0:
        print(f"  [跳过] {label}：没找到")
        return
    e = block_end(i)
    print(f"  删除 {label}：第 {i + 1}~{e + 1} 行")
    del lines[i:e + 1]


# 1) 大模型结果弹窗
cut(lambda l: l.strip().startswith("// 大模型结果弹窗"), "结果弹窗")
# 2) 生成会议纪要那一行（含查看纪要/查看回答）
cut(lambda l: l.strip() == "if (tab != 2) {", "生成会议纪要入口")
# 3) 提问输入行
i = next((k for k, l in enumerate(lines) if "androidx.compose.material3.OutlinedTextField(" in l), -1)
if i >= 0:
    r = i
    while r > 0 and "Row(horizontalArrangement" not in lines[r]:
        r -= 1
    e = block_end(r)
    print(f"  删除 提问行：第 {r + 1}~{e + 1} 行")
    del lines[r:e + 1]

text = "\n".join(lines)

# 4) 文案：不再提"提问"
text = text.replace('"识别图片里的文字，然后用下面的输入框提问"', '"识别图片里的文字（可一键复制）"')
text = text.replace('"选一张带文字的图片（合同 / 截图 / 文档 / 名片），识别出来的文字会显示在这里，" +',
                    '"选一张带文字的图片（合同 / 截图 / 文档 / 名片），识别出来的文字会显示在这里，可一键复制。\\n\\n全程在手机上完成。" +')

# 5) 平衡自检
depth = 0
in_str = False
for ch in text:
    if ch == '"':
        in_str = not in_str
    if not in_str:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
print(f"\n括号平衡自检：末尾深度 = {depth}（应为 0）")
assert depth == 0, "括号不平衡，已放弃写入"

m.write_text(text, encoding="utf-8")
print("MainActivity.kt 已精简并写入 ✓（行数 %d）" % len(text.split("\n")))
