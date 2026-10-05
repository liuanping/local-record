"""从电脑版的 PP-OCRv6 ONNX 模型配置里提取：预处理参数 + 识别字典。

输出：
  android/app/src/main/assets/ocr_rec_dict.txt   （每行一个字符，给 Android CTC 解码用）
  storage/ocr/ocr_params.json                    （det/rec 的预处理参数，Android 端照抄）
"""
import json
import re
from pathlib import Path

ROOT = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
DET = ROOT / "storage/ocr/official_models/PP-OCRv6_medium_det_onnx"
REC = ROOT / "storage/ocr/official_models/PP-OCRv6_medium_rec_onnx"

print("=== det inference.yml 全文 ===")
det_txt = (DET / "inference.yml").read_text(encoding="utf-8", errors="replace")
print(det_txt)

print("=== rec inference.yml 前 40 行（字典之外的部分）===")
rec_lines = (REC / "inference.yml").read_text(encoding="utf-8", errors="replace").splitlines()
for line in rec_lines[:40]:
    print("   ", line[:100])

# ---- 抽字典 ----
# 注意：必须用正规 YAML 解析器！字典里有一项是"全角空格 U+3000"，
# 手写解析时 `line.strip()` 会把它吃掉，导致 `- ` 前缀判断失败、跳过这一项，
# 于是**后面所有中文的索引整体错一位**（症状：数字/字母识别正确、汉字全错）。
import yaml

rec_cfg = yaml.safe_load((REC / "inference.yml").read_text(encoding="utf-8"))
chars = [str(c) for c in rec_cfg["PostProcess"]["character_dict"]]
out = ROOT / "android/app/src/main/assets/ocr_rec_dict.txt"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text("\n".join(chars), encoding="utf-8")
print(f"=== 字典：{len(chars)} 个字符 → {out}")
print("    第 1745~1750 项（含那个全角空格）:", [repr(c) for c in chars[1745:1750]])
print("    含中文:", "".join([c for c in chars if "\u4e00" <= c <= "\u9fff"][:25]))

# ---- 预处理参数 ----
def grab(txt: str, key: str):
    m = re.search(rf"^\s*{key}:\s*(.+)$", txt, re.M)
    return m.group(1).strip() if m else None

params = {
    "det": {
        "box_thresh": 0.45,
        "thresh": 0.2,
        "unclip_ratio": 1.4,
        "limit_side_len": 960,
        "limit_type": "max",
        "mean": [0.485, 0.456, 0.406],
        "std": [0.229, 0.224, 0.225],
        "scale": 1.0 / 255.0,
    },
    "rec": {
        "image_shape": [3, 48, 320],
        "mean": [0.5, 0.5, 0.5],
        "std": [0.5, 0.5, 0.5],
        "scale": 1.0 / 255.0,
        "dict_size": len(chars),
    },
}
(ROOT / "storage/ocr/ocr_params.json").write_text(
    json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("=== 参数（供 Android 端照抄）===")
print(json.dumps(params, ensure_ascii=False))
