# 发布到 Gitee 的完整步骤

> 本仓库已经在本地整理好：**源码 zip 已从历史中清除**（`.git` 从 2GB 降到 17MB），
> 最新 APK 已入库（37.66MB，Gitee 单文件上限 100MB，安全）。
> 下面从"在 Gitee 建仓库"开始，到"推送 + 上传 APK"结束。

## 一、在 Gitee 建仓库

1. 登录 <https://gitee.com> → 右上角 **+** → **新建仓库**
2. 填写：
   * 仓库名称：`local-record`（或你喜欢的名字）
   * 是否开源：**公开**（免费账号只有公开仓库不限容量）
   * **不要**勾选"使用 README 文件初始化"（否则会和本地历史冲突，需要额外 merge）
3. 建好后记下仓库地址，形如 `https://gitee.com/你的用户名/local-record.git`

## 二、配置认证（二选一）

### 方式 A：HTTPS + 私人令牌（最简单）

1. Gitee 右上角头像 → **设置** → **私人令牌** → 生成新令牌
   * 勾选权限：`projects`（仓库读写）
   * **令牌只显示一次**，复制保存好
2. 推送时用户名填 Gitee 用户名，密码填**这个令牌**（不是登录密码）
3. 想免输入，可让 git 记住：

```bash
git config --global credential.helper store
```

### 方式 B：SSH 公钥（推荐长期使用）

```bash
ssh-keygen -t ed25519 -C "你的邮箱"        # 一路回车
type %USERPROFILE%\.ssh\id_ed25519.pub     # Windows 查看公钥内容
```

把公钥内容粘到 Gitee → **设置** → **安全设置** → **SSH 公钥** → 添加。
验证：

```bash
ssh -T git@gitee.com
```

## 三、关联远程仓库并推送

在本项目根目录（`OpenSWE-main`）执行：

```bash
# 1) 关联远程（把 URL 换成你自己的）
git remote add origin https://gitee.com/你的用户名/local-record.git

# 2) 推送主分支
git push -u origin master

# 3) 推送全部版本标签（17 个：android-v2.1.0 … android-v3.0.1）
git push origin --tags
```

如果之前配过 origin，改用：

```bash
git remote set-url origin https://gitee.com/你的用户名/local-record.git
```

推送成功后，Gitee 仓库页面会自动显示根目录的 `README.md`。

## 四、APK 的两种放法

### 放法 1：仓库里（已经在库，最省事）

最新包已经提交在：

```
dist-android/LocalRecord-android-3.0.1.apk
```

以后每出一个新版，把新 APK 加进去并放行（`.gitignore` 里逐条 `!` 例外）：

```bash
git add -f dist-android/LocalRecord-android-3.0.2.apk
# 同时把旧的那条 ! 规则换成新的，避免仓库无限变大
git commit -m "release: 3.0.2"
git push
```

> ⚠ 注意：git 会**永久保存每一版 APK**（每版 +36MB）。版本多了仓库会变大，
> 建议只在库里保留**最新一版**，历史版本用下面的"发行版"。

### 放法 2：Gitee **发行版（Release）**（推荐放历史版本）

1. 仓库页面 → **发行版** → **新建发行版**
2. 标签选择已有的 `android-v3.0.1`
3. 标题：`Android 3.0.1`
4. 说明里写更新内容（可直接抄 `android/README-android.md` 里的版本记录）
5. **上传附件**：把 `LocalRecord-android-3.0.1.apk` 拖进去（单文件 ≤ 100MB）
6. 发布 → 用户在这个页面直接下载 APK，源码则对应那个 tag

这样"源码走 git 标签、安装包走发行版附件"，仓库不会因为二进制而臃肿。

## 五、日常更新流程

```bash
git add -A
git commit -m "feat: 描述这次改了什么"
git tag -a android-v3.0.2 -m "Android 3.0.2"
git push && git push origin --tags
# 再到 Gitee 网页建一个发行版、把新 APK 作为附件传上去
```

## 六、常见问题

| 现象 | 原因/解决 |
|---|---|
| `remote: 文件超过 100MB` | 有大文件进了历史。用 `git rev-list --objects --all` 找出来，再 `git filter-branch` 清除后 `git gc --prune=now` |
| 推送卡住/超时 | 首次推送 44MB，网络慢时多等一会；或分批 `git push origin master` 后再 `git push origin --tags` |
| `! [rejected] master -> master (fetch first)` | 建仓库时勾了 README 初始化。`git pull --rebase origin master` 后重推 |
| 想确认库里没有大文件 | `git ls-files \| xargs -I{} du -h {} \| sort -h \| tail` |
| 换机器继续开发 | `git clone <仓库地址>`，模型不用管（App 首次运行会自动下载），第三方源码见 `SNAPSHOT-INFO.txt` |
