"""3.1.8 文档更新（避免在 PowerShell 里处理中文引号）。"""
from pathlib import Path

R = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
for rel in [".gitignore", "README.md", "docs/链接汇总.md"]:
    p = R / rel
    if p.exists():
        p.write_text(p.read_text(encoding="utf-8").replace("3.1.7", "3.1.8"), encoding="utf-8")
        print(f"  {rel} -> 3.1.8")

r = (R / "android/README-android.md").read_text(encoding="utf-8")
if "**3.1.8**" not in r:
    entry = """* **3.1.8**：修翻译中英串扰（用户实测：简单词会半翻半留，如「头盔」被翻成「head 盔」）：
  * 提示词加 few-shot 例子，并明确要求「绝不允许在译文里保留另一种语言」（小模型跟例子比跟规则靠谱）；
  * 代码侧最多试三种问法：few-shot 提示 → 「Translate into English: xxx」直译式 → 「What is the English word for this?」，
    每一步都用语言检测判断有没有串扰，三种都不行才保留原样并打日志；
  * 自检用例加入短词，实测：头盔→helmet、会议纪要→meeting minutes、中英整句互译均正确，RESULT PASS。

"""
    (R / "android/README-android.md").write_text(
        r.replace("* **3.1.7**：", entry + "* **3.1.7**：", 1), encoding="utf-8")
    print("  README-android 已加 3.1.8")

s = R / "SNAPSHOT-INFO.txt"
s.write_text(s.read_text(encoding="utf-8").replace(
    "Android 3.1.7（对应 git 标签 android-v3.1.7）",
    "Android 3.1.8（对应 git 标签 android-v3.1.8）"), encoding="utf-8")
print("  SNAPSHOT-INFO -> 3.1.8")
