# 发布到 GitHub 的完整步骤

> 本仓库已经整理好，**只有一个提交**（master，标签 `v3.0.1`），
> 推送体积约 41MB（源码 5MB + APK 36MB），远低于 GitHub 的限制。

## 一、GitHub 的两条硬规则（和 Gitee 不同，务必先看）

| 规则 | 说明 |
|---|---|
| **不能再用密码推送** | GitHub 2021 年起禁用了密码认证。HTTPS 推送时**必须用 Personal Access Token（PAT）** 当密码；或用 SSH 公钥。 |
| **国内网络经常连不上** | `github.com` 在国内不稳定。需要代理，或改用 SSH over 443（见第四节）。 |

另外：GitHub 对**单文件 > 100MB 直接拒绝**、> 50MB 会警告 —— 我们的最大文件是 APK 35.9MB ✓ 安全。

## 二、在 GitHub 建仓库

1. 登录 <https://github.com> → 右上角 **+** → **New repository**
2. 填写：
   * Repository name：`local-record`
   * 选 **Public**（公开仓库免费且不限制 Actions 额度）
   * **不要**勾 "Add a README file"（否则和本地历史冲突）
3. 记下地址，形如 `https://github.com/你的用户名/local-record.git`

## 三、配置认证（二选一）

### 方式 A：Personal Access Token（HTTPS，最简单）

1. GitHub 右上角头像 → **Settings** → 左下 **Developer settings**
   → **Personal access tokens** → **Tokens (classic)** → **Generate new token (classic)**
2. 勾选作用域：`repo`（fine-grained token 则给该仓库 Contents: Read and write）
3. 有效期按需（建议 90 天），**生成后立刻复制**（只显示一次）
4. 推送时：
   * 用户名：GitHub 用户名
   * 密码：**粘贴这个 token**（不是登录密码！）
5. 让 git 记住（可选）：

```bash
git config --global credential.helper store
```

### 方式 B：SSH 公钥（推荐长期使用）

```bash
ssh-keygen -t ed25519 -C "你的邮箱"         # 一路回车
type %USERPROFILE%\.ssh\id_ed25519.pub      # 复制公钥内容
```

粘到 GitHub → **Settings** → **SSH and GPG keys** → **New SSH key**。验证：

```bash
ssh -T git@github.com
```

## 四、国内网络连不上时的办法

```bash
# 1) 走本地代理（Clash/V2Ray 常见端口 7890，按实际改）
git config --global http.https://github.com.proxy http://127.0.0.1:7890
git config --global https.https://github.com.proxy http://127.0.0.1:7890

# 取消
git config --global --unset http.https://github.com.proxy

# 2) 或者用 SSH over 443（很多网络封 22 端口但放行 443）
# 在 %USERPROFILE%\.ssh\config 里加：
#   Host github.com
#     HostName ssh.github.com
#     Port 443
#     User git
```

## 五、推送（代码 + 这一个版本）

```bash
cd E:\DeepSeek\deepseek1\deepseek2\OpenSWE-main

git remote add github https://github.com/你的用户名/local-record.git
git push -u github master
git push github v3.0.1
```

> ⚠️ **不要 `git push --tags`**：本地还有 17 个旧标签指向旧历史，一推会把 20 个旧提交也带上。
> 只推 `master` 和 `v3.0.1`。

## 六、一次推送到 Gitee + GitHub（推荐配置）

配好两个地址后，`git push` 一条命令就能同时推两边：

```bash
# 先配 Gitee
git remote add origin https://gitee.com/你的用户名/local-record.git

# 再给 origin 追加 GitHub 的推送地址
git remote set-url --add --push origin https://github.com/你的用户名/local-record.git

# 查看（fetch 用第一个，push 用两个）
git remote -v
# origin  https://gitee.com/.../local-record.git (fetch)
# origin  https://gitee.com/.../local-record.git (push)
# origin  https://github.com/.../local-record.git (push)

# 以后一条命令推两边
git push
git push origin v3.0.1        # 标签也要单独推
```

## 七、APK 放到 Releases（推荐）

GitHub 的 Releases 比仓库更适合放安装包：

1. 仓库页 → 右侧 **Releases** → **Create a new release**
2. **Choose a tag** → 选 `v3.0.1`（已推送过的）
3. Release title：`Android 3.0.1`
4. 说明里写更新内容
5. 把 `dist-android/LocalRecord-android-3.0.1.apk` 拖到 **Attach binaries** 区域
6. **Publish release**

这样用户从 Releases 页直接下载 APK，源码对应 tag —— 仓库也不会因为每版 +36MB 而膨胀。

## 八、常见问题

| 现象 | 原因/解决 |
|---|---|
| `Support for password authentication was removed` | 用了登录密码。改用 **PAT** 或 SSH |
| `Failed to connect to github.com port 443: Timed out` | 网络被墙。按第四节配代理或 SSH over 443 |
| `remote: error: File ... is 128.00 MB; this exceeds GitHub's file size limit of 100 MB` | 有大文件进了历史。用 `git rev-list --objects --all` 排查，`git filter-branch` 清除后 `git gc --prune=now` |
| `! [rejected] master -> master (fetch first)` | 建仓库时勾了 README。`git pull --rebase github master` 后重推 |
| 想确认不会有超大文件 | `git ls-tree -r -l HEAD \| sort -k4 -n \| tail` |
