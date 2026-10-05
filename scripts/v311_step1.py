"""3.1.1：按用户反馈改翻译开关。
① 开关从底部 Switch 挪到转写列表顶部，做成和「⇣ 最新/⧉ 复制/清空」同风格的小内联链接，且**常显**
   （列表为空时也能开关）。
② 打开开关**不再翻译历史**（之前会把已有段落全排进队列，说久了就跟不上）。
③ 加积压保护：待翻译队列超过 5 句就丢掉最旧的，并在那一句标「（来不及，已跳过）」，保证永远追最新。
④ 太短的段（少于 2 字，如"嗯"）不翻译，省时间。
"""
import re
from pathlib import Path

R = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
m = R / "android/app/src/main/java/com/localrecord/app/MainActivity.kt"
src = m.read_text(encoding="utf-8")


def sub1(old, new, label):
    global src
    assert old in src, f"锚点没找到：{label}"
    src = src.replace(old, new, 1)
    print(f"  ✓ {label}")


# ---------- ① 删除底部的 Switch 块 ----------
sub1("""                Spacer(Modifier.width(12.dp))
                // 逐句翻译开关：打开后每识别出一句立刻翻译，原文与译文并排显示
                Text(
                    "边识别边翻译",
                    color = if (translationOn) Accent else Color(0xFF6B7686),
                    fontSize = 11.sp
                )
                androidx.compose.material3.Switch(
                    checked = translationOn,
                    onCheckedChange = { on ->
                        translationOn = on
                        if (on) {
                            translateMissing()
                            if (segments.isNotEmpty()) status = "正在翻译已有 ${segments.size} 句…"
                        } else {
                            status = "已关闭翻译"
                        }
                    }
                )
            }""", """            }""", "删除底部 Switch")

# ---------- ② 顶部加常显的小内联开关 ----------
sub1("""                                color = Color(0xFF9AA4B2), fontSize = 11.sp,
                                modifier = Modifier.weight(1f)
                            )
                            // 常显「⇣ 最新」""",
"""                                color = Color(0xFF9AA4B2), fontSize = 11.sp,
                                modifier = Modifier.weight(1f)
                            )
                            // 翻译开关：小内联链接（和复制/清空同风格），**常显**（列表空着也能开）。
                            // 打开后**只翻译之后的句子**，不动历史 —— 否则说久了队列会越堆越多，追不上。
                            Text(
                                if (translationOn) "翻译 开" else "翻译 关",
                                color = if (translationOn) Color(0xFF7FD1A8) else Color(0xFF9AA4B2),
                                fontSize = 11.sp,
                                modifier = Modifier.clickable {
                                    translationOn = !translationOn
                                    status = if (translationOn) {
                                        "已开启翻译：从这一句开始逐句翻译（之前几句保持原文）"
                                    } else {
                                        "已关闭翻译"
                                    }
                                }
                            )
                            Spacer(Modifier.width(12.dp))
                            // 常显「⇣ 最新」""", "顶部加小开关")

# ---------- ③ 队列逻辑：积压保护 + 跳过过短文本 + 删除 translateMissing ----------
sub1("""    /** 把一句转写排进翻译队列：串行执行，避免几个请求同时抢大模型 */
    private fun enqueueTranslation(idx: Int, text: String) {
        if (!translationOn || text.isBlank() || translations.containsKey(idx)) return
        translateQueue.offer(idx to text)
        startTranslateWorker()
    }""",
"""    /** 待翻译最多留几句：超了就丢最旧的，保证翻译始终追着"最新一句"而不是越拖越远 */
    private val MAX_PENDING = 5

    /** 因为积压被跳过的段（界面标一下，免得一直显示"翻译中…"） */
    private val translateSkipped = androidx.compose.runtime.mutableStateListOf<Int>()

    /** 把一句转写排进翻译队列：串行执行，避免几个请求同时抢大模型 */
    private fun enqueueTranslation(idx: Int, text: String) {
        if (!translationOn || translations.containsKey(idx)) return
        // 太短的（"嗯"、"好"、单个符号）不值得花 1 秒去翻译，直接跳过省时间
        if (text.trim().count { it.isLetterOrDigit() } < 2) return
        translateQueue.offer(idx to text)
        while (translateQueue.size > MAX_PENDING) {
            val dropped = translateQueue.poll() ?: break
            translateSkipped.add(dropped.first)
            android.util.Log.i("Translate", "积压过多，跳过第 ${dropped.first + 1} 句")
        }
        startTranslateWorker()
    }""", "队列积压保护")

