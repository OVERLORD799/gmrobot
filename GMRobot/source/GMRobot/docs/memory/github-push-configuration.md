---
name: github-push-configuration
description: How to configure and execute GitHub pushes for the GMRobot repository
metadata: 
  node_type: memory
  type: reference
  originSessionId: 5b577256-9251-4a9d-b870-39f850097a5c
---

## 仓库信息

| 项 | 值 |
|:------|:-----|
| GitHub 仓库 | `OVERLORD799/gmrobot`（私有） |
| 分支 | `main` |
| 本地路径 | `/root/GMRobot` |
| 最新推送 | **2026-07-01 13:55 UTC** commit `1cc035a` |

## 推送方法（二选一）

### 方法 1：使用项目内置脚本（推荐）

```bash
cd /root/GMRobot
bash scripts/git_push_gh_proxy.sh push
```

该脚本自动：
1. 从 `/root/.github_token` 读取 token
2. 启动本地 HTTP 代理（`127.0.0.1:18743`），将 Git 的 Bearer 认证改写为 gh-proxy 需要的 Basic 认证
3. 代理转发到 `gh-proxy.org`
4. 推送完成后自动清理

### 方法 2：后台运行（交互式不可用时）

```bash
nohup bash scripts/git_push_gh_proxy.sh push > /tmp/git_push.log 2>&1 &
# 等待几秒后检查
cat /tmp/git_push.log
```

## 凭据文件

- **路径**：`/root/.github_token`（不在仓库内，chmod 600）
- 包含 `GITHUB_TOKEN`、`GITHUB_USER`（OVERLORD799）、`GITHUB_REPO`（OVERLORD799/gmrobot）等变量
- **禁止**提交到 Git 或写入文档

## 远程地址

```
origin:  https://gh-proxy.org/https://github.com/OVERLORD799/gmrobot.git
overlord: https://github.com/OVERLORD799/gmrobot.git
```

origin 经 gh-proxy 镜像（防墙），overlord 直连 GitHub。当前两种方式都需 token 认证。

**How to apply:** 每次完成代码变更后，commit 然后执行上述推送命令。记录每次推送的时间戳。
