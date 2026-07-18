# GMrobot Monorepo

本仓库合并了三个相关项目，便于统一开发、部署与 Docker 仿真。

## 子项目

| 目录 | 说明 |
|:-----|:-----|
| `GMRobot/` | Isaac Lab / GM-SafePick 主工程（抓取与重规划等） |
| `g1_ur10e_disturbance/` | G1 + UR10e 扰动仿真；含 `docker/` 镜像构建 |
| `pressure_mat_repro/` | 压力垫 / 触觉相关复现与部署 |

根目录脚本（`env.sh`、`activate_isaaclab.sh`、`setup_*.sh`）用于本机 Isaac / Docker 环境准备。

## Docker（扰动仿真镜像）

镜像基于 **Isaac Sim 5.1**，定义见 `g1_ur10e_disturbance/docker/Dockerfile`。

### 构建（本地）

```bash
cd g1_ur10e_disturbance/docker
./build.sh
```

### 从 GHCR 拉取

```bash
docker pull ghcr.io/overlord799/gmrobot:latest
docker pull ghcr.io/overlord799/gmrobot:v2.3.2-sim5.1
```

本地常用标签：`gmdisturb:latest` / `gmdisturb:v2.3.2-sim5.1`。

## 安全提示

- **不要**将 GitHub PAT、密码、`.github_token` 提交进仓库。
- 文档中的 `x-access-token:<GITHUB_TOKEN>` 仅为占位符，请使用本地凭据文件或环境变量。

## 旧仓库备份

合并前各子目录的 `.git` 已备份为 `.git.bak`（已加入 `.gitignore`），工作区文件与大资产保留在对应子目录中。