sub1("""    /** 开关重新打开时，把还没翻译的句子补上 */
    private fun translateMissing() {
        segments.forEachIndexed { i, s -> if (!translations.containsKey(i)) enqueueTranslation(i, s.text) }
    }""", "", "删除 translateMissing（不再翻历史）")

# ---------- ④ 清空时连"跳过"标记一起清 ----------
sub1("""        translations.clear()
        translateQueue.clear()""",
"""        translations.clear()
        translateSkipped.clear()
        translateQueue.clear()""", "清空跳过标记")

# ---------- ⑤ 列表渲染：区分 翻译中 / 跳过 ----------
sub1("""                            if (translationOn) {
                                val tr = translations[i]
                                Text(
                                    if (tr == null) "翻译中…" else tr,
                                    color = if (tr == null) Color(0xFF6B7686) else Color(0xFF7FD1A8),
                                    fontSize = 12.sp
                                )
                            }""",
"""                            if (translationOn) {
                                val tr = translations[i]
                                val skipped = translateSkipped.contains(i)
                                Text(
                                    when {
                                        tr != null -> tr
                                        skipped -> "（说得太快，这句没来得及翻）"
                                        else -> "翻译中…"
                                    },
                                    color = when {
                                        tr != null -> Color(0xFF7FD1A8)
                                        skipped -> Color(0xFF5A6372)
                                        else -> Color(0xFF6B7686)
                                    },
                                    fontSize = 12.sp
                                )
                            }""", "列表渲染区分三态")

m.write_text(src, encoding="utf-8")

# 自检
depth, in_str = 0, False
for ch in src:
    if ch == '"':
        in_str = not in_str
    if not in_str:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
print(f"\n括号平衡 = {depth}（应为 0）")
for kw in ["translateMissing", "Switch(", "translateSkipped", "MAX_PENDING"]:
    print(f"  {kw}: {src.count(kw)} 处")
assert depth == 0

# 版本与文档
g = R / "android/app/build.gradle.kts"
gt = g.read_text(encoding="utf-8").replace("versionCode = 310", "versionCode = 311").replace('versionName = "3.1.0"', 'versionName = "3.1.1"')
g.write_text(gt, encoding="utf-8")
print("版本 -> 3.1.1 / 311 ✓")

readme = R / "android/README-android.md"
r = readme.read_text(encoding="utf-8")
if "**3.1.1**" not in r:
    a = "* **3.1.0**："
    entry = """* **3.1.1**：按用户反馈改翻译开关的交互（用户原话："开关比较奇怪"、"打开开关后不该把历史的都翻译，
  说久了会跟不上"）：
  1. **开关位置**：从底部一个孤立的 Material Switch，挪到转写列表**顶部**，做成与
     「⇣ 最新 / ⧉ 复制 / 清空」同风格的小内联链接（`翻译 开` / `翻译 关`，绿色=开），
     并且**常显** —— 列表还是空的时候也能先打开。
  2. **不再翻译历史**：打开开关只翻译**之后**新识别出的句子，之前的保持原文
     （原先会把已有段落全部排进队列，说久了必然追不上）。
  3. **积压保护**：待翻译队列最多留 **5 句**，超了丢最旧的，并在那一句标
     「（说得太快，这句没来得及翻）」—— 保证翻译永远追着最新一句。
  4. 少于 2 个有效字符的段（"嗯""好"）不翻译，省时间。

"""
    readme.write_text(r.replace(a, entry + a, 1), encoding="utf-8")
    print("README 已加 3.1.1 ✓")

snap = R / "SNAPSHOT-INFO.txt"
s = snap.read_text(encoding="utf-8")
s = s.replace("版本：Android 3.1.0（对应 git 标签 android-v3.1.0）", "版本：Android 3.1.1（对应 git 标签 android-v3.1.1）")
if "本版新增（3.1.1" not in s:
    s = s.replace("本版新增（3.1.0，相对 3.0.1）", """本版新增（3.1.1，相对 3.1.0）
------------------------------
翻译开关挪到转写列表顶部（小内联链接、常显）；打开只翻译之后的句子、不再翻历史；
待翻译队列上限 5 句、超了丢最旧并标注；过短的段不翻译。

上一版新增（3.1.0，相对 3.0.1）""", 1)
snap.write_text(s, encoding="utf-8")
print("SNAPSHOT-INFO 已更新 ✓")
