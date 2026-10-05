"""上传前检查：提交里最大的文件、是否会触发 GitHub/Gitee 的限制。"""
import subprocess

out = subprocess.run(["git", "ls-tree", "-r", "-l", "HEAD"],
                     capture_output=True, text=True, encoding="utf-8").stdout
rows = []
for line in out.splitlines():
    parts = line.split()
    if len(parts) >= 4 and parts[3].isdigit():
        rows.append((int(parts[3]), " ".join(parts[4:])))
rows.sort(reverse=True)

print("  提交里最大的 6 个文件：")
for size, name in rows[:6]:
    print(f"    {size / 1e6:8.2f} MB  {name}")

mx = rows[0][0] if rows else 0
total = sum(s for s, _ in rows)
print()
print(f"  最大单文件：{mx / 1e6:.1f} MB")
if mx < 50_000_000:
    verdict = "安全（低于 50MB 警告线）"
elif mx < 100_000_000:
    verdict = "会警告但能传"
else:
    verdict = "会被拒绝"
print("  GitHub：100MB 硬上限 / 50MB 警告  ->  " + verdict)
print("  Gitee ：单文件 100MB 上限          ->  " + verdict)
print(f"  文件总数 {len(rows)}，合计 {total / 1e6:.1f} MB（推送压缩后更小）")
