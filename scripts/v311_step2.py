"""3.1.1（重做）：用单行正则做替换，避开多行锚点在 CRLF/LF 上的坑。"""
import re
from pathlib import Path

R = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
m = R / "android/app/src/main/java/com/localrecord/app/MainActivity.kt"
raw = m.read_bytes()
print("换行符：CRLF 数 =", raw.count(b"\r\n"), " 裸 LF 数 =", raw.count(b"\n") - raw.count(b"\r\n"))

src = m.read_text(encoding="utf-8")
n = 0


def rsub(pat, rep, label, count=1, flags=re.S):
    global src, n
    src2, k = re.subn(pat, rep, src, count=count, flags=flags)
    print(f"  {'✓' if k else '✗'} {label}（{k} 处）")
    src = src2
    n += k


# ① 底部 Switch 删掉
rsub(r"\n *Spacer\(Modifier\.width\(12\.dp\)\)\n *// 逐句翻译开关：[\s\S]*?\n *\}\)\n(?= *\}\n *Text\(\n *\"本地录音)", "\n", "底部 Switch 删除")

# ② 顶部加常显小开关（插在 weight(1f) 那一行之后）
rsub(r"( *modifier = Modifier\.weight\(1f\)\n *\)\n)( *// 常显「⇣ 最新」)",
     r"""\1                            // 翻译开关：小内联链接（和复制/清空同风格），**常显**（列表空着也能开）。
                            // 打开后**只翻译之后的句子**，不动历史 —— 否则说久了队列越堆越多，追不上。
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
\2""", "顶部常显小开关")

# ③ 队列：积压保护 + 跳过过短文本
rsub(r"    /\*\* 把一句转写排进翻译队列：串行执行，避免多个请求同时抢大模型 \*/\n",
     """    /** 待翻译最多留几句：超了丢最旧的，保证翻译追着"最新一句"而不是越拖越远 */
    private val MAX_PENDING = 5

    /** 因积压被跳过的段（界面标一下，免得一直显示"翻译中…"） */
    private val translateSkipped = androidx.compose.runtime.mutableStateListOf<Int>()

    /** 把一句转写排进翻译队列：串行执行，避免几个请求同时抢大模型 */
""", "加 MAX_PENDING 与 translateSkipped")

rsub(r"        if \(!translationOn \|\| text\.isBlank\(\) \|\| translations\.containsKey\(idx\)\) return\n *translateQueue\.offer\(idx to text\)\n",
     """        if (!translationOn || translations.containsKey(idx)) return
        // 太短的（"嗯"、"好"、单个符号）不值得花一秒去翻译，直接跳过省时间
        if (text.trim().count { it.isLetterOrDigit() } < 2) return
        translateQueue.offer(idx to text)
        // 积压保护：只保留最新 MAX_PENDING 句，多出来的丢掉并标注
        while (translateQueue.size > MAX_PENDING) {
            val dropped = translateQueue.poll() ?: break
            translateSkipped.add(dropped.first)
            android.util.Log.i("Translate", "积压过多，跳过第 ${dropped.first + 1} 句")
        }
""", "队列积压保护")

# ④ 删除 translateMissing（不再翻历史）
rsub(r"\n    /\*\* 开关重新打开时，把还没翻译的句子补上 \*/\n    private fun translateMissing\(\) \{\n[^\n]*\n    \}\n", "\n", "删除 translateMissing")

# ⑤ 清空时连跳过标记一起清
rsub(r"( *private fun clearSegments\(why: String\) \{[\s\S]{0,400}?translations\.clear\(\)\n)",
     r"\1        translateSkipped.clear()\n", "清空跳过标记")

# ⑥ 列表渲染三态
rsub(r" *if \(translationOn\) \{\n *val tr = translations\[i\]\n *Text\(\n *if \(tr == null\) \"翻译中…\" else tr,\n *color = if \(tr == null\) Color\(0xFF6B7686\) else Color\(0xFF7FD1A8\),\n *fontSize = 12\.sp\n *\)\n *\}",
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
                            }""", "列表渲染三态")

m.write_text(src, encoding="utf-8")
depth, in_str = 0, False
for ch in src:
    if ch == '"':
        in_str = not in_str
    if not in_str:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
print(f"\n共替换 {n} 处；括号平衡 = {depth}（应为 0）")
for kw in ["translateMissing", "Switch(", "translateSkipped", "MAX_PENDING", "翻译 开"]:
    print(f"  {kw}: {src.count(kw)} 处")
