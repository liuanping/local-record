"""3.2.0 补漏：Context 4096→1024；录音停止后补翻挂到 toggleRecord 的停止分支。"""
from pathlib import Path

R = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
APP = R / "android/app/src/main/java/com/localrecord/app"

# ① 上下文 4096 → 1024（省内存、更快）
le = APP / "LlmEngine.kt"
t = le.read_text(encoding="utf-8")
t = t.replace("const val CONTEXT = 4096", "const val CONTEXT = 1024")
le.write_text(t, encoding="utf-8")
print("LlmEngine：CONTEXT 4096 → 1024 ✓")
for l in t.split("\n"):
    if "CONTEXT" in l or "coerceIn(2" in l:
        print("   ", l.strip()[:90])

# ② 录音停止分支里挂"补翻"
m = APP / "MainActivity.kt"
mt = m.read_text(encoding="utf-8")
old = """            } else status = "这次没有采到音频"
            return
        }"""
new = """            } else status = "这次没有采到音频"
            // 录音结束：这时才允许加载大模型，把录音期间没翻的句子补上
            // （录音期间故意不加载、不推理，避免和识别抢 CPU/内存）
            if (translationOn && segments.isNotEmpty() && llm.findModel() != null) {
                Thread({
                    android.os.Process.setThreadPriority(android.os.Process.THREAD_PRIORITY_BACKGROUND)
                    if (llm.ready || llm.init()) {
                        llmReady = true
                        runOnUiThread {
                            status = "录音结束，正在补翻 ${segments.size} 句…"
                            segments.forEachIndexed { i, s ->
                                if (!translations.containsKey(i)) enqueueTranslation(i, s.text)
                            }
                        }
                    }
                }, "llm-catchup").start()
            }
            return
        }"""
assert old in mt, "找不到录音停止分支"
mt = mt.replace(old, new, 1)
m.write_text(mt, encoding="utf-8")
print("MainActivity：录音结束后自动补翻 ✓")

# 清掉之前没被调用的 resumeTranslateAfterRecord / translateMissing2（避免死代码）
import re
for name in ["resumeTranslateAfterRecord", "translateMissing2"]:
    if name in mt:
        mt2 = m.read_text(encoding="utf-8")
        i = mt2.find(f"    private fun {name}(")
        if i != -1:
            # 往前吃掉注释
            s = i
            while s > 0 and mt2[:s].rstrip().endswith(("*/",)) or mt2[s - 1:s].strip() == "":
                s -= 1
                if mt2[:s].rstrip().endswith("*/"):
                    s = mt2.rfind("/**", 0, s)
                    break
            # 用花括号配对找结束
            depth, j = 0, i
            while j < len(mt2):
                if mt2[j] == "{":
                    depth += 1
                elif mt2[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            end = mt2.find("\n", j) + 1
            mt2 = mt2[:i] + mt2[end:]
            m.write_text(mt2, encoding="utf-8")
            print(f"  已删除未使用的 {name}()")
            mt = mt2

# 自检
depth, ins = 0, False
for ch in mt:
    if ch == '"':
        ins = not ins
    if not ins:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
print(f"MainActivity 括号平衡 = {depth}（应为 0）")
print("  补翻钩子:", mt.count("llm-catchup"), "处")

# ③ 版本
g = R / "android/app/build.gradle.kts"
g.write_text(g.read_text(encoding="utf-8").replace("versionCode = 319", "versionCode = 320").replace("3.1.9", "3.2.0"), encoding="utf-8")
print("版本 -> 3.2.0 / 320 ✓")
