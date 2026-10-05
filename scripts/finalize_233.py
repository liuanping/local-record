"""2.3.3 定稿：把 README/SNAPSHOT 的描述改成"按 VAD 人声证据判断"（用户提出的判据）。"""
from pathlib import Path

ROOT = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
readme = ROOT / "android/README-android.md"
r = readme.read_text(encoding="utf-8")

old_start = r.find("* **2.3.3**：")
old_end = r.find("* **2.3.2**：")
assert old_start != -1 and old_end != -1, "找不到 2.3.3 / 2.3.2 锚点"

new_entry = """* **2.3.3**：**修"有些话不展示"**（用户反馈：说"哈哈哈"这类看不到），并按用户建议改成
  **用 VAD 的人声证据判断，而不是看文字像什么**：
  * 原因：我之前的两条文字规则太激进 —— `isMeaningless` 把"3 个字以内全是语气词"一律丢掉
    （"哈哈哈""嗯嗯"中招），`looksLikeHallucination` 把"连续 4 个相同字"当幻觉（"哈哈哈哈"中招）。
  * 现在：`SileroVad` 按 **512 采样（32ms）逐窗**询问 VAD「这窗是人声吗」，统计出每段的
    **人声窗数与人声占比**（`lastSpeechWindows` / `lastSpeechRatio`）。
    文字层面的丢弃规则**只在证据很弱时**（人声 <8 窗 或 占比 <40%）才生效；
    证据充分就原样展示，哪怕内容是"哈哈哈""嗯""谢谢观看"。
  * 实测（模拟器，真人语音 3 遍）：每段 **人声 132 窗 / 94%** → 远高于门槛，文字一律展示；
    12 秒纯噪声仍然 **0 段**（噪声连文字这一步都到不了，VAD 就挡住了）。
  * 黑名单也从"点赞/订阅/转发/字幕"这类常见词改成**完整短语**（谢谢观看/请不吝点赞/下期再见…），
    避免误杀"转发给我"这种真话。
  * 新增 `TextFilter`（纯 Kotlin）+ 5 个 JVM 单元测试，锁住"哈哈哈/嗯/啊必须展示"；
    语音页状态行现在显示 `（人声 N 窗 / X%）`，一眼能看出这段是不是真说话。

"""
r = r[:old_start] + new_entry + r[old_end:]
readme.write_text(r, encoding="utf-8")
print("README 2.3.3 条目已改写为「按 VAD 证据判断」 ✓")

snap = ROOT / "SNAPSHOT-INFO.txt"
s = snap.read_text(encoding="utf-8")
s = s.replace("""修「有些话不展示」：以前"3 字以内全是语气词"（哈哈哈/嗯嗯）和"连续 4 个相同字"（哈哈哈哈）
被当作无效丢掉。现在真实说话一律展示，"噪声幻觉"规则只在低信噪比段生效；黑名单改为完整短语。
新增 TextFilter + 单元测试锁住该行为。""",
              """修「有些话不展示」：改为**按 VAD 的人声证据判断**（逐 512 采样窗统计人声窗数/占比）——
证据充分（≥8 窗且≥40%，实测真人语音是 132 窗/94%）就原样展示文字，包括"哈哈哈"；
只有证据很弱时才启用"合成幻觉文本/长串重复字"兜底规则。黑名单改为完整短语。
新增 TextFilter + 5 个单元测试锁住该行为。""", 1)
snap.write_text(s, encoding="utf-8")
print("SNAPSHOT-INFO 已更新 ✓")
