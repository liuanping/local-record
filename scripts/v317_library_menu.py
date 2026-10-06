"""3.1.7：录音库加「⋯」菜单 —— 重命名 / 分享 / 另存为 / 删除（对齐系统录音机的做法）。"""
import re
from pathlib import Path

R = Path(r"E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main")
APP = R / "android/app/src/main/java/com/localrecord/app"
m = APP / "MainActivity.kt"
src = m.read_text(encoding="utf-8")
n0 = len(src)


def sub1(old, new, label):
    global src
    assert old in src, f"锚点没找到：{label}"
    src = src.replace(old, new, 1)
    print(f"  ✓ {label}")


# ---------- 1) file_paths.xml ----------
xml = R / "android/app/src/main/res/xml"
xml.mkdir(parents=True, exist_ok=True)
(xml / "file_paths.xml").write_text("""<?xml version="1.0" encoding="utf-8"?>
<!-- FileProvider 可分享的目录：录音都在 externalFilesDir()/recordings 下 -->
<paths>
    <external-files-path name="recordings" path="recordings/" />
    <external-files-path name="files" path="." />
    <files-path name="internal" path="." />
</paths>
""", encoding="utf-8")
print("  ✓ res/xml/file_paths.xml")

# ---------- 2) Manifest：FileProvider（分享文件必须走它，否则 Android 7+ 直接崩）----------
mf = R / "android/app/src/main/AndroidManifest.xml"
mt = mf.read_text(encoding="utf-8")
if "FileProvider" not in mt:
    mt = mt.replace("""        <!-- 下载模型期间的前台服务""", """        <!-- 分享录音文件用：Android 7+ 不允许直接传 file:// 出去，
             必须用 FileProvider 生成 content:// 并临时授权 -->
        <provider
            android:name="androidx.core.content.FileProvider"
            android:authorities="${applicationId}.fileprovider"
            android:exported="false"
            android:grantUriPermissions="true">
            <meta-data
                android:name="android.support.FILE_PROVIDER_PATHS"
                android:resource="@xml/file_paths" />
        </provider>

        <!-- 下载模型期间的前台服务""", 1)
    mf.write_text(mt, encoding="utf-8")
    print("  ✓ Manifest 加了 FileProvider")
else:
    print("  Manifest 已有 FileProvider")

# ---------- 3) 状态字段 ----------
sub1("    private var textCopied by mutableStateOf(false)            // 转写文字刚被复制",
     """    private var textCopied by mutableStateOf(false)            // 转写文字刚被复制
    private var renameDialog by mutableStateOf<File?>(null)    // 重命名对话框（目标文件）
    private var renameText by mutableStateOf("")               // 重命名输入框内容
    private var saveAsSource: File? = null                     // 「另存为」的源文件""",
     "加状态字段")

# ---------- 4) 三个功能函数 + 另存为 launcher ----------
sub1("    private fun transcribe(f: File) {",
     '''    /** 分享录音：走系统分享面板（微信 / 邮件 / 蓝牙 / 网盘都行） */
    private fun shareAudio(f: File) {
        try {
            val uri = androidx.core.content.FileProvider.getUriForFile(
                this, "$packageName.fileprovider", f
            )
            val send = Intent(Intent.ACTION_SEND).apply {
                type = "audio/*"
                putExtra(Intent.EXTRA_STREAM, uri)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            startActivity(Intent.createChooser(send, "分享录音"))
        } catch (e: Throwable) {
            android.util.Log.e("MainActivity", "分享失败", e)
            status = "分享失败：${e.message}"
        }
    }

    /** 另存为：系统文件选择器（SAF）让用户挑位置，然后把音频复制过去 */
    private val pickSaveAs = registerForActivityResult(
        ActivityResultContracts.CreateDocument("audio/*")
    ) { uri ->
        val srcFile = saveAsSource
        saveAsSource = null
        if (uri == null || srcFile == null) return@registerForActivityResult
        status = "正在另存为…"
        io.execute {
            val ok = try {
                contentResolver.openOutputStream(uri)?.use { out ->
                    srcFile.inputStream().use { input -> input.copyTo(out) }
                }
                true
            } catch (e: Throwable) {
                android.util.Log.e("MainActivity", "另存为失败", e)
                false
            }
            runOnUiThread { status = if (ok) "已另存为 ${srcFile.name}" else "另存为失败" }
        }
    }

    private fun saveAsAudio(f: File) {
        saveAsSource = f
        try {
            pickSaveAs.launch(f.name)
        } catch (e: Throwable) {
            status = "打不开保存对话框：${e.message}"
        }
    }

    /** 重命名：保留原扩展名；正在播放就先停掉，避免重命名后播放出错 */
    private fun doRename(f: File, input: String) {
        val clean = input.trim().replace("/", "_").replace("\\\\", "_")
        if (clean.isEmpty()) {
            status = "文件名不能为空"
            return
        }
        val ext = f.name.substringAfterLast('.', "")
        val newName = if (ext.isNotEmpty() && !clean.endsWith(".$ext")) "$clean.$ext" else clean
        val target = File(f.parentFile, newName)
        if (target.absolutePath == f.absolutePath) return
        if (target.exists()) {
            status = "已经有同名文件了：$newName"
            return
        }
        if (playingPath == f.absolutePath) {
            try {
                player?.stop()
                player?.release()
            } catch (_: Throwable) {
            }
            player = null
            playingPath = null
            playingPaused = false
        }
        val ok = try {
            f.renameTo(target)
        } catch (_: Throwable) {
            false
        }
        status = if (ok) "已重命名为 ${target.name}" else "重命名失败"
        if (ok) refreshRecordings()
    }

    private fun transcribe(f: File) {''', "加分享/另存为/重命名")

