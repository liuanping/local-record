"""只打印 Qwen3.5-4B 模板里的思考控制部分 + 从 ModelScope API 取精确字节数。"""
import json
import re
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 Chrome/120"}
REPO = "unsloth/Qwen3.5-4B-GGUF"
FILE = "Qwen3.5-4B-Q4_K_M.gguf"

# 1) 精确大小
url = f"https://www.modelscope.cn/api/v1/models/{REPO}/repo/files?Revision=master"
data = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read())
for f in data["Data"]["Files"]:
    if f["Type"] == "blob" and f["Path"] == FILE:
        print(f"精确大小：{f['Size']} 字节 = {f['Size'] / 1e6:.1f} MB")
        print(f"下载地址：https://www.modelscope.cn/models/{REPO}/resolve/master/{FILE}")

# 2) 模板里的思考控制
import importlib.util
spec = importlib.util.spec_from_file_location(
    "probe", r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main\scripts\probe_qwen35_template.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
buf = probe.fetch_range(24 * 1024 * 1024)
tmpl, info = probe.parse_template(buf)
print(f"\n模板长度 {len(tmpl)} 字符（{info}）\n")

print("=== 含 enable_thinking / think 的位置 ===")
for m in re.finditer(r"enable_thinking|no_think|think", tmpl):
    s = max(0, m.start() - 90)
    seg = tmpl[s:m.start() + 110].replace("\n", " ")
    print(f"  …{seg}…\n")
