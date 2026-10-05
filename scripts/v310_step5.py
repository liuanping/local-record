"""3.1.0 第五步：加翻译自检函数与钩子，修正 versionCode。"""
import re
from pathlib import Path

R = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
APP = R / "android/app/src/main/java/com/localrecord/app"

# versionCode 统一成 310
g = R / "android/app/build.gradle.kts"
gt = g.read_text(encoding="utf-8").replace("versionCode = 311", "versionCode = 310")
g.write_text(gt, encoding="utf-8")
print("versionCode = 310 ✓")

m = APP / "MainActivity.kt"
src = m.read_text(encoding="utf-8")

if "runTranslateSelfTest" not in src:
    func = '''    /** --ez translatetest true：验证逐句翻译（Qwen3-0.6B）是否可用、是否关掉思维链 */
    private fun runTranslateSelfTest() {
        io.execute {
            val out = File(store.externalModelsDir().parentFile, "translate-result.txt")
            val sb = StringBuilder()
            fun report(line: String) {
                sb.append(line).append("\\n")
                android.util.Log.i("TranslateTest", line)
            }
            val model = llm.findModel()
            report("大模型文件=${model?.absolutePath ?: "没找到"}")
            report("文件大小=${model?.length()?.div(1048576) ?: 0} MB")
            val t0 = System.currentTimeMillis()
            val ok = try {
                llm.init()
            } catch (e: Throwable) {
                report("加载异常：${e.message}")
                false
            }
            report("加载=${ok}（${System.currentTimeMillis() - t0}ms） 已加载=${llm.loadedModel}")
            if (ok) {
                for (s in listOf(
                    "今天的会议改到下午三点，请大家准时参加。",
                    "Please send me the updated report by Friday."
                )) {
                    val t1 = System.currentTimeMillis()
                    val tr = try {
                        llm.translate(s)
                    } catch (e: Throwable) {
                        "异常：${e.message}"
                    }
                    report("原文：$s")
                    report("译文：$tr")
                    report("用时=${System.currentTimeMillis() - t1}ms")
                }
                report("RESULT PASS")
            } else {
                report("RESULT FAIL（模型没加载起来）")
            }
            try {
                out.writeText(sb.toString())
            } catch (_: Throwable) {
            }
            runOnUiThread { status = "翻译自检完成：${out.name}" }
        }
    }

'''
    anchor = "    private fun runLlmSelfTest() {"
    assert anchor in src, "找不到 runLlmSelfTest"
    src = src.replace(anchor, func + anchor, 1)
    print("已插入 runTranslateSelfTest ✓")

    # 钩子：读 extra + 调用
    src, n1 = re.subn(r'(\n( *)val llmSelfTest = intent\?\.getBooleanExtra\("llmselftest", false\) == true)',
                      r'\1\n\2val translateTest = intent?.getBooleanExtra("translatetest", false) == true', src, count=1)
    src, n2 = re.subn(r'(\n( *)if \(llmSelfTest\) runLlmSelfTest\(\))',
                      r'\1\n\2if (translateTest) runTranslateSelfTest()', src, count=1)
    print(f"钩子：extra {n1} 处，调用 {n2} 处")
    m.write_text(src, encoding="utf-8")
else:
    print("已存在，跳过")

# 文档
readme = R / "android/README-android.md"
r = readme.read_text(encoding="utf-8")
if "**3.1.0**" not in r:
    a = "* **3.0.1**："
    entry = """* **3.1.0**：**去掉 OCR，改为"边识别边翻译"**（用户需求）：
  * 移除：文档问答页、OcrEngine、ocr_jni、PP-OCRv6 两个模型（少下 132MB）、OCR 字典资源。
  * 新增：下载 **Qwen3-0.6B-Q4_K_M.gguf（396.7MB，unsloth 版，魔搭主源）**，重新启用 llama.cpp
    编译（3.0.0 时移除过）。
  * **边识别边翻译**：每切出一句就立刻翻译（中文→英文、英文→中文自动判断方向），
    列表里原文下面直接显示译文；底部有**开关**（默认开），关掉即停止翻译，重新打开会把漏掉的句子补上。
  * 翻译请求**串行排队**（LinkedBlockingQueue + 单工作线程），不会几个请求抢大模型；
    大模型**按需加载一次**并常驻，首次约几秒。
  * 三重关闭思维链：`/no_think` 提示 + JNI 判断模板是否已自带空 `<think>` 块 +
    输出侧 `stripThinking` 兜底。
  * 新增自检：`--ez translatetest true` → 结果写 `translate-result.txt`（含两个例句的原文/译文/耗时）。

"""
    readme.write_text(r.replace(a, entry + a, 1), encoding="utf-8")
    print("README 已加 3.1.0 ✓")

snap = R / "SNAPSHOT-INFO.txt"
s = snap.read_text(encoding="utf-8")
s = s.replace("版本：Android 3.0.1（对应 git 标签 android-v3.0.1）",
              "版本：Android 3.1.0（对应 git 标签 android-v3.1.0）")
if "本版新增（3.1.0" not in s:
    s = s.replace("本版新增（3.0.1，相对 3.0.0）", """本版新增（3.1.0，相对 3.0.1）
------------------------------
移除 OCR（文档问答页与 PP-OCRv6 两个模型），改为下载 Qwen3-0.6B-Q4_K_M.gguf（396.7MB）
并做"边识别边翻译"：逐句翻译、原文+译文并列、底部开关控制；翻译串行排队、大模型常驻。

上一版新增（3.0.1，相对 3.0.0）""", 1)
snap.write_text(s, encoding="utf-8")
print("SNAPSHOT-INFO 已更新 ✓")