# ---------- 5) 行内按钮：删除 → 「⋯」菜单 ----------
sub1("""                            Spacer(Modifier.width(5.dp))
                            OutlinedButton(
                                onClick = { deleteDialog = f },
                                contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp)
                            ) { Text("删除", fontSize = 12.sp, color = Color(0xFFE05B5B)) }
                        }""",
'''                            Spacer(Modifier.width(5.dp))
                            // 「⋯」菜单：重命名 / 分享 / 另存为 / 删除（和系统录音机一样）
                            Box {
                                var menuOpen by remember { mutableStateOf(false) }
                                OutlinedButton(
                                    onClick = { menuOpen = true },
                                    contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp)
                                ) { Text("⋯", fontSize = 14.sp) }
                                androidx.compose.material3.DropdownMenu(
                                    expanded = menuOpen,
                                    onDismissRequest = { menuOpen = false }
                                ) {
                                    androidx.compose.material3.DropdownMenuItem(
                                        text = { Text("重命名", fontSize = 13.sp) },
                                        onClick = {
                                            menuOpen = false
                                            renameText = f.name
                                            renameDialog = f
                                        }
                                    )
                                    androidx.compose.material3.DropdownMenuItem(
                                        text = { Text("分享", fontSize = 13.sp) },
                                        onClick = { menuOpen = false; shareAudio(f) }
                                    )
                                    androidx.compose.material3.DropdownMenuItem(
                                        text = { Text("另存为", fontSize = 13.sp) },
                                        onClick = { menuOpen = false; saveAsAudio(f) }
                                    )
                                    androidx.compose.material3.DropdownMenuItem(
                                        text = {
                                            Text("删除", fontSize = 13.sp, color = Color(0xFFE05B5B))
                                        },
                                        onClick = { menuOpen = false; deleteDialog = f }
                                    )
                                }
                            }
                        }''', "行内「⋯」菜单")

# ---------- 6) 重命名对话框（放在 LibraryTab 的 LazyColumn 之后）----------
anchor = """            LazyColumn(modifier = Modifier.fillMaxSize()) {
                items(recordings) { f ->"""
assert anchor in src
# 找到 LibraryTab 里 LazyColumn 的结尾：在其后插入对话框（用 LibraryTab 结束前的空行做锚点较脆，改为紧跟 pathDialog 渲染）
src = src.replace("    private fun LibraryTab() {",
                  """    private fun LibraryTab() {
        // 重命名对话框（放在页面里，滚动时也不会被裁掉）
        renameDialog?.let { target ->
            androidx.compose.material3.AlertDialog(
                onDismissRequest = { renameDialog = null },
                title = { Text("重命名", fontSize = 15.sp, color = Color.White) },
                text = {
                    androidx.compose.material3.OutlinedTextField(
                        value = renameText,
                        onValueChange = { renameText = it },
                        singleLine = true,
                        label = { Text("文件名（含扩展名）", fontSize = 11.sp) }
                    )
                },
                confirmButton = {
                    Text(
                        "确定", color = Accent, fontSize = 13.sp,
                        modifier = Modifier.clickable {
                            val name = renameText
                            renameDialog = null
                            doRename(target, name)
                        }
                    )
                },
                dismissButton = {
                    Text(
                        "取消", color = Color(0xFF9AA4B2), fontSize = 13.sp,
                        modifier = Modifier.clickable { renameDialog = null }
                    )
                }
            )
        }
""", 1)
print("  ✓ 重命名对话框")

m.write_text(src, encoding="utf-8")

# 自检
depth, ins = 0, False
for ch in src:
    if ch == '"':
        ins = not ins
    if not ins:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
print(f"\n括号平衡 = {depth}（应为 0）；文件从 {n0} 增到 {len(src)} 字符")
for kw in ["shareAudio", "saveAsAudio", "doRename", "FileProvider", "pickSaveAs", "DropdownMenu"]:
    print(f"  {kw}: {src.count(kw)} 处")
assert depth == 0
print("完成 ✓")
