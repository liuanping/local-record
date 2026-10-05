"""Stage 2：删掉界面上的大模型入口（生成会议纪要 / 提问 / 结果弹窗）+ 文案调整 + R8 keep 规则。"""
from pathlib import Path

ROOT = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
m = ROOT / "android/app/src/main/java/com/localrecord/app/MainActivity.kt"
lines = m.read_text(encoding="utf-8").split("\n")


def find_line(pred, start=0):
    for i in range(start, len(lines)):
        if pred(lines[i]):
            return i
    return -1


# ---- 1) 删除“生成会议纪要”那一块（if (tab != 2) { ... }）----
a = find_line(lambda l: l.strip() == "if (tab != 2) {")
assert a != -1, "找不到生成会议纪要块"
# 找到与之配对的收尾（该块内没有嵌套同名结构，向下找到第一个只含一个 } 且缩进相同的行）
depth = 0
b = a
for i in range(a, len(lines)):
    depth += lines[i].count("{") - lines[i].count("}")
    if depth == 0:
        b = i
        break
print(f"删除「生成会议纪要」块：第 {a + 1}~{b + 1} 行")
del lines[a:b + 1]

# ---- 2) 删除“提问”输入行（OutlinedTextField + 提问 按钮）----
a = find_line(lambda l: "androidx.compose.material3.OutlinedTextField(" in l)
assert a != -1, "找不到提问输入框"
# 往前吃掉 Row(
r = a
while r > 0 and "Row(horizontalArrangement" not in lines[r]:
    r -= 1
depth = 0
b = a
for i in range(r, len(lines)):
    depth += lines[i].count("{") - lines[i].count("}")
    if depth == 0 and i > r:
        b = i
        break
print(f"删除「提问」行：第 {r + 1}~{b + 1} 行")
del lines[r:b + 1]

text = "\n".join(lines)

# ---- 3) 删除大模型结果弹窗 ----
i = text.find("// 大模型结果弹窗")
if i != -1:
    j = text.find("                }\n            }\n        }\n    }", i)
    if j == -1:
        j = text.find("                    }\n                }", i)
    assert j != -1, "找不到弹窗结尾"
    j = text.find("                    }\n", j + 10)
    text = text[:i] + text[j + len("                    }\n"):]
    print("已删除大模型结果弹窗 ✓")

# ---- 4) 文档问答页文案：不再提“提问” ----
text = text.replace('"识别图片里的文字，然后用下面的输入框提问"', '"识别图片里的文字（可一键复制）"')
text = text.replace('"选一张带文字的图片（合同 / 截图 / 文档 / 名片），识别出来的文字会显示在这里，" +\n' \
                    '                                "然后就能在下面输入框里对它提问。\\n\\n全程在手机上完成，图片和文字都不会上传。"',
                    '"选一张带文字的图片（合同 / 截图 / 文档 / 名片），识别出来的文字会显示在这里，可一键复制。\\n\\n' \
                    '全程在手机上完成，图片和文字都不会上传。"')
text = text.replace('"选一张带文字的图片（合同 / 截图 / 文档 / 名片），识别出来的文字会显示在这里，" +',
                    '"选一张带文字的图片（合同 / 截图 / 文档 / 名片），识别出来的文字会显示在这里，可一键复制。\\n\\n全程在手机上完成。" +')
m.write_text(text, encoding="utf-8")
print("MainActivity 界面已精简 ✓")

# ---- 5) R8 keep 规则 ----
pg = ROOT / "android/app/proguard-rules.pro"
pg.write_text("""# sherpa-onnx 的 Kotlin 类会被 native 代码按名字构造/调用，必须保留
-keep class com.k2fsa.sherpa.onnx.** { *; }

# 自己写的 native 方法与 JNI 入口
-keepclasseswithmembernames class * {
    native <methods>;
}
-keep class com.localrecord.app.OcrEngine { *; }

# 保留行号，便于看崩溃栈
-keepattributes SourceFile,LineNumberTable
-renamesourcefileattribute SourceFile
""", encoding="utf-8")
print("proguard-rules.pro 已写入 ✓")
